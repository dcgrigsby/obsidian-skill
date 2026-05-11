# Obsidian Sync and recoverability

Load when writes are happening and the user might be editing the file in the Obsidian app, when investigating a "modified externally" prompt, or when a write went wrong and you need to know what recovery is available.

## Sync awareness

If Obsidian Sync is enabled, it watches the vault filesystem and propagates changes outward. The skill writes directly to disk — there's no Obsidian API we're bypassing. Practices:

- **Atomic writes** for `create` and `replace` (handled by the bundled script and by the write semantics in SKILL.md).
- **Avoid rapid repeated writes** to the same file — gives Sync more chances to race. Batch updates locally, then write once.
- **Don't write inside `.obsidian/`** unless the user explicitly asks. That's where Sync conflicts get ugly.
- **Sync conflict files** (`Note (conflict 2026-05-02 1430).md`) may appear in the vault. Don't surface them as normal notes; if you see one, mention it to the user.

## Concurrent editing in the Obsidian app

If the user is actively editing a note in Obsidian and the skill writes to it, Obsidian shows a "modified externally" prompt and there's a real chance of data loss depending on which side the user picks.

Heuristic: if the user has just mentioned editing something or you have reason to believe Obsidian is open on that file, ask before writing to it.

## Recoverability

Two failure modes to keep in mind:

1. **Fast-detected mistakes** ("undo what you just did"): if Sync is present, point the user at **File → View file history** in Obsidian (or right-click → Show version history). Without Sync, point at whatever else they have running (Time Machine, git, etc.).
2. **Slow-detected mistakes** (a paragraph quietly overwritten, noticed weeks later): version history retention is finite. The skill's design — no silent overwrites, mandatory visibility on `replace`, soft-delete by default — is meant to prevent this class of error in the first place. Conversation history is the audit trail.

If the user has **Obsidian Sync**, per-file version history is the primary recovery backstop. Without Sync, recovery falls to whatever else is running (Time Machine, iCloud Drive history, git, Dropbox versions). The safety design in SKILL.md does not depend on Sync — it just gets cheaper to recover from honest mistakes when Sync is present.
