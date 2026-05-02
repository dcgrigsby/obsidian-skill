# obsidian-skill

A capability skill that lets agents read, write, and manage notes in an
Obsidian vault on macOS. Surface-only: it knows how to find the vault,
read/write notes safely, do link-aware operations like rename, and respect
Obsidian Sync. It does **not** know personal organizational conventions
(folder layout, daily-log format, naming) — those belong in a separate
workflow skill.

## Companion skills

This skill is one of three:

- **`obsidian-skill`** (this repo) — surface for Obsidian.
- **`omnifocus-skill`** — surface for OmniFocus.
- **`personal-workflow`** — content-routing decisions (where things go,
  daily-log conventions, cross-tool patterns). Loads alongside the two
  capability skills.

## Install

```bash
npx skills add <repo> -g -a claude-code -a gemini-cli -a codex -a pi -y
```

Replace `<repo>` with the GitHub slug. After install, see `SKILL.md` for
the full surface and `scripts/obsidian.py` for the bundled helper script.

## Development

```bash
make test     # run the 66-case mechanical test suite
make package  # build the .skill bundle
make clean    # remove generated artifacts
```

Tests cover the bundled script's behavior end-to-end: insert anchors
(end / after-heading / before-heading), code-fence-aware heading match,
frontmatter preservation, link rewriting across all 6 wikilink/markdown
forms, path containment, the `--update-h1` opt-in, and error paths.

## Future considerations

**Decision table at the top of SKILL.md.** When the skill is used heavily
on smaller / faster models (Sonnet, Haiku), the SKILL.md body's narrative
form may cost more context than needed for routine ops. A possible
refinement is a one-paragraph routing table at the top:

> "For read / list / single-file create → use harness tools directly,
> after the path-containment check.
> For insert at heading / rename / backlinks → invoke `scripts/obsidian.py`.
> For replace / delete → see safety section before acting."

The narrative explanations stay below for when the model needs them. This
follows the progressive-disclosure pattern (metadata → body → references)
without restructuring the skill. Worth doing once we have evidence that
smaller models are over-reading the body or under-using the script.

Don't optimize this preemptively. Ship and observe failure modes first.
