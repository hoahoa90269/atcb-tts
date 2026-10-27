#!/bin/bash
# ATCB Giọng đọc (macOS): cài uv nếu chưa có, rồi mở cửa sổ công cụ. Không tắt cửa sổ này khi công cụ đang chạy.
cd "$(dirname "$0")" || exit 1
[ -f pyproject.toml ] || cd .. || exit 1
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "Lần đầu: đang cài uv (chỉ cho tài khoản của cô, không cần quyền quản trị). Cần mạng, vài phút..."
  curl -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 sh || { echo "Không cài được uv. Kiểm tra mạng rồi mở lại."; read -r -n 1 -p "Bấm phím bất kỳ để đóng."; exit 1; }
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "Đang mở ATCB Giọng đọc. Lần đầu sẽ tải Python và thư viện nên hơi lâu. Không tắt cửa sổ này."
uv run --frozen --extra gui python -m atcb_tts.gui || { echo; echo "Công cụ gặp lỗi. Chụp màn hình cửa sổ này gửi nhóm hỗ trợ."; read -r -n 1 -p "Bấm phím bất kỳ để đóng."; }
