# agent-toolkit

My curated agent skills, MCP servers and plugins, installed the same way on every machine and in
every harness (Claude Code, Codex, Gemini CLI, Antigravity, Cursor).

## How it works

1. **Scout (daily).** The `toolkit-scout` skill runs as a Claude Code desktop scheduled task. It
   searches Anthropic, the MCP registry, GitHub and curated lists, reviews the best finds for fit
   and safety, and opens one PR that edits `catalog/`. It also refreshes the browse page.
2. **Review.** I merge the PR, edit it, or close it.
3. **Apply (each machine).** `git pull` runs `scripts/apply.py` via a git hook. It installs the
   catalog through [skillshare](https://github.com/runkids/skillshare) (pinned, audited), which
   syncs skills, MCP servers and plugins into every harness, then pushes skillshare's source repo
   so other machines get it with `skillshare pull`.

## Layout

| Path | What |
|---|---|
| `config/preferences.yaml` | Categories, search queries, limits: what the scout looks for |
| `catalog/skills.yaml` | Upstream skills, pinned to a commit |
| `catalog/mcp.yaml` | MCP servers, pinned versions, secrets as `${VAR}` |
| `catalog/plugins.yaml` | Harness-specific plugins |
| `local-skills/` | My own skills (including the scout); installed into skillshare as copies |
| `scripts/apply.py` | Applies the catalog to skillshare; only removes what it installed |
| `reports/` | Daily scout reports; `latest.json` feeds the browse page |
| `.env.example` | Secret names; real values go in `~/.secrets/agent.env` |

## New machine

Every machine gets the toolkit from skillshare's source repo:

```bash
mkdir -p ~/.secrets && cp .env.example ~/.secrets/agent.env && chmod 600 ~/.secrets/agent.env
gh api repos/Diz312/skillshare-source/contents/bootstrap.sh -H "Accept: application/vnd.github.raw" | sh
```

Then `skillshare pull && skillshare sync --all` (or the Herdr skillshare panel) keeps it current.

Only the machine that runs the scout needs this repo:

```bash
git clone https://github.com/Diz312/agent-toolkit.git ~/myCode/agent-toolkit
uv run --script ~/myCode/agent-toolkit/scripts/apply.py --install-hook
```

Requires `uv`, `skillshare` (`brew install skillshare`) and `gh` logged in.

## Development

```bash
uv sync && uv run pre-commit install
uv run pytest
```
