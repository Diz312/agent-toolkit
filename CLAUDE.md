# agent-toolkit

Curated, harness-agnostic monorepo of agent skills, MCP servers and plugins. See README.md.

## Rules

- The catalog (`catalog/*.yaml`) is data. Adding/removing items never requires code changes.
- Upstream skills are pinned to full commit SHAs; MCP packages to exact versions.
- Secrets appear only as `${VAR}` placeholders, with the name listed in `.env.example`.
- Skills follow the Agent Skills standard (`<name>/SKILL.md` with `name` + `description`
  frontmatter); paths inside a skill are relative to its folder, never `~/.claude/...`.
- Skill data that must persist goes in `~/.agent-toolkit/data/<skill>/`, not in the repo.
- Only `toolkit-sync/scripts/sync.py` writes to harness config. Don't hand-edit those files.

## Commands

```bash
uv run pytest                                                   # tests
uv run --script local-skills/toolkit-sync/scripts/sync.py --dry-run
uv run --script local-skills/toolkit-scout/scripts/build_page.py --catalog-ref origin/main
```

## Harness targets (verified Nov 2026)

| Harness | Skills | MCP |
|---|---|---|
| Claude Code | `~/.claude/skills` | `claude mcp add-json -s user` |
| Codex CLI | `~/.agents/skills` | `~/.codex/config.toml` `[mcp_servers.*]` |
| Gemini CLI | `~/.agents/skills` | `~/.gemini/settings.json` (`httpUrl` for remote) |
| Antigravity | `~/.gemini/config/skills` | `~/.gemini/config/mcp_config.json` (`serverUrl`) |
| Cursor | `~/.cursor/skills` | `~/.cursor/mcp.json` |
