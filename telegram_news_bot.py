"""
AI News Chatbot - Telegram Bot gửi tin tức VNExpress mỗi sáng

Bot tự động lấy khoảng 15 tin nóng nhất trong 24h gần nhất và gửi qua
Telegram lúc 6:00 sáng mỗi ngày bằng GitHub Actions.

Cấu hình:
  - TELEGRAM_BOT_TOKEN: Token bot từ @BotFather
  - TELEGRAM_CHAT_ID: ID chat để nhận tin (user hoặc group)

Cách chạy:
  python telegram_news_bot.py
"""
from __future__ import annotations

import calendar
import html
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List
from urllib.parse import urlsplit

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

# RSS feeds cho các chủ đề
VNEXPRESS_RSS_FEEDS = {
    "tin-noi-bat": "https://vnexpress.net/rss/tin-noi-bat.rss",
    "tin-moi-nhat": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "tin-xem-nhieu": "https://vnexpress.net/rss/tin-xem-nhieu.rss",
    "cong-nghe": "https://vnexpress.net/rss/cong-nghe.rss",
    "thoi-su": "https://vnexpress.net/rss/thoi-su.rss",
    "kinh-doanh": "https://vnexpress.net/rss/kinh-doanh.rss",
    "the-gioi": "https://vnexpress.net/rss/the-gioi.rss",
    "giai-tri": "https://vnexpress.net/rss/giai-tri.rss",
    "the-thao": "https://vnexpress.net/rss/the-thao.rss",
    "giao-duc": "https://vnexpress.net/rss/giao-duc.rss",
    "suc-khoe": "https://vnexpress.net/rss/suc-khoe.rss",
    "phap-luat": "https://vnexpress.net/rss/phap-luat.rss",
}

HOT_NEWS_FEED_KEYS = (
    "tin-noi-bat",
    "tin-moi-nhat",
    "tin-xem-nhieu",
    "thoi-su",
    "the-gioi",
    "kinh-doanh",
    "cong-nghe",
    "suc-khoe",
    "giao-duc",
    "phap-luat",
)

GEMINI_MODEL_FALLBACK = (
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
)
TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_PHOTO_CAPTION_LIMIT = 1024
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRY_DELAY_SECONDS = 60


def _get_vn_timezone() -> timezone:
    """Lấy timezone Việt Nam (UTC+7)."""
    try:
        from zoneinfo import ZoneInfo  # type: ignore

        return ZoneInfo("Asia/Ho_Chi_Minh")  # type: ignore[return-value]
    except Exception:
        return timezone(timedelta(hours=7))


VN_TZ = _get_vn_timezone()


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """Đọc biến môi trường dạng số nguyên, có chặn giá trị tối thiểu."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"⚠️ Invalid {name}={raw!r}; using {default}")
        return default
    return max(minimum, value)


def _clip_text(text: str, limit: int) -> str:
    """Cắt text theo giới hạn Telegram, giữ dấu ba chấm nếu bị rút gọn."""
    text = text.strip()
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _escape_html_text(text: str) -> str:
    """Escape nội dung động để Telegram HTML parse mode không bị lỗi."""
    return html.escape(text or "", quote=False)


def _escape_and_clip_text(text: str, limit: int) -> str:
    """Escape rồi cắt text mà không làm vỡ HTML entity."""
    escaped = _escape_html_text(text.strip())
    if len(escaped) <= limit:
        return escaped
    if limit <= 3:
        return ""

    suffix = "..."
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = _escape_html_text(text[:mid].rstrip()) + suffix
        if len(candidate) <= limit:
            low = mid
        else:
            high = mid - 1
    return _escape_html_text(text[:low].rstrip()) + suffix if low else ""


def _safe_http_url(url: str | None) -> str | None:
    """Chỉ nhận URL HTTP(S) tuyệt đối để đưa vào Telegram."""
    if not url:
        return None
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return url.strip()


def _safe_error(exc: Exception, *secrets: str | None) -> str:
    """Giữ log hữu ích nhưng không để token/API key lọt vào URL lỗi."""
    message = str(exc)
    for secret in secrets:
        if secret:
            message = message.replace(secret, "<redacted>")
    return f"{type(exc).__name__}: {message}"[:500]


def _allow_basic_telegram_html(text: str) -> str:
    """
    Cho phép AI dùng một số tag Telegram an toàn, escape toàn bộ phần còn lại.
    """
    escaped = _escape_html_text(text)
    for tag in ("b", "i", "u", "s", "code", "pre"):
        escaped = escaped.replace(f"&lt;{tag}&gt;", f"<{tag}>")
        escaped = escaped.replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    return escaped


def _extract_gemini_text(data: dict) -> str | None:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        text = "".join(texts).strip()
        return text or None
    except (KeyError, IndexError, TypeError):
        return None


def _post_with_retries(url: str, *, attempts: int = 3, **kwargs) -> requests.Response:
    """POST có retry ngắn cho Telegram/Gemini khi gặp rate-limit hoặc 5xx."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(url, **kwargs)
            if response.status_code not in RETRY_STATUS_CODES or attempt == attempts:
                return response
            retry_after = response.headers.get("Retry-After", "")
            if not retry_after.isdigit() and response.status_code == 429:
                try:
                    retry_after = str(response.json().get("parameters", {}).get("retry_after", ""))
                except (TypeError, ValueError):
                    retry_after = ""
            delay = int(retry_after) if retry_after.isdigit() else attempt
            delay = min(delay, MAX_RETRY_DELAY_SECONDS)
            print(f"⚠️ POST {response.status_code}; retrying in {delay}s ({attempt}/{attempts})")
            time.sleep(delay)
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts:
                raise
            time.sleep(attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("POST failed without a response")


def _generate_gemini_text(
    *,
    prompt: str,
    api_key: str,
    temperature: float,
    max_output_tokens: int,
) -> str | None:
    """Gọi Gemini với model fallback để bot không chết vì một model lỗi/quota."""
    if not api_key:
        return None

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }

    configured_model = os.getenv("GEMINI_MODEL", "").strip()
    models = tuple(dict.fromkeys((configured_model, *GEMINI_MODEL_FALLBACK))) if configured_model else GEMINI_MODEL_FALLBACK

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            response = _post_with_retries(
                url,
                params={"key": api_key},
                headers=headers,
                json=payload,
                timeout=30,
                attempts=2,
            )
            if response.status_code == 200:
                return _extract_gemini_text(response.json())
            if response.status_code in {404, 429, 500, 502, 503, 504}:
                print(f"⚠️ Gemini model {model} unavailable/quota ({response.status_code}); trying fallback")
                continue
            print(f"⚠️ Gemini API error {response.status_code}: {response.text[:200]}")
            return None
        except Exception as exc:
            print(f"⚠️ Gemini model {model} failed: {_safe_error(exc, api_key)}")
            continue

    return None


@dataclass(frozen=True)
class Article:
    """Đại diện một bài báo từ RSS."""

    title: str
    link: str
    published_at: datetime | None = None
    image_url: str | None = None
    summary: str = ""


def fetch_vnexpress_latest_raw(rss_url: str) -> feedparser.FeedParserDict:
    """Lấy và parse RSS feed từ VNExpress."""
    insecure = os.getenv("RSS_INSECURE", "").strip().lower() in {"1", "true", "yes"}
    try:
        r = requests.get(rss_url, timeout=30, verify=not insecure)
        r.raise_for_status()
    except Exception as e:
        hint = " (try set RSS_INSECURE=1 if behind proxy)" if not insecure else ""
        raise RuntimeError(f"Failed to fetch RSS: {e}{hint}") from e

    feed = feedparser.parse(r.content)
    if getattr(feed, "bozo", False):
        raise RuntimeError(f"Failed to parse RSS XML: {getattr(feed, 'bozo_exception', 'unknown error')}")
    return feed


def _extract_image_url(entry) -> str | None:
    """Trích xuất URL hình ảnh từ RSS entry."""
    # Ưu tiên 1: Lấy từ enclosures (nếu có type='image/...')
    enclosures = getattr(entry, "enclosures", [])
    for enc in enclosures:
        if isinstance(enc, dict):
            enc_type = enc.get("type", "").lower()
            if enc_type.startswith("image/"):
                href = _safe_http_url(enc.get("href", ""))
                if href:
                    return href

    # Ưu tiên 2: Parse từ summary HTML (tìm thẻ <img>)
    summary = getattr(entry, "summary", "") or ""
    if summary:
        # Tìm pattern <img src="...">
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, re.IGNORECASE)
        if img_match:
            img_url = _safe_http_url(html.unescape(img_match.group(1)))
            if img_url:
                return img_url

    return None


def _extract_summary(entry) -> str:
    """Trích xuất summary/description từ RSS entry (loại bỏ HTML tags và links)."""
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    if summary:
        # Loại bỏ HTML tags
        summary = html.unescape(re.sub(r"<[^>]+>", "", summary))
        summary = summary.strip()
        # Loại bỏ các link URL (http/https)
        summary = re.sub(r"https?://[^\s]+", "", summary)
        summary = re.sub(r"www\.[^\s]+", "", summary)
        summary = " ".join(summary.split())  # Normalize whitespace
        # Giới hạn độ dài
        if len(summary) > 300:
            summary = summary[:300] + "..."
    return summary

def summarize_with_gemini(article: Article, api_key: str) -> str | None:
    """
    Dùng Gemini để tóm tắt bài báo.
    Trả về None nếu lỗi hoặc không có API key.
    """
    if not api_key:
        return None
    
    # Chuẩn bị prompt với thông tin từ RSS
    prompt = f"""Bạn là một AI chuyên tóm tắt tin tức tiếng Việt. 
Hãy tóm tắt ngắn gọn bài báo sau đây trong 2-3 câu, tập trung vào thông tin quan trọng nhất.

Tiêu đề: {article.title}

Nội dung từ RSS: {article.summary if article.summary else "Không có nội dung chi tiết"}

Yêu cầu:
- Tóm tắt ngắn gọn, súc tích (2-3 câu, khoảng 100-200 từ)
- Giữ nguyên thông tin quan trọng và sự kiện chính
- Viết bằng tiếng Việt
- Không thêm ý kiến cá nhân hoặc thông tin không có trong bài
- Loại bỏ các từ ngữ không cần thiết
"""

    return _generate_gemini_text(
        prompt=prompt,
        api_key=api_key,
        temperature=0.3,
        max_output_tokens=250,
    )

def format_article_caption(
    article: Article,
    index: int,
    ai_summary: str | None = None,
    *,
    max_length: int = TELEGRAM_MESSAGE_LIMIT,
) -> str:
    """Format caption cho một bài báo (ưu tiên AI summary nếu có, fallback về RSS summary)."""
    raw_title = article.title or "(Không có tiêu đề)"
    body = ai_summary or article.summary or ""
    prefix = f"<b>{index}. "
    suffix = "</b>"

    safe_link = _safe_http_url(article.link)
    link = ""
    if safe_link:
        escaped_link = html.escape(safe_link, quote=True)
        candidate = f'\n\n<a href="{escaped_link}">🔗 Đọc bài gốc</a>'
        if len(prefix) + len(suffix) + len(candidate) + 1 <= max_length:
            link = candidate

    title_limit = max_length - len(prefix) - len(suffix) - len(link)
    if title_limit <= 0:
        return _escape_and_clip_text(raw_title, max_length)

    title = _escape_and_clip_text(raw_title, title_limit)
    caption = f"{prefix}{title}{suffix}"
    body_limit = max_length - len(caption) - len(link) - 2
    if body and body_limit > 3:
        escaped_body = _escape_and_clip_text(body, body_limit)
        if escaped_body:
            caption += f"\n\n{escaped_body}"
    return caption + link

def fetch_crypto_data() -> dict:
    """Lấy dữ liệu giá và biến động 24h của BTC, ETH, SOL."""
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"⚠️ Failed to fetch crypto data: {e}")
        return {}

def fetch_fear_and_greed_index() -> str:
    """Lấy chỉ số sợ hãi và tham lam (Fear & Greed Index)."""
    url = "https://api.alternative.me/fng/?limit=1"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return f"{data['data'][0]['value']} - {data['data'][0]['value_classification']}"
    except Exception as e:
        print(f"⚠️ Failed to fetch Fear & Greed Index: {e}")
        return "Unknown"

def predict_crypto_with_gemini(crypto_data: dict, fng: str, world_news: List[Article], api_key: str) -> str | None:
    """Dự đoán xu hướng Crypto với Gemini dựa trên tin tức thế giới và dữ liệu."""
    if not api_key or not crypto_data:
        return None
        
    news_context = "\n".join([f"- {a.title}" for a in world_news]) if world_news else "Không có tin tức nổi bật."
    
    prompt = f"""Bạn là một chuyên gia phân tích tài chính và Crypto.
Trọng tâm phân tích là Bitcoin (BTC), Ethereum (ETH), và Solana (SOL).

Dữ liệu hiện tại:
- Tâm lý thị trường (Fear & Greed Index): {fng}
- BTC: {crypto_data.get('bitcoin', {}).get('usd', 'N/A')} USD (Biến động 24h: {crypto_data.get('bitcoin', {}).get('usd_24h_change', 0):.2f}%)
- ETH: {crypto_data.get('ethereum', {}).get('usd', 'N/A')} USD (Biến động 24h: {crypto_data.get('ethereum', {}).get('usd_24h_change', 0):.2f}%)
- SOL: {crypto_data.get('solana', {}).get('usd', 'N/A')} USD (Biến động 24h: {crypto_data.get('solana', {}).get('usd_24h_change', 0):.2f}%)

Tin tức thế giới nổi bật:
{news_context}

Yêu cầu:
Dựa vào tình hình địa chính trị (tin tức trên), biến động giá và tâm lý người chơi (Fear & Greed), hãy đưa ra dự đoán ngắn gọn về xu hướng sắp tới của BTC, ETH, SOL. Phân tích qua về góc nhìn biểu đồ (Price action) và tâm lý.
Viết 1 đoạn (khoảng 150-250 từ), sử dụng tiếng Việt, định dạng dễ đọc bằng HTML tags hợp lệ cho Telegram (<b>, <i>).
Cuối đoạn thêm dòng chữ in nghiêng: "<i>Lưu ý: Nhận định từ AI chỉ mang tính tham khảo, không phải lời khuyên đầu tư.</i>"
"""
    
    return _generate_gemini_text(
        prompt=prompt,
        api_key=api_key,
        temperature=0.5,
        max_output_tokens=600,
    )

def _entry_to_article(entry) -> Article:
    """Chuyển RSS entry thành Article object."""
    title = (getattr(entry, "title", "") or "").strip()
    link = (getattr(entry, "link", "") or "").strip()
    published_parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if published_parsed is not None:
        # published_parsed là struct_time UTC.
        dt_utc = datetime.fromtimestamp(calendar.timegm(published_parsed), tz=timezone.utc)
        dt_vn = dt_utc.astimezone(VN_TZ)
    else:
        dt_vn = None

    image_url = _extract_image_url(entry)
    summary = _extract_summary(entry)
    return Article(title=title, link=link, published_at=dt_vn, image_url=image_url, summary=summary)


def _is_article_recent(article: Article, since: datetime | None) -> bool:
    if since is None:
        return True
    if article.published_at is None:
        return False
    return article.published_at >= since


def fetch_articles_from_feed(
    rss_url: str,
    limit: int = 3,
    *,
    since: datetime | None = None,
) -> List[Article]:
    """Lấy tin từ một RSS feed cụ thể."""
    feed = fetch_vnexpress_latest_raw(rss_url)
    all_articles: List[Article] = [_entry_to_article(e) for e in getattr(feed, "entries", [])]
    all_articles = [a for a in all_articles if _is_article_recent(a, since)]
    all_articles.sort(key=lambda a: a.published_at or datetime.min.replace(tzinfo=VN_TZ), reverse=True)
    all_articles = _dedupe_articles(all_articles)
    return all_articles[:limit]

def _dedupe_articles(articles: List[Article]) -> List[Article]:
    seen = set()
    out: List[Article] = []
    for a in articles:
        key = (a.link or a.title).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def fetch_articles_with_fallback(
    primary_url: str,
    fallback_url: str,
    limit: int,
    *,
    since: datetime | None = None,
) -> List[Article]:
    """
    Lấy đủ `limit` bài: ưu tiên primary, thiếu thì bù từ fallback.
    """
    primary: List[Article] = []
    try:
        primary = fetch_articles_from_feed(primary_url, limit=limit, since=since)
    except Exception as e:
        print(f"⚠️ Primary feed failed: {e}")

    primary = _dedupe_articles(primary)

    if len(primary) >= limit:
        return primary[:limit]

    fallback: List[Article] = []
    try:
        fallback = fetch_articles_from_feed(fallback_url, limit=limit + 10, since=since)  # lấy dư để dedupe
    except Exception as e:
        print(f"⚠️ Fallback feed failed: {e}")

    combined = _dedupe_articles(primary + fallback)
    return combined[:limit]


def fetch_hot_articles(
    *,
    limit: int = 15,
    since: datetime | None = None,
    feed_keys: tuple[str, ...] = HOT_NEWS_FEED_KEYS,
) -> List[Article]:
    """Gom nhiều RSS feed, dedupe, rồi lấy các bài mới nhất trong ngày."""
    candidates: List[Article] = []
    per_feed_limit = max(limit, 20)

    for key in feed_keys:
        rss_url = VNEXPRESS_RSS_FEEDS[key]
        try:
            candidates.extend(fetch_articles_from_feed(rss_url, limit=per_feed_limit, since=since))
        except Exception as exc:
            print(f"⚠️ Failed to fetch feed {key}: {exc}")

    candidates.sort(key=lambda a: a.published_at or datetime.min.replace(tzinfo=VN_TZ), reverse=True)
    return _dedupe_articles(candidates)[:limit]


def send_telegram_message(*, token: str, chat_id: str, text: str) -> None:
    """Gửi message qua Telegram Bot API."""
    payload = {
        "chat_id": chat_id,
        "text": _clip_text(text, TELEGRAM_MESSAGE_LIMIT),
        "disable_web_page_preview": True,
        "parse_mode": "HTML",
    }
    _post_telegram(token=token, method="sendMessage", payload=payload)


def send_telegram_photo(*, token: str, chat_id: str, photo_url: str, caption: str = "") -> None:
    """Gửi hình ảnh qua Telegram Bot API."""
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": _clip_text(caption, TELEGRAM_PHOTO_CAPTION_LIMIT),
        "parse_mode": "HTML",
    }
    _post_telegram(token=token, method="sendPhoto", payload=payload)


def _post_telegram(*, token: str, method: str, payload: dict) -> None:
    """Gọi Telegram API và bảo đảm exception không lộ bot token."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        response = _post_with_retries(url, data=payload, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Telegram {method} failed: {_safe_error(exc, token)}") from None


def send_article_to_telegram(
    *,
    token: str,
    chat_id: str,
    article: Article,
    index: int,
    ai_summary: str | None = None,
) -> bool:
    """Gửi một bài báo, ưu tiên ảnh nhưng fallback sang text nếu ảnh lỗi."""
    if article.image_url:
        try:
            caption = format_article_caption(
                article,
                index,
                ai_summary,
                max_length=TELEGRAM_PHOTO_CAPTION_LIMIT,
            )
            send_telegram_photo(
                token=token,
                chat_id=chat_id,
                photo_url=article.image_url,
                caption=caption,
            )
            return True
        except Exception as exc:
            print(f"⚠️ sendPhoto failed for #{index}: {_safe_error(exc, token)} -> fallback to text")

    caption = format_article_caption(
        article,
        index,
        ai_summary,
        max_length=TELEGRAM_MESSAGE_LIMIT,
    )
    send_telegram_message(token=token, chat_id=chat_id, text=caption)
    return True


def main() -> int:
    """Hàm main."""
    # Cố gắng set encoding UTF-8 để in tiếng Việt trên một số console Windows.
    try:
        stdout_reconf = getattr(sys.stdout, "reconfigure", None)
        stderr_reconf = getattr(sys.stderr, "reconfigure", None)
        if callable(stdout_reconf):
            stdout_reconf(encoding="utf-8")
        if callable(stderr_reconf):
            stderr_reconf(encoding="utf-8")
    except Exception:
        pass

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    lookback_hours = _env_int("ARTICLE_LOOKBACK_HOURS", 24)
    news_article_count = _env_int("NEWS_ARTICLE_COUNT", 15)
    now_vn = datetime.now(VN_TZ)
    since_vn = now_vn - timedelta(hours=lookback_hours)

    if not token or not chat_id:
        # Cho phép chạy thử local mà không cần cấu hình đủ env.
        print(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID. "
            "Set these env vars (hoặc GitHub Secrets) để bot gửi tin."
        )
        # Test với một feed
        articles = fetch_hot_articles(limit=news_article_count, since=since_vn)
        print(f"\n📰 Preview - {len(articles)} tin nóng trong {lookback_hours}h gần nhất:")
        for i, a in enumerate(articles, 1):
            published = a.published_at.strftime("%d/%m %H:%M") if a.published_at else "không rõ giờ"
            print(f"{i}. [{published}] {a.title}")
            if a.summary:
                print(f"   {a.summary[:100]}...")
        return 0

    articles = fetch_hot_articles(limit=news_article_count, since=since_vn)
    if not articles:
        message = f"⚠️ Không tìm thấy tin nào trong {lookback_hours}h gần nhất"
        print(message)
        send_telegram_message(token=token, chat_id=chat_id, text=message)
        return 1

    today = now_vn.date()
    header_msg = f"📰 <b>{len(articles)} tin tức nóng nhất trong {lookback_hours}h qua</b> - {today.strftime('%d/%m/%Y')}\n"
    if gemini_api_key:
        header_msg += "🤖 Đã bật tóm tắt AI bằng Gemini\n"
    send_telegram_message(token=token, chat_id=chat_id, text=header_msg)

    sent_total = 0

    for i, article in enumerate(articles, start=1):
        try:
            ai_summary = None
            if gemini_api_key:
                ai_summary = summarize_with_gemini(article, gemini_api_key)

            if send_article_to_telegram(
                token=token,
                chat_id=chat_id,
                article=article,
                index=i,
                ai_summary=ai_summary,
            ):
                sent_total += 1
        except Exception as e:
            print(f"⚠️ Failed to send hot article #{i}: {_safe_error(e, token, gemini_api_key)}")

    print(f"✅ Sent {sent_total}/{len(articles)} articles to Telegram.")
    return 0 if sent_total == len(articles) else 1


if __name__ == "__main__":
    raise SystemExit(main())
