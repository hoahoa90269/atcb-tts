"""Command line for the dev team: `uv run make_audio.py <export.json> --out ./out` (spec 12.3)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import os

from .core import ExportError, auto_jobs, load_export, load_lexicon, make_all
from .defaults import MODEL, VOICE

HERE = Path(__file__).resolve().parent.parent


def resolve_jobs(flag: int | None, env: str | None) -> int:
    """--jobs wins, then ATCB_TTS_JOBS, then a number picked for this machine."""
    for value in (flag, env):
        try:
            if value is not None and int(value) >= 1:
                return int(value)
        except ValueError:
            pass
    return auto_jobs()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tạo mp3 giọng đọc từ file atcb-tts-export.")
    parser.add_argument("export", type=Path, help="file .json xuất từ web (hoặc npm run content:export)")
    parser.add_argument("--out", type=Path, default=Path("out"), help="thư mục ghi mp3")
    parser.add_argument("--voice", default=None, help=f"tên giọng (mặc định theo file xuất, thường là {VOICE})")
    parser.add_argument("--only-missing", action="store_true", default=True, help="bỏ qua file đã có (mặc định)")
    parser.add_argument("--force", action="store_true", help="tạo lại dù đã có file (sau khi sửa lexicon.json)")
    parser.add_argument("--limit", type=int, default=None, help="chỉ tạo n câu đầu để nghe thử")
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="số tiến trình chạy song song, mỗi tiến trình nạp model riêng (~1 GB RAM). Mặc định tự chọn theo máy (tối đa 3); "
        "cũng đọc biến ATCB_TTS_JOBS",
    )
    parser.add_argument("--lexicon", type=Path, default=HERE / "lexicon.json")
    args = parser.parse_args(argv)

    try:
        export = load_export(args.export)
        if export.model != MODEL:
            print(f"Cảnh báo: file xuất dùng model {export.model}, công cụ mặc định là {MODEL}.", file=sys.stderr)
        from tqdm import tqdm

        jobs = resolve_jobs(args.jobs, os.environ.get("ATCB_TTS_JOBS"))
        if jobs > 1:
            print(f"Chạy {jobs} tiến trình song song.", file=sys.stderr)

        bar = tqdm(total=min(len(export.items), args.limit or len(export.items)), unit="câu")

        def progress(_i, _n, item, status):
            bar.update(1)
            if status.startswith("error"):
                tqdm.write(f"  {item.file}: {status}")

        report = make_all(
            export,
            args.out,
            voice_name=args.voice,
            lexicon=load_lexicon(args.lexicon),
            only_missing=not args.force,
            limit=args.limit,
            jobs=jobs,
            on_progress=progress,
        )
        bar.close()
    except ExportError as err:
        print(err, file=sys.stderr)
        return 1
    failed = [r for r in report if r["status"].startswith("error")]
    made = sum(r["status"] == "ok" for r in report)
    print(f"Xong: {made} file mới, {sum(r['status'] == 'skipped' for r in report)} bỏ qua, {len(failed)} lỗi. Báo cáo: {args.out / 'report.csv'}")
    return 1 if failed else 0
