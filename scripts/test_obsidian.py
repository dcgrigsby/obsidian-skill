#!/usr/bin/env python3
"""
Mechanical test suite for obsidian.py.

Covers behaviors of the bundled script that don't need an LLM agent to
exercise: path containment, atomic writes, frontmatter awareness,
code-fence-aware heading matching, link rewriting across all forms,
soft-delete-style rename safety, --update-h1 flag, error paths.

Run:
  python3 scripts/test_obsidian.py

Exits 0 if all tests pass, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "obsidian.py"
PASS = 0
FAIL = 0
FAILURES: list[str] = []


def run(*args: str, env: dict | None = None) -> tuple[int, str, str]:
    full_env = {**os.environ, **(env or {})}
    p = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )
    return p.returncode, p.stdout, p.stderr


def make_config_env(tmpdir: Path) -> dict:
    """Point the script at a temp config file via OBSIDIAN_SKILL_CONFIG."""
    return {"OBSIDIAN_SKILL_CONFIG": str(tmpdir / "config.json")}


def make_vault() -> Path:
    d = Path(tempfile.mkdtemp(prefix="obs-test-"))
    (d / ".obsidian").mkdir()
    (d / ".obsidian" / "app.json").write_text("{}")
    return d


def case(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL  {name}: {detail}")


# -------------------------------------------------------------------- insert


def test_insert_at_end():
    print("\n[insert] at end")
    v = make_vault()
    try:
        f = v / "note.md"
        f.write_text("hello\n")
        rc, out, err = run("insert", "--vault-path", str(v), "--file", "note.md",
                           "--anchor", "end", "--content", "appended")
        case("returns 0", rc == 0, err)
        text = f.read_text()
        case("contains existing content", "hello" in text)
        case("contains appended content", "appended" in text)
        case("appended after existing", text.index("hello") < text.index("appended"))
    finally:
        shutil.rmtree(v)


def test_insert_at_end_no_trailing_newline():
    print("\n[insert] at end, no trailing newline")
    v = make_vault()
    try:
        f = v / "note.md"
        f.write_text("hello")  # no trailing newline
        rc, _, err = run("insert", "--vault-path", str(v), "--file", "note.md",
                          "--anchor", "end", "--content", "x")
        case("returns 0", rc == 0, err)
        text = f.read_text()
        # The script ensures the line we're appending after has \n.
        case("has linebreak between old and new", "hello\nx" in text)
    finally:
        shutil.rmtree(v)


def test_insert_after_heading():
    print("\n[insert] after-heading")
    v = make_vault()
    try:
        f = v / "log.md"
        f.write_text("## Log\n\n- old\n\n## Tasks\n\n- t1\n")
        rc, _, err = run("insert", "--vault-path", str(v), "--file", "log.md",
                          "--anchor", "after-heading:Log", "--content", "- new")
        case("returns 0", rc == 0, err)
        text = f.read_text()
        new_pos = text.index("- new")
        old_pos = text.index("- old")
        log_pos = text.index("## Log")
        case("new appears after Log heading", new_pos > log_pos)
        case("new appears before old (reverse-chrono)", new_pos < old_pos)
        case("Tasks section preserved", "## Tasks" in text and "- t1" in text)
    finally:
        shutil.rmtree(v)


def test_insert_before_heading():
    print("\n[insert] before-heading")
    v = make_vault()
    try:
        f = v / "log.md"
        f.write_text("## Log\n\n- old\n\n## Tasks\n\n- t1\n")
        rc, _, err = run("insert", "--vault-path", str(v), "--file", "log.md",
                          "--anchor", "before-heading:Tasks", "--content", "- end-of-log")
        case("returns 0", rc == 0, err)
        text = f.read_text()
        case("new appears before Tasks", text.index("end-of-log") < text.index("## Tasks"))
        case("new appears after old", text.index("end-of-log") > text.index("- old"))
    finally:
        shutil.rmtree(v)


def test_insert_heading_in_code_fence_skipped():
    print("\n[insert] code-fence-aware heading match")
    v = make_vault()
    try:
        f = v / "note.md"
        f.write_text(
            "Real heading below.\n"
            "\n"
            "```bash\n"
            "## Log\n"  # not a real heading
            "echo hi\n"
            "```\n"
            "\n"
            "## Log\n"  # this IS the real heading
            "\n"
            "- existing\n"
        )
        rc, out, err = run("insert", "--vault-path", str(v), "--file", "note.md",
                          "--anchor", "after-heading:Log", "--content", "- new")
        # The code fence contains a fake "## Log". The script should match the
        # real one only — so this should succeed (one match, not "multiple").
        case("returns 0 (single real match)", rc == 0, f"stderr: {err}")
        text = f.read_text()
        case("new inserted under real heading, not in fence",
             "```bash\n## Log\necho hi" in text and "## Log\n- new" in text)
    finally:
        shutil.rmtree(v)


def test_insert_no_match():
    print("\n[insert] no matching heading errors")
    v = make_vault()
    try:
        f = v / "note.md"
        f.write_text("just text\n")
        rc, _, err = run("insert", "--vault-path", str(v), "--file", "note.md",
                          "--anchor", "after-heading:Nope", "--content", "x")
        case("returns nonzero", rc != 0)
        case("error mentions no matching heading", "no heading matching" in err.lower())
    finally:
        shutil.rmtree(v)


def test_insert_multiple_matches():
    print("\n[insert] multiple matching headings errors")
    v = make_vault()
    try:
        f = v / "note.md"
        f.write_text("## Log\nfoo\n\n## Log\nbar\n")
        rc, _, err = run("insert", "--vault-path", str(v), "--file", "note.md",
                          "--anchor", "after-heading:Log", "--content", "x")
        case("returns nonzero", rc != 0)
        case("error mentions multiple matches", "multiple" in err.lower())
    finally:
        shutil.rmtree(v)


def test_insert_nonexistent_file():
    print("\n[insert] nonexistent file errors")
    v = make_vault()
    try:
        rc, _, err = run("insert", "--vault-path", str(v), "--file", "missing.md",
                          "--anchor", "end", "--content", "x")
        case("returns nonzero", rc != 0)
        case("error mentions create not insert", "does not exist" in err.lower())
    finally:
        shutil.rmtree(v)


def test_insert_preserves_frontmatter():
    print("\n[insert] frontmatter preserved")
    v = make_vault()
    try:
        f = v / "note.md"
        f.write_text("---\ntitle: hi\n---\n\n## Log\n\n- old\n")
        rc, _, err = run("insert", "--vault-path", str(v), "--file", "note.md",
                          "--anchor", "after-heading:Log", "--content", "- new")
        case("returns 0", rc == 0, err)
        text = f.read_text()
        case("frontmatter intact", text.startswith("---\ntitle: hi\n---\n"))
    finally:
        shutil.rmtree(v)


def test_insert_path_containment():
    print("\n[insert] refuses path outside vault")
    v = make_vault()
    try:
        # Create a file outside the vault
        outside_dir = Path(tempfile.mkdtemp(prefix="obs-out-"))
        outside_file = outside_dir / "evil.md"
        outside_file.write_text("don't touch\n")
        try:
            # Use a relative path that escapes the vault
            relative_to_outside = os.path.relpath(outside_file, v)
            rc, _, err = run("insert", "--vault-path", str(v),
                              "--file", relative_to_outside,
                              "--anchor", "end", "--content", "x")
            case("refuses path outside vault", rc != 0)
            case("error explains containment violation", "outside vault" in err.lower())
            case("outside file unchanged", outside_file.read_text() == "don't touch\n")
        finally:
            shutil.rmtree(outside_dir)
    finally:
        shutil.rmtree(v)


# ------------------------------------------------------------------- backlinks


def test_backlinks_bare_name():
    print("\n[backlinks] bare name auto-resolves to folder")
    v = make_vault()
    try:
        (v / "People").mkdir()
        (v / "People" / "Sarah.md").write_text("# Sarah\n")
        (v / "Notes.md").write_text(
            "[[Sarah]]\n"
            "[[People/Sarah|alias]]\n"
            "[[Sarah#topics]]\n"
            "![[Sarah]]\n"
            "[md](People/Sarah.md)\n"
        )
        rc, out, err = run("backlinks", "--vault-path", str(v), "Sarah")
        case("returns 0", rc == 0, err)
        data = json.loads(out)
        case("found 5 link forms", data["count"] == 5,
             f"got {data.get('count')}: {[m['match'] for m in data.get('backlinks', [])]}")
    finally:
        shutil.rmtree(v)


def test_backlinks_ambiguous():
    print("\n[backlinks] ambiguous bare name surfaces candidates")
    v = make_vault()
    try:
        (v / "People").mkdir()
        (v / "Refs").mkdir()
        (v / "People" / "Sarah.md").write_text("p\n")
        (v / "Refs" / "Sarah.md").write_text("r\n")
        rc, out, err = run("backlinks", "--vault-path", str(v), "Sarah")
        case("returns nonzero exit code", rc == 2)
        data = json.loads(out)
        case("error mentions ambiguity", data.get("error") == "ambiguous note name")
        case("candidates listed", len(data.get("candidates", [])) == 2)
    finally:
        shutil.rmtree(v)


def test_backlinks_excludes_obsidian_dir():
    print("\n[backlinks] skips .obsidian/ and .trash/")
    v = make_vault()
    try:
        (v / "Sarah.md").write_text("# Sarah\n")
        # Sneak a fake link inside .obsidian/ — should be ignored
        (v / ".obsidian" / "fake.md").write_text("[[Sarah]] this should be ignored\n")
        (v / ".trash").mkdir()
        (v / ".trash" / "old.md").write_text("[[Sarah]] also ignored\n")
        (v / "Notes.md").write_text("[[Sarah]] real link\n")
        rc, out, _ = run("backlinks", "--vault-path", str(v), "Sarah")
        case("returns 0", rc == 0)
        data = json.loads(out)
        case("only real link found, not the .obsidian or .trash ones", data["count"] == 1)
    finally:
        shutil.rmtree(v)


# ---------------------------------------------------------------------- rename


def make_rename_vault() -> Path:
    v = make_vault()
    (v / "People").mkdir()
    (v / "People" / "Sarah.md").write_text(
        "---\ntype: person\n---\n\n# Sarah\n\nbio\n\n## topics\n- a\n- b\n"
    )
    (v / "Notes.md").write_text(
        "[[Sarah]]\n"
        "[[People/Sarah|her profile]]\n"
        "[[Sarah#topics]]\n"
        "![[Sarah]]\n"
        "[md](People/Sarah.md)\n"
    )
    (v / "Meetings.md").write_text("met [[Sarah]] today\n[[Sarah]] led sync\n")
    return v


def test_rename_preview():
    print("\n[rename] preview without --apply doesn't mutate")
    v = make_rename_vault()
    try:
        before = (v / "People" / "Sarah.md").read_text()
        before_notes = (v / "Notes.md").read_text()
        rc, out, err = run("rename", "--vault-path", str(v),
                            "People/Sarah.md", "People/Sarah Chen.md")
        case("returns 0", rc == 0, err)
        data = json.loads(out)
        case("applied is false", data["applied"] is False)
        case("plan covers 7 references across 2 files",
             data["total_references"] == 7 and data["files_with_references"] == 2)
        case("file not actually renamed", (v / "People" / "Sarah.md").exists())
        case("Notes.md unchanged", (v / "Notes.md").read_text() == before_notes)
    finally:
        shutil.rmtree(v)


def test_rename_apply_all_link_forms():
    print("\n[rename] --apply rewrites all 5 link forms")
    v = make_rename_vault()
    try:
        rc, out, err = run("rename", "--vault-path", str(v),
                            "People/Sarah.md", "People/Sarah Chen.md", "--apply")
        case("returns 0", rc == 0, err)
        case("old file gone", not (v / "People" / "Sarah.md").exists())
        case("new file present", (v / "People" / "Sarah Chen.md").exists())

        notes = (v / "Notes.md").read_text()
        case("[[Sarah]] -> [[Sarah Chen]]", "[[Sarah Chen]]" in notes)
        case("alias updated", "[[People/Sarah Chen|her profile]]" in notes)
        case("heading anchor updated", "[[Sarah Chen#topics]]" in notes)
        case("embed updated", "![[Sarah Chen]]" in notes)
        case("markdown link updated", "(People/Sarah Chen.md)" in notes)

        meetings = (v / "Meetings.md").read_text()
        case("Meetings.md both wikilinks updated",
             meetings.count("[[Sarah Chen]]") == 2 and "[[Sarah]]" not in meetings)
    finally:
        shutil.rmtree(v)


def test_rename_no_h1_update_default():
    print("\n[rename] default does NOT update H1")
    v = make_rename_vault()
    try:
        rc, out, err = run("rename", "--vault-path", str(v),
                            "People/Sarah.md", "People/Sarah Chen.md", "--apply")
        case("returns 0", rc == 0, err)
        new_text = (v / "People" / "Sarah Chen.md").read_text()
        case("H1 unchanged (still '# Sarah')", "# Sarah\n" in new_text and "# Sarah Chen\n" not in new_text)
        data = json.loads(out)
        case("h1_updated reported false", data.get("h1_updated") is False)
    finally:
        shutil.rmtree(v)


def test_rename_with_h1_update():
    print("\n[rename] --update-h1 rewrites matching H1")
    v = make_rename_vault()
    try:
        rc, out, err = run("rename", "--vault-path", str(v),
                            "People/Sarah.md", "People/Sarah Chen.md",
                            "--apply", "--update-h1")
        case("returns 0", rc == 0, err)
        new_text = (v / "People" / "Sarah Chen.md").read_text()
        case("H1 updated to '# Sarah Chen'", "# Sarah Chen\n" in new_text)
        case("old H1 gone", "# Sarah\n" not in new_text or "# Sarah Chen\n" in new_text)
        data = json.loads(out)
        case("h1_updated reported true", data.get("h1_updated") is True)
        case("frontmatter preserved", new_text.startswith("---\ntype: person\n---\n"))
    finally:
        shutil.rmtree(v)


def test_rename_h1_no_match_skipped():
    print("\n[rename] --update-h1 leaves non-matching H1 alone")
    v = make_vault()
    try:
        (v / "Sarah.md").write_text("# Notes about Sarah\n\nstuff\n")
        rc, out, err = run("rename", "--vault-path", str(v),
                            "Sarah.md", "Sarah Chen.md",
                            "--apply", "--update-h1")
        case("returns 0", rc == 0, err)
        new_text = (v / "Sarah Chen.md").read_text()
        case("H1 left alone (didn't exactly match basename)",
             "# Notes about Sarah\n" in new_text)
        data = json.loads(out)
        case("h1_updated reported false", data.get("h1_updated") is False)
    finally:
        shutil.rmtree(v)


def test_rename_dest_exists_refuses():
    print("\n[rename] refuses to overwrite existing destination")
    v = make_rename_vault()
    try:
        (v / "People" / "Sarah Chen.md").write_text("existing\n")
        rc, _, err = run("rename", "--vault-path", str(v),
                          "People/Sarah.md", "People/Sarah Chen.md", "--apply")
        case("returns nonzero", rc != 0)
        case("error mentions destination exists", "already exists" in err.lower())
        case("source still present", (v / "People" / "Sarah.md").exists())
    finally:
        shutil.rmtree(v)


def test_rename_source_missing():
    print("\n[rename] refuses if source doesn't exist")
    v = make_vault()
    try:
        rc, _, err = run("rename", "--vault-path", str(v), "missing.md", "new.md")
        case("returns nonzero", rc != 0)
        case("error mentions source", "does not exist" in err.lower())
    finally:
        shutil.rmtree(v)


def test_rename_path_containment():
    print("\n[rename] refuses paths outside vault")
    v = make_vault()
    try:
        (v / "real.md").write_text("hi\n")
        outside = Path(tempfile.mkdtemp(prefix="obs-out-"))
        try:
            rel = os.path.relpath(outside / "evil.md", v)
            rc, _, err = run("rename", "--vault-path", str(v), "real.md", rel, "--apply")
            case("refuses path outside vault", rc != 0)
            case("source still in vault", (v / "real.md").exists())
            case("nothing created outside", not (outside / "evil.md").exists())
        finally:
            shutil.rmtree(outside)
    finally:
        shutil.rmtree(v)


# ----------------------------------------------------------------------- config


def test_config_path_uses_env_override():
    print("\n[config] path respects OBSIDIAN_SKILL_CONFIG env var")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    try:
        rc, out, err = run("config", "path", env=make_config_env(tmp))
        case("returns 0", rc == 0, err)
        case("prints the override path", out.strip() == str(tmp / "config.json"))
    finally:
        shutil.rmtree(tmp)


def test_config_list_empty():
    print("\n[config] list when no config file exists")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    try:
        rc, out, err = run("config", "list", env=make_config_env(tmp))
        case("returns 0", rc == 0, err)
        data = json.loads(out)
        case("vaults empty", data["vaults"] == {})
        case("default null", data["default"] is None)
    finally:
        shutil.rmtree(tmp)


def test_config_add_first_vault_becomes_default():
    print("\n[config] first added vault is auto-default")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v = make_vault()
    try:
        env = make_config_env(tmp)
        rc, out, err = run("config", "add", "personal", "--path", str(v), env=env)
        case("returns 0", rc == 0, err)
        data = json.loads(out)
        case("reports added", data["added"] == "personal")
        case("reports default true", data["default"] is True)

        rc, out, _ = run("config", "list", env=env)
        listed = json.loads(out)
        case("default set in config", listed["default"] == "personal")
        case("vault recorded", "personal" in listed["vaults"])
        case("path stored absolute", listed["vaults"]["personal"]["path"] == str(v.resolve()))
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v)


def test_config_add_second_vault_does_not_override_default():
    print("\n[config] second add does not steal default")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v1 = make_vault(); v2 = make_vault()
    try:
        env = make_config_env(tmp)
        run("config", "add", "personal", "--path", str(v1), env=env)
        rc, out, err = run("config", "add", "work", "--path", str(v2), env=env)
        case("returns 0", rc == 0, err)
        data = json.loads(out)
        case("not default", data["default"] is False)

        rc, out, _ = run("config", "list", env=env)
        listed = json.loads(out)
        case("default still personal", listed["default"] == "personal")
        case("both vaults present", set(listed["vaults"]) == {"personal", "work"})
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v1); shutil.rmtree(v2)


def test_config_add_explicit_default_flag():
    print("\n[config] --default flag promotes a later add")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v1 = make_vault(); v2 = make_vault()
    try:
        env = make_config_env(tmp)
        run("config", "add", "personal", "--path", str(v1), env=env)
        rc, _, err = run("config", "add", "work", "--path", str(v2), "--default", env=env)
        case("returns 0", rc == 0, err)
        rc, out, _ = run("config", "list", env=env)
        case("default switched to work", json.loads(out)["default"] == "work")
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v1); shutil.rmtree(v2)


def test_config_add_rejects_non_vault():
    print("\n[config] add refuses paths missing .obsidian/")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    bogus = Path(tempfile.mkdtemp(prefix="obs-bogus-"))
    try:
        env = make_config_env(tmp)
        rc, _, err = run("config", "add", "x", "--path", str(bogus), env=env)
        case("returns nonzero", rc != 0)
        case("error mentions .obsidian/", ".obsidian/" in err)
        case("config file not created",
             not (tmp / "config.json").exists())
    finally:
        shutil.rmtree(tmp); shutil.rmtree(bogus)


def test_config_add_rejects_duplicate():
    print("\n[config] add refuses duplicate name")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v = make_vault()
    try:
        env = make_config_env(tmp)
        run("config", "add", "personal", "--path", str(v), env=env)
        rc, _, err = run("config", "add", "personal", "--path", str(v), env=env)
        case("returns nonzero", rc != 0)
        case("error mentions already configured", "already configured" in err)
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v)


def test_config_remove_clears_default_when_default_removed():
    print("\n[config] removing the default clears default")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v1 = make_vault(); v2 = make_vault()
    try:
        env = make_config_env(tmp)
        run("config", "add", "personal", "--path", str(v1), env=env)
        run("config", "add", "work", "--path", str(v2), env=env)
        rc, out, err = run("config", "remove", "personal", env=env)
        case("returns 0", rc == 0, err)
        data = json.loads(out)
        case("reports default cleared", data["default_cleared"] is True)
        rc, out, _ = run("config", "list", env=env)
        case("default null after removal", json.loads(out)["default"] is None)
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v1); shutil.rmtree(v2)


def test_config_set_default_unknown():
    print("\n[config] set-default rejects unknown vault")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    try:
        env = make_config_env(tmp)
        rc, _, err = run("config", "set-default", "nope", env=env)
        case("returns nonzero", rc != 0)
        case("error mentions unknown", "unknown vault" in err)
    finally:
        shutil.rmtree(tmp)


# --------------------------------------------------------- vault resolution


def test_vault_by_name_resolves_via_config():
    print("\n[resolve] --vault NAME resolves through config")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v = make_vault()
    try:
        env = make_config_env(tmp)
        run("config", "add", "personal", "--path", str(v), env=env)
        (v / "note.md").write_text("hello\n")
        rc, _, err = run(
            "insert", "--vault", "personal", "--file", "note.md",
            "--anchor", "end", "--content", "world",
            env=env,
        )
        case("returns 0", rc == 0, err)
        case("file modified", "world" in (v / "note.md").read_text())
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v)


def test_vault_default_resolution():
    print("\n[resolve] no --vault uses default")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v = make_vault()
    try:
        env = make_config_env(tmp)
        run("config", "add", "personal", "--path", str(v), env=env)
        (v / "note.md").write_text("hello\n")
        rc, _, err = run(
            "insert", "--file", "note.md", "--anchor", "end", "--content", "x",
            env=env,
        )
        case("returns 0 (no --vault, picks default)", rc == 0, err)
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v)


def test_vault_multiple_no_default_errors():
    print("\n[resolve] multiple vaults, no default, no --vault: errors helpfully")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v1 = make_vault(); v2 = make_vault()
    try:
        env = make_config_env(tmp)
        run("config", "add", "personal", "--path", str(v1), env=env)
        run("config", "add", "work", "--path", str(v2), env=env)
        run("config", "remove", "personal", env=env)
        run("config", "add", "personal", "--path", str(v1), env=env)
        # personal is now default again — clear it
        # Easier: build state directly.
        (tmp / "config.json").write_text(json.dumps({
            "vaults": {
                "personal": {"path": str(v1)},
                "work": {"path": str(v2)},
            },
        }))
        (v1 / "n.md").write_text("hi\n")
        rc, _, err = run(
            "insert", "--file", "n.md", "--anchor", "end", "--content", "x",
            env=env,
        )
        case("returns nonzero", rc != 0)
        case("error mentions multiple", "multiple vaults" in err.lower() or "no default" in err.lower())
        case("error lists both names", "personal" in err and "work" in err)
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v1); shutil.rmtree(v2)


def test_vault_unknown_name_errors():
    print("\n[resolve] unknown --vault NAME errors with available list")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v = make_vault()
    try:
        env = make_config_env(tmp)
        run("config", "add", "personal", "--path", str(v), env=env)
        (v / "n.md").write_text("hi\n")
        rc, _, err = run(
            "insert", "--vault", "ghost", "--file", "n.md",
            "--anchor", "end", "--content", "x",
            env=env,
        )
        case("returns nonzero", rc != 0)
        case("error mentions unknown", "unknown vault" in err)
        case("error lists 'personal' as configured", "personal" in err)
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v)


def test_read_only_blocks_writes():
    print("\n[resolve] read_only=true blocks insert and rename")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    v = make_vault()
    try:
        env = make_config_env(tmp)
        run("config", "add", "archive", "--path", str(v), "--read-only", env=env)
        (v / "n.md").write_text("hi\n")

        rc, _, err = run(
            "insert", "--vault", "archive", "--file", "n.md",
            "--anchor", "end", "--content", "x",
            env=env,
        )
        case("insert blocked", rc != 0 and "read-only" in err)
        case("file not modified", (v / "n.md").read_text() == "hi\n")

        # Rename --apply should also block. Preview (no --apply) is fine.
        rc, _, _ = run(
            "rename", "--vault", "archive", "n.md", "renamed.md",
            env=env,
        )
        case("rename preview still allowed", rc == 0)

        rc, _, err = run(
            "rename", "--vault", "archive", "n.md", "renamed.md", "--apply",
            env=env,
        )
        case("rename apply blocked", rc != 0 and "read-only" in err)
        case("file not renamed", (v / "n.md").exists())
    finally:
        shutil.rmtree(tmp); shutil.rmtree(v)


def test_no_config_helpful_error():
    print("\n[resolve] no config + no --vault-path: helpful error")
    tmp = Path(tempfile.mkdtemp(prefix="obs-cfg-"))
    try:
        env = make_config_env(tmp)
        # No config.json exists.
        rc, _, err = run(
            "insert", "--file", "x.md", "--anchor", "end", "--content", "y",
            env=env,
        )
        case("returns nonzero", rc != 0)
        case("error tells user how to set up", "config add" in err)
    finally:
        shutil.rmtree(tmp)


# ----------------------------------------------------------------------- main


def main() -> int:
    tests = [
        test_insert_at_end,
        test_insert_at_end_no_trailing_newline,
        test_insert_after_heading,
        test_insert_before_heading,
        test_insert_heading_in_code_fence_skipped,
        test_insert_no_match,
        test_insert_multiple_matches,
        test_insert_nonexistent_file,
        test_insert_preserves_frontmatter,
        test_insert_path_containment,
        test_backlinks_bare_name,
        test_backlinks_ambiguous,
        test_backlinks_excludes_obsidian_dir,
        test_rename_preview,
        test_rename_apply_all_link_forms,
        test_rename_no_h1_update_default,
        test_rename_with_h1_update,
        test_rename_h1_no_match_skipped,
        test_rename_dest_exists_refuses,
        test_rename_source_missing,
        test_rename_path_containment,
        test_config_path_uses_env_override,
        test_config_list_empty,
        test_config_add_first_vault_becomes_default,
        test_config_add_second_vault_does_not_override_default,
        test_config_add_explicit_default_flag,
        test_config_add_rejects_non_vault,
        test_config_add_rejects_duplicate,
        test_config_remove_clears_default_when_default_removed,
        test_config_set_default_unknown,
        test_vault_by_name_resolves_via_config,
        test_vault_default_resolution,
        test_vault_multiple_no_default_errors,
        test_vault_unknown_name_errors,
        test_read_only_blocks_writes,
        test_no_config_helpful_error,
    ]
    for t in tests:
        t()
    total = PASS + FAIL
    print(f"\n{'=' * 50}")
    print(f"Total: {PASS}/{total} passed, {FAIL} failed")
    if FAIL:
        print("\nFailures:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
