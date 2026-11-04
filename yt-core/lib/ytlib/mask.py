"""Find (and optionally mask) secrets, personal data, and locally blocked terms in text.

Secret patterns come from the repo guard (.githooks/repo_guard.py), so one list serves
both; personal-data patterns are added here. Findings report the kind and line only,
never the matched text.
"""
import importlib.util
import os
import re

from . import core

PERSONAL = [
    ("email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("phone number", re.compile(r"(?<!\d)(?:\+?82[- ]?)?0?1[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)")),
    ("resident registration number", re.compile(r"(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)")),
    ("card number", re.compile(r"(?<!\d)\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}(?!\d)")),
]


def _guard():
    path = os.path.join(core.REPO, ".githooks", "repo_guard.py")
    spec = importlib.util.spec_from_file_location("yt_repo_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rules():
    """[(kind, compiled pattern)] including the local blocked terms."""
    guard = _guard()
    found = [(n, p) for n, p in guard.PATTERNS if n != "personal-path"] + PERSONAL
    found += [("blocked term", re.compile(re.escape(t), re.I)) for t in guard.load_blocked_terms()]
    return found


def scan(text):
    """[(line number, kind)], sorted, without the matched text."""
    hits = set()
    for kind, pattern in rules():
        for m in pattern.finditer(text):
            hits.add((text.count("\n", 0, m.start()) + 1, kind))
    return sorted(hits)


def redact(text):
    for kind, pattern in rules():
        text = pattern.sub(f"[MASKED:{kind}]", text)
    return text
