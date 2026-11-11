#!/usr/bin/env python3
"""yt-vault: the vault kind and conventions come from the vault's own files.

Usage: tests/wiki/run.py      exit 0 when every check passes
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO, "yt-core", "lib"))
from ytlib import gitwork, vault  # noqa: E402

results = {"pass": 0, "fail": 0}


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))


def make(files):
    root = tempfile.mkdtemp(prefix="ytvault")
    for rel, body in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body if isinstance(body, str) else json.dumps(body))
    return root


def main():
    p = vault.profile(make({"notes/a.md": "# a\n"}))
    check("plain: inbox with YAML front matter", p["kind"] == "plain" and p["newNotes"].startswith("inbox/"), p)
    check("plain: no rules, no git", p["rules"] == [] and p["git"] is False, p)

    root = make({".obsidian/app.json": {"newFileLocation": "folder", "newFileFolderPath": "Zettel/",
                                        "useMarkdownLinks": False, "attachmentFolderPath": "assets"},
                 ".obsidian/templates.json": {"folder": "Templates"}, "AGENTS.md": "Notes go to Zettel.\n"})
    os.makedirs(os.path.join(root, ".git"))
    p = vault.profile(root)
    check("obsidian: new notes in its configured folder", p["kind"] == "obsidian" and p["newNotes"] == "Zettel/<title>.md", p)
    check("obsidian: wikilinks unless markdown links are set", p["links"].startswith("wikilinks"), p)
    check("obsidian: templates and the tool folder are skipped", "Templates" in p["skip"] and ".obsidian" in p["skip"], p)
    check("rules and git are reported", p["rules"] == ["AGENTS.md"] and p["git"] is True, p)
    p = vault.profile(make({".obsidian/app.json": {"useMarkdownLinks": True}}))
    check("obsidian: default location is the root; markdown links when set",
          p["newNotes"].startswith("<title>.md") and p["links"].startswith("markdown"), p)
    p = vault.profile(make({".obsidian/app.json": "not json"}))
    check("obsidian: a broken settings file falls back to defaults", p["kind"] == "obsidian", p)

    p = vault.profile(make({"logseq/config.edn": '{:pages-directory "wiki" :journals-directory "days"}\n'}))
    check("logseq: page and journal folders from config.edn",
          p["kind"] == "logseq" and p["newNotes"].startswith("wiki/") and p["search"] == ["wiki", "days"], p)
    check("logseq: properties, not YAML", "title::" in p["metadata"] and "YAML" in p["metadata"], p)
    p = vault.profile(make({"logseq/config.edn": "{}\n"}))
    check("logseq: default folders", p["search"] == ["pages", "journals"], p)

    p = vault.profile(make({"dendron.yml": "version: 5\n"}))
    check("dendron: dot hierarchy", p["kind"] == "dendron" and "hierarchy" in p["newNotes"], p)
    p = vault.profile(make({"mkdocs.yml": "site_name: x\ndocs_dir: content  # here\n"}))
    check("mkdocs: docs_dir and navigation", p["kind"] == "mkdocs" and p["search"] == ["content"]
          and "nav" in p["navigation"], p)
    p = vault.profile(make({"docusaurus.config.ts": "export default {}\n"}))
    check("docusaurus: docs/ and the build folders skipped", p["kind"] == "docusaurus" and "build" in p["skip"], p)

    out = subprocess.run([sys.executable, os.path.join(REPO, "yt-core", "bin", "yt-vault"), root],
                         capture_output=True, text=True)
    check("yt-vault: prints kind, rules first, and git", out.returncode == 0 and "kind: obsidian" in out.stdout
          and "they override everything below" in out.stdout and "git: yes" in out.stdout, out)
    bad = subprocess.run([sys.executable, os.path.join(REPO, "yt-core", "bin", "yt-vault"), "/no/such"],
                         capture_output=True, text=True)
    check("yt-vault: a missing folder is an error", bad.returncode == 1)
    src = make({".obsidian/app.json": {"newFileFolderPath": "Z"}})
    clone, outside = make({}), make({})
    os.symlink(outside, os.path.join(clone, ".obsidian"))
    gitwork.copy_vault_settings(src, clone)
    check("settings copy never follows a link out of the clone", os.listdir(outside) == [])
    clone = make({})
    gitwork.copy_vault_settings(src, clone)
    check("settings copy: ignored Obsidian settings reach the clone", os.path.isfile(os.path.join(clone, ".obsidian", "app.json")))
    print(f"\n{results['pass']} passed, {results['fail']} failed")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
