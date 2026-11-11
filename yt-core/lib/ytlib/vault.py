"""What kind of knowledge vault a folder is, and its conventions, read from the vault's own files.

The yt-wiki skills run `yt-vault <vault>` first, so Claude and Codex follow the same
conventions. Precedence: the vault's own rule files (AGENTS.md, CLAUDE.md,
CONVENTIONS.md, README.md at its root) > the tool's settings read here > the default
(a plain folder of Markdown notes with new ones in inbox/).

Kinds: obsidian (.obsidian/), logseq (logseq/config.edn), dendron (dendron.yml),
mkdocs (mkdocs.yml), docusaurus (docusaurus.config.*), plain. Remote wikis (Notion,
Confluence) are not vaults: export them to a folder first.
"""
import glob
import json
import os
import re

RULE_FILES = ("AGENTS.md", "CLAUDE.md", "CONVENTIONS.md", "README.md")
SKIP_ALWAYS = [".git", ".obsidian", ".trash", "node_modules"]


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _json(path):
    try:
        data = json.loads(_read(path) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _edn(text, key, default):
    m = re.search(r":" + re.escape(key) + r"\s+\"([^\"]*)\"", text)
    return m.group(1) if m else default


def _yaml_value(text, key, default):
    m = re.search(r"^" + re.escape(key) + r":\s*['\"]?([^'\"\n#]+?)['\"]?\s*(?:#.*)?$", text, re.MULTILINE)
    return m.group(1).strip() if m else default


def _obsidian(root):
    app = _json(os.path.join(root, ".obsidian", "app.json"))
    new_dir = (app.get("newFileFolderPath") or "").strip("/") if app.get("newFileLocation") == "folder" else ""
    attach = (app.get("attachmentFolderPath") or "").strip("/") or None
    templates = (_json(os.path.join(root, ".obsidian", "templates.json")).get("folder") or "").strip("/") or None
    daily = _json(os.path.join(root, ".obsidian", "daily-notes.json"))
    return {
        "kind": "obsidian",
        # Obsidian's own setting for new notes: a set folder, else the vault root.
        "newNotes": f"{new_dir}/<title>.md" if new_dir else "<title>.md (vault root, Obsidian's setting)",
        "fileName": "the note title as written (spaces allowed), unique in the vault",
        "metadata": "YAML front matter (properties)",
        "links": "markdown [text](path.md)" if app.get("useMarkdownLinks") else "wikilinks [[Note title]]",
        "templates": templates,
        "attachments": attach,
        "dailyNotes": (daily.get("folder") or "").strip("/") or None,
        "search": ["."],
        "skip": SKIP_ALWAYS + ([templates] if templates else []),
    }


def _logseq(root):
    config = _read(os.path.join(root, "logseq", "config.edn"))
    pages = _edn(config, "pages-directory", "pages")
    journals = _edn(config, "journals-directory", "journals")
    return {
        "kind": "logseq",
        "newNotes": f"{pages}/<title>.md (one page per subject; dated captures may go to {journals}/yyyy_mm_dd.md)",
        "fileName": "the page title; `/` in a title becomes `___` in the file name",
        "metadata": "page properties as the first block: `title:: x`, `tags:: a, b` (no YAML front matter)",
        "links": "wikilinks [[Page title]]; the body is an outline of `- ` blocks",
        "templates": None, "attachments": "assets", "dailyNotes": journals,
        "search": [pages, journals],
        "skip": SKIP_ALWAYS + ["logseq"],
    }


def _dendron(root):
    return {
        "kind": "dendron",
        "newNotes": "<hierarchy.name>.md in the vault folder listed in dendron.yml (e.g. project.release.cadence.md)",
        "fileName": "lowercase dot-separated hierarchy; parents need not exist",
        "metadata": "YAML front matter with id, title, desc, updated, created (ms since epoch)",
        "links": "wikilinks [[hierarchy.name]]",
        "templates": None, "attachments": "assets", "dailyNotes": "daily.journal.*",
        "search": ["."], "skip": SKIP_ALWAYS + [".dendron.cache.json"],
    }


def _site(root, kind, docs):
    return {
        "kind": kind,
        "newNotes": f"{docs}/<topic>/<slug>.md, next to related pages",
        "fileName": "lowercase-with-dashes",
        "metadata": "YAML front matter as the existing pages use it (title, sidebar_position, ...)",
        "links": "relative markdown links [text](../other.md)",
        "templates": None, "attachments": None, "dailyNotes": None,
        "navigation": ("mkdocs.yml nav: add the page if nav lists pages explicitly" if kind == "mkdocs"
                       else "sidebars.*: add the page if the sidebar lists pages explicitly"),
        "search": [docs], "skip": SKIP_ALWAYS + ["site", "build", ".docusaurus"],
    }


def _plain():
    return {
        "kind": "plain",
        "newNotes": "inbox/<yyyy-mm-dd>-<short-slug>.md",
        "fileName": "lowercase-with-dashes after the date",
        "metadata": "YAML front matter: title, source, captured, tags",
        "links": "relative markdown links [text](path.md)",
        "templates": None, "attachments": None, "dailyNotes": None,
        "search": ["."], "skip": SKIP_ALWAYS,
    }


def profile(root):
    """The vault's kind and conventions as a dict (paths relative to the vault)."""
    root = os.path.realpath(root)
    if os.path.isdir(os.path.join(root, ".obsidian")):
        found = _obsidian(root)
    elif os.path.isfile(os.path.join(root, "logseq", "config.edn")):
        found = _logseq(root)
    elif os.path.isfile(os.path.join(root, "dendron.yml")):
        found = _dendron(root)
    elif os.path.isfile(os.path.join(root, "mkdocs.yml")):
        found = _site(root, "mkdocs", _yaml_value(_read(os.path.join(root, "mkdocs.yml")), "docs_dir", "docs"))
    elif glob.glob(os.path.join(root, "docusaurus.config.*")):
        found = _site(root, "docusaurus", "docs")
    else:
        found = _plain()
    found["rules"] = [n for n in RULE_FILES if os.path.isfile(os.path.join(root, n))]
    found["git"] = os.path.exists(os.path.join(root, ".git"))
    return found


def render(root):
    p = profile(root)
    lines = [f"vault: {os.path.realpath(root)}", f"kind: {p['kind']}"]
    if p["rules"]:
        lines.append("rules: " + ", ".join(p["rules"]) + "  (read them first; they override everything below)")
    else:
        lines.append("rules: none")
    for key in ("newNotes", "fileName", "metadata", "links", "templates", "attachments", "dailyNotes", "navigation"):
        if p.get(key):
            lines.append(f"{key}: {p[key]}")
    lines.append("search: " + " ".join(p["search"]))
    lines.append("skip: " + " ".join(p["skip"]))
    lines.append("git: " + ("yes. Commit on the branch the work order names; never push" if p["git"] else "no"))
    return "\n".join(lines)
