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

Install the AI apps you use (Claude Code, Cursor, ...) first, so they are detected. Then:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Diz312/agent-toolkit/main/bootstrap.sh)"
```

[`bootstrap.sh`](bootstrap.sh) does everything else, and is safe to re-run any time:

1. **Tools**: installs Homebrew if missing, then `git`, `gh`, `skillshare`, `uv` and Node >= 24.22.1.
2. **GitHub**: signs in if needed so git can push (`gh auth setup-git`).
3. **Secrets**: asks for every key in [`.env.example`](.env.example) that isn't in
   `~/.secrets/agent.env` yet (input hidden; Enter skips).
4. **Skills, MCP servers, plugins**: runs skillshare-source's `bootstrap.sh`. It connects
   `~/.config/skillshare` to the repo, links all skills into the AI tools it finds, wires MCP servers
   to Claude Code / Cursor / Codex / Gemini CLI, installs the Claude Code plugins in `plugins.txt`,
   and loads the secrets in shells (`~/.zshrc`) and GUI apps (`com.diz312.agent-env` LaunchAgent).
5. **This repo**: clones it to `~/myCode/agent-toolkit` (or `$AGENT_TOOLKIT_DIR`) and installs the
   `git pull` hook with a first `scripts/apply.py` run.
6. **Herdr**: if Herdr is installed, adds the skillshare panel and switches to its layout.
7. **Check**: `skillshare doctor` and `claude mcp list`, then lists anything that needs you.

Afterwards, quit and reopen Claude Code (desktop and terminal sessions) and Cursor.

**The scout runs on one machine only** (two would open duplicate PRs). On that machine, add a daily
scheduled task in the Claude desktop app, in `~/myCode/agent-toolkit`, with the prompt "Run the
toolkit scout". It refreshes the browse page, whose URL is kept in `~/.agent-toolkit/page.json`.

## Day to day

| I want to... | Do this |
|---|---|
| Take the scout's picks | Review and merge its PR, then `git pull` here. Other machines: `skillshare pull && skillshare sync --all`, or **Pull and sync** on the Herdr skillshare panel's Machines tab |
| Add or remove something I chose | Edit `catalog/*.yaml` (formats in `local-skills/toolkit-scout/SKILL.md` step 5), `uv run --script scripts/apply.py --check`, open a PR, merge, `git pull` |
| Try a skill without curating it | `skillshare install <github url> -g`, then `skillshare push` to share it. `apply.py` never removes what it didn't install; `skillshare uninstall <name> -g` removes it |
| Work on my own skills | Edit `local-skills/<name>/`, then `uv run --script scripts/apply.py`: it re-copies changed skills and pushes |
| Update pinned skills | The scout proposes `ref` bumps after reading the diff; `skillshare check` shows what has moved upstream |
| Add a secret | Add `VAR=` with a comment to `.env.example`; on each machine re-run `bootstrap.sh`: it asks for the new value and loads it for shells and GUI apps |
| Start using a new AI tool | Install it, re-run `bootstrap.sh`. For its MCP servers, add it to `mcp.targets` in `~/.config/skillshare/config.yaml` and run `skillshare sync mcp` |
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
| `bootstrap.sh` | Sets up a new machine end to end |
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
