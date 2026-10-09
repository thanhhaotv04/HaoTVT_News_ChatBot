# HaoTVT News ChatBot

Bot Python tong hop 10 tin Viet Nam, 5 tin quoc te va 3 tin cong nghe trong 24h gan nhat, tom tat bang Gemini neu co API key, roi gui qua Telegram luc 6:30 sang moi ngay bang GitHub Actions.

## Chuc nang

- Loc tin theo khung thoi gian `ARTICLE_LOOKBACK_HOURS`, mac dinh 24h.
- Gui ba muc rieng: `VIETNAM_NEWS_COUNT=10`, `INTERNATIONAL_NEWS_COUNT=5`, `TECHNOLOGY_NEWS_COUNT=3`.
- Tin Viet Nam lay tu cac chuyen muc trong nuoc cua VNExpress; tin quoc te lay tu BBC World, The Guardian World va Al Jazeera.
- Tin cong nghe lay tu BBC Technology, The Guardian Technology va TechCrunch.
- Tin quoc te va cong nghe chi chon bai co anh RSS; ho tro `media:thumbnail`, `media:content`, enclosure va anh trong HTML.
- Tu dong dedupe URL va uu tien bai co thoi gian dang moi nhat.
- Moi bai hien thi ro nguon; mot nguon loi khong lam mat cac muc tin con lai.
- Gui anh kem caption neu co anh RSS; neu anh loi thi fallback sang tin nhan text.
- Escape HTML va cat noi dung theo gioi han Telegram de tranh loi `parse_mode=HTML`.
- Moi tin co link `Doc bai goc`, ke ca khi RSS khong co anh.
- Gemini tom tat ngan theo tung section (toi da 3 request thay vi 18), co fallback model va fallback RSS khi AI loi.
- Che token/API key trong log loi va bao loi workflow neu gui thieu tin.
- GitHub Actions chay test truoc khi gui tin.

## Cau hinh

Tao GitHub Secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GEMINI_API_KEY` tuy chon

Bien moi truong tuy chon:

- `ARTICLE_LOOKBACK_HOURS=24`
- `VIETNAM_NEWS_COUNT=10`
- `INTERNATIONAL_NEWS_COUNT=5`
- `TECHNOLOGY_NEWS_COUNT=3`
- `RSS_INSECURE=1` chi dung khi moi truong local bi loi SSL proxy
- `GEMINI_MODEL=gemini-3.5-flash-lite` de uu tien model tuy chon truoc danh sach fallback

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

Workflow uu tien chay luc `06:30` gio Viet Nam. Hai moc `06:40` va `06:50` la du phong neu GitHub bo mot scheduled run; delivery marker va concurrency dam bao bot chi gui mot lan moi ngay. Nut chay thu cong luon cho phep gui lai khi can.
