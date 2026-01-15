"""
AI News Chatbot - Telegram Bot gửi tin tức VNExpress mỗi sáng

Bot tự động lấy tin nóng từ các chủ đề:
- 3 tin Công nghệ, Chính trị, Kinh tế (Việt Nam)
- 4 tin Thế giới
Gửi qua Telegram mỗi sáng kèm hình ảnh (không có link).

Cấu hình:
  - TELEGRAM_BOT_TOKEN: Token bot từ @BotFather
  - TELEGRAM_CHAT_ID: ID chat để nhận tin (user hoặc group)

Cách chạy:
  python telegram_news_bot.py
"""
from __future__ import annotations

import calendar
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, List, Tuple

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

# RSS feeds cho các chủ đề
VNEXPRESS_RSS_FEEDS = {
    "cong-nghe": "https://vnexpress.net/rss/cong-nghe.rss",
    "chinh-tri": "https://vnexpress.net/rss/chinh-tri.rss",
    "kinh-te": "https://vnexpress.net/rss/kinh-te.rss",
    "the-gioi": "https://vnexpress.net/rss/the-gioi.rss",
}


def _get_vn_timezone() -> timezone:
    """Lấy timezone Việt Nam (UTC+7)."""
    try:
        from zoneinfo import ZoneInfo  # type: ignore

        return ZoneInfo("Asia/Ho_Chi_Minh")  # type: ignore[return-value]
    except Exception:
        return timezone(timedelta(hours=7))


VN_TZ = _get_vn_timezone()


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
                href = enc.get("href", "").strip()
                if href:
                    return href

    # Ưu tiên 2: Parse từ summary HTML (tìm thẻ <img>)
    summary = getattr(entry, "summary", "") or ""
    if summary:
        # Tìm pattern <img src="...">
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, re.IGNORECASE)
        if img_match:
            img_url = img_match.group(1).strip()
            if img_url:
                return img_url

    return None


def _extract_summary(entry) -> str:
    """Trích xuất summary/description từ RSS entry (loại bỏ HTML tags và links)."""
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    if summary:
        # Loại bỏ HTML tags
        summary = re.sub(r"<[^>]+>", "", summary)
        summary = summary.strip()
        # Loại bỏ các link URL (http/https)
        summary = re.sub(r"https?://[^\s]+", "", summary)
        summary = re.sub(r"www\.[^\s]+", "", summary)
        summary = " ".join(summary.split())  # Normalize whitespace
        # Giới hạn độ dài
        if len(summary) > 300:
            summary = summary[:300] + "..."
    return summary


def _entry_to_article(entry) -> Article:
    """Chuyển RSS entry thành Article object."""
    title = (getattr(entry, "title", "") or "").strip()
    link = (getattr(entry, "link", "") or "").strip()
    published_parsed = getattr(entry, "published_parsed", None)
    if published_parsed is not None:
        # published_parsed là struct_time UTC.
        dt_utc = datetime.fromtimestamp(calendar.timegm(published_parsed), tz=timezone.utc)
        dt_vn = dt_utc.astimezone(VN_TZ)
    else:
        dt_vn = None

    image_url = _extract_image_url(entry)
    summary = _extract_summary(entry)
    return Article(title=title, link=link, published_at=dt_vn, image_url=image_url, summary=summary)


def fetch_articles_from_feed(rss_url: str, limit: int = 3) -> List[Article]:
    """Lấy tin từ một RSS feed cụ thể."""
    feed = fetch_vnexpress_latest_raw(rss_url)
    all_articles: List[Article] = [_entry_to_article(e) for e in getattr(feed, "entries", [])]
    return all_articles[:limit]


def format_article_caption(article: Article, index: int) -> str:
    """Format caption cho một bài báo (có summary, không có link)."""
    title = article.title or "(Không có tiêu đề)"
    caption = f"<b>{index}. {title}</b>"
    if article.summary:
        caption += f"\n\n{article.summary}"
    return caption


def send_telegram_message(*, token: str, chat_id: str, text: str) -> None:
    """Gửi message qua Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "HTML",
    }
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()


def send_telegram_photo(*, token: str, chat_id: str, photo_url: str, caption: str = "") -> None:
    """Gửi hình ảnh qua Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML",
    }
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()


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

    if not token or not chat_id:
        # Cho phép chạy thử local mà không cần cấu hình đủ env.
        print(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID. "
            "Set these env vars (hoặc GitHub Secrets) để bot gửi tin."
        )
        # Test với một feed
        articles = fetch_articles_from_feed(VNEXPRESS_RSS_FEEDS["cong-nghe"], limit=3)
        print(f"\n📰 Preview - Công nghệ (3 tin):")
        for i, a in enumerate(articles, 1):
            print(f"{i}. {a.title}")
            if a.summary:
                print(f"   {a.summary[:100]}...")
        return 0

    now_vn = datetime.now(VN_TZ)
    today = now_vn.date()

    # Gửi header
    header_msg = f"📰 Tin tức nóng ngày {today.strftime('%d/%m/%Y')}\n"
    send_telegram_message(token=token, chat_id=chat_id, text=header_msg)

    sent_total = 0

    # Gửi tin VN: 3 tin mỗi chủ đề
    vn_topics = {
        "Công nghệ": VNEXPRESS_RSS_FEEDS["cong-nghe"],
        "Chính trị": VNEXPRESS_RSS_FEEDS["chinh-tri"],
        "Kinh tế": VNEXPRESS_RSS_FEEDS["kinh-te"],
    }

    for topic_name, rss_url in vn_topics.items():
        try:
            articles = fetch_articles_from_feed(rss_url, limit=3)
            if articles:
                # Gửi header chủ đề
                topic_header = f"🇻🇳 <b>{topic_name}</b>\n"
                send_telegram_message(token=token, chat_id=chat_id, text=topic_header)

                # Gửi từng tin
                for i, article in enumerate(articles, start=1):
                    try:
                        if article.image_url:
                            caption = format_article_caption(article, i)
                            send_telegram_photo(
                                token=token,
                                chat_id=chat_id,
                                photo_url=article.image_url,
                                caption=caption,
                            )
                        else:
                            caption = format_article_caption(article, i)
                            send_telegram_message(token=token, chat_id=chat_id, text=caption)
                        sent_total += 1
                    except Exception as e:
                        print(f"⚠️ Failed to send article: {e}")
        except Exception as e:
            print(f"⚠️ Failed to fetch {topic_name}: {e}")

    # Gửi tin Thế giới: 4 tin hot nhất
    try:
        world_articles = fetch_articles_from_feed(VNEXPRESS_RSS_FEEDS["the-gioi"], limit=4)
        if world_articles:
            world_header = f"🌍 <b>Thế giới</b>\n"
            send_telegram_message(token=token, chat_id=chat_id, text=world_header)

            for i, article in enumerate(world_articles, start=1):
                try:
                    if article.image_url:
                        caption = format_article_caption(article, i)
                        send_telegram_photo(
                            token=token,
                            chat_id=chat_id,
                            photo_url=article.image_url,
                            caption=caption,
                        )
                    else:
                        caption = format_article_caption(article, i)
                        send_telegram_message(token=token, chat_id=chat_id, text=caption)
                    sent_total += 1
                except Exception as e:
                    print(f"⚠️ Failed to send world article: {e}")
    except Exception as e:
        print(f"⚠️ Failed to fetch Thế giới: {e}")

    print(f"✅ Sent {sent_total} articles to Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
