MODEL = "VieNeu-TTS-v3-Turbo"
VOICE = "Kim Thanh"
# Models the tool can load: label shown to the teacher -> VieNeu `mode`.
MODELS = {MODEL: "v3turbo", "VieNeu-TTS-v3-Nano": "v3nano"}
SAMPLE_RATE = 24000
BITRATE_KBPS = 64
MAX_TEXT_CHARS = 300
MAX_SLUG_CHARS = 40
EXPORT_FORMAT = "atcb-tts-export"
# 2 added owner `game-<id>` with game slots (spec 17.6); the item fields are the same.
SUPPORTED_VERSIONS = (1, 2)


def tool_url() -> str:
    """Where teachers download a newer tool: `tool_url.txt` next to pyproject.toml (written by make_bundle.py --url)."""
    from pathlib import Path

    try:
        return (Path(__file__).resolve().parent.parent / "tool_url.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
