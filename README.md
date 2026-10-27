# ATCB Giọng đọc

Công cụ tạo file mp3 giọng đọc tiếng Việt, dùng cho dự án An Toàn Cùng Bé (dạy trẻ mầm non kỹ năng tự bảo vệ). Có hai cách dùng: dòng lệnh để tạo hàng loạt file, và cửa sổ đồ họa để soạn từng câu.

Công cụ chạy offline trên CPU bằng model VieNeu-TTS. Model được tải từ Hugging Face lần đầu chạy, repo này không chứa model hay giọng.

## Điều kiện sử dụng

**Model và giọng đọc chỉ dùng phi thương mại.** Model VieNeu-TTS-v3-Turbo và giọng Kim Thanh do Phạm Nguyễn Ngọc Bảo (pnnbao-ump) phát triển. Khi dùng, cần ghi công tác giả. Chi tiết xem [Ghi công và giấy phép](#ghi-công-và-giấy-phép) bên dưới.

## Cài đặt

Cần [uv](https://docs.astral.sh/uv/). Không cần ffmpeg.

```bash
uv sync               # GPU NVIDIA: uv sync --extra cuda
```

Lần đầu chạy, VieNeu tải model từ Hugging Face (cần mạng).

## Tạo giọng

```bash
uv run make_audio.py đường-dẫn/tới/file-xuất.json --out ./out
```

File xuất có định dạng `atcb-tts-export`. Tùy chọn:

- `--voice "Kim Thanh"`: chọn giọng.
- `--limit 3`: chỉ tạo vài câu để nghe thử.
- `--force`: tạo lại dù đã có file, dùng sau khi sửa `lexicon.json`.
- `--jobs N`: chạy N tiến trình song song, mỗi tiến trình nạp model riêng và khoảng 1 GB RAM. Không đặt thì tự chọn theo số nhân CPU và RAM, tối đa 3. Có thể đặt biến môi trường `ATCB_TTS_JOBS`.

Mặc định bỏ qua file đã có. Kết quả là các file `<owner>__<slot>__<text_hash>.mp3` và `out/report.csv`.

Mỗi file mp3 mono 24 kHz, 64 kbps, đã cân âm lượng, có tag ID3 `atcb` (`model=…;voice=…;tool=…;text_hash=…`).

`lexicon.json` sửa cách đọc riêng cho giọng nói (ví dụ `"QR": "kiu a"`). Sửa lexicon không đổi `text_hash`.

## Kiểm thử phần thuần (không cần VieNeu)

```bash
uv run --no-project --with numpy --with soxr --with lameenc --with pyloudnorm python -m unittest discover -s tests -t .
# hoặc, khi đã `uv sync`: uv run python -m unittest discover -s tests -t .
```

## Cửa sổ đồ họa và gói cài cho người dùng

Cửa sổ PySide6 (`atcb_tts/gui.py`) dùng chung lõi `core.py`:

```bash
uv run --extra gui python -m atcb_tts.gui          # mở cửa sổ
uv run make_bundle.py [--url <link tải>]           # tạo dist/ATCB-GiongDoc-<version>.zip (Windows + Mac)
```

`launcher/` có `ChayCongCu.bat`, `ChayCongCu.command` và `HUONG-DAN.txt`; `make_bundle.py` đặt chúng ở gốc thư mục zip. Nghe thử dùng trình phát có sẵn của máy (`afplay` trên Mac, MCI trên Windows), không cần thư viện âm thanh.

Chưa thử trên Windows và Mac thật.

## Ghi công và giấy phép

- **Model VieNeu-TTS-v3-Turbo và giọng Kim Thanh**: tác giả Phạm Nguyễn Ngọc Bảo (pnnbao-ump). Theo điều khoản đi kèm, chỉ dùng phi thương mại và cần ghi công tác giả. Trang model: https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo
- **SDK `vieneu`** (Apache-2.0): https://github.com/pnnbao97/VieNeu-TTS
- **Codec MOSS-Audio-Tokenizer-Nano** (OpenMOSS-Team) và **sea-g2p**: thành phần của model. Xem giấy phép tại trang của từng thành phần.
- **PySide6** (giao diện): theo giấy phép của Qt.

Giấy phép cho mã trong repo này chưa được chọn.
