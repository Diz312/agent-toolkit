#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Apply catalog/ to skillshare. The catalog is the curated intent; skillshare installs it.

  - skills: `skillshare install <repo>/<path> --branch <ref>` for missing or re-pinned skills
  - local-skills/*: installed as copies, re-copied when their files change
  - mcp: catalog/mcp.yaml -> servers in skillshare's mcp.yaml (`${VAR}` -> `fromEnv: VAR`)
  - plugins (claude-code): `claude plugin install`, then `skillshare plugin import`
then `skillshare sync --all` and `skillshare push`.

Only items this script installed are ever removed (tracked in
~/.agent-toolkit/data/toolkit-apply/state.json), so anything added to skillshare by hand stays.

Usage: apply.py [--dry-run] [--check] [--no-push] [--install-hook]
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("AGENT_TOOLKIT_HOME", str(Path.home())))
SS = Path(os.environ.get("SKILLSHARE_HOME", str(HOME / ".config/skillshare")))
STATE_FILE = HOME / ".agent-toolkit/data/toolkit-apply/state.json"
SECRETS = HOME / ".secrets/agent.env"
SHA = re.compile(r"^[0-9a-f]{40}$")
WHOLE_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
BEARER_REF = re.compile(r"^Bearer \$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
IGNORE = ["__pycache__", ".DS_Store", ".skillshare-meta.json", ".agent-toolkit-ref"]
MCP_HEADER = (
    "# MCP servers for every machine. Committed with `skillshare push`; each machine picks its\n"
    "# receiving clients in its own config.yaml (mcp.targets). Entries from agent-toolkit's\n"
    "# catalog/mcp.yaml are written by scripts/apply.py; secrets only as fromEnv references\n"
    "# (values live in ~/.secrets/agent.env on each machine).\n"
)

Run = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


@dataclass
class Report:
    dry_run: bool
    done: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CatalogError(ValueError):
    pass


# --------------------------------------------------------------------------- reading


def read_yaml(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    items = (yaml.safe_load(path.read_text()) or {}).get(key) or []
    if not isinstance(items, list):
        raise CatalogError(f"{path.name}: '{key}' must be a list")
    return items


def load_state() -> dict[str, list[str]]:
    if STATE_FILE.is_file():
        data = json.loads(STATE_FILE.read_text())
        return {k: list(data.get(k, [])) for k in ("skills", "mcp", "plugins")}
    return {"skills": [], "mcp": [], "plugins": []}


def save_state(state: dict[str, list[str]]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({k: sorted(set(v)) for k, v in state.items()}, indent=2))


def skill_metadata() -> dict[str, dict[str, Any]]:
    meta = SS / "skills/.metadata.json"
    return dict(json.loads(meta.read_text()).get("entries", {})) if meta.is_file() else {}


def same_tree(a: Path, b: Path) -> bool:
    if not b.is_dir():
        return False
    cmp = filecmp.dircmp(a, b, ignore=IGNORE)

    def walk(c: filecmp.dircmp[str]) -> bool:
        if c.left_only or c.right_only or c.funny_files:
            return False
        _, mismatch, errors = filecmp.cmpfiles(c.left, c.right, c.common_files, shallow=False)
        return not mismatch and not errors and all(walk(s) for s in c.subdirs.values())

    return walk(cmp)


def local_skills(repo: Path) -> list[Path]:
    d = repo / "local-skills"
    return sorted(p for p in d.iterdir() if (p / "SKILL.md").is_file()) if d.is_dir() else []


# --------------------------------------------------------------------------- conversion


def ref_or_literal(value: str, where: str) -> Any:
    if m := WHOLE_REF.match(value):
        return {"fromEnv": m.group(1)}
    if "${" in value:
        raise CatalogError(f"{where}: a secret must be the whole value, like ${{VAR}}")
    return value


def to_skillshare_mcp(s: dict[str, Any]) -> dict[str, Any]:
    """catalog/mcp.yaml entry -> skillshare portable server definition."""
    name = s["name"]
    if s.get("transport") == "http":
        out: dict[str, Any] = {"url": s["url"]}
        headers: dict[str, Any] = {}
        for k, v in (s.get("headers") or {}).items():
            if k.lower() == "authorization" and (m := BEARER_REF.match(str(v))):
                out["bearerToken"] = {"fromEnv": m.group(1)}
            else:
                headers[k] = ref_or_literal(str(v), f"mcp {name} header {k}")
        if headers:
            out["headers"] = headers
        return out
    if not s.get("command"):
        raise CatalogError(f"mcp {name}: stdio servers need a command")
    out = {"command": s["command"], "args": list(s.get("args") or [])}
    env = {
        k: ref_or_literal(str(v), f"mcp {name} env {k}") for k, v in (s.get("env") or {}).items()
    }
    if env:
        out["env"] = env
    return out


def check_catalog(repo: Path) -> list[str]:
    """Problems that would make apply fail; empty when the catalog is valid."""
    problems: list[str] = []
    names: set[str] = {p.name for p in local_skills(repo)}
    try:
        skills = read_yaml(repo / "catalog/skills.yaml", "skills")
        mcp = read_yaml(repo / "catalog/mcp.yaml", "mcp")
        plugins = read_yaml(repo / "catalog/plugins.yaml", "plugins")
    except (CatalogError, yaml.YAMLError) as exc:
        return [str(exc)]
    for s in skills:
        n = s.get("name", "?")
        if not all(s.get(k) for k in ("name", "repo", "ref")):
            problems.append(f"skill {n}: needs name, repo and ref")
        elif not SHA.match(str(s["ref"])):
            problems.append(f"skill {n}: ref must be a full 40-character commit SHA")
        if n in names or n == "synced":
            problems.append(f"skill {n}: name clashes with a local skill or is reserved")
        names.add(n)
    for m in mcp:
        try:
            to_skillshare_mcp(m)
        except (CatalogError, KeyError) as exc:
            problems.append(str(exc))
    for p in plugins:
        if not all(p.get(k) for k in ("name", "plugin", "marketplace", "marketplace_name")):
            problems.append(f"plugin {p.get('name', '?')}: needs name, plugin, marketplace(_name)")
    return problems


# --------------------------------------------------------------------------- applying


def _do(report: Report, run: Run, msg: str, cmd: list[str]) -> bool:
    report.done.append(("[dry-run] " if report.dry_run else "") + msg)
    if report.dry_run:
        return True
    res = run(cmd)
    if res.returncode != 0:
        report.errors.append(f"{msg}: {(res.stderr or res.stdout).strip().splitlines()[-1:]}")
        return False
    return True


def apply_skills(repo: Path, report: Report, run: Run, state: dict[str, list[str]]) -> None:
    meta = skill_metadata()
    wanted: set[str] = set()
    for s in read_yaml(repo / "catalog/skills.yaml", "skills"):
        name, ref = s["name"], s["ref"]
        wanted.add(name)
        current = meta.get(name)
        if current and current.get("commit") == ref:
            state["skills"].append(name)  # adopt: already installed at this pin
            continue
        src = f"{s['repo']}/{s['path']}".rstrip("/") if s.get("path") else s["repo"]
        cmd = ["skillshare", "install", src, "--branch", ref, "--name", name, "-g", "--json"]
        if current:
            cmd.append("--force")
        verb = "re-pin" if current else "install"
        if _do(report, run, f"skill {name}: {verb} {s['repo']}@{ref[:7]}", cmd):
            state["skills"].append(name)
    for d in local_skills(repo):
        wanted.add(d.name)
        if same_tree(d, SS / "skills" / d.name):
            state["skills"].append(d.name)
            continue
        cmd = ["skillshare", "install", str(d), "-g", "--json", "--force"]
        if _do(report, run, f"skill {d.name}: copy from local-skills", cmd):
            state["skills"].append(d.name)
    for name in sorted(set(state["skills"]) - wanted):
        cmd = ["skillshare", "uninstall", name, "-g", "--force", "--json"]
        if _do(report, run, f"skill {name}: uninstall (left the catalog)", cmd):
            state["skills"].remove(name)


def apply_mcp(repo: Path, report: Report, state: dict[str, list[str]]) -> bool:
    path = SS / "mcp.yaml"
    doc: dict[str, Any] = (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}
    servers: dict[str, Any] = dict(doc.get("servers") or {})
    desired = {m["name"]: to_skillshare_mcp(m) for m in read_yaml(repo / "catalog/mcp.yaml", "mcp")}
    changed = False
    for name, spec in desired.items():
        if servers.get(name) != spec:
            report.done.append(("[dry-run] " if report.dry_run else "") + f"mcp {name}: set")
            servers[name] = spec
            changed = True
    for name in sorted(set(state["mcp"]) - set(desired)):
        if name in servers:
            report.done.append(("[dry-run] " if report.dry_run else "") + f"mcp {name}: remove")
            servers.pop(name)
            changed = True
    state["mcp"] = sorted(desired)
    if changed and not report.dry_run:
        doc["servers"] = servers
        path.write_text(MCP_HEADER + yaml.safe_dump(doc, sort_keys=False))
    return changed


def apply_plugins(repo: Path, report: Report, run: Run, state: dict[str, list[str]]) -> None:
    cfg_file = SS / "config.yaml"
    cfg = (yaml.safe_load(cfg_file.read_text()) or {}) if cfg_file.is_file() else {}
    have = set(((cfg.get("plugins") or {}).get("packages") or {}).keys())
    wanted: set[str] = set()
    for p in read_yaml(repo / "catalog/plugins.yaml", "plugins"):
        name, ident = p["name"], f"{p['plugin']}@{p['marketplace_name']}"
        if p.get("harness", "claude-code") != "claude-code":
            report.errors.append(f"plugin {name}: install by hand in {p['harness']}")
            continue
        wanted.add(name)
        if name in have:
            state["plugins"].append(name)
            continue
        if not report.dry_run:  # fails harmlessly when the marketplace is already added
            run(["claude", "plugin", "marketplace", "add", p["marketplace"]])
        install = ["claude", "plugin", "install", ident, "-s", "user"]
        imp = [
            "skillshare",
            "plugin",
            "import",
            ident,
            "--from",
            "claude",
            "--name",
            name,
            "--no-tui",
        ]
        if _do(report, run, f"plugin {name}: install {ident}", install) and _do(
            report, run, f"plugin {name}: import into skillshare", imp
        ):
            state["plugins"].append(name)
    for name in sorted(set(state["plugins"]) - wanted):
        report.errors.append(
            f"plugin {name}: left the catalog; remove it with `claude plugin "
            f"uninstall` and `skillshare plugin remove {name}`"
        )


def secrets_env() -> dict[str, str]:
    env = dict(os.environ)
    if SECRETS.is_file():
        for line in SECRETS.read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and k and not k.startswith("#"):
                env.setdefault(k.removeprefix("export ").strip(), v.strip().strip("'\""))
    return env


def finish(report: Report, run: Run, push: bool, message: str) -> None:
    _do(report, run, "skillshare sync --all", ["skillshare", "sync", "--all", "--no-tui"])
    if push:
        st = run(["git", "-C", str(SS), "status", "--porcelain"])
        if report.dry_run or st.stdout.strip():
            _do(report, run, "skillshare push", ["skillshare", "push", "-m", message])


HOOK = """#!/bin/sh
# Installed by agent-toolkit: apply the catalog through skillshare after every pull or merge.
uv run --script "$(git rev-parse --show-toplevel)/scripts/apply.py" \\
  || echo "agent-toolkit: apply failed (run scripts/apply.py to see why)"
"""


def install_hook(repo: Path) -> Path:
    hook = repo / ".git/hooks/post-merge"
    hook.write_text(HOOK)
    hook.chmod(0o755)
    return hook


def main(argv: list[str] | None = None, run: Run | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    ap.add_argument("--check", action="store_true", help="validate the catalog only")
    ap.add_argument(
        "--no-push", action="store_true", help="don't commit/push the skillshare source"
    )
    ap.add_argument("--install-hook", action="store_true", help="run apply after every git pull")
    args = ap.parse_args(argv)

    problems = check_catalog(REPO)
    for p in problems:
        print(f"  ! {p}", file=sys.stderr)
    if args.check or problems:
        print("catalog ok" if not problems else f"{len(problems)} catalog problem(s)")
        return 1 if problems else 0
    if args.install_hook:
        print(f"hook: {install_hook(REPO)}")

    if run is None:
        env = secrets_env()

        def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd, capture_output=True, text=True, check=False, cwd=HOME, env=env
            )

    report = Report(dry_run=args.dry_run)
    state = load_state()
    apply_skills(REPO, report, run, state)
    apply_mcp(REPO, report, state)
    apply_plugins(REPO, report, run, state)
    head = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    finish(report, run, not args.no_push, f"Apply agent-toolkit catalog {head}".strip())
    if not args.dry_run:
        save_state(state)

    print("\n".join(f"  + {d}" for d in report.done) or "  nothing to change")
    for e in report.errors:
        print(f"  ! {e}", file=sys.stderr)
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
