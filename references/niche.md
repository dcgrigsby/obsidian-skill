# Niche surfaces

Load when the user wants to "open this in Obsidian" via URI, asks about attachments / non-markdown files, or pushes against the skill's documented out-of-scope boundaries.

## URI scheme (opening notes in the Obsidian app)

When the user wants to "open this in Obsidian":

```
obsidian://open?vault=<vault-name>&file=<note-path-without-extension>
```

URL-encode the vault name and file path.

```bash
open "obsidian://open?vault=MyVault&file=Daily%2F2026-05-02"
```

If the URI doesn't open the right note, the registered vault name may not match what Obsidian expects — re-derive from `~/Library/Application Support/obsidian/obsidian.json`.

**Note:** depending on the user's Obsidian settings, this URI may *create* the note if it doesn't exist. If you want to be sure you're opening an existing note, check that it exists first.

## Attachments and non-markdown files

Obsidian vaults often contain images, PDFs, audio, `.canvas` JSON files, Excalidraw drawings, and other non-markdown content. The skill operates on `.md` files. When the user asks about attachments explicitly, be conservative: don't move, rename, or delete them without confirmation, since they may be referenced from notes via embed syntax (`![[image.png]]`).

## Out of scope

This skill stays at the surface layer. The following belong in a separate personal-workflow skill (or are user-specific decisions):

- Folder layout inside the vault (`Daily/`, `Reference/`, etc.)
- Daily log format, location, or append patterns
- Meeting transcript naming conventions
- Tag taxonomies
- Templating (Templater, core Templates plugin)
- Linking conventions ([[wikilinks]] vs markdown links)
- Routing decisions ("does this go in Obsidian or somewhere else")
- Cross-tool patterns (e.g. pulling from OmniFocus completed tasks plus daily log for a "what did I do today" review)

If a personal-workflow skill is loaded alongside this one, defer to it for those decisions. If not, ask the user rather than guessing.
