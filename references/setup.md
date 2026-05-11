# Setup and vault management

Load when registering a new vault, adding additional vaults, fixing a misregistered vault, or troubleshooting the vault registry. The SKILL.md has a 3-line summary; this file has the full flow.

## Deriving the vault name from a path

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

Obsidian's display name for a vault is the basename of its `path`. The URI scheme uses this name. Prefer reading `obsidian.json` over guessing.

If the file doesn't exist or doesn't list a path, fall back to the directory's basename and tell the user that's what you did.

## Validating that a path is a vault

Before registering a path, check that it contains a `.obsidian/` directory. Obsidian creates that directory on first open of a vault, so its absence almost always means a typo, a wrong folder, or a vault that's never been opened.

If the path doesn't have `.obsidian/`, surface the issue: "This path doesn't look like an Obsidian vault — there's no `.obsidian/` directory inside. Did you mean a different folder, or is this a new vault you haven't opened yet?"

## First-use flow (no vault registered)

1. Run `python3 scripts/obsidian.py config list` to confirm there are no vaults configured yet.
2. Read `~/Library/Application Support/obsidian/obsidian.json`. If it lists exactly one vault, propose: "I see one Obsidian vault at `<path>`. Want me to register it as `personal`?" (Suggest a sensible short name; the user can pick another.)
3. If multiple vaults are listed, show them and ask which to register (offer to add them all).
4. If the file is missing, ask the user for the vault path and a name.
5. Persist via `config add` (see "Configuration management" below). The script validates `.obsidian/` exists and writes the entry atomically.

## Multi-vault selection within a conversation

- One configured vault → use it implicitly (the script falls back to the sole vault when no `--vault` is given).
- Multiple configured, one marked default → the script uses the default unless the user names another.
- Multiple configured, no default → the script errors with the list of available names. Ask the user which to use, and offer to mark one as default with `config set-default`.
- Once a vault is selected in a conversation, stick with it for the rest of the conversation unless the user redirects.

## Adding or correcting a vault

User cues like "I have another vault," "add my work vault," "the vault is actually at X" → update the config. For corrections, `config remove` the old entry and `config add` the new one (the script intentionally refuses duplicate names so a stale entry never silently shadows the correct one). Confirm path and name before running.

## Configuration management

Vault profiles live in:

```
~/.config/obsidian-skill/config.json
```

(Override with `OBSIDIAN_SKILL_CONFIG=<path>` for tests; respects `XDG_CONFIG_HOME` if set.)

Schema:

```json
{
  "default": "personal",
  "vaults": {
    "personal": { "path": "/Users/dan/Documents/Personal" },
    "work":     { "path": "/Users/dan/Documents/Work", "read_only": true }
  }
}
```

Manage it through the bundled script — don't hand-edit unless you have to. The script does atomic writes and `.obsidian/` validation.

```
config path                          # print the config file path
config list                          # show all profiles + default
config show NAME                     # show one profile
config add NAME --path PATH \        # add a profile (validates .obsidian/)
            [--default] [--read-only]
config remove NAME                   # remove a profile
config set-default NAME              # set the top-level default
```

The first profile added becomes the default automatically. Subsequent profiles only become default when `--default` is passed.

**Tell the user where the file lives** the first time you write to it. Persistence is invisible by default; the user should know what's on disk so they can inspect or edit it.

## Selecting a vault for an operation

Every operation that touches a vault accepts:

- `--vault NAME` — resolve the profile via `config.json`. The normal path.
- `--vault-path PATH` — direct filesystem path. Escape hatch; bypasses the config and the read-only flag. Use it for tests, one-offs, or scripts that already know the path.

When neither is passed, the script falls back to the configured default, or — if exactly one profile is configured — that one.
