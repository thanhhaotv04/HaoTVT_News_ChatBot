# HaoTVT — Trợ lý tin tức trên Telegram

**Nhận bản tin mỗi sáng ngay trên Telegram.** Dự án tự động tổng hợp tin Việt Nam, quốc tế và công nghệ, kèm tóm tắt ngắn, hình ảnh và liên kết đọc bài gốc.

## Nội dung bản tin

Theo cấu hình mặc định, bot chọn tin trong **24 giờ gần nhất** với số lượng tối đa cho mỗi nhóm:

| Nhóm tin | Số lượng | Nguồn tin |
| --- | --- | --- |
| Việt Nam | 10 tin | VnExpress |
| Quốc tế | 5 tin | BBC, The Guardian, Al Jazeera |
| Công nghệ | 3 tin | BBC, The Guardian, TechCrunch |

Số tin thực tế phụ thuộc vào các bài mới có sẵn từ nguồn tin.

## Chức năng chính

- **Tổng hợp tự động:** lọc bài theo thời gian, loại bỏ liên kết trùng lặp và ưu tiên tin mới.
- **Đọc nhanh trên Telegram:** mỗi tin hiển thị tiêu đề, phần tóm tắt, nguồn và liên kết đọc đầy đủ.
- **Gửi ảnh minh họa:** tin quốc tế và công nghệ chỉ chọn bài có ảnh; nếu gửi ảnh thất bại, bot chuyển sang gửi văn bản.
- **Tóm tắt bằng Gemini:** khi có khóa truy cập, bot tạo tóm tắt ngắn bằng tiếng Việt. Khi không dùng được Gemini, bot dùng mô tả từ nguồn tin.
- **Gửi bản tin mỗi sáng:** GitHub Actions được đặt lịch chính lúc **06:30 giờ Việt Nam**, có lượt dự phòng lúc 06:40 và 06:50 cùng cơ chế kiểm tra để hạn chế gửi lặp trong ngày.

## Cấu hình để nhận tin

Trong phần cài đặt kho mã trên GitHub, lưu các giá trị sau dưới dạng thông tin bí mật cho GitHub Actions:

| Tên cấu hình | Ý nghĩa |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Mã truy cập bot Telegram, lấy từ `@BotFather`. |
| `TELEGRAM_CHAT_ID` | Mã cuộc trò chuyện hoặc nhóm nhận bản tin. |
| `GEMINI_API_KEY` | Khóa truy cập Gemini để tóm tắt tin; không bắt buộc. |

Bật GitHub Actions để chạy theo lịch. Bạn cũng có thể chạy thủ công khi muốn nhận bản tin ngay.

## Chạy trên máy

Dự án sử dụng Python. Tại thư mục dự án, chạy:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python telegram_news_bot.py
```

Nếu chưa đặt `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID` trong biến môi trường, chương trình chỉ hiển thị bản tin xem trước trên màn hình. Khi đã đặt đủ hai giá trị, chương trình sẽ gửi tin qua Telegram.

Có thể điều chỉnh khoảng thời gian lấy tin bằng `ARTICLE_LOOKBACK_HOURS` và số lượng từng nhóm bằng `VIETNAM_NEWS_COUNT`, `INTERNATIONAL_NEWS_COUNT`, `TECHNOLOGY_NEWS_COUNT`. Khi chạy bằng GitHub Actions, sửa các giá trị tương ứng trong [tệp lịch gửi tin](.github/workflows/daily_news.yml).

Để chạy bộ kiểm thử trong môi trường Python đã kích hoạt:

```bash
pytest -q
```
