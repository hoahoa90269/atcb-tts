import json
import tempfile
import unittest
from pathlib import Path

from atcb_tts import core


class FakeEngine:
    sample_rate = 48000

    def list_preset_voices(self):
        return [("Hải Đăng - Nam", "hd"), ("Kim Thanh - Nữ - Nam - Phong cách đọc truyện", "kt")]

    def infer(self, text, voice):
        import numpy as np

        self.last = (text, voice)
        t = np.arange(48000) / 48000
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32")


def export_file(directory: Path, text="Con làm gì?") -> Path:
    item = {"file": f"s1__question__{core.text_hash(text)}.mp3", "owner_type": "scenario", "owner_id": "s1", "slot": "question", "text": text, "text_hash": core.text_hash(text)}
    path = directory / "e.json"
    path.write_text(json.dumps({"format": "atcb-tts-export", "version": 1, "model": "VieNeu-TTS-v3-Turbo", "voice": "Kim Thanh", "items": [item]}), encoding="utf-8")
    return path


class CoreTest(unittest.TestCase):
    def test_hash_matches_the_web(self):
        # Computed by src/lib/speech/textHash.ts for the same string.
        self.assertEqual(core.text_hash("  Khi con  bị lạc "), core.text_hash("Khi con bị lạc"))
        self.assertEqual(len(core.text_hash("a")), 8)

    def test_export_validation(self):
        with tempfile.TemporaryDirectory() as d:
            ok = export_file(Path(d))
            self.assertEqual(len(core.load_export(ok).items), 1)
            bad = Path(d) / "bad.json"
            bad.write_text(json.dumps({"format": "x"}))
            with self.assertRaises(core.ExportError):
                core.load_export(bad)
            bad.write_text(json.dumps({"format": "atcb-tts-export", "version": 3, "items": []}))
            with self.assertRaisesRegex(core.ExportError, "bản mới"):
                core.load_export(bad)

    def test_version_2_with_game_items(self):
        # Same item fields as version 1; owner `game-<id>` and game slots (spec 17.6).
        text = "Nhìn hai bên"
        item = {"file": f"game-g1__step-2-choice-1__{core.text_hash(text)}.mp3", "owner_type": "game", "owner_id": "g1", "slot": "step-2-choice-1", "text": text, "text_hash": core.text_hash(text)}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "v2.json"
            path.write_text(json.dumps({"format": "atcb-tts-export", "version": 2, "items": [item]}), encoding="utf-8")
            export = core.load_export(path)
            self.assertEqual([(i.file, i.slot) for i in export.items], [(item["file"], "step-2-choice-1")])
            self.assertEqual(core.export_scope(export), "game-g1")

    def test_lexicon_only_changes_spoken_text(self):
        self.assertEqual(core.apply_lexicon("Quét QR nhé", {"QR": "kiu a"}), "Quét kiu a nhé")
        self.assertEqual(core.apply_lexicon("QRS", {"QR": "kiu a"}), "QRS")

    def test_pick_voice(self):
        voices = FakeEngine().list_preset_voices()
        self.assertEqual(core.pick_voice(voices, "kim thanh"), "kt")
        with self.assertRaises(core.ExportError):
            core.pick_voice(voices, "Nobody")

    def test_make_all_writes_a_tagged_mp3(self):
        with tempfile.TemporaryDirectory() as d:
            engine = FakeEngine()
            export = core.load_export(export_file(Path(d)))
            report = core.make_all(export, Path(d) / "out", lexicon={}, engine=engine)
            self.assertEqual(report[0]["status"], "ok")
            data = (Path(d) / "out" / export.items[0].file).read_bytes()
            self.assertTrue(data.startswith(b"ID3"))
            self.assertIn(b"atcb\x00model=VieNeu-TTS-v3-Turbo;voice=Kim Thanh;tool=1.1.0;text_hash=", data)
            self.assertEqual(engine.last[1], "kt")
            again = core.make_all(export, Path(d) / "out", engine=engine)
            self.assertEqual(again[0]["status"], "skipped")
            import os
            if os.environ.get("ATCB_DUMP"):
                Path(os.environ["ATCB_DUMP"]).write_bytes(data)


class AutoJobsTest(unittest.TestCase):
    def test_weak_machines_get_one_worker(self):
        self.assertEqual(core.auto_jobs(cpus=2, ram_gb=16), 1)  # too few cores
        self.assertEqual(core.auto_jobs(cpus=8, ram_gb=4), 1)  # too little RAM

    def test_unknown_ram_means_one_worker(self):
        from unittest import mock

        with mock.patch.object(core, "total_ram_gb", return_value=None):
            self.assertEqual(core.auto_jobs(cpus=8), 1)

    def test_scales_with_cores_and_ram_up_to_three(self):
        self.assertEqual(core.auto_jobs(cpus=4, ram_gb=8), 1)
        self.assertEqual(core.auto_jobs(cpus=6, ram_gb=8), 2)
        self.assertEqual(core.auto_jobs(cpus=10, ram_gb=16), 3)
        self.assertEqual(core.auto_jobs(cpus=64, ram_gb=256), 3)

    def test_ram_limits_workers(self):
        self.assertEqual(core.auto_jobs(cpus=12, ram_gb=5), 2)  # (5-2)/1.5 = 2


class JobsOptionTest(unittest.TestCase):
    def test_flag_beats_env_beats_auto(self):
        from atcb_tts.cli import resolve_jobs

        self.assertEqual(resolve_jobs(2, "3"), 2)
        self.assertEqual(resolve_jobs(None, "3"), 3)
        self.assertGreaterEqual(resolve_jobs(None, None), 1)
        self.assertGreaterEqual(resolve_jobs(0, "abc"), 1)  # invalid values fall back to auto

    def test_jobs_with_given_engine_runs_in_this_process(self):
        with tempfile.TemporaryDirectory() as d:
            export = core.load_export(export_file(Path(d)))
            engine = FakeEngine()
            report = core.make_all(export, Path(d) / "out", engine=engine, jobs=3)
            self.assertEqual(report[0]["status"], "ok")
            self.assertTrue(hasattr(engine, "last"))

    def test_dead_worker_pool_falls_back_to_this_process(self):
        from concurrent.futures.process import BrokenProcessPool
        from unittest import mock

        class DeadPool:
            def __init__(self, **_kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def map(self, *_a):
                raise BrokenProcessPool("worker killed")

        with tempfile.TemporaryDirectory() as d:
            export = core.load_export(export_file(Path(d)))
            export.items.append(core.Item(file=export.items[0].file.replace("question", "hint"), text="Con nhớ nhé", text_hash=core.text_hash("Con nhớ nhé")))
            with mock.patch("concurrent.futures.ProcessPoolExecutor", DeadPool), mock.patch.object(core, "load_engine", return_value=FakeEngine()):
                report = core.make_all(export, Path(d) / "out", jobs=3)
            self.assertEqual([r["status"] for r in report], ["ok", "ok"])


if __name__ == "__main__":
    unittest.main()


class TypedSentencesTest(unittest.TestCase):
    def test_slug_and_file_name(self):
        self.assertEqual(core.slugify_vi("An toàn trong nhà bếp"), "an-toan-trong-nha-bep")
        self.assertEqual(core.slugify_vi("Đường đi?!"), "duong-di")
        self.assertEqual(core.slugify_vi("???"), "cau")
        self.assertLessEqual(len(core.slugify_vi("a" * 100)), 40)
        items, _ = core.typed_items("An toàn trong nhà bếp")
        self.assertEqual(items[0].file, f"an-toan-trong-nha-bep__{core.text_hash('An toàn trong nhà bếp')}.mp3")
        self.assertRegex(items[0].file, core.TYPED_FILE_PATTERN)

    def test_slug_never_ends_with_a_dash_after_cutting(self):
        self.assertFalse(core.slugify_vi("abcd efgh " * 10).endswith("-"))

    def test_blank_lines_duplicates_and_long_lines(self):
        long_line = "a" * 301
        items, notes = core.typed_items(f"Câu một.\n\n   \nCâu  một.\n{long_line}\nCâu hai.")
        self.assertEqual([i.text for i in items], ["Câu một.", "Câu hai."])
        self.assertEqual(len(notes), 1)
        self.assertIn("Dòng 5", notes[0])

    def test_hash_is_the_same_as_for_the_exported_text(self):
        items, _ = core.typed_items("  Khi con  bị lạc ")
        self.assertEqual(items[0].text_hash, core.text_hash("Khi con bị lạc"))

    def test_slot_labels(self):
        self.assertEqual(core.slot_label("question"), "Câu hỏi")
        self.assertEqual(core.slot_label("choice-2"), "Cách 2")
        self.assertEqual(core.slot_label("explain-3"), "Giải thích 3")
        self.assertEqual(core.slot_label("lesson"), "Bé rút ra")
        self.assertEqual(core.slot_label("start-greeting"), "start-greeting")
        self.assertEqual(core.slot_label("title"), "Tên trò chơi")
        self.assertEqual(core.slot_label("card-3"), "Thẻ 3")
        self.assertEqual(core.slot_label("step-2-choice-1"), "Bước 2, cách 1")
        self.assertEqual(core.slot_label("round-1-after"), "Lượt 1, lời dặn")
        self.assertEqual(core.slot_label("round-4-choice-3"), "Lượt 4, cách 3")

    def test_scope_and_voice_helpers(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(core.export_scope(core.load_export(export_file(Path(d)))), "s1")
        self.assertEqual(core.short_voice("Kim Thanh - Nữ - Phong cách đọc truyện"), "Kim Thanh")
        self.assertEqual(core.short_voice("⭐ Thùy Dung — Nữ · Nam · Phong cách tin tức"), "Thùy Dung")
        self.assertEqual(core.voice_details("⭐ Mai Anh — Nữ · Bắc · Phong cách tin tức"), "Nữ · Bắc · Phong cách tin tức")
        self.assertEqual(core.voice_details("Kim Thanh"), "")
        self.assertEqual(core.voice_summary("Nữ · Bắc · Phong cách tin tức"), "Giới tính: Nữ · Vùng: Bắc · Phong cách tin tức")
        self.assertEqual(core.voice_summary("Nữ"), "Nữ")

        self.assertFalse(core.differs_from_default("VieNeu-TTS-v3-Turbo", "Kim Thanh"))
        self.assertTrue(core.differs_from_default("VieNeu-TTS-v3-Turbo", "Mỹ Duyên"))


class MakeAllControlTest(unittest.TestCase):

    def test_is_current_follows_model_voice_and_hash(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a.mp3"
            path.write_bytes(core.id3_tag("VieNeu-TTS-v3-Turbo", "Kim Thanh", "abc12345") + b"\0" * 20)
            self.assertTrue(core.is_current(path, "VieNeu-TTS-v3-Turbo", "Kim Thanh", "abc12345"))
            self.assertFalse(core.is_current(path, "VieNeu-TTS-v3-Nano", "Kim Thanh", "abc12345"))
            self.assertFalse(core.is_current(path, "VieNeu-TTS-v3-Turbo", "Mai Anh", "abc12345"))
            self.assertFalse(core.is_current(path, "VieNeu-TTS-v3-Turbo", "Kim Thanh", "zzzz"))
            self.assertFalse(core.is_current(Path(d) / "missing.mp3", "m", "v", "h"))

    def test_stop_between_sentences_keeps_finished_files(self):
        with tempfile.TemporaryDirectory() as d:
            items, _ = core.typed_items("Câu một.\nCâu hai.\nCâu ba.")
            export = core.Export(model="VieNeu-TTS-v3-Turbo", voice="Kim Thanh", items=items)
            made, started = [], []
            report = core.make_all(
                export,
                Path(d) / "out",
                engine=FakeEngine(),
                on_start=lambda item: started.append(item.file),
                on_progress=lambda i, n, item, status: made.append(item.file),
                should_stop=lambda: len(made) >= 1,
            )
            self.assertEqual(len(report), 1)
            self.assertEqual(len(started), 1)
            self.assertTrue((Path(d) / "out" / items[0].file).exists())
            self.assertFalse((Path(d) / "out" / items[1].file).exists())


class Mp3SecondsTest(unittest.TestCase):
    def test_length_skips_the_id3_tag(self):
        tag = core.id3_tag("VieNeu-TTS-v3-Turbo", "Kim Thanh", "4c1d07aa")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a.mp3"
            path.write_bytes(tag + b"\x00" * 16000)  # 16000 bytes at 64 kbps = 2 s
            self.assertAlmostEqual(core.mp3_seconds(path), 2.0, places=3)
