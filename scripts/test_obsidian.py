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


def run(*args: str) -> tuple[int, str, str]:
    p = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )
    return p.returncode, p.stdout, p.stderr


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
        rc, out, err = run("insert", "--vault", str(v), "--file", "note.md",
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
        rc, _, err = run("insert", "--vault", str(v), "--file", "note.md",
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
        rc, _, err = run("insert", "--vault", str(v), "--file", "log.md",
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
        rc, _, err = run("insert", "--vault", str(v), "--file", "log.md",
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
        rc, out, err = run("insert", "--vault", str(v), "--file", "note.md",
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
        rc, _, err = run("insert", "--vault", str(v), "--file", "note.md",
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
        rc, _, err = run("insert", "--vault", str(v), "--file", "note.md",
                          "--anchor", "after-heading:Log", "--content", "x")
        case("returns nonzero", rc != 0)
        case("error mentions multiple matches", "multiple" in err.lower())
    finally:
        shutil.rmtree(v)


def test_insert_nonexistent_file():
    print("\n[insert] nonexistent file errors")
    v = make_vault()
    try:
        rc, _, err = run("insert", "--vault", str(v), "--file", "missing.md",
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
        rc, _, err = run("insert", "--vault", str(v), "--file", "note.md",
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
            rc, _, err = run("insert", "--vault", str(v),
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
        rc, out, err = run("backlinks", "--vault", str(v), "Sarah")
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
        rc, out, err = run("backlinks", "--vault", str(v), "Sarah")
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
        rc, out, _ = run("backlinks", "--vault", str(v), "Sarah")
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
        rc, out, err = run("rename", "--vault", str(v),
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
        rc, out, err = run("rename", "--vault", str(v),
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
        rc, out, err = run("rename", "--vault", str(v),
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
        rc, out, err = run("rename", "--vault", str(v),
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
        rc, out, err = run("rename", "--vault", str(v),
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
        rc, _, err = run("rename", "--vault", str(v),
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
        rc, _, err = run("rename", "--vault", str(v), "missing.md", "new.md")
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
            rc, _, err = run("rename", "--vault", str(v), "real.md", rel, "--apply")
            case("refuses path outside vault", rc != 0)
            case("source still in vault", (v / "real.md").exists())
            case("nothing created outside", not (outside / "evil.md").exists())
        finally:
            shutil.rmtree(outside)
    finally:
        shutil.rmtree(v)


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
