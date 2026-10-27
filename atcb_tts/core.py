"""Reads an atcb-tts-export file, speaks every text with VieNeu and writes named, tagged mp3 files.

Heavy libraries (vieneu, numpy, soxr, lameenc, pyloudnorm) are imported lazily so the pure parts
(hash, file validation, lexicon, ID3 tag) can be tested without them.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import TOOL_VERSION
from .defaults import BITRATE_KBPS, EXPORT_FORMAT, MAX_SLUG_CHARS, MAX_TEXT_CHARS, MODEL, MODELS, SAMPLE_RATE, SUPPORTED_VERSIONS, VOICE

FILE_PATTERN = re.compile(r"^[a-z0-9-]+__[a-z0-9-]+__[0-9a-f]{8}\.mp3$")
TYPED_FILE_PATTERN = re.compile(r"^[a-z0-9-]+__[0-9a-f]{8}\.mp3$")


class ExportError(Exception):
    """The export file cannot be used; the message is shown to the teacher as is (Vietnamese)."""


def normalize(text: str) -> str:
    """Same as src/lib/speech/textHash.ts: NFC, trim, collapse whitespace."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).strip())


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:8]


@dataclass
class Item:
    file: str
    text: str
    text_hash: str
    slot: str = ""


@dataclass
class Export:
    model: str
    voice: str
    items: list[Item]


def load_export(path: Path) -> Export:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise ExportError(f"Không đọc được file: {err}") from err
    if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT:
        raise ExportError("Đây không phải file xuất từ web An Toàn Cùng Bé (format sai).")
    if data.get("version") not in SUPPORTED_VERSIONS:
        raise ExportError("Cần tải bản mới của công cụ (file xuất có phiên bản mới hơn).")
    items: list[Item] = []
    for raw in data.get("items", []):
        file, text = raw.get("file", ""), raw.get("text", "")
        if not FILE_PATTERN.match(file) or not isinstance(text, str) or not text.strip():
            raise ExportError(f"Mục không hợp lệ trong file xuất: {file!r}")
        if text_hash(text) != raw.get("text_hash"):
            raise ExportError(f"Mã câu chữ (text_hash) không khớp với câu chữ ở {file}")
        items.append(Item(file=file, text=text, text_hash=raw["text_hash"], slot=raw.get("slot", "")))
    return Export(model=data.get("model") or MODEL, voice=data.get("voice") or VOICE, items=items)


def slugify_vi(text: str, max_chars: int = MAX_SLUG_CHARS) -> str:
    """Vietnamese sentence -> ASCII file name part: 'An toàn trong nhà bếp' -> 'an-toan-trong-nha-bep'."""
    plain = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:max_chars].strip("-")
    return slug or "cau"


def typed_items(raw: str) -> tuple[list[Item], list[str]]:
    """The 'Gõ câu' tab: one sentence per line, one mp3 each (spec 12.8).

    Returns (items, notes). Blank lines are dropped silently, a repeated sentence is made once,
    a sentence over MAX_TEXT_CHARS is skipped with a note for the teacher.
    """
    items: list[Item] = []
    notes: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(raw.splitlines(), 1):
        text = normalize(line)
        if not text:
            continue
        if len(text) > MAX_TEXT_CHARS:
            notes.append(f"Dòng {number} dài {len(text)} ký tự (tối đa {MAX_TEXT_CHARS}), đã bỏ qua.")
            continue
        digest = text_hash(text)
        if digest in seen:
            continue
        seen.add(digest)
        items.append(Item(file=f"{slugify_vi(text)}__{digest}.mp3", text=text, text_hash=digest))
    return items, notes


SLOT_LABELS = {
    "question": "Câu hỏi",
    "hint": "Gợi ý",
    "lesson": "Bé rút ra",
    "name": "Tên chủ đề",
    # games (spec 17.6, export version 2)
    "title": "Tên trò chơi",
    "intro": "Lời dẫn",
    "done": "Lời khen",
}
SLOT_NUMBERED = {
    "choice": "Cách",
    "explain": "Giải thích",
    "card": "Thẻ",
    "item": "Chỗ",
    "left": "Bên trái",
    "right": "Bên phải",
    "step": "Bước",
    "basket": "Giỏ",
    "round": "Lượt",
}
SLOT_PARTS = {"who": "người ngoài cửa", "after": "lời dặn", "shout": "câu nói to"}
GAME_SLOT = re.compile(r"^(step|round)-(\d+)-(?:(who|after|shout)|choice-(\d+))$")


def slot_label(slot: str) -> str:
    """Teacher-facing name of an export slot ('choice-2' -> 'Cách 2'); unknown slots are shown as they are."""
    if slot in SLOT_LABELS:
        return SLOT_LABELS[slot]
    game = GAME_SLOT.match(slot)
    if game:
        head, number, part, choice = game.groups()
        return f"{SLOT_NUMBERED[head]} {number}, " + (SLOT_PARTS[part] if part else f"cách {choice}")
    head, _, number = slot.rpartition("-")
    if head in SLOT_NUMBERED and number.isdigit():
        return f"{SLOT_NUMBERED[head]} {number}"
    return slot


def export_scope(export: "Export") -> str:
    """Short name of what an export covers, from its owner ids ('lost-1', or 'lost-1 và 2 phần khác')."""
    owners: list[str] = []
    for item in export.items:
        owner = item.file.split("__")[0]
        if owner not in owners:
            owners.append(owner)
    if not owners:
        return "giong-doc"
    return owners[0] if len(owners) == 1 else f"{owners[0]}-va-{len(owners) - 1}-phan-khac"


def short_voice(label: str) -> str:
    """'⭐ Kim Thanh — Nữ · Nam · Phong cách đọc truyện' -> 'Kim Thanh' (also accepts ' - ' as the separator)."""
    return re.split(r" [—-] ", label.replace("⭐", "").strip())[0].strip()


def voice_details(label: str) -> str:
    """'⭐ Mai Anh — Nữ · Bắc · Phong cách tin tức' -> 'Nữ · Bắc · Phong cách tin tức' ('' when the label has none)."""
    parts = re.split(r" [—-] ", label.replace("⭐", "").strip(), maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def voice_summary(details: str) -> str:
    """'Nữ · Bắc · Phong cách tin tức' -> 'Giới tính: Nữ · Vùng: Bắc · Phong cách tin tức'; other shapes are shown as they are."""
    parts = [part.strip() for part in details.split("·")]
    if len(parts) == 3:
        return f"Giới tính: {parts[0]} · Vùng: {parts[1]} · {parts[2]}"
    return details


def differs_from_default(model: str, voice: str) -> bool:
    return model != MODEL or voice != VOICE


def load_lexicon(path: Path | None) -> dict[str, str]:
    if path is None or not Path(path).exists():
        return {}
    return {str(k): str(v) for k, v in json.loads(Path(path).read_text(encoding="utf-8")).items()}


def apply_lexicon(text: str, lexicon: dict[str, str]) -> str:
    """Spoken form only; the text_hash always comes from the original text."""
    for word, spoken in sorted(lexicon.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", spoken, text)
    return text


def pick_voice(voices: list[tuple[str, str]], wanted: str) -> str:
    """voices = list_preset_voices() pairs of (label, id); returns the id of the first label containing `wanted`."""
    for label, voice_id in voices:
        if wanted.lower() in label.lower():
            return voice_id
    available = "\n".join(f"  - {label}" for label, _ in voices)
    raise ExportError(f"Không thấy giọng “{wanted}”. Các giọng hiện có:\n{available}")


def id3_tag(model: str, voice: str, hash_: str) -> bytes:
    """ID3v2.3 tag with one TXXX frame: atcb = model=..;voice=..;tool=..;text_hash=.. (spec 12.8)."""
    value = f"model={model};voice={voice};tool={TOOL_VERSION};text_hash={hash_}"
    data = b"\x03" + b"atcb\x00" + value.encode("utf-8")  # encoding 3 = UTF-8 (read by id3.ts)
    frame = b"TXXX" + struct.pack(">I", len(data)) + b"\x00\x00" + data
    size = len(frame)
    synchsafe = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    return b"ID3\x03\x00\x00" + synchsafe + frame


def is_current(path: Path, model: str, voice: str, hash_: str) -> bool:
    """True when `path` exists and its atcb tag says it was made by this model and voice for this text."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError:
        return False
    expected = f"model={model};voice={voice};".encode("utf-8")
    return expected in head and f"text_hash={hash_}".encode("utf-8") in head


def mp3_seconds(path: Path) -> float:
    """Length of a file made by encode_mp3 (constant bitrate, see BITRATE_KBPS), after the ID3 tag."""
    data = Path(path).read_bytes()
    start = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        start = 10 + ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 | (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
    return max(len(data) - start, 0) * 8 / (BITRATE_KBPS * 1000)


def encode_mp3(audio, sample_rate: int) -> tuple[bytes, float]:
    """Float mono samples -> (mp3 bytes at SAMPLE_RATE / BITRATE_KBPS, seconds)."""
    import lameenc
    import numpy as np
    import pyloudnorm as pyln
    import soxr

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if sample_rate != SAMPLE_RATE:
        samples = soxr.resample(samples, sample_rate, SAMPLE_RATE)
    try:
        loudness = pyln.Meter(SAMPLE_RATE).integrated_loudness(samples)
        samples = pyln.normalize.loudness(samples, loudness, -20.0)
    except ValueError:  # clip shorter than the meter's block
        pass
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 0.97:
        samples = samples * (0.97 / peak)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(BITRATE_KBPS)
    encoder.set_in_sample_rate(SAMPLE_RATE)
    encoder.set_channels(1)
    encoder.set_quality(2)
    return bytes(encoder.encode(pcm) + encoder.flush()), samples.size / SAMPLE_RATE


def load_engine(model: str):
    """VieNeu engine for one of the models in defaults.MODELS."""
    from vieneu import Vieneu

    if model not in MODELS:
        raise ExportError(f"Model “{model}” chưa được hỗ trợ (có: {', '.join(MODELS)}).")
    return Vieneu(mode=MODELS[model])


MAX_AUTO_JOBS = 3
GB_PER_WORKER = 1.5  # measured ~1 GB per VieNeu worker; keep some headroom
RESERVED_GB = 2.0  # left for the OS and the main process


def total_ram_gb() -> float | None:
    """Physical RAM in GB, or None when it cannot be read (e.g. Windows without psutil)."""
    import os

    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**3
    except (AttributeError, ValueError, OSError):
        return None


def auto_jobs(cpus: int | None = None, ram_gb: float | None = None) -> int:
    """How many worker processes this machine can carry: about one per 3 cores and per 1.5 GB RAM, at most 3.

    Unknown RAM is treated as small (1 worker) so a weak or unusual machine never gets overloaded.
    """
    import os

    cpus = cpus if cpus is not None else (os.cpu_count() or 1)
    ram_gb = ram_gb if ram_gb is not None else total_ram_gb()
    by_cpu = cpus // 3
    by_ram = int((ram_gb - RESERVED_GB) // GB_PER_WORKER) if ram_gb is not None else 1
    return max(1, min(MAX_AUTO_JOBS, by_cpu, by_ram))


def _speak(engine, voice_id, sample_rate, model, voice_name, lexicon, item: Item, target: Path) -> dict:
    """Speaks one item into `target`; a failing sentence is reported, never raised."""
    row = {"file": item.file, "seconds": "", "chars": len(item.text), "status": ""}
    try:
        audio = engine.infer(apply_lexicon(item.text, lexicon or {}), voice=voice_id)
        mp3, seconds = encode_mp3(audio, sample_rate)
        target.write_bytes(id3_tag(model, voice_name, item.text_hash) + mp3)
        row.update(seconds=f"{seconds:.1f}", status="ok")
    except Exception as err:  # noqa: BLE001 - report and carry on with the next sentence
        row["status"] = f"error: {err}"
    return row


_WORKER: dict = {}


def _init_worker(model: str, voice_name: str, lexicon: dict[str, str] | None) -> None:
    """Each worker process loads its own engine (the model is not shared between processes)."""
    engine = load_engine(model)
    _WORKER.update(
        engine=engine,
        voice_id=pick_voice(engine.list_preset_voices(), voice_name),
        sample_rate=int(getattr(engine, "sample_rate", 48000) or 48000),
        model=model,
        voice_name=voice_name,
        lexicon=lexicon,
    )


def _worker_speak(job: tuple[Item, str]) -> dict:
    item, target = job
    w = _WORKER
    return _speak(w["engine"], w["voice_id"], w["sample_rate"], w["model"], w["voice_name"], w["lexicon"], item, Path(target))


def make_all(
    export: Export,
    out_dir: Path,
    *,
    voice_name: str | None = None,
    lexicon: dict[str, str] | None = None,
    only_missing: bool = True,
    limit: int | None = None,
    on_progress: Callable[[int, int, Item, str], None] | None = None,
    engine=None,
    jobs: int = 1,
    on_start: Callable[[Item], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[dict]:
    """Makes every item; returns report rows (file, seconds, chars, status). A failing sentence does not stop the rest.

    `jobs` > 1 runs that many worker processes, each with its own engine (faster, uses more memory).
    `on_start` and `should_stop` work in the single-process path only (what the window uses): the sentence being
    made is reported before it starts, and a stop request is honoured between sentences. Items not reached are
    left out of the report.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    voice_name = voice_name or export.voice
    items = export.items[:limit] if limit else export.items
    # A file made by another model or voice is not 'already there': the choice in the window must take effect.
    todo = [i for i in items if not (only_missing and is_current(out_dir / i.file, export.model, voice_name, i.text_hash))]
    done: dict[str, dict] = {}

    def finish(index: int, item: Item, row: dict) -> None:
        done[item.file] = row
        if on_progress:
            on_progress(index, len(items), item, row["status"])

    skipped = {i.file for i in items} - {i.file for i in todo}
    for index, item in enumerate(items, 1):
        if item.file in skipped:
            finish(index, item, {"file": item.file, "seconds": "", "chars": len(item.text), "status": "skipped"})

    if jobs > 1 and engine is None and len(todo) > 1:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        from concurrent.futures.process import BrokenProcessPool

        workers = min(jobs, len(todo))
        try:
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_init_worker,
                initargs=(export.model, voice_name, lexicon),
            ) as pool:
                results = pool.map(_worker_speak, [(i, str(out_dir / i.file)) for i in todo])
                for item, row in zip(todo, results):
                    finish(len(done) + 1, item, row)
        except BrokenProcessPool:
            pass  # a worker died (usually out of memory): the rest runs below in this process
        todo = [i for i in todo if i.file not in done]
    # Sequential path: jobs=1, a given engine, a single sentence, or what is left after a worker died.
    if todo:
        engine = engine or load_engine(export.model)
        voice_id = pick_voice(engine.list_preset_voices(), voice_name)
        sample_rate = int(getattr(engine, "sample_rate", 48000) or 48000)
        for item in todo:
            if should_stop and should_stop():
                break
            if on_start:
                on_start(item)
            finish(len(done) + 1, item, _speak(engine, voice_id, sample_rate, export.model, voice_name, lexicon, item, out_dir / item.file))

    report = [done[i.file] for i in items if i.file in done]
    with (out_dir / "report.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["file", "seconds", "chars", "status"])
        writer.writeheader()
        writer.writerows(report)
    return report
