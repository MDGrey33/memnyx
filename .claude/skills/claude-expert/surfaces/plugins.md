# Plugins — deep reference

Source: https://code.claude.com/docs/en/plugins

## What a plugin is

A distributable bundle of Claude Code extensions. A plugin is a directory
with `.claude-plugin/plugin.json` plus any of:

- `skills/<name>/SKILL.md`
- `commands/*.md` (legacy; use `skills/` for new plugins)
- `agents/*.md`
- `hooks/hooks.json`
- `.mcp.json` at plugin root
- `.lsp.json` at plugin root
- `monitors/monitors.json`
- `bin/` (executables added to PATH while enabled)
- `settings.json` (default settings when enabled; only `agent` and
  `subagentStatusLine` keys currently honored)

## Manifest: `.claude-plugin/plugin.json`

```json
{
  "name": "my-plugin",
  "description": "What this plugin does",
  "version": "1.0.0",
  "author": { "name": "Your Name" },
  "homepage": "...",
  "repository": "...",
  "license": "..."
}
```

`name` becomes the plugin namespace. Version uses semver.

**The root skill is invokable bare; sub-skills and agents are namespaced.** A
plugin's **root** skill — registered via `"skills": ["./"]`, so the plugin
directory's own `SKILL.md` is the root — resolves to **`/<plugin-name>`** (bare).
This holds in **both** load forms: a skills-directory plugin
(`<name>@skills-dir`) and a marketplace-installed plugin (`<name>@<marketplace>`).
**Sub-skills** (under `skills/<sub>/`) and **agents** always carry the
`<plugin>:` prefix (an agent dispatches as `<plugin>:<agent-name>`). To keep a
clean `/<name>` invocation, make your skill the plugin's root skill, not a
sub-skill.

For a marketplace plugin, the root skill resolves under **both** the bare form
and the namespaced alias `/<plugin-name>:<plugin-name>`; the session's skill
listing surfaces the namespaced name as canonical, but the bare command is also
registered.

Verified by behavioural resolution against Claude Code 2.1.181: with a
`"skills": ["./"]` plugin installed from a local marketplace, both
`/<name>` and `/<name>:<name>` resolved and fired the skill, while a bad
sub-name (`/<name>:bogus`) and a truncated name returned `Unknown command` —
confirming exact-match resolution, not fuzzy matching. (Asking a session to
*report* its registered identifier is unreliable — it returns the canonical
namespaced label and hides the bare alias; resolve-and-observe instead.)
Re-verify against current docs — the CLI evolves.

## Plugin vs standalone

| | Standalone (`.claude/`) | Plugin |
|:--|:--|:--|
| Skill names | `/hello` | root skill `/my-plugin` (bare); sub-skills `/my-plugin:sub` |
| Best for | Personal, project-specific, quick experiments | Sharing, versioned, multi-project |

The docs recommend: start standalone, convert when ready to share.

## Loading

- Installed via `/plugin` (browse a marketplace, install, toggle).
- Local development: `claude --plugin-dir ./my-plugin` (repeatable for multi).
- `--plugin-dir` overrides an installed marketplace plugin of the same
  name for that session (except managed-force-enabled plugins).
- `/reload-plugins` picks up changes mid-session.

## Skills-directory plugin — bundle a skill with its agents, keep autoload

A skills-directory plugin lives at `.claude/skills/<name>/` and **autoloads on
session start** — the same zero-config behaviour a bare skill has, but it can
bundle companion **agents** alongside the skill. This is the form to reach for
when in-workspace autoload matters and you want the skill and the agents it
dispatches to travel as one unit.

Layout:

```
.claude/skills/<name>/
├── .claude-plugin/
│   └── plugin.json     {"name":"<name>","skills":["./"], ...}
├── SKILL.md            ← registers as the plugin's ROOT skill (via "skills":["./"])
├── ...companion files
└── agents/
    └── <agent>.md
```

- Loads automatically as `<name>@skills-dir` — user scope automatically;
  project scope after a one-time workspace-trust prompt.
- Root skill invoked bare `/<name>`; bundled agents dispatch as
  `<name>:<agent>`.
- **Choose by requirement:** skills-directory when in-workspace autoload
  matters; **marketplace** plugin (enabled via `enabledPlugins`) when
  distributing to other people's machines — marketplace trades zero-config
  autoload for shareable, versioned distribution.

**Scaffolding:** `claude plugin init <name> --with skills agents` generates the
canonical layout (manifest + `skills/` + `agents/`).

**Verification trap — the one that bites.** The `--plugin-dir <path>` developer
flag namespaces *even the root skill* (`/<name>:<name>`), so loading a plugin
that way is **not** a faithful preview of the deployed skills-directory form. A
reader who stops at the dev-flag result will conclude the skill must be invoked
`/<name>:<name>` and design around the wrong invocation. Verify in the real
deployed form instead:

- `claude plugin list` → shows `<name>@skills-dir … loaded`
- `claude plugin details <name>` → component inventory (skills + agents) and
  token cost
- Enumerate the available skill/agent names from a session that has the plugin
  loaded to confirm the bare-vs-namespaced exposure.

(These behaviours were established empirically; the CLI surface evolves —
re-verify against the current Claude Code docs.)

## Env vars inside plugin code

- `${CLAUDE_PLUGIN_ROOT}` — install directory. Use for bundled files.
- `${CLAUDE_PLUGIN_DATA}` — persistent per-plugin data dir that survives
  updates.

## Security restrictions on plugin-provided content

Plugin-provided **subagents** do NOT support `hooks`, `mcpServers`, or
`permissionMode`. These fields are silently ignored. Copy the agent file
into `.claude/agents/` if you need those fields, or use permission rules
or `enabledPlugins` in managed settings.

Plugin-provided **hooks** are subject to `allowManagedHooksOnly` if that
managed-only setting is on.

## Known public marketplaces

Source: https://github.com/davila7/claude-code-templates, https://github.com/wshobson/commands

| Marketplace | Contents | Notable |
|:--|:--|:--|
| Anthropic official skills | https://github.com/anthropics/skills | 21 official skills |
| wshobson/commands | https://github.com/wshobson/commands | 57 commands/workflows |
| davila7/claude-code-templates | https://github.com/davila7/claude-code-templates | 169+ scientific skills, agent templates, MCP configs, settings, hooks |

Install flow: `/plugin` opens the browser, type the marketplace URL or plugin name,
toggle to enable. Local development: `claude --plugin-dir ./my-plugin`.

## Marketplaces

A marketplace is a JSON manifest (`.claude-plugin/marketplace.json`) that
lists available plugins. Marketplace source types:

| Type | Fields |
|:--|:--|
| `github` | `repo`, optional `ref`, `path` |
| `git` | `url`, optional `ref`, `path` |
| `url` | `url`, optional `headers` (download marketplace.json only; plugins must use external sources) |
| `npm` | `package` (scoped ok) |
| `file` | `path` (absolute to marketplace.json) |
| `directory` | `path` (absolute dir with `.claude-plugin/marketplace.json`) |
| `hostPattern` | `hostPattern` (regex against marketplace host) |
| `settings` | Inline plugin list; plugins must reference external sources |

## Settings for plugins

In `~/.claude/settings.json`, `.claude/settings.json`, or
`.claude/settings.local.json`:

```json
{
  "enabledPlugins": {
    "formatter@acme-tools": true,
    "experimental@personal": false
  },
  "extraKnownMarketplaces": {
    "acme-tools": {
      "source": { "source": "github", "repo": "acme-corp/claude-plugins" }
    }
  }
}
```

`enabledPlugins` format: `"<plugin-name>@<marketplace-name>": true|false`.
When a project ships `extraKnownMarketplaces`, team members trust-dialog
that marketplace, then see prompts per-plugin.

## Managed controls

Managed-only settings for plugins:

| Setting | Effect |
|:--|:--|
| `enabledPlugins` (managed) | Force-enable or block plugins org-wide |
| `strictKnownMarketplaces` | Allowlist of marketplace sources |
| `blockedMarketplaces` | Blocklist checked before download |
| `pluginTrustMessage` | Custom warning text |

Exact matching on `repo`, `ref`, `path` for git-type sources. `hostPattern`
uses regex on extracted host.

## Converting standalone to plugin

1. `mkdir -p my-plugin/.claude-plugin`.
2. Write `my-plugin/.claude-plugin/plugin.json`.
3. Copy `.claude/commands/`, `.claude/agents/`, `.claude/skills/` into
   `my-plugin/` at same names.
4. If migrating hooks from `settings.json`, create
   `my-plugin/hooks/hooks.json` with the `hooks` object from settings.
   Hook command format is identical.
5. `claude --plugin-dir ./my-plugin` to test.

After migration, remove originals from `.claude/` to avoid duplicates (the
plugin version takes precedence when loaded).

## `.lsp.json` — language servers

```json
{
  "go": {
    "command": "gopls",
    "args": ["serve"],
    "extensionToLanguage": { ".go": "go" }
  }
}
```

Users installing the plugin must have the LSP binary installed.

## `monitors/monitors.json` — background watchers

```json
[
  {
    "name": "error-log",
    "command": "tail -F ./logs/error.log",
    "description": "Application error log"
  }
]
```

Each stdout line becomes a notification in the session. Auto-start when
plugin enabled.

## Viewing / debugging

- `/plugin` — manage plugins in the CLI.
- `/mcp` — list MCP servers including plugin-provided.
- `/agents` — see subagents including plugin-provided.
- `/hooks` — see hooks including plugin-provided (flagged as source).

## Gotchas

- Don't nest `commands/`, `agents/`, `skills/`, or `hooks/` **inside**
  `.claude-plugin/`. Only `plugin.json` goes there.
- A plugin's **root** skill (`"skills": ["./"]`) resolves **bare** as
  `/<plugin>` in both load forms (marketplace also registers the
  `/<plugin>:<plugin>` alias). Sub-skills and agents are always namespaced
  (`/<plugin>:<name>`).
- Plugin `settings.json` only honors `agent` and `subagentStatusLine` as of
  docs-read (docs may expand this — verify current list).
- Plugin-provided subagent `hooks`, `mcpServers`, `permissionMode` silently
  ignored.
- URL-based marketplaces only fetch `marketplace.json` — plugins must
  reference external sources. For relative paths, use git-based marketplace.

## Disambiguation

- **Plugin vs standalone `.claude/`:** standalone for personal; plugin for
  sharing.
- **Plugin vs MCP:** plugin is a bundle of Claude-config; MCP is a single
  external-tool integration. A plugin can CONTAIN MCP servers.
- **Marketplace vs plugin:** marketplace is the index; plugin is the unit
  installed.

## Minimal example

```
my-first-plugin/
├── .claude-plugin/
│   └── plugin.json     {"name":"my-first-plugin","version":"1.0.0"}
└── skills/
    └── hello/
        └── SKILL.md
```

```yaml
# skills/hello/SKILL.md
---
description: Greet the user warmly and ask how you can help them today.
---

Greet the user named "$ARGUMENTS" warmly. Make the greeting personal.
```

`claude --plugin-dir ./my-first-plugin` then `/my-first-plugin:hello Alex`.

## Submit to the Anthropic marketplace

- Claude.ai: https://claude.ai/settings/plugins/submit
- Console: https://platform.claude.com/plugins/submit

After listing, use `/en/plugin-hints` to prompt users from your own CLI.
