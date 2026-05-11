---
name: obsidian
description: |-
  Read, write, and manage notes in the user's Obsidian vault(s) on macOS. Use whenever the user wants to find, read, search, create, edit, append to, rename, or delete notes; capture meeting transcripts or reference material; add to a daily log; query backlinks; or otherwise interact with their Obsidian-managed knowledge base. The user keeps reference notes, journals, meeting transcripts, and freeform writing in Obsidian — anything that is not a committed action item belongs here (action items go to OmniFocus). This skill is the surface layer; it knows how to find the vault, read and write notes safely, protect against accidental data loss, and respect Obsidian Sync. It does NOT know personal organizational conventions (folder layout, daily log format, naming) — those come from the personal-workflow skill if it is loaded.
---

# Obsidian

This skill gives agents a safe, generic surface for interacting with the user's Obsidian vault. It deliberately stays out of personal organizational conventions — folder layout, naming patterns, daily log format, tag taxonomy. Those belong in a separate workflow skill. This one knows how to find the vault, read and write `.md` files, and avoid destroying notes.

**Scope: macOS only in v1.** Linux and Windows have analogous Obsidian config paths; extending support to them is straightforward future work but not done here.

## Progressive disclosure

This file is the always-loaded core. Load these only when their topic comes up:

- `references/setup.md` — registering a new vault, multi-vault selection, fixing a misregistered vault, the full `config.json` schema.
- `references/sync-and-recovery.md` — Obsidian Sync awareness, concurrent editing in the Obsidian app, recoverability after a write goes wrong.
- `references/niche.md` — URI scheme for opening notes in the app, attachments handling, and the documented out-of-scope list.

---

## Vault discovery

The user has at least one Obsidian vault. They may have several. Treat the vault registry as a list, even when it has one entry — keeps the model uniform.

### What to know about a vault

- `name` — short profile name the agent uses to refer to the vault (e.g. `personal`, `work`). Becomes the lookup key in `config.json`.
- `path` — absolute filesystem path to the vault directory.
- `read_only` — optional; if `true`, the skill blocks all write ops on this vault (see "Read-only mode").

The default vault is recorded once at the top level of `config.json` (`"default": "<name>"`), not per-profile.

### Quick path to a usable vault

1. `python3 scripts/obsidian.py config list` — shows configured vaults.
2. If none are configured, load `references/setup.md` and follow the first-use flow (it derives a vault path from `~/Library/Application Support/obsidian/obsidian.json` when possible).
3. Otherwise, select the appropriate profile — the script falls back to the default (or sole) vault when no `--vault` is passed.

For multi-vault selection rules, registering new vaults, and correcting a misregistered one, see `references/setup.md`.

---

## Operations

The skill exposes these operations. Several are implemented by a small bundled script (`scripts/obsidian.py`) — see "Bundled script" below for which ones and why.

### Reading

#### `read <path>`
Read a note's contents. Path is relative to the vault root, e.g. `Daily/2026-05-02.md`.

#### `list [folder]`
List `.md` files in the vault, optionally scoped to a subfolder. Recursive by default. Always exclude `.obsidian/`, `.trash/`, and `.git/`. Don't include attachments by default — see `references/niche.md`.

#### `search <query>`
Full-text search across the vault.

**Prefer ripgrep.** Detect with `command -v rg`. If available:

```bash
rg --type md --glob '!.obsidian' --glob '!.trash' --glob '!.git' \
   "<query>" "<vault-path>"
```

If `rg` is not available, fall back to `grep`:

```bash
grep -r --include='*.md' \
  --exclude-dir=.obsidian --exclude-dir=.trash --exclude-dir=.git \
  "<query>" "<vault-path>"
```

When `rg` is missing, mention it once per conversation: "Using grep — `rg` (ripgrep) would be faster if you want to install it." Don't repeat the message after the first search.

#### `backlinks <note-name>`
Find every note that links to `<note-name>`. Convenience over `search` because Obsidian links come in several forms; the skill knows them all and the agent doesn't have to reinvent the regex:

- `[[<name>]]` — basic wikilink
- `[[<name>|alias]]` — with display alias
- `[[<name>#heading]]` — heading anchor
- `[[<name>^block-id]]` — block reference
- `![[<name>]]` — embed (`!` prefix)
- `[text](<name>.md)` and `[text](path/<name>.md)` — markdown links (URL-encoded forms too)

Match across all of these. Match folder-qualified forms when the name includes a path. Bundled script handles this; agents don't need to implement the regex themselves.

### Writing

The write operations are designed around one principle: **never silently overwrite existing content.** Sync's per-file version history is a real safety net, but it works best for mistakes the user catches quickly. Slow drift — a paragraph quietly lost two weeks ago — is what we want to make structurally hard.

**Path containment.** Before any write, resolve the target path with `realpath` and verify it's inside the registered vault directory. Refuse writes that resolve outside the vault. This prevents path traversal (`../../etc/...`) and catches honest typos.

**Frontmatter awareness.** Obsidian notes commonly start with YAML frontmatter delimited by `---` lines. Treat frontmatter as structural:

- `insert --at end` is fine — it operates at end of file regardless.
- `insert --at after-heading` and `before-heading` only match headings in the body, not characters that appear inside frontmatter.
- `replace` should preserve frontmatter unless the agent is explicitly rewriting it. If frontmatter is being modified, surface that.
- `create` may include frontmatter or not, as appropriate.

**Atomic writes.** For `create` and `replace`: write to a temp file in the same directory, then `mv` into place. Avoids partial reads if Obsidian's filesystem watcher catches the file mid-write.

If the user is actively editing a note in Obsidian, the write may collide. See `references/sync-and-recovery.md` for the "modified externally" semantics and recovery options after a write goes wrong.

#### `create <path> <content>`
Create a new note. **Errors if the file already exists** — use `replace` to overwrite. Creates parent folders if needed.

#### `insert <path> <content> --at <anchor>`
Add content to an existing note without replacing existing content. **Errors if the file doesn't exist** — use `create` instead. Anchors:

- `end` — append to end of file. Add a leading newline if the file doesn't already end with one.
- `after-heading "Heading text"` — insert immediately after the matching heading line. New content goes before any existing section content (good for reverse-chronological logs).
- `before-heading "Heading text"` — insert immediately before the matching heading line. Good for appending to the section that precedes the named heading.

**Heading match rules:**
- Match exact heading text after the leading `#`s and a single space.
- Match any heading level (`#` through `######`).
- Heading line must start at column 0 — no leading whitespace.
- Skip lines inside fenced code blocks (` ``` ` or `~~~`) — they look like headings but aren't.
- Match the raw text. `## **Bold**` matches the literal string `**Bold**`, not `Bold`.
- If multiple headings match, ask the user which.
- If none match, error rather than guessing.

The bundled script handles the parsing.

#### `replace <path> <new-content>`
Replace the entire contents of an existing file. **The agent must clearly surface the change in the conversation** — at minimum a summary of what's changing and why; ideally a diff for non-trivial edits. The user reading the conversation is the backstop against silent drift.

For partial edits (one paragraph, a typo), prefer the harness's structural edit tools (e.g. exact-string `Edit`) over reading the whole file and writing it back — they're inherently more visible about what's changing.

#### `rename <old-path> <new-path>`
Rename a note and update all inbound links across the vault. This is non-trivial because Obsidian links come in several forms (see `backlinks`); the bundled script handles them all.

Flow:
1. Resolve all references to `<old-path>` in every other note.
2. Show the user a preview: "Renaming will touch N references across M files. Show list?" — on confirmation, proceed.
3. Rename the file via `mv`, then rewrite all references in one pass.
4. Surface any references the script couldn't confidently update (e.g. ambiguous case-folding) so the user can fix them by hand.

If the user says "actually let me rename it in Obsidian instead," respect that — Obsidian's in-app rename also handles links.

**Updating the in-body H1.** By default `rename` only touches link references — the file's own `# Heading` is left alone. This is the conservative contract. But a common case is renaming a note where the file IS its title (e.g. `People/Sarah.md` whose first line is `# Sarah`): after rename, the file is "Sarah Chen.md" but greets you with "# Sarah".

If the renamed file's first body H1 exactly matches the old basename, offer the user the `--update-h1` flag, which rewrites that H1 to the new basename. Use it when the H1 looks like the file's own title; skip it when the H1 is something like `# Notes about Sarah` (where the rename isn't really about the H1 subject).

#### `delete <path>`
**Soft-delete by default.** Move the file to the vault's `.trash/` folder (create if missing). Obsidian recognizes `.trash/` and surfaces it in the trash view.

Only do a hard `rm` if the user explicitly asks ("permanently delete," "hard delete," "rm it"). Surface what you're doing either way.

If a file with the same name already exists in `.trash/`, append a timestamp (e.g. `Note (2026-05-02-1430).md`) to disambiguate rather than overwriting.

#### `trash-list`
List the contents of `.trash/` with mtime and size. Useful for "what have I thrown away recently."

#### `trash-empty [--older-than <duration>]`
Permanently remove items from `.trash/`.

- Without `--older-than`: deletes everything in `.trash/`. **Confirm before doing it** — show a count and total size first.
- With `--older-than`: deletes only items older than the specified duration (e.g. `30d`, `6m`). Confirmation optional but still recommended for large amounts.

---

## Read-only mode

Two ways to enter read-only mode; either one blocks all write ops.

- **Vault-level**: the profile in `config.json` has `"read_only": true`. The bundled script enforces this on `insert` and `rename --apply` — even if the agent ignores the flag, the script will refuse the write. Useful for archive vaults the user never wants mutated. (Note: `--vault-path` bypasses the config, so it also bypasses this flag — it's an escape hatch, not a sandbox.)
- **Conversation-level**: user says "read-only please," "don't write to my vault," etc. Hold for the rest of the conversation unless the user lifts it.

When a write op is blocked, surface clearly: "I can't do that — vault is in read-only mode. Switch out of read-only mode if you want to proceed."

---

## Bundled script

Several operations are implemented by `scripts/obsidian.py`:

- `rename` — link-aware rename across all note formats
- `insert --at after-heading` / `before-heading` — markdown structure parsing (code-fence aware, frontmatter aware)
- `backlinks` — multi-form link search
- `config` — vault-profile management (see `references/setup.md`)

The other operations (`read`, `list`, `search`, `create`, `replace`, `delete`, `trash-list`, `trash-empty`) are simple enough that the agent can do them inline with standard tools (Read, Write, Edit, `mv`, `find`, `grep`/`rg`). Even so, the agent still needs to know *which* vault — read `config.json` first (or run `config list`) to resolve the path before touching files inline.

**Dependency:** Python 3.8+, stdlib only. macOS ships a recent enough `/usr/bin/python3` by default. No third-party packages, no `pip install`, no `uv` — clone and run.

The script is invoked as:

```bash
python3 <skill-path>/scripts/obsidian.py <command> [args...]
```
