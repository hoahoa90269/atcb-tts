"""Builds ATCB-GiongDoc-<version>.zip for the teachers' tool (spec 12.8). Standard library only.

    uv run make_bundle.py [--out dist] [--url https://where-to-download]

One zip for Windows and macOS. The .command file keeps its execute bit inside the zip.
"""

from __future__ import annotations

import argparse
import re
import stat
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCHER = HERE / "launcher"
ROOT_FILES = ["pyproject.toml", "uv.lock", ".python-version", "make_audio.py", "lexicon.json"]
LAUNCHER_FILES = ["ChayCongCu.bat", "ChayCongCu.command", "HUONG-DAN.txt"]
EXECUTABLE = {"ChayCongCu.command"}


def tool_version() -> str:
    match = re.search(r'TOOL_VERSION\s*=\s*"([^"]+)"', (HERE / "atcb_tts" / "__init__.py").read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("Không đọc được TOOL_VERSION")
    return match.group(1)


def bundle_entries(url: str = "") -> list[tuple[str, bytes, int]]:
    """(path inside the zip, content, unix mode). Launchers and the guide sit at the root, where the teacher looks first."""
    entries: list[tuple[str, bytes, int]] = []
    for name in LAUNCHER_FILES:
        mode = 0o755 if name in EXECUTABLE else 0o644
        entries.append((name, (LAUNCHER / name).read_bytes(), mode))
    for name in ROOT_FILES:
        entries.append((name, (HERE / name).read_bytes(), 0o644))
    for path in sorted((HERE / "atcb_tts").glob("*.py")):
        entries.append((f"atcb_tts/{path.name}", path.read_bytes(), 0o644))
    if url:
        entries.append(("tool_url.txt", url.encode("utf-8") + b"\n", 0o644))
    return entries


def build(out_dir: Path, url: str = "") -> Path:
    version = tool_version()
    folder = f"ATCB-GiongDoc-{version}"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{folder}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content, mode in bundle_entries(url):
            info = zipfile.ZipInfo(f"{folder}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3  # Unix, so the mode below is honoured by macOS
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Đóng gói công cụ ATCB Giọng đọc cho cô.")
    parser.add_argument("--out", type=Path, default=HERE / "dist")
    parser.add_argument("--url", default="", help="đường dẫn tải bản mới, hiện trong thông báo “Cần tải bản mới”")
    args = parser.parse_args(argv)
    print(build(args.out, args.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
