---
name: obsidian
description: |-
  Read, write, and manage notes in the user's Obsidian vault(s) on macOS. Use whenever the user wants to find, read, search, create, edit, append to, rename, or delete notes; capture meeting transcripts or reference material; add to a daily log; query backlinks; or otherwise interact with their Obsidian-managed knowledge base. The user keeps reference notes, journals, meeting transcripts, and freeform writing in Obsidian — anything that is not a committed action item belongs here (action items go to OmniFocus). This skill is the surface layer; it knows how to find the vault, read and write notes safely, protect against accidental data loss, and respect Obsidian Sync. It does NOT know personal organizational conventions (folder layout, daily log format, naming) — those come from the personal-workflow skill if it is loaded.
---

# Obsidian

This skill gives agents a safe, generic surface for interacting with the
user's Obsidian vault. It deliberately stays out of personal organizational
conventions — folder layout, naming patterns, daily log format, tag
taxonomy. Those belong in a separate workflow skill. This one knows how to
find the vault, read and write `.md` files, and avoid destroying notes.

**Scope: macOS only in v1.** Linux and Windows have analogous Obsidian
config paths; extending support to them is straightforward future work but
not done here.

If the user has **Obsidian Sync**, per-file version history is the primary
recovery backstop. Without Sync, recovery falls to whatever else is
running (Time Machine, iCloud Drive history, git, Dropbox versions). The
safety design below does not depend on Sync — it just gets cheaper to
recover from honest mistakes when Sync is present.

---

## Vault discovery

The user has at least one Obsidian vault. They may have several. Treat
the vault registry as a list, even when it has one entry — keeps the
model uniform.

### What to know about a vault

- `path` — absolute filesystem path to the vault directory
- `name` — Obsidian's display name (used by the URI scheme)
- `default` — optional; only meaningful when there are multiple vaults
- `readOnly` — optional; if `true`, the skill blocks all write ops on
  this vault (see "Read-only mode")

### Deriving the vault name from a path

On macOS, Obsidian maintains a registry of vaults at:

```
~/Library/Application Support/obsidian/obsidian.json
```

Structure (roughly):

```json
{
  "vaults": {
    "<vault-id>": { "path": "/Users/dan/Documents/MyVault", "ts": ... }
  }
}
```

Obsidian's display name for a vault is the basename of its `path`. The
URI scheme uses this name. Prefer reading `obsidian.json` over guessing.

If the file doesn't exist or doesn't list a path, fall back to the
directory's basename and tell the user that's what you did.

### Validating that a path is a vault

Before registering a path, check that it contains a `.obsidian/`
directory. Obsidian creates that directory on first open of a vault, so
its absence almost always means a typo, a wrong folder, or a vault
that's never been opened.

If the path doesn't have `.obsidian/`, surface the issue: "This path
doesn't look like an Obsidian vault — there's no `.obsidian/` directory
inside. Did you mean a different folder, or is this a new vault you
haven't opened yet?"

### First-use flow (no vault registered)

1. Read `~/Library/Application Support/obsidian/obsidian.json`. If it
   lists exactly one vault, propose: "I see one Obsidian vault at
   `<path>`. Use this one?"
2. If multiple vaults are listed, show them and ask which (offer to
   register all).
3. If the file is missing, ask the user for the vault path directly.
4. Validate the path (`.obsidian/` check).
5. Persist (see "Persisting vault info").

### Multi-vault selection within a conversation

- One registered vault → use it implicitly.
- Multiple registered, one marked `default` → use the default unless
  the user names another.
- Multiple registered, no default → ask which on first reference;
  offer to mark one as default after.
- Once a vault is selected in a conversation, stick with it for the
  rest of the conversation unless the user redirects.

### Adding or correcting a vault

User cues like "I have another vault," "add my work vault," "the vault
is actually at X" → update the registry. For corrections, edit the
existing entry — don't append a duplicate. Confirm path and name
before saving. Run the `.obsidian/` validation step.

---

## Persisting vault info across agent harnesses

Different harnesses have different persistence mechanisms. Adapt rather
than assume.

- **Structured memory system** (e.g. Claude Code's per-project memory):
  write a memory entry that captures the vault registry. One entry per
  vault, or one entry containing the list — either is fine, as long as
  it's discoverable on future conversations.
- **Project-level config file fallbacks**, in order of preference:
  - Project `CLAUDE.md` in the working directory
  - User-global `~/.claude/CLAUDE.md`
  - `AGENTS.md` in the working directory
  - `.cursorrules` if Cursor is in use
  Append a small "Obsidian vaults" section if one isn't already there.
- **No persistence available**: ask the user each session, and offer to
  set up persistence ("I can save this to `<path>` — want me to?").

In all cases, **tell the user where the info is being stored** before
writing it. Persistence is invisible by default and that's a footgun —
the user should know what's on disk and where, so they can edit or
remove it.

When checking on later conversations, look in all the places the info
might have been stored: memory first, then likely config files in the
working directory and home directory.

---

## Operations

The skill exposes these operations. Several are implemented by a small
bundled script (`scripts/obsidian.py`) — see "Bundled script" below for
which ones and why.

### Reading

#### `read <path>`
Read a note's contents. Path is relative to the vault root, e.g.
`Daily/2026-05-02.md`.

#### `list [folder]`
List `.md` files in the vault, optionally scoped to a subfolder.
Recursive by default. Always exclude `.obsidian/`, `.trash/`, and
`.git/`. Don't include attachments by default — see "Attachments."

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

When `rg` is missing, mention it once per conversation: "Using grep —
`rg` (ripgrep) would be faster if you want to install it." Don't repeat
the message after the first search.

#### `backlinks <note-name>`
Find every note that links to `<note-name>`. Convenience over `search`
because Obsidian links come in several forms; the skill knows them all
and the agent doesn't have to reinvent the regex:

- `[[<name>]]` — basic wikilink
- `[[<name>|alias]]` — with display alias
- `[[<name>#heading]]` — heading anchor
- `[[<name>^block-id]]` — block reference
- `![[<name>]]` — embed (`!` prefix)
- `[text](<name>.md)` and `[text](path/<name>.md)` — markdown links
  (URL-encoded forms too)

Match across all of these. Match folder-qualified forms when the name
includes a path. Bundled script handles this; agents don't need to
implement the regex themselves.

### Writing

The write operations are designed around one principle: **never silently
overwrite existing content.** Sync's per-file version history is a real
safety net, but it works best for mistakes the user catches quickly.
Slow drift — a paragraph quietly lost two weeks ago — is what we want
to make structurally hard.

**Path containment.** Before any write, resolve the target path with
`realpath` and verify it's inside the registered vault directory.
Refuse writes that resolve outside the vault. This prevents path
traversal (`../../etc/...`) and catches honest typos.

**Frontmatter awareness.** Obsidian notes commonly start with YAML
frontmatter delimited by `---` lines. Treat frontmatter as structural:

- `insert --at end` is fine — it operates at end of file regardless.
- `insert --at after-heading` and `before-heading` only match headings
  in the body, not characters that appear inside frontmatter.
- `replace` should preserve frontmatter unless the agent is explicitly
  rewriting it. If frontmatter is being modified, surface that.
- `create` may include frontmatter or not, as appropriate.

**Atomic writes.** For `create` and `replace`: write to a temp file in
the same directory, then `mv` into place. Avoids partial reads if
Obsidian's filesystem watcher catches the file mid-write.

#### `create <path> <content>`
Create a new note. **Errors if the file already exists** — use
`replace` to overwrite. Creates parent folders if needed.

#### `insert <path> <content> --at <anchor>`
Add content to an existing note without replacing existing content.
**Errors if the file doesn't exist** — use `create` instead. Anchors:

- `end` — append to end of file. Add a leading newline if the file
  doesn't already end with one.
- `after-heading "Heading text"` — insert immediately after the
  matching heading line. New content goes before any existing
  section content (good for reverse-chronological logs).
- `before-heading "Heading text"` — insert immediately before the
  matching heading line. Good for appending to the section that
  precedes the named heading.

**Heading match rules:**
- Match exact heading text after the leading `#`s and a single space.
- Match any heading level (`#` through `######`).
- Heading line must start at column 0 — no leading whitespace.
- Skip lines inside fenced code blocks (` ``` ` or `~~~`) — they look
  like headings but aren't.
- Match the raw text. `## **Bold**` matches the literal string
  `**Bold**`, not `Bold`.
- If multiple headings match, ask the user which.
- If none match, error rather than guessing.

The bundled script handles the parsing.

#### `replace <path> <new-content>`
Replace the entire contents of an existing file. **The agent must
clearly surface the change in the conversation** — at minimum a
summary of what's changing and why; ideally a diff for non-trivial
edits. The user reading the conversation is the backstop against
silent drift.

For partial edits (one paragraph, a typo), prefer the harness's
structural edit tools (e.g. exact-string `Edit`) over reading the
whole file and writing it back — they're inherently more visible
about what's changing.

#### `rename <old-path> <new-path>`
Rename a note and update all inbound links across the vault. This is
non-trivial because Obsidian links come in several forms (see
`backlinks`); the bundled script handles them all.

Flow:
1. Resolve all references to `<old-path>` in every other note.
2. Show the user a preview: "Renaming will touch N references across
   M files. Show list?" — on confirmation, proceed.
3. Rename the file via `mv`, then rewrite all references in one pass.
4. Surface any references the script couldn't confidently update
   (e.g. ambiguous case-folding) so the user can fix them by hand.

If the user says "actually let me rename it in Obsidian instead,"
respect that — Obsidian's in-app rename also handles links.

**Updating the in-body H1.** By default `rename` only touches link
references — the file's own `# Heading` is left alone. This is the
conservative contract. But a common case is renaming a note where the
file IS its title (e.g. `People/Sarah.md` whose first line is `# Sarah`):
after rename, the file is "Sarah Chen.md" but greets you with "# Sarah".

If the renamed file's first body H1 exactly matches the old basename,
offer the user the `--update-h1` flag, which rewrites that H1 to the new
basename. Use it when the H1 looks like the file's own title; skip it
when the H1 is something like `# Notes about Sarah` (where the rename
isn't really about the H1 subject).

#### `delete <path>`
**Soft-delete by default.** Move the file to the vault's `.trash/`
folder (create if missing). Obsidian recognizes `.trash/` and surfaces
it in the trash view.

Only do a hard `rm` if the user explicitly asks ("permanently
delete," "hard delete," "rm it"). Surface what you're doing either
way.

If a file with the same name already exists in `.trash/`, append a
timestamp (e.g. `Note (2026-05-02-1430).md`) to disambiguate rather
than overwriting.

#### `trash-list`
List the contents of `.trash/` with mtime and size. Useful for "what
have I thrown away recently."

#### `trash-empty [--older-than <duration>]`
Permanently remove items from `.trash/`.

- Without `--older-than`: deletes everything in `.trash/`. **Confirm
  before doing it** — show a count and total size first.
- With `--older-than`: deletes only items older than the specified
  duration (e.g. `30d`, `6m`). Confirmation optional but still
  recommended for large amounts.

---

## Read-only mode

Two ways to enter read-only mode; either one blocks all write ops.

- **Vault-level**: the registry entry has `readOnly: true`. Useful for
  archive vaults the user never wants mutated.
- **Conversation-level**: user says "read-only please," "don't write
  to my vault," etc. Hold for the rest of the conversation unless
  the user lifts it.

When a write op is blocked, surface clearly: "I can't do that — vault
is in read-only mode. Switch out of read-only mode if you want to
proceed."

---

## Bundled script

Several operations are implemented by `scripts/obsidian.py`:

- `rename` — link-aware rename across all note formats
- `insert --at after-heading` / `before-heading` — markdown structure
  parsing (code-fence aware, frontmatter aware)
- `backlinks` — multi-form link search

The other operations (`read`, `list`, `search`, `create`, `replace`,
`delete`, `trash-list`, `trash-empty`) are simple enough that the
agent can do them inline with standard tools (Read, Write, Edit,
`mv`, `find`, `grep`/`rg`).

**Dependency:** Python 3, available on macOS by default at
`/usr/bin/python3`. If `python3` is missing, the script fails with a
helpful message.

The script is invoked as:

```bash
python3 <skill-path>/scripts/obsidian.py <command> [args...]
```

---

## Sync awareness

If Obsidian Sync is enabled, it watches the vault filesystem and
propagates changes outward. The skill writes directly to disk —
there's no Obsidian API we're bypassing. Practices:

- **Atomic writes** for `create` and `replace` (described above).
- **Avoid rapid repeated writes** to the same file — gives Sync more
  chances to race. Batch updates locally, then write once.
- **Don't write inside `.obsidian/`** unless the user explicitly asks.
  That's where Sync conflicts get ugly.
- **Sync conflict files** (`Note (conflict 2026-05-02 1430).md`) may
  appear in the vault. Don't surface them as normal notes; if you see
  one, mention it to the user.

### Concurrent editing in the Obsidian app

If the user is actively editing a note in Obsidian and the skill writes
to it, Obsidian shows a "modified externally" prompt and there's a
real chance of data loss depending on which side the user picks.
Heuristic: if the user has just mentioned editing something or you
have reason to believe Obsidian is open on that file, ask before
writing to it.

---

## Recoverability

Two failure modes to keep in mind:

1. **Fast-detected mistakes** ("undo what you just did"): if Sync is
   present, point the user at **File → View file history** in
   Obsidian (or right-click → Show version history). Without Sync,
   point at whatever else they have running (Time Machine, git, etc.).
2. **Slow-detected mistakes** (a paragraph quietly overwritten,
   noticed weeks later): version history retention is finite. The
   skill's design — no silent overwrites, mandatory visibility on
   `replace`, soft-delete by default — is meant to prevent this
   class of error in the first place. Conversation history is the
   audit trail.

---

## URI scheme (opening notes in the Obsidian app)

When the user wants to "open this in Obsidian":

```
obsidian://open?vault=<vault-name>&file=<note-path-without-extension>
```

URL-encode the vault name and file path.

```bash
open "obsidian://open?vault=MyVault&file=Daily%2F2026-05-02"
```

If the URI doesn't open the right note, the registered vault name may
not match what Obsidian expects — re-derive from `obsidian.json`.

**Note:** depending on the user's Obsidian settings, this URI may
*create* the note if it doesn't exist. If you want to be sure you're
opening an existing note, check that it exists first.

---

## Attachments and non-markdown files

Obsidian vaults often contain images, PDFs, audio, `.canvas` JSON
files, Excalidraw drawings, and other non-markdown content. The skill
operates on `.md` files. When the user asks about attachments
explicitly, be conservative: don't move, rename, or delete them
without confirmation, since they may be referenced from notes via
embed syntax (`![[image.png]]`).

---

## Out of scope

This skill stays at the surface layer. The following belong in a
separate personal-workflow skill (or are user-specific decisions):

- Folder layout inside the vault (`Daily/`, `Reference/`, etc.)
- Daily log format, location, or append patterns
- Meeting transcript naming conventions
- Tag taxonomies
- Templating (Templater, core Templates plugin)
- Linking conventions ([[wikilinks]] vs markdown links)
- Routing decisions ("does this go in Obsidian or somewhere else")
- Cross-tool patterns (e.g. pulling from OmniFocus completed tasks
  plus daily log for a "what did I do today" review)

If a personal-workflow skill is loaded alongside this one, defer to
it for those decisions. If not, ask the user rather than guessing.
