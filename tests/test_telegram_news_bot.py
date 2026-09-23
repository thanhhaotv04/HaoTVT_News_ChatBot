from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests

import telegram_news_bot as bot


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = "OK", headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def _entry(title: str, link: str, published_at: datetime, summary: str = "", image_url: str | None = None):
    summary_html = summary
    if image_url:
        summary_html = f'<img src="{image_url}" /> {summary}'
    return SimpleNamespace(
        title=title,
        link=link,
        published_parsed=published_at.astimezone(timezone.utc).timetuple(),
        summary=summary_html,
    )


def test_fetch_articles_filters_last_24h_sorts_and_dedupes(monkeypatch):
    now = datetime(2026, 8, 7, 9, 0, tzinfo=bot.VN_TZ)
    since = now - timedelta(hours=24)
    entries = [
        _entry("old", "https://example.com/old", now - timedelta(hours=25)),
        _entry("duplicate older", "https://example.com/a", now - timedelta(hours=2)),
        _entry("newest", "https://example.com/b", now - timedelta(minutes=20)),
        _entry("duplicate newest", "https://example.com/a", now - timedelta(minutes=10)),
    ]
    monkeypatch.setattr(bot, "fetch_vnexpress_latest_raw", lambda _url: SimpleNamespace(entries=entries))

    articles = bot.fetch_articles_from_feed("https://rss.test", limit=5, since=since)

    assert [a.title for a in articles] == ["duplicate newest", "newest"]
    assert all(a.published_at and a.published_at >= since for a in articles)


def test_fetch_hot_articles_merges_feeds_and_limits(monkeypatch):
    now = datetime(2026, 8, 9, 6, 0, tzinfo=bot.VN_TZ)
    since = now - timedelta(hours=24)
    feed_articles = {
        bot.VNEXPRESS_RSS_FEEDS["tin-moi-nhat"]: [
            bot.Article("A", "https://example.com/a", now - timedelta(minutes=1)),
            bot.Article("B", "https://example.com/b", now - timedelta(minutes=2)),
            bot.Article("old", "https://example.com/old", now - timedelta(hours=30)),
        ],
        bot.VNEXPRESS_RSS_FEEDS["thoi-su"]: [
            bot.Article("A duplicate", "https://example.com/a", now - timedelta(minutes=3)),
            bot.Article("C", "https://example.com/c", now - timedelta(minutes=4)),
        ],
        bot.VNEXPRESS_RSS_FEEDS["the-gioi"]: [
            bot.Article("D", "https://example.com/d", now - timedelta(minutes=5)),
        ],
    }

    def fake_fetch(rss_url, limit=3, *, since=None):
        articles = feed_articles[rss_url]
        return [a for a in articles if since is None or (a.published_at and a.published_at >= since)][:limit]

    monkeypatch.setattr(bot, "fetch_articles_from_feed", fake_fetch)

    articles = bot.fetch_hot_articles(
        limit=3,
        since=since,
        feed_keys=("tin-moi-nhat", "thoi-su", "the-gioi"),
    )

    assert [a.title for a in articles] == ["A", "B", "C"]
    assert len({a.link for a in articles}) == 3


def test_format_article_caption_escapes_html_and_respects_limit():
    article = bot.Article(
        title="A <hot> & important",
        link="https://example.com/a",
        summary="Summary with <b>bad html</b> & details " + ("x" * 200),
    )

    caption = bot.format_article_caption(article, 1, max_length=120)

    assert len(caption) <= 120
    assert "<b>1. A &lt;hot&gt; &amp; important</b>" in caption
    assert "&lt;b&gt;bad" in caption
    assert "<b>bad" not in caption


def test_format_article_caption_keeps_valid_html_and_adds_source_link():
    article = bot.Article("x" * 120, "https://example.com/a?x=1&y=2", summary="A & B")

    short_caption = bot.format_article_caption(article, 1, max_length=40)
    full_caption = bot.format_article_caption(article, 1, max_length=300)

    assert len(short_caption) <= 40
    assert short_caption.startswith("<b>1. ") and short_caption.endswith("</b>")
    assert '<a href="https://example.com/a?x=1&amp;y=2">' in full_caption
    assert "🔗 Đọc bài gốc" in full_caption


def test_extract_summary_decodes_html_entities():
    entry = SimpleNamespace(summary="<p>A &amp; B</p>", description="")

    assert bot._extract_summary(entry) == "A & B"


def test_send_article_falls_back_to_text_when_photo_fails(monkeypatch):
    calls = []
    article = bot.Article(
        title="Photo story",
        link="https://example.com/photo",
        image_url="https://example.com/photo.jpg",
        summary="short",
    )

    def fail_photo(**_kwargs):
        raise requests.HTTPError("bad photo")

    def record_message(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(bot, "send_telegram_photo", fail_photo)
    monkeypatch.setattr(bot, "send_telegram_message", record_message)

    assert bot.send_article_to_telegram(token="t", chat_id="c", article=article, index=1)
    assert calls and calls[0]["text"].startswith("<b>1. Photo story</b>")


def test_post_with_retries_retries_429(monkeypatch):
    responses = [
        FakeResponse(429, headers={"Retry-After": "0"}),
        FakeResponse(200),
    ]
    monkeypatch.setattr(bot.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(bot.requests, "post", lambda *_args, **_kwargs: responses.pop(0))

    response = bot._post_with_retries("https://api.test", attempts=2)

    assert response.status_code == 200
    assert responses == []


def test_post_with_retries_uses_telegram_retry_after(monkeypatch):
    responses = [
        FakeResponse(429, payload={"parameters": {"retry_after": 2}}),
        FakeResponse(200),
    ]
    delays = []
    monkeypatch.setattr(bot.time, "sleep", delays.append)
    monkeypatch.setattr(bot.requests, "post", lambda *_args, **_kwargs: responses.pop(0))

    bot._post_with_retries("https://api.test", attempts=2)

    assert delays == [2]


def test_generate_gemini_text_uses_model_fallback(monkeypatch):
    urls = []
    payload = {"candidates": [{"content": {"parts": [{"text": "Tóm tắt tốt"}]}}]}
    responses = [FakeResponse(404), FakeResponse(200, payload=payload)]

    def fake_post(url, **_kwargs):
        urls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(bot.requests, "post", fake_post)

    text = bot._generate_gemini_text(
        prompt="hello",
        api_key="key",
        temperature=0.1,
        max_output_tokens=32,
    )

    assert text == "Tóm tắt tốt"
    assert len(urls) == 2
    assert "gemini-3.5-flash-lite" in urls[0]
    assert "gemini-3.6-flash" in urls[1]


def test_generate_gemini_text_redacts_api_key_from_errors(monkeypatch, capsys):
    api_key = "secret-api-key"

    def fail_post(url, **_kwargs):
        raise requests.ConnectionError(f"failed: {url}?key={api_key}")

    monkeypatch.setattr(bot, "GEMINI_MODEL_FALLBACK", ("test-model",))
    monkeypatch.setattr(bot.requests, "post", fail_post)
    monkeypatch.setattr(bot.time, "sleep", lambda _seconds: None)

    assert bot._generate_gemini_text(
        prompt="hello",
        api_key=api_key,
        temperature=0.1,
        max_output_tokens=32,
    ) is None
    output = capsys.readouterr().out
    assert api_key not in output
    assert "<redacted>" in output


def test_telegram_exception_does_not_expose_token(monkeypatch):
    token = "123456:secret-token"

    def fail_post(url, **_kwargs):
        raise requests.ConnectionError(f"failed: {url}")

    monkeypatch.setattr(bot, "_post_with_retries", fail_post)

    with pytest.raises(RuntimeError) as error:
        bot.send_telegram_message(token=token, chat_id="chat", text="hello")

    assert token not in str(error.value)
    assert "<redacted>" in str(error.value)


def test_main_uses_actual_article_count_and_reports_partial_failure(monkeypatch, capsys):
    token = "123456:secret-token"
    articles = [
        bot.Article("A", "https://example.com/a"),
        bot.Article("B", "https://example.com/b"),
    ]
    messages = []
    attempts = 0

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(bot, "fetch_hot_articles", lambda **_kwargs: articles)
    monkeypatch.setattr(bot, "send_telegram_message", lambda **kwargs: messages.append(kwargs["text"]))

    def send_article(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise requests.HTTPError(f"failed https://api.telegram.org/bot{token}/sendMessage")
        return True

    monkeypatch.setattr(bot, "send_article_to_telegram", send_article)

    assert bot.main() == 1
    assert "<b>2 tin tức" in messages[0]
    assert token not in capsys.readouterr().out


def test_main_reports_empty_feed_to_telegram(monkeypatch):
    messages = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(bot, "fetch_hot_articles", lambda **_kwargs: [])
    monkeypatch.setattr(bot, "send_telegram_message", lambda **kwargs: messages.append(kwargs["text"]))

    assert bot.main() == 1
    assert messages == ["⚠️ Không tìm thấy tin nào trong 24h gần nhất"]
