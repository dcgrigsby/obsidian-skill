#!/usr/bin/env python3
"""
obsidian.py — bundled helper for the obsidian skill.

Implements the operations that are too fiddly to do reliably inline:

  rename      Rename a note and update inbound links across the vault.
  insert      Insert content into a note at a heading anchor.
  backlinks   Find every note that links to a given note.

The simpler operations (read, list, search, create, replace, delete,
trash-list, trash-empty) are handled by the agent inline with standard
tools — they don't need this script.

All paths are relative to the vault root.

Usage:
  obsidian.py rename    --vault PATH OLD NEW [--apply]
  obsidian.py insert    --vault PATH --file PATH --anchor ANCHOR --content TEXT
  obsidian.py backlinks --vault PATH NOTE
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


EXCLUDE_DIRS = {".obsidian", ".trash", ".git"}


# ---------------------------------------------------------------------------
# Vault traversal
# ---------------------------------------------------------------------------


def walk_markdown(vault: Path) -> Iterator[Path]:
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f.endswith(".md"):
                yield Path(root) / f


def resolve_in_vault(vault: Path, rel: str) -> Path:
    """Resolve a relative path inside the vault, refusing escapes."""
    target = (vault / rel).resolve()
    vault_resolved = vault.resolve()
    try:
        target.relative_to(vault_resolved)
    except ValueError:
        raise SystemExit(
            f"refusing path outside vault: {rel} -> {target}"
        )
    return target


# ---------------------------------------------------------------------------
# Frontmatter and code-fence detection
# ---------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block, body). Frontmatter includes the closing
    delimiter and trailing newline. If absent, frontmatter is empty."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return "", text
    # Find the closing --- line.
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            fm = "".join(lines[: i + 1])
            body = "".join(lines[i + 1:])
            return fm, body
    # Unclosed frontmatter; treat the whole thing as body.
    return "", text


@dataclass
class Heading:
    level: int
    text: str
    line_index: int  # index into body lines (frontmatter excluded)


HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
CODE_FENCE_RE = re.compile(r"^(```|~~~)")


def find_headings(body: str) -> list[Heading]:
    headings: list[Heading] = []
    in_fence = False
    fence_marker: str | None = None
    for i, raw in enumerate(body.splitlines()):
        line = raw.rstrip("\r")
        fence = CODE_FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif fence_marker is not None and line.startswith(fence_marker):
                in_fence = False
                fence_marker = None
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            headings.append(Heading(len(m.group(1)), m.group(2), i))
    return headings


# ---------------------------------------------------------------------------
# insert
# ---------------------------------------------------------------------------


def cmd_insert(args: argparse.Namespace) -> int:
    vault = Path(args.vault)
    target = resolve_in_vault(vault, args.file)
    if not target.exists():
        raise SystemExit(
            f"file does not exist: {args.file} (use create, not insert)"
        )

    text = target.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    content = args.content
    if not content.endswith("\n"):
        content += "\n"

    if args.anchor == "end":
        new_body = body
        if new_body and not new_body.endswith("\n"):
            new_body += "\n"
        new_body += content
        new_text = fm + new_body

    elif args.anchor.startswith("after-heading:") or args.anchor.startswith(
        "before-heading:"
    ):
        before, _, heading_text = args.anchor.partition(":")
        mode = before  # "after-heading" or "before-heading"
        headings = [h for h in find_headings(body) if h.text == heading_text]
        if not headings:
            raise SystemExit(
                f"no heading matching {heading_text!r} (exact match required)"
            )
        if len(headings) > 1:
            lines_info = ", ".join(f"line {h.line_index + 1}" for h in headings)
            raise SystemExit(
                f"multiple headings match {heading_text!r}: {lines_info}. "
                "Disambiguate (the agent should ask the user)."
            )
        h = headings[0]
        body_lines = body.splitlines(keepends=True)
        insert_at = h.line_index + 1 if mode == "after-heading" else h.line_index
        # Ensure the line we're inserting after has a trailing newline.
        if insert_at > 0 and not body_lines[insert_at - 1].endswith("\n"):
            body_lines[insert_at - 1] = body_lines[insert_at - 1] + "\n"
        body_lines.insert(insert_at, content)
        new_text = fm + "".join(body_lines)
    else:
        raise SystemExit(
            f"unknown anchor: {args.anchor} "
            "(use 'end', 'after-heading:TEXT', or 'before-heading:TEXT')"
        )

    # Atomic write: temp file in same dir, then rename.
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, target)
    return 0


# ---------------------------------------------------------------------------
# Link parsing (for rename and backlinks)
# ---------------------------------------------------------------------------


def link_patterns(note_basename_no_ext: str, note_relpath_no_ext: str) -> list[re.Pattern]:
    """Build patterns matching all the ways a note can be linked.

    note_basename_no_ext: filename without .md (e.g. "Sarah Chen")
    note_relpath_no_ext: relpath without .md (e.g. "People/Sarah Chen")
    """
    names = {note_basename_no_ext, note_relpath_no_ext}
    patterns = []
    for name in names:
        esc = re.escape(name)
        # [[name]], [[name|alias]], [[name#h]], [[name^b]], ![[name]]
        patterns.append(
            re.compile(rf"!?\[\[{esc}(\||#|\^|\])")
        )
        # [text](name.md) and [text](path/name.md), with optional URL encoding
        # of spaces (%20). Be conservative — only match the .md form to avoid
        # false positives on common english phrases.
        url_form = esc.replace(r"\ ", r"(?:\\ |%20)")
        patterns.append(
            re.compile(rf"\]\(({url_form})\.md\)")
        )
    return patterns


def find_link_matches(
    text: str,
    note_basename_no_ext: str,
    note_relpath_no_ext: str,
) -> list[tuple[int, int, str]]:
    """Return list of (start, end, matched_text) for all link references."""
    matches = []
    for pat in link_patterns(note_basename_no_ext, note_relpath_no_ext):
        for m in pat.finditer(text):
            matches.append((m.start(), m.end(), m.group(0)))
    # Deduplicate overlapping matches; sort by position.
    matches.sort()
    deduped = []
    last_end = -1
    for start, end, t in matches:
        if start >= last_end:
            deduped.append((start, end, t))
            last_end = end
    return deduped


# ---------------------------------------------------------------------------
# backlinks
# ---------------------------------------------------------------------------


def cmd_backlinks(args: argparse.Namespace) -> int:
    vault = Path(args.vault)
    note = args.note
    # Strip .md if user provided it.
    if note.endswith(".md"):
        note = note[:-3]
    basename = Path(note).name
    relpath = note

    # If the user passed just a bare name (no folder), try to resolve the
    # full relpath by walking the vault. Folder-qualified link forms only
    # match when we know the folder.
    if "/" not in note:
        candidates = [
            p.relative_to(vault).with_suffix("")
            for p in walk_markdown(vault)
            if p.stem == basename
        ]
        if len(candidates) == 1:
            relpath = str(candidates[0])
        elif len(candidates) > 1:
            # Multiple notes share this basename; surface them so the agent
            # can disambiguate with the user.
            print(
                json.dumps(
                    {
                        "error": "ambiguous note name",
                        "basename": basename,
                        "candidates": [str(c) for c in candidates],
                    },
                    indent=2,
                )
            )
            return 2

    results: list[dict] = []
    for path in walk_markdown(vault):
        text = path.read_text(encoding="utf-8", errors="replace")
        matches = find_link_matches(text, basename, relpath)
        if matches:
            rel = path.relative_to(vault)
            for start, end, t in matches:
                # Compute line number.
                line_no = text.count("\n", 0, start) + 1
                results.append(
                    {
                        "file": str(rel),
                        "line": line_no,
                        "match": t,
                    }
                )

    print(json.dumps({"backlinks": results, "count": len(results)}, indent=2))
    return 0


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


def cmd_rename(args: argparse.Namespace) -> int:
    vault = Path(args.vault)
    old_path = resolve_in_vault(vault, args.old)
    new_path = resolve_in_vault(vault, args.new)

    if not old_path.exists():
        raise SystemExit(f"source does not exist: {args.old}")
    if new_path.exists():
        raise SystemExit(f"destination already exists: {args.new}")

    old_rel = args.old[:-3] if args.old.endswith(".md") else args.old
    new_rel = args.new[:-3] if args.new.endswith(".md") else args.new
    old_basename = Path(old_rel).name
    new_basename = Path(new_rel).name

    # Walk vault, find all references, build update plan.
    plan: list[dict] = []
    for path in walk_markdown(vault):
        if path.resolve() == old_path.resolve():
            continue  # skip the file being renamed
        text = path.read_text(encoding="utf-8", errors="replace")
        matches = find_link_matches(text, old_basename, old_rel)
        if matches:
            rel = path.relative_to(vault)
            plan.append(
                {
                    "file": str(rel),
                    "matches": [
                        {"line": text.count("\n", 0, s) + 1, "match": t}
                        for s, _, t in matches
                    ],
                }
            )

    summary = {
        "old": args.old,
        "new": args.new,
        "files_with_references": len(plan),
        "total_references": sum(len(p["matches"]) for p in plan),
        "plan": plan,
        "applied": False,
    }

    if not args.apply:
        # Preview only.
        print(json.dumps(summary, indent=2))
        return 0

    # Apply: rename file, then update references.
    new_path.parent.mkdir(parents=True, exist_ok=True)
    os.rename(old_path, new_path)

    h1_updated = False
    if getattr(args, "update_h1", False):
        text = new_path.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        body_lines = body.splitlines(keepends=True)
        # Find the first non-blank body line; if it's a level-1 heading whose
        # text exactly matches the old basename, rewrite to new basename.
        for i, line in enumerate(body_lines):
            stripped = line.rstrip("\r\n")
            if stripped == "":
                continue
            m = re.match(r"^#\s+(.+?)\s*$", stripped)
            if m and m.group(1) == old_basename:
                body_lines[i] = f"# {new_basename}\n"
                tmp = new_path.with_suffix(new_path.suffix + ".tmp")
                tmp.write_text(fm + "".join(body_lines), encoding="utf-8")
                os.replace(tmp, new_path)
                h1_updated = True
            break  # only inspect the first non-blank body line

    updated_files: list[str] = []
    for entry in plan:
        path = vault / entry["file"]
        text = path.read_text(encoding="utf-8")
        # Apply link substitutions: replace any reference to the old path/name
        # with the new equivalent. Use the same pattern set we used to find.
        new_text = text
        for pat in link_patterns(old_basename, old_rel):
            def _sub(m: re.Match) -> str:
                matched = m.group(0)
                # Substitute basename or relpath occurrence inside the match.
                # Try relpath first to avoid clobbering when basename is a
                # substring of relpath.
                if old_rel in matched and old_rel != old_basename:
                    return matched.replace(old_rel, new_rel)
                return matched.replace(old_basename, new_basename)

            new_text = pat.sub(_sub, new_text)

        if new_text != text:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(new_text, encoding="utf-8")
            os.replace(tmp, path)
            updated_files.append(str(entry["file"]))

    summary["applied"] = True
    summary["updated_files"] = updated_files
    summary["h1_updated"] = h1_updated
    print(json.dumps(summary, indent=2))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 8):
        raise SystemExit(
            f"python 3.8+ required (have {sys.version.split()[0]}). "
            "On macOS, /usr/bin/python3 is recent enough."
        )

    parser = argparse.ArgumentParser(prog="obsidian.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rename = sub.add_parser("rename", help="rename a note and update links")
    p_rename.add_argument("--vault", required=True)
    p_rename.add_argument("old")
    p_rename.add_argument("new")
    p_rename.add_argument(
        "--apply",
        action="store_true",
        help="apply the rename (without this, only previews)",
    )
    p_rename.add_argument(
        "--update-h1",
        action="store_true",
        help="if the renamed file's first H1 exactly matches the old basename, "
        "rewrite it to the new basename (off by default — rename only touches "
        "links, not in-body content)",
    )

    p_insert = sub.add_parser("insert", help="insert content at an anchor")
    p_insert.add_argument("--vault", required=True)
    p_insert.add_argument("--file", required=True)
    p_insert.add_argument(
        "--anchor",
        required=True,
        help="'end', 'after-heading:TEXT', or 'before-heading:TEXT'",
    )
    p_insert.add_argument("--content", required=True)

    p_back = sub.add_parser("backlinks", help="find references to a note")
    p_back.add_argument("--vault", required=True)
    p_back.add_argument("note")

    args = parser.parse_args(argv)

    if args.cmd == "rename":
        return cmd_rename(args)
    if args.cmd == "insert":
        return cmd_insert(args)
    if args.cmd == "backlinks":
        return cmd_backlinks(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
