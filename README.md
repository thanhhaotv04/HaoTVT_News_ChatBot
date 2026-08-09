# HaoTVT News ChatBot

Bot Python lay tin moi tu RSS VNExpress, loc khoang 15 tin nong nhat trong 24h gan nhat, tom tat bang Gemini neu co API key, roi gui qua Telegram luc 6:00 sang moi ngay bang GitHub Actions.

## Chuc nang

- Loc tin theo khung thoi gian `ARTICLE_LOOKBACK_HOURS`, mac dinh 24h.
- Gui mot danh sach `NEWS_ARTICLE_COUNT`, mac dinh 15 tin.
- Gom ung vien tu feed `tin-moi-nhat` va cac chuyen muc quan trong.
- Tu dong dedupe URL va uu tien bai co thoi gian dang moi nhat.
- Gui anh kem caption neu co anh RSS; neu anh loi thi fallback sang tin nhan text.
- Escape HTML va cat noi dung theo gioi han Telegram de tranh loi `parse_mode=HTML`.
- Gemini co fallback model de bot van chay khi mot model bi quota/khong kha dung.
- GitHub Actions chay test truoc khi gui tin.

## Cau hinh

Tao GitHub Secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GEMINI_API_KEY` tuy chon

Bien moi truong tuy chon:

- `ARTICLE_LOOKBACK_HOURS=24`
- `NEWS_ARTICLE_COUNT=15`
- `RSS_INSECURE=1` chi dung khi moi truong local bi loi SSL proxy

## Chay local

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python telegram_news_bot.py
```

Neu chua cau hinh Telegram token/chat id, lenh tren se chi preview cac tin nong trong 24h gan nhat.

## Test

```bash
. .venv/bin/activate
pytest -q
```

## Lich GitHub Actions

Workflow `.github/workflows/daily_news.yml` chi chay luc `23:00 UTC`, tuong duong `06:00` gio Viet Nam ngay hom sau.
