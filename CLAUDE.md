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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **agent-toolkit** (219 symbols, 313 relationships, 4 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/agent-toolkit/context` | Codebase overview, check index freshness |
| `gitnexus://repo/agent-toolkit/clusters` | All functional areas |
| `gitnexus://repo/agent-toolkit/processes` | All execution flows |
| `gitnexus://repo/agent-toolkit/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
