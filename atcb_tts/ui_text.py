"""Teacher-facing wording that does not need Qt, so it can be tested on its own."""

from __future__ import annotations


def format_seconds(seconds: float) -> str:
    """4.2 -> '4,2 giây' (Vietnamese decimal comma)."""
    return f"{seconds:.1f}".replace(".", ",") + " giây"


def eta_text(done: int, total: int, elapsed: float, made: int) -> str:
    """'4/9 câu · còn khoảng 1 phút'. `made` = sentences actually spoken (skipped ones take no time)."""
    base = f"{done}/{total} câu"
    if total <= done:
        return base
    if made <= 0 or elapsed <= 0:
        return base
    left = (total - done) * elapsed / made
    if left < 15:
        return f"{base} · còn vài giây"
    if left < 90:
        return f"{base} · còn khoảng 1 phút"
    return f"{base} · còn khoảng {round(left / 60)} phút"


def scope_text(count: int, scope: str) -> str:
    """'9 câu · getting-lost-1'."""
    return f"{count} câu · {scope}"
