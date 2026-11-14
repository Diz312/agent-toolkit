# agent-toolkit

Curated, harness-agnostic monorepo of agent skills, MCP servers and plugins. See README.md.

## Rules

- The catalog (`catalog/*.yaml`) is data. Adding/removing items never requires code changes.
- Upstream skills are pinned to full commit SHAs; MCP packages to exact versions.
- Secrets appear only as whole-value `${VAR}` placeholders, with the name listed in `.env.example`.
  Values live in `~/.secrets/agent.env` on each machine, never in a repo or harness config.
- Skills follow the Agent Skills standard (`<name>/SKILL.md` with `name` + `description`
  frontmatter); paths inside a skill are relative to its folder, never `~/.claude/...`.
- Skill data that must persist goes in `~/.agent-toolkit/data/<skill>/`, not in the repo.
- skillshare installs and syncs everything. Only `scripts/apply.py` (catalog -> skillshare) and
  `skillshare` itself write skills, MCP or plugin config. Don't hand-edit harness config files.
- skillshare's source is `~/.config/skillshare` (git root, remote `Diz312/skillshare-source`);
  its `config.yaml` is per machine and never committed.

## Commands

```bash
uv run pytest                                          # tests
uv run --script scripts/apply.py --check               # validate the catalog
uv run --script scripts/apply.py --dry-run --no-push   # preview catalog -> skillshare
uv run --script local-skills/toolkit-scout/scripts/build_page.py --catalog-ref origin/main
skillshare doctor && skillshare mcp check              # health of the installed toolkit
```

## Harnesses

skillshare owns the per-harness paths and formats (`skillshare target list`, its
`targets.yaml`). Machines run `skillshare init --discover` after installing a new harness.
Cursor's own skills folder is off (`skillshare target cursor --skills=false`): Cursor already
reads `~/.claude/skills` and `~/.agents/skills`. Antigravity cannot take secret MCP headers.
