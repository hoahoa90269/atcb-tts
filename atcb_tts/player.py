"""Plays one mp3 for 'nghe thử' with what the operating system already has (no audio library to install)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def play_command(path: Path, platform: str = sys.platform) -> list[str] | None:
    """Command that plays `path` and exits, or None when the platform is played through MCI (Windows)."""
    if platform == "darwin":
        return ["afplay", str(path)]
    if platform.startswith("win"):
        return None
    return ["xdg-open", str(path)]


class Player:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._mci = False

    def play(self, path: Path) -> None:
        self.stop()
        command = play_command(path)
        if command is not None:
            self._proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        import ctypes

        mci = ctypes.windll.winmm.mciSendStringW  # type: ignore[attr-defined]
        mci('close atcbplay', None, 0, None)
        if mci(f'open "{path}" type mpegvideo alias atcbplay', None, 0, None) == 0:
            mci("play atcbplay", None, 0, None)
            self._mci = True

    def stop(self) -> None:
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.terminate()
            self._proc = None
        if self._mci:
            import ctypes

            ctypes.windll.winmm.mciSendStringW("close atcbplay", None, 0, None)  # type: ignore[attr-defined]
            self._mci = False
