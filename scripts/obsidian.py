#!/usr/bin/env python3
"""
obsidian.py — bundled helper for the obsidian skill.

Implements the operations that are too fiddly to do reliably inline:

  rename      Rename a note and update inbound links across the vault.
  insert      Insert content into a note at a heading anchor.
  backlinks   Find every note that links to a given note.
  config      Manage vault profiles in ~/.config/obsidian-skill/config.json.

The simpler operations (read, list, search, create, replace, delete,
trash-list, trash-empty) are handled by the agent inline with standard
tools — they don't need this script.

Vault selection. Every operation that touches a vault accepts either:
  --vault NAME       resolve via config.json (the normal path)
  --vault-path PATH  direct filesystem path (escape hatch; skips config)

If neither is given, falls back to the configured default. If exactly one
vault is configured, it is used implicitly.

All file paths inside operations are relative to the vault root.

Stdlib only — no third-party dependencies, no `pip install` step.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


EXCLUDE_DIRS = {".obsidian", ".trash", ".git"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def config_path() -> Path:
    """Resolve where the config file lives.

    Order of precedence:
      1. OBSIDIAN_SKILL_CONFIG env var (full path) — primarily for tests.
      2. $XDG_CONFIG_HOME/obsidian-skill/config.json if XDG_CONFIG_HOME set.
      3. ~/.config/obsidian-skill/config.json (default).
    """
    override = os.environ.get("OBSIDIAN_SKILL_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "obsidian-skill" / "config.json"


@dataclass
class Vault:
    name: str
    path: Path
    read_only: bool = False


@dataclass
class Config:
    default: str | None = None
    vaults: dict = field(default_factory=dict)


def load_config() -> Config:
    p = config_path()
    if not p.exists():
        return Config()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"config file is not valid JSON ({p}): {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"config root must be a JSON object: {p}")
    vaults = data.get("vaults") or {}
    if not isinstance(vaults, dict):
        raise SystemExit(f"'vaults' must be a JSON object in {p}")
    default = data.get("default")
    if default is not None and not isinstance(default, str):
        raise SystemExit(f"'default' must be a string in {p}")
    return Config(default=default, vaults=vaults)


def save_config(cfg: Config) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {}
    if cfg.default is not None:
        payload["default"] = cfg.default
    payload["vaults"] = cfg.vaults
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(serialized, encoding="utf-8")
    os.replace(tmp, p)


def resolve_vault(cfg: Config, name: str | None) -> Vault:
    """Pick a vault by explicit name, configured default, or sole-vault rule."""
    if not cfg.vaults:
        raise SystemExit(
            f"no vaults configured. Run: "
            f"obsidian.py config add NAME --path PATH "
            f"(config: {config_path()})"
        )
    if name is None:
        if cfg.default and cfg.default in cfg.vaults:
            name = cfg.default
        elif len(cfg.vaults) == 1:
            name = next(iter(cfg.vaults))
        else:
            available = ", ".join(sorted(cfg.vaults))
            raise SystemExit(
                f"multiple vaults configured but no default set. "
                f"Pass --vault NAME (one of: {available}), "
                f"or run: obsidian.py config set-default NAME"
            )
    if name not in cfg.vaults:
        available = ", ".join(sorted(cfg.vaults)) or "(none)"
        raise SystemExit(f"unknown vault: {name!r}. Configured: {available}")
    entry = cfg.vaults[name]
    if not isinstance(entry, dict) or "path" not in entry:
        raise SystemExit(f"malformed vault entry for {name!r} in {config_path()}")
    return Vault(
        name=name,
        path=Path(entry["path"]),
        read_only=bool(entry.get("read_only", False)),
    )


def vault_from_args(args: argparse.Namespace) -> Vault:
    """Resolve the vault for a subcommand from CLI args.

    --vault and --vault-path are mutually exclusive (enforced by argparse).
    --vault-path skips the config entirely; the resulting Vault has
    read_only=False because the read-only flag only lives in config.
    """
    direct = getattr(args, "vault_path", None)
    if direct:
        return Vault(name="<direct>", path=Path(direct), read_only=False)
    cfg = load_config()
    return resolve_vault(cfg, getattr(args, "vault", None))


def ensure_writable(v: Vault) -> None:
    if v.read_only:
        raise SystemExit(
            f"vault {v.name!r} is read-only "
            f"(read_only = true in {config_path()}). Refusing write."
        )


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
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            fm = "".join(lines[: i + 1])
            body = "".join(lines[i + 1:])
            return fm, body
    return "", text


@dataclass
class Heading:
    level: int
    text: str
    line_index: int


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
    v = vault_from_args(args)
    ensure_writable(v)
    vault = v.path
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
        mode = before
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
        if insert_at > 0 and not body_lines[insert_at - 1].endswith("\n"):
            body_lines[insert_at - 1] = body_lines[insert_at - 1] + "\n"
        body_lines.insert(insert_at, content)
        new_text = fm + "".join(body_lines)
    else:
        raise SystemExit(
            f"unknown anchor: {args.anchor} "
            "(use 'end', 'after-heading:TEXT', or 'before-heading:TEXT')"
        )

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
        patterns.append(re.compile(rf"!?\[\[{esc}(\||#|\^|\])"))
        url_form = esc.replace(r"\ ", r"(?:\\ |%20)")
        patterns.append(re.compile(rf"\]\(({url_form})\.md\)"))
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
    v = vault_from_args(args)
    vault = v.path
    note = args.note
    if note.endswith(".md"):
        note = note[:-3]
    basename = Path(note).name
    relpath = note

    if "/" not in note:
        candidates = [
            p.relative_to(vault).with_suffix("")
            for p in walk_markdown(vault)
            if p.stem == basename
        ]
        if len(candidates) == 1:
            relpath = str(candidates[0])
        elif len(candidates) > 1:
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
    v = vault_from_args(args)
    if args.apply:
        ensure_writable(v)
    vault = v.path
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

    plan: list[dict] = []
    for path in walk_markdown(vault):
        if path.resolve() == old_path.resolve():
            continue
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
        print(json.dumps(summary, indent=2))
        return 0

    new_path.parent.mkdir(parents=True, exist_ok=True)
    os.rename(old_path, new_path)

    h1_updated = False
    if getattr(args, "update_h1", False):
        text = new_path.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        body_lines = body.splitlines(keepends=True)
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
            break

    updated_files: list[str] = []
    for entry in plan:
        path = vault / entry["file"]
        text = path.read_text(encoding="utf-8")
        new_text = text
        for pat in link_patterns(old_basename, old_rel):
            def _sub(m: re.Match) -> str:
                matched = m.group(0)
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
# config subcommands
# ---------------------------------------------------------------------------


def cmd_config_path(args: argparse.Namespace) -> int:
    print(config_path())
    return 0


def cmd_config_list(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(json.dumps(
        {
            "config_path": str(config_path()),
            "default": cfg.default,
            "vaults": cfg.vaults,
        },
        indent=2,
        sort_keys=True,
    ))
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.name not in cfg.vaults:
        available = ", ".join(sorted(cfg.vaults)) or "(none)"
        raise SystemExit(f"unknown vault: {args.name!r}. Configured: {available}")
    entry = dict(cfg.vaults[args.name])
    entry["name"] = args.name
    entry["is_default"] = (cfg.default == args.name)
    print(json.dumps(entry, indent=2, sort_keys=True))
    return 0


def cmd_config_add(args: argparse.Namespace) -> int:
    raw = Path(args.path).expanduser()
    try:
        path = raw.resolve(strict=True)
    except FileNotFoundError:
        raise SystemExit(f"path does not exist: {args.path}")
    if not path.is_dir():
        raise SystemExit(f"path is not a directory: {args.path}")
    if not (path / ".obsidian").is_dir():
        raise SystemExit(
            f"this path doesn't look like an Obsidian vault — no .obsidian/ "
            f"directory inside: {path}. Open it in Obsidian first, or pick "
            f"a different folder."
        )

    cfg = load_config()
    if args.name in cfg.vaults:
        raise SystemExit(
            f"vault {args.name!r} is already configured. "
            f"Remove it first (config remove {args.name}) or pick a different name."
        )

    entry: dict = {"path": str(path)}
    if args.read_only:
        entry["read_only"] = True
    cfg.vaults[args.name] = entry

    became_default = False
    if args.default or cfg.default is None:
        cfg.default = args.name
        became_default = True

    save_config(cfg)
    print(json.dumps(
        {
            "added": args.name,
            "path": str(path),
            "read_only": bool(args.read_only),
            "default": became_default,
            "config_path": str(config_path()),
        },
        indent=2,
        sort_keys=True,
    ))
    return 0


def cmd_config_remove(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.name not in cfg.vaults:
        raise SystemExit(f"unknown vault: {args.name!r}")
    del cfg.vaults[args.name]
    cleared_default = False
    if cfg.default == args.name:
        cfg.default = None
        cleared_default = True
    save_config(cfg)
    print(json.dumps(
        {"removed": args.name, "default_cleared": cleared_default},
        indent=2,
        sort_keys=True,
    ))
    return 0


def cmd_config_set_default(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.name not in cfg.vaults:
        available = ", ".join(sorted(cfg.vaults)) or "(none)"
        raise SystemExit(f"unknown vault: {args.name!r}. Configured: {available}")
    cfg.default = args.name
    save_config(cfg)
    print(json.dumps({"default": cfg.default}, indent=2, sort_keys=True))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def add_vault_args(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--vault",
        help="vault profile name from config.json. Omit to use the configured "
        "default (or the sole configured vault).",
    )
    g.add_argument(
        "--vault-path",
        help="direct filesystem path to a vault. Escape hatch — bypasses "
        "config.json and the read-only flag. Mostly for tests and one-offs.",
    )


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 8):
        raise SystemExit(
            f"python 3.8+ required (have {sys.version.split()[0]}). "
            "On macOS, /usr/bin/python3 is recent enough."
        )

    parser = argparse.ArgumentParser(prog="obsidian.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rename = sub.add_parser("rename", help="rename a note and update links")
    add_vault_args(p_rename)
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
    add_vault_args(p_insert)
    p_insert.add_argument("--file", required=True)
    p_insert.add_argument(
        "--anchor",
        required=True,
        help="'end', 'after-heading:TEXT', or 'before-heading:TEXT'",
    )
    p_insert.add_argument("--content", required=True)

    p_back = sub.add_parser("backlinks", help="find references to a note")
    add_vault_args(p_back)
    p_back.add_argument("note")

    p_config = sub.add_parser("config", help="manage vault profiles")
    config_sub = p_config.add_subparsers(dest="config_cmd", required=True)

    config_sub.add_parser("path", help="print the path to config.json")
    config_sub.add_parser("list", help="list configured vaults")

    p_show = config_sub.add_parser("show", help="show one configured vault")
    p_show.add_argument("name")

    p_add = config_sub.add_parser("add", help="add a vault profile")
    p_add.add_argument("name")
    p_add.add_argument("--path", required=True, help="filesystem path to the vault")
    p_add.add_argument("--default", action="store_true",
                       help="mark as default (first added vault is auto-default)")
    p_add.add_argument("--read-only", action="store_true",
                       help="block writes to this vault")

    p_remove = config_sub.add_parser("remove", help="remove a vault profile")
    p_remove.add_argument("name")

    p_setdef = config_sub.add_parser("set-default", help="set the default vault")
    p_setdef.add_argument("name")

    args = parser.parse_args(argv)

    if args.cmd == "rename":
        return cmd_rename(args)
    if args.cmd == "insert":
        return cmd_insert(args)
    if args.cmd == "backlinks":
        return cmd_backlinks(args)
    if args.cmd == "config":
        if args.config_cmd == "path":
            return cmd_config_path(args)
        if args.config_cmd == "list":
            return cmd_config_list(args)
        if args.config_cmd == "show":
            return cmd_config_show(args)
        if args.config_cmd == "add":
            return cmd_config_add(args)
        if args.config_cmd == "remove":
            return cmd_config_remove(args)
        if args.config_cmd == "set-default":
            return cmd_config_set_default(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
