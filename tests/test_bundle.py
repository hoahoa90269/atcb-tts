import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

import make_bundle


class BundleTest(unittest.TestCase):
    def test_zip_has_launchers_core_and_keeps_the_exec_bit(self):
        with tempfile.TemporaryDirectory() as d:
            target = make_bundle.build(Path(d), url="https://example.test/tool")
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
                folder = target.stem
                for needed in ("ChayCongCu.bat", "ChayCongCu.command", "HUONG-DAN.txt", "pyproject.toml", "uv.lock", "atcb_tts/core.py", "atcb_tts/gui.py", "tool_url.txt"):
                    self.assertIn(f"{folder}/{needed}", names)
                self.assertFalse(any("__pycache__" in n or "exports/" in n or n.endswith(".mp3") for n in names))
                mode = archive.getinfo(f"{folder}/ChayCongCu.command").external_attr >> 16
                self.assertTrue(mode & stat.S_IXUSR)
                self.assertIn(b"\r\n", archive.read(f"{folder}/ChayCongCu.bat"))

    def test_launchers_run_the_gui_with_the_locked_environment(self):
        for name in ("ChayCongCu.bat", "ChayCongCu.command"):
            text = (make_bundle.LAUNCHER / name).read_text(encoding="utf-8")
            self.assertIn("uv run --frozen --extra gui python -m atcb_tts.gui", text)
