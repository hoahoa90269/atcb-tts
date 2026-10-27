@echo off
chcp 65001 >nul
rem ATCB Giong doc (Windows): cai uv neu chua co, roi mo cua so cong cu. Khong tat cua so nay khi cong cu dang chay.
cd /d "%~dp0"
if not exist pyproject.toml cd /d ..
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo Lan dau: dang cai uv ^(chi cho tai khoan cua co, khong can quyen quan tri^). Can mang, vai phut...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_NO_MODIFY_PATH=1; irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
)
where uv >nul 2>nul
if errorlevel 1 (
  echo Khong cai duoc uv. Kiem tra mang roi mo lai.
  pause
  exit /b 1
)
echo Dang mo ATCB Giong doc. Lan dau se tai Python va thu vien nen hoi lau. Khong tat cua so nay.
uv run --frozen --extra gui python -m atcb_tts.gui
if errorlevel 1 (
  echo.
  echo Cong cu gap loi. Chup man hinh cua so nay gui nhom ho tro.
  pause
)
