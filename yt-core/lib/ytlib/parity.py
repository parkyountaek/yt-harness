"""Global (user-level) runtime setup that every sub-session inherits.

Claude and Codex each load their own user-level instructions, hooks, and plugins
into every session, sub-sessions included. If those differ, the two runtimes no
longer get the same work order. This module reads both sides and reports drift.
It never changes the files; the human fixes them.

Checked:
  instructions  ~/.claude/CLAUDE.md (+ ~/.claude/rules/*.md) vs ~/.codex/AGENTS.override.md
                or ~/.codex/AGENTS.md (+ instruction keys in config.toml): same text
  hooks         not compared: sub-sessions run only their harness plugin's hooks; user-level
                hooks are off on both runtimes (launch.claude_isolation, codex_isolation)
  plugins       globally enabled plugins: same names on both sides (the human's own sessions).
                Sub-sessions load only their harness plugin. The human's Claude interface
                mods (mods/ in this checkout) are left out: they never reach a work order
"""
import glob
import json
import os
import re
import shutil

from . import core

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

HOME = os.path.expanduser("~")
CODEX_INSTRUCTION_KEYS = ("instructions", "developer_instructions", "model_instructions_file",
                          "experimental_instructions_file")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _norm(text):
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines())


def _codex_home(home):
    return os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")


def codex_config(home=HOME):
    """~/.codex/config.toml as a dict (only the parts this package reads when tomllib is missing)."""
    return _codex_config(home)


def _codex_config(home):
    text = _read(os.path.join(_codex_home(home), "config.toml")) or ""
    if tomllib:
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            pass
    # Fallback: only what this module needs.
    cfg = {"plugins": {}}
    for m in re.finditer(r'^\[plugins\."([^"]+)"\]\s*\n(?:enabled\s*=\s*(true|false))?', text, re.M):
        cfg["plugins"][m.group(1)] = {"enabled": m.group(2) != "false"}
    cfg["mcp_servers"] = {m.group(1): {} for m in re.finditer(r'^\[mcp_servers\.([A-Za-z0-9_-]+)\]', text, re.M)}
    for key in CODEX_INSTRUCTION_KEYS:
        if re.search(rf"^{key}\s*=", text, re.M):
            cfg[key] = "(set)"
    return cfg


def claude_side(home=HOME):
    base = os.path.join(home, ".claude")
    parts = [_read(os.path.join(base, "CLAUDE.md")) or ""]
    parts += [_read(p) or "" for p in sorted(glob.glob(os.path.join(base, "rules", "*.md")))]
    try:
        settings = json.loads(_read(os.path.join(base, "settings.json")) or "{}")
    except ValueError:
        settings = {}
    plugins = {k.split("@")[0] for k, v in (settings.get("enabledPlugins") or {}).items() if v}
    dirs = (settings.get("env") or {}).get("CLAUDE_CODE_PLUGIN_DIRS", "")
    plugins |= {os.path.basename(d.rstrip("/")) for d in dirs.split(os.pathsep) if d and not core.is_mod_dir(d)}
    return {"instructions": _norm("\n".join(p for p in parts if p)),
            "hooks": sorted((settings.get("hooks") or {}).keys()),
            "plugins": plugins,
            "outputStyle": settings.get("outputStyle")}


def codex_side(home=HOME):
    base = _codex_home(home)
    text = _read(os.path.join(base, "AGENTS.override.md"))
    if text is None or not text.strip():
        text = _read(os.path.join(base, "AGENTS.md")) or ""
    cfg = _codex_config(home)
    try:
        hooks = json.loads(_read(os.path.join(base, "hooks.json")) or "{}").get("hooks") or {}
    except ValueError:
        hooks = {"(unreadable hooks.json)": True}
    plugins = {k.split("@")[0] for k, v in (cfg.get("plugins") or {}).items()
               if isinstance(v, dict) and v.get("enabled", True)}
    return {"instructions": _norm(text),
            "instructionKeys": [k for k in CODEX_INSTRUCTION_KEYS if cfg.get(k)],
            "hooks": sorted(hooks.keys()),
            "plugins": plugins}


def problems(home=HOME, require_both=True):
    """Human-readable drift between the two runtimes' global setup; empty when they match.

    With only one runtime installed there is nothing to compare (require_both skips the check).
    """
    if require_both and not (shutil.which("claude") and shutil.which("codex")):
        return []
    c, x = claude_side(home), codex_side(home)
    out = []
    if c["instructions"] != x["instructions"]:
        out.append("global instructions differ: ~/.claude/CLAUDE.md (+ rules/) and ~/.codex/AGENTS.md "
                   "(or AGENTS.override.md) must have the same text")
    if x["instructionKeys"]:
        out.append("~/.codex/config.toml sets " + ", ".join(x["instructionKeys"]) + "; Claude has no equivalent")
    if c["outputStyle"]:
        out.append(f"Claude outputStyle {c['outputStyle']!r} is set; Codex has no equivalent")
    if c["plugins"] != x["plugins"]:
        only_c, only_x = sorted(c["plugins"] - x["plugins"]), sorted(x["plugins"] - c["plugins"])
        out.append("globally enabled plugins differ: "
                   + "; ".join(s for s in (only_c and "Claude only: " + ", ".join(only_c),
                                           only_x and "Codex only: " + ", ".join(only_x)) if s))
    return out
