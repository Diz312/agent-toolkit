# agent-toolkit

My curated agent skills, MCP servers and plugins, installed the same way on every machine and in
every harness (Claude Code, Codex, Gemini CLI, Antigravity, Cursor).

## How it works

1. **Scout (daily).** The `toolkit-scout` skill runs as a Claude Code desktop scheduled task. It
   searches Anthropic, the MCP registry, GitHub and curated lists, reviews the best finds for fit
   and safety, and opens one PR that edits `catalog/`. It also refreshes the browse page.
2. **Review.** I merge the PR, edit it, or close it.
3. **Sync (each machine).** `git pull` triggers the `toolkit-sync` script via a git hook. It
   installs everything in the catalog into each harness's own format.

## Layout

| Path | What |
|---|---|
| `config/preferences.yaml` | Categories, search queries, limits: what the scout looks for |
| `catalog/skills.yaml` | Upstream skills, pinned to a commit |
| `catalog/mcp.yaml` | MCP servers, pinned versions, secrets as `${VAR}` |
| `catalog/plugins.yaml` | Harness-specific plugins |
| `local-skills/` | My own skills (including the scout and sync skills) |
| `reports/` | Daily scout reports; `latest.json` feeds the browse page |
| `.env.example` | Secret names; real values go in `~/.agent-toolkit/.env` |

## New machine

```bash
git clone https://github.com/Diz312/agent-toolkit.git ~/agent-toolkit
mkdir -p ~/.agent-toolkit && cp ~/agent-toolkit/.env.example ~/.agent-toolkit/.env
uv run --script ~/agent-toolkit/local-skills/toolkit-sync/scripts/sync.py --install-hook
```

Requires `uv`, and `gh` logged in. After that, `git pull` keeps the machine in sync.

## Development

```bash
uv sync && uv run pre-commit install
uv run pytest
```
