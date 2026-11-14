# agent-toolkit

My curated agent skills, MCP servers and plugins, the same on every machine and in every AI tool
(Claude Code, Cursor, Codex, Gemini CLI, Antigravity). Two repos split the work:

| Repo | Role | Who changes it |
|---|---|---|
| **[agent-toolkit](https://github.com/Diz312/agent-toolkit)** (this one) | *What* I want and *why*: the curated catalog, the daily scout that proposes additions, my own skills | Me, by reviewing the scout's PRs |
| **[skillshare-source](https://github.com/Diz312/skillshare-source)** (private) | *What is installed*: skill files, `mcp.yaml`, `plugins.txt`, `bootstrap.sh`. It is skillshare's source folder, `~/.config/skillshare` | `scripts/apply.py` and the `skillshare` CLI; never by hand |

[skillshare](https://github.com/runkids/skillshare) does the installing: it audits each skill, pins
it, links it into every AI tool, writes each tool's MCP config, and moves it all between machines
with git.

## How it fits together

```
toolkit-scout (daily)            -> PR editing catalog/ + reports/
      | I review and merge on GitHub
git pull here (scout machine)    -> post-merge hook runs scripts/apply.py
      |                             - skillshare install <repo>/<path> --branch <sha>   (audited)
      |                             - catalog/mcp.yaml     -> skillshare-source/mcp.yaml
      |                             - catalog/plugins.yaml -> claude plugin install + plugins.txt
      |                             - skillshare sync --all, skillshare push
other machines                   -> skillshare pull && skillshare sync --all
```

Nothing installs when a PR merges on GitHub; it installs at the next `git pull` on the scout
machine, and reaches the other machines at their next `skillshare pull`.

## New machine

macOS with [Homebrew](https://brew.sh). Install the AI tools you use (Claude Code, Cursor, ...)
first, so skillshare detects them.

**1. Tools and GitHub access**

```bash
brew install gh skillshare node      # node >= 24.22.1: MCP servers run through npx (rea needs it)
gh auth login && gh auth setup-git   # skillshare-source is private; git must be able to read it
```

**2. Secrets.** MCP configs only hold `${VAR}` references; each machine keeps the values in one file.

```bash
mkdir -p ~/.secrets
gh api repos/Diz312/agent-toolkit/contents/.env.example -H "Accept: application/vnd.github.raw" \
  > ~/.secrets/agent.env
chmod 600 ~/.secrets/agent.env
$EDITOR ~/.secrets/agent.env         # fill in each KEY=value; comments say where to get them
```

**3. Bootstrap** (idempotent; re-run any time)

```bash
gh api repos/Diz312/skillshare-source/contents/bootstrap.sh -H "Accept: application/vnd.github.raw" | sh
```

It connects `~/.config/skillshare` to the repo, pulls every skill, adds the AI tools it finds as
targets, wires MCP servers to Claude Code / Cursor / Codex / Gemini CLI, installs the Claude Code
plugins from `plugins.txt`, makes the secrets visible to shells (`~/.zshrc`) and to GUI apps (a
`com.diz312.agent-env` LaunchAgent), then syncs and runs `skillshare mcp check`.

**4. Restart and check.** Quit and reopen Claude Code (desktop and terminal sessions), Cursor and
any other AI app, then:

```bash
skillshare doctor        # skills linked, integrity, MCP and plugins OK
skillshare mcp check     # every server's command found and every ${VAR} set
claude mcp list          # servers connect
```

In a new Claude Code session, ask it to list its skills and MCP servers.

### Also on the scout machine

One machine runs the scout and applies the catalog. It needs this repo and `uv`:

```bash
brew install uv
git clone https://github.com/Diz312/agent-toolkit.git ~/myCode/agent-toolkit
cd ~/myCode/agent-toolkit && uv run --script scripts/apply.py --install-hook   # hook + first apply
```

Then schedule the scout in the Claude desktop app: a daily scheduled task in
`~/myCode/agent-toolkit` with the prompt "Run the toolkit scout". Each run opens at most one PR and
refreshes the browse page (its URL is kept in `~/.agent-toolkit/page.json`).

## Day to day

| I want to... | Do this |
|---|---|
| Take the scout's picks | Review and merge its PR, then `git pull` here. Other machines: `skillshare pull && skillshare sync --all`, or **Pull and sync** on the Herdr skillshare panel's Machines tab |
| Add or remove something I chose | Edit `catalog/*.yaml` (formats in `local-skills/toolkit-scout/SKILL.md` step 5), `uv run --script scripts/apply.py --check`, open a PR, merge, `git pull` |
| Try a skill without curating it | `skillshare install <github url> -g`, then `skillshare push` to share it. `apply.py` never removes what it didn't install; `skillshare uninstall <name> -g` removes it |
| Work on my own skills | Edit `local-skills/<name>/`, then `uv run --script scripts/apply.py`: it re-copies changed skills and pushes |
| Update pinned skills | The scout proposes `ref` bumps after reading the diff; `skillshare check` shows what has moved upstream |
| Add a secret | Add `VAR=` with a comment to `.env.example`; on each machine add the value to `~/.secrets/agent.env` and re-run the bootstrap (or log out and in) so GUI apps see it |
| Start using a new AI tool | Install it, re-run the bootstrap. For its MCP servers, add it to `mcp.targets` in `~/.config/skillshare/config.yaml` and run `skillshare sync mcp` |
| Check health | `skillshare doctor`, `skillshare mcp check`, or the Herdr skillshare panel |

## Rules

- **The catalog is the curated record** (with `why` and `category` for the browse page). Skills
  pin a full commit SHA, MCP packages an exact version, secrets are whole-value `${VAR}`s.
- **Never hand-edit an AI tool's skills folder or MCP config.** skillshare owns them; a hand edit
  shows up as a conflict on the next sync.
- **`~/.config/skillshare/config.yaml` is per machine** (its targets, `mcp.targets`, plugin
  receipts) and is never committed. Everything else in that folder is the shared repo.
- **Secret values live only in `~/.secrets/agent.env`**: never in a repo or a tool's config.

## Known limits

- **Cursor's own skills folder is off** (`skillshare target cursor --skills=false`): Cursor already
  reads `~/.claude/skills` and `~/.agents/skills`, so syncing there too showed every skill 3 times.
- **Antigravity can't receive secret MCP headers** (no documented env interpolation), so
  context7 isn't sent there. The bootstrap leaves it out of `mcp.targets`.
- **`grill-me` only runs as `/grill-me`**: upstream sets `disable-model-invocation`, so it isn't
  in the model's skill list.
- **Plugins** are Claude Code only today; other tools' plugins are listed in the catalog with
  their `harness` and installed by hand.
- `skillshare doctor` reports a reference error in `executing-plans` (upstream links to a sibling
  skill's file). Harmless.

## Layout

| Path | What |
|---|---|
| `catalog/skills.yaml` | Upstream skills, pinned to a commit |
| `catalog/mcp.yaml` | MCP servers, pinned versions, secrets as `${VAR}` |
| `catalog/plugins.yaml` | Plugins, with their `harness` |
| `local-skills/` | My own skills (`toolkit-scout`, `youtube-learn`), installed into skillshare as copies |
| `scripts/apply.py` | Applies the catalog to skillshare; only removes what it installed |
| `config/preferences.yaml` | Categories, search queries, limits: what the scout looks for |
| `reports/` | Daily scout reports; `latest.json` feeds the browse page |
| `.env.example` | Secret names and where to get them; values go in `~/.secrets/agent.env` |

Machine-local state: `~/.agent-toolkit/data/` (skill data, apply's record of what it installed),
`~/.agent-toolkit/page.json` (browse page URL).

## Development

```bash
uv sync && uv run pre-commit install
uv run pytest                                       # >70% coverage required
uv run --script scripts/apply.py --dry-run --no-push
```
