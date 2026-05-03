# obsidian-skill

A capability skill that lets agents read, write, and manage notes in an
Obsidian vault on macOS. Surface-only: it knows how to find the vault,
read/write notes safely, do link-aware operations like rename, and respect
Obsidian Sync. It does **not** know personal organizational conventions
(folder layout, daily-log format, naming) — those belong in a separate
workflow skill.

## ⛔ DANGER — READ BEFORE USE

> **By installing or using this skill, you give an AI agent full read/write
> access to your Obsidian vault. Deletes can be irreversible. Read
> [NOTICE](NOTICE) before proceeding.**

Specifically:

- The skill writes directly to your vault filesystem with no sandboxing
  and no per-call confirmation. Destructive-action guardrails are skill
  instructions, not enforced mechanisms.
- The `rename` operation modifies many files in a single pass to keep
  links intact. A misinterpreted or hallucinated rename can mass-rewrite
  the wrong references across the vault.
- An agent following a prompt-injection payload — embedded in note
  contents, meeting transcripts, or pasted material — can be directed
  to overwrite or delete unrelated notes.
- Recovery depends on Obsidian Sync version history (if enabled) or
  whatever else you have running (Time Machine, git). The skill keeps
  no backups of its own.
- **Back up your Obsidian vault before use.**

The authors accept no liability. See [LICENSE](LICENSE) and [NOTICE](NOTICE)
for full terms.

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
make test     # run the mechanical test suite
make package  # build the .skill bundle
make clean    # remove generated artifacts
```

Tests cover the bundled script end-to-end: insert anchors (end /
after-heading / before-heading), code-fence-aware heading match,
frontmatter preservation, link rewriting across all 6 wikilink/markdown
forms, path containment, the `--update-h1` opt-in, vault-profile
configuration (`config add` / `list` / `remove` / `set-default`),
`--vault NAME` resolution and default fallback, the read-only flag, and
error paths.

## Configuration

Vault profiles are stored in `~/.config/obsidian-skill/config.json`,
managed via the `config` subcommand:

```bash
python3 scripts/obsidian.py config add personal --path /Users/you/Documents/Personal
python3 scripts/obsidian.py config add work     --path /Users/you/Documents/Work --read-only
python3 scripts/obsidian.py config list
```

The first profile becomes the default. See SKILL.md for the full
surface.

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

## License

Apache 2.0 — see [LICENSE](LICENSE).
