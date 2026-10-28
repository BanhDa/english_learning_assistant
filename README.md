# Trợ lý học tiếng Anh (Telegram + Claude)

Bot Telegram riêng cho hai người. Trong ngày bot tự nhắc: từ mới, ôn từ, bài tập, hội thoại.
Giải thích và sửa lỗi bằng tiếng Việt. Dữ liệu lưu trong một file SQLite trên máy bạn.

## Tính năng

| Lệnh | Việc làm |
|---|---|
| `/words [n]` | Claude chọn n từ mới theo trình độ, mục tiêu, sở thích; bot gửi mỗi từ thành một ảnh flashcard (từ, phiên âm IPA, loại từ, nghĩa, ví dụ) và lưu vào danh sách ôn |
| `/review` | Ôn từ đến hạn bằng thẻ nhớ (nhớ lại chủ động, lặp lại ngắt quãng kiểu Leitner) |
| `/exercise [n]` | Bài tập trắc nghiệm, điền từ, dịch Việt-Anh, sửa lỗi; ưu tiên từ hay quên và lỗi gần đây |
| `/practice [chủ đề]` | Hội thoại tiếng Anh, bot sửa lỗi sau mỗi tin nhắn và ghi lỗi để luyện lại |
| `/ask ...` hoặc gõ thẳng | Hỏi ngữ pháp, từ vựng; bot trả lời bằng tiếng Việt |
| `/reminders`, `/remind` | Bật/tắt và đổi giờ nhắc; mặc định từ mới 6 lần/ngày (07:30, 09:30, 11:00, 14:30, 16:00, 19:00), ôn từ 12:30 và 20:00, bài tập 17:30, hội thoại 21:00 (giờ Việt Nam) |
| `/plan`, `/lesson`, `/nextweek` | Xem giáo án, bài học ngữ pháp của tuần, hoặc sang tuần kế ngay |
| `/level /goal /interests /tz` | Cá nhân hóa (mỗi người một hồ sơ riêng) |
| `/stats`, `/pause`, `/deleteme` | Tiến độ, tạm dừng nhắc, xóa dữ liệu |

Mỗi bot chỉ trả lời các ID khai báo cho nó (`BOTn_USER_IDS`). Người lạ chỉ nhận lại ID của chính họ.
Mỗi người có giới hạn `MAX_LLM_CALLS_PER_DAY` lần gọi Claude mỗi ngày để tránh chi phí bất ngờ.

## Nội dung học lấy từ đâu

- **Giáo án**: file `curriculum.toml`, 8 tuần cho mỗi cấp A1, A2, B1, B2, C1 (C2 dùng chung C1). Mỗi tuần có một chủ điểm
  ngữ pháp và một chủ đề từ vựng. Mỗi người đi theo giáo án của trình độ mình, tự chuyển tuần sau 7 ngày
  (khoảng 7 giờ sáng giờ địa phương) hoặc dùng `/nextweek`. Đổi cấp bằng `/level` thì giáo án bắt đầu lại từ tuần 1.
  Giáo án này soạn theo thang CEFR phổ biến, bạn nên chỉnh cho khớp với sách hoặc khóa học hai bạn đang theo.
- **Nội dung chi tiết**: do Claude soạn dựa trên chủ điểm của tuần. Từ mới bám chủ đề tuần, bài tập dành khoảng 60%
  cho ngữ pháp của tuần, hội thoại dẫn người học dùng cấu trúc của tuần. Bài học `/lesson` được soạn một lần cho mỗi
  cấp và tuần rồi lưu lại, những lần sau không tốn thêm lượt gọi Claude.
- **Danh sách từ riêng (tùy chọn)**: tạo file `wordlists/B1.txt` (tên theo cấp, mỗi dòng một từ, dòng bắt đầu bằng `#`
  là ghi chú). Nếu file tồn tại, `/words` lấy đúng các từ chưa học theo thứ tự trong file, Claude chỉ soạn nghĩa và ví dụ.
  Repo không kèm sẵn danh sách nào, vì các danh sách như Oxford 3000 có điều kiện bản quyền riêng.
- Claude có thể mắc lỗi hoặc diễn đạt chưa tự nhiên. Nếu nghi ngờ, hỏi lại bằng `/ask` hoặc đối chiếu từ điển.

## Phiên âm và flashcard

- **Phiên âm IPA** lấy từ [dictionaryapi.dev](https://dictionaryapi.dev) (miễn phí, không cần key) cho từ đơn. Cụm từ hoặc từ
  không có trong từ điển thì dùng phiên âm Claude đưa ra, nên phần này có thể chưa chính xác tuyệt đối. Mất mạng hoặc từ điển
  lỗi không làm hỏng bài học.
- **Flashcard** là ảnh PNG vẽ bằng Pillow (`src/study_bot/cards.py`), chiều cao tự co giãn theo nội dung. Nếu không vẽ hoặc
  không gửi được ảnh, bot tự gửi bản chữ.
- Font Noto Sans (giấy phép SIL OFL 1.1) nằm trong `src/study_bot/assets/fonts/`, hỗ trợ ký tự IPA và tiếng Việt.
- Thẻ chỉ có chữ và ký hiệu, chưa có hình minh họa cho nghĩa của từ.

## Cài đặt

Yêu cầu: Python 3.11+, [uv](https://docs.astral.sh/uv/).

Mỗi người dùng một bot Telegram riêng, nhưng cả hai bot chạy trong **một chương trình duy nhất**. Khi đến giờ nhắc,
chương trình gửi nhắc của mỗi người qua đúng bot của người đó. Dữ liệu học vẫn tách riêng theo từng người.

1. Tạo hai bot với [@BotFather](https://t.me/BotFather) (`/newbot`, mỗi lần một bot), lấy hai token.
2. Lấy API key tại <https://console.anthropic.com>.
3. Cài đặt và tạo file cấu hình:
   ```bash
   uv venv --python 3.11 .venv
   uv pip install -e . --python .venv/bin/python
   cp .env.example .env
   ```
   Trong `.env` điền `ANTHROPIC_API_KEY`, rồi `BOT1_TOKEN` và `BOT2_TOKEN` (có thể đặt tên ở `BOT1_NAME`, `BOT2_NAME`).
   Để trống `BOT1_USER_IDS` và `BOT2_USER_IDS` ở bước này.
4. Chạy lần đầu để lấy ID: `.venv/bin/python -m study_bot`. Mỗi người mở bot của mình và nhắn `/start`,
   bot sẽ trả lại ID Telegram của người đó. Điền vào `BOT1_USER_IDS` và `BOT2_USER_IDS`, dừng chương trình (Ctrl+C) rồi chạy lại.
5. Mỗi người nhắn `/start` cho bot của mình, chọn trình độ, đặt `/goal` và `/interests`.

Thêm người thứ ba: tạo thêm một bot, thêm `BOT3_TOKEN` và `BOT3_USER_IDS` vào `.env`, chạy lại chương trình.
Một người chỉ được dùng một bot (chương trình báo lỗi nếu cùng một ID xuất hiện ở hai bot).
Chỉ dùng một bot thì có thể giữ cách cũ: `TELEGRAM_BOT_TOKEN` và `ALLOWED_USER_IDS`.

Chương trình phải đang chạy thì mới nhắc được. Muốn chạy liên tục, đặt nó trên một máy luôn bật (VPS, Raspberry Pi,
hoặc Mac không ngủ), chạy dưới `launchd`/`systemd`/`tmux`. Khi dừng bằng Ctrl+C, cả hai bot dừng gọn.

## Chi phí

Mặc định dùng `claude-haiku-4-5`, rẻ nhất. Mỗi lệnh `/words`, `/exercise` hay mỗi tin nhắn hội thoại là một lần gọi Claude.
Ôn từ (`/review`) không gọi Claude nên miễn phí. Xem chi phí thực tế tại console.anthropic.com. Có thể đổi model trong `.env`.

## Cấu trúc

```
src/study_bot/
  main.py       khởi tạo bot, đăng ký handler, vòng lặp nhắc mỗi 60 giây
  handlers.py   lệnh, nút bấm, kiểm tra quyền, gửi nhắc
  flows.py      luồng từ mới, ôn từ, bài tập, hội thoại
  llm.py        gọi Claude (đầu ra có cấu trúc qua tool use)
  db.py         SQLite
  srs.py        lịch ôn tập ngắt quãng
  reminders.py  tính giờ nhắc theo múi giờ
```

## Hạn chế hiện tại

- Chỉ dùng văn bản (chưa có giọng nói/phát âm).
- Trạng thái đang làm dở (bài tập, hội thoại) nằm trong bộ nhớ, bị mất khi khởi động lại bot. Từ vựng và tiến độ thì được lưu.
- Tin nhắn được xử lý lần lượt, nên khi một người đang chờ Claude trả lời, người còn lại chờ vài giây.
