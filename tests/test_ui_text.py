import unittest

from atcb_tts import ui_text
from atcb_tts.player import play_command
from pathlib import Path


class UiTextTest(unittest.TestCase):
    def test_seconds_use_a_comma(self):
        self.assertEqual(ui_text.format_seconds(4.2), "4,2 giây")

    def test_eta(self):
        self.assertEqual(ui_text.eta_text(0, 9, 0, 0), "0/9 câu")
        self.assertEqual(ui_text.eta_text(4, 9, 40, 4), "4/9 câu · còn khoảng 1 phút")
        self.assertEqual(ui_text.eta_text(8, 9, 40, 8), "8/9 câu · còn vài giây")
        self.assertEqual(ui_text.eta_text(1, 30, 60, 1), "1/30 câu · còn khoảng 29 phút")
        self.assertEqual(ui_text.eta_text(9, 9, 90, 9), "9/9 câu")

    def test_player_command_per_platform(self):
        self.assertEqual(play_command(Path("a.mp3"), "darwin")[0], "afplay")
        self.assertIsNone(play_command(Path("a.mp3"), "win32"))
