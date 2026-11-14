---
name: toolkit-sync
description: Install or refresh the agent-toolkit catalog (skills, MCP servers, plugins) into every agent harness on this machine - Claude Code, Codex, Gemini CLI, Antigravity, Cursor. Use when the user asks to sync, install or refresh their toolkit, set up a new machine, or after pulling toolkit changes.
---

# toolkit-sync

Runs one deterministic script. Do not hand-edit harness config files instead of running it.

## Run

```bash
uv run --script scripts/sync.py --dry-run   # preview
uv run --script scripts/sync.py             # apply
```

`scripts/` is relative to this skill's folder. Requires `uv`; `gh` (logged in) is used for GitHub
downloads when available.

## New machine

```bash
git clone https://github.com/Diz312/agent-toolkit.git ~/agent-toolkit
cp ~/agent-toolkit/.env.example ~/.agent-toolkit/.env   # then fill in the keys you use
uv run --script ~/agent-toolkit/local-skills/toolkit-sync/scripts/sync.py --install-hook
```

`--install-hook` adds a git post-merge hook so every `git pull` re-syncs automatically.

## What it does

| Item | Where it goes |
|---|---|
| Upstream skills (`catalog/skills.yaml`, pinned SHA) | downloaded to `~/.agent-toolkit/skills/<name>` |
| Own skills (`local-skills/`) | linked into `~/.agent-toolkit/skills/<name>` |
| Every skill | symlinked into `~/.claude/skills`, `~/.agents/skills` (Codex, Gemini CLI), `~/.gemini/config/skills` (Antigravity), `~/.cursor/skills` - only for harnesses present |
| MCP servers (`catalog/mcp.yaml`) | `claude mcp add-json -s user`, `~/.codex/config.toml`, `~/.gemini/settings.json`, `~/.gemini/config/mcp_config.json`, `~/.cursor/mcp.json` |
| Plugins (`catalog/plugins.yaml`) | Claude Code plugins via `claude plugin install`; other harnesses are listed as manual steps |

Secrets: `${VAR}` placeholders are filled from the environment or `~/.agent-toolkit/.env`. A
server whose secret is missing is skipped with a warning, never written with a blank key.

Safety: the script only changes entries it created (tracked in `~/.agent-toolkit/state.json`),
never overwrites a skill folder or MCP entry you made yourself, and backs up each config file once
as `<file>.agent-toolkit.bak` before its first write.

Report the script's output to the user, including every `!` warning.
