"""The runtime status lines yt-setup offers: what the human sees, never what a task gets.

Claude gets its view from the interface mods (mods/). Codex has no mods, but its
status line can show context and limits from built-in items, so yt-setup sets those
in ~/.codex/config.toml. It changes the line only while it is unset or still Codex's
own default; a line the human chose is left alone. "codexStatusLine": false in
~/yt-local/config.json turns this off.
"""
import json
import re

try:
    import tomllib
except ImportError:  # Python < 3.11: report only, never edit
    tomllib = None

CODEX_ITEMS = ["model-with-reasoning", "context-used", "five-hour-limit", "weekly-limit", "task-progress"]
CODEX_DEFAULTS = (None, ["model-with-reasoning", "current-dir"])
LINE = "status_line = " + json.dumps(CODEX_ITEMS)
HEADER = re.compile(r"^\s*\[([^\]\[]+)\]\s*(#.*)?$", re.M)


def codex_plan(text):
    """(new text or None, state): state is ok, set, custom (left alone), or unreadable."""
    if tomllib is None:
        return None, "unreadable"
    try:
        cur = (tomllib.loads(text).get("tui") or {}).get("status_line")
    except (tomllib.TOMLDecodeError, AttributeError):
        return None, "unreadable"
    if cur == CODEX_ITEMS:
        return None, "ok"
    if cur not in CODEX_DEFAULTS:
        return None, "custom"
    headers = list(HEADER.finditer(text))
    tui = next((i for i, m in enumerate(headers) if m.group(1).strip() == "tui"), None)
    if tui is None:
        if cur is not None:
            return None, "custom"   # set as a dotted key somewhere else: leave it to the human
        new = text.rstrip("\n") + ("\n\n" if text.strip() else "") + f"[tui]\n{LINE}\n"
    else:
        start = headers[tui].end()
        end = headers[tui + 1].start() if tui + 1 < len(headers) else len(text)
        body = text[start:end]
        if cur is None:
            body = f"\n{LINE}" + body
        else:
            body, n = re.subn(r"^status_line\s*=\s*\[[^\]\n]*\]\s*$", LINE, body, count=1, flags=re.M)
            if n != 1:
                return None, "custom"   # written over several lines: leave it
        new = text[:start] + body + text[end:]
    try:
        if (tomllib.loads(new).get("tui") or {}).get("status_line") != CODEX_ITEMS:
            return None, "unreadable"
    except tomllib.TOMLDecodeError:
        return None, "unreadable"
    return new, "set"
