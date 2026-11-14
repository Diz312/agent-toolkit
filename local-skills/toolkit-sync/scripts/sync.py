#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0", "tomlkit>=0.13"]
# ///
"""Install the agent-toolkit catalog into every agent harness on this machine.

Reads catalog/{skills,mcp,plugins}.yaml and local-skills/, then:
  - installs pinned upstream skills into ~/.agent-toolkit/skills/ and links every skill into
    each detected harness's skills folder
  - writes MCP servers into each harness's own config format, filling ${VAR} placeholders from
    the environment or ~/.agent-toolkit/.env (servers with missing secrets are skipped)
  - installs Claude Code plugins
Only entries this script created are ever changed or removed. Safe to re-run.

Usage: sync.py [--dry-run] [--install-hook]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import tomlkit
import yaml

REPO = Path(__file__).resolve().parents[3]
HOME = Path(os.environ.get("AGENT_TOOLKIT_HOME", str(Path.home())))
STORE = HOME / ".agent-toolkit"
SKILL_STORE = STORE / "skills"
STATE_FILE = STORE / "state.json"
ENV_FILE = STORE / ".env"
RESERVED_SKILL_NAMES = {"synced"}  # Claude Code reserves ~/.claude/skills/synced


# --------------------------------------------------------------------------- harnesses


@dataclass(frozen=True)
class Harness:
    name: str
    detect: tuple[Path, ...]
    skills_dir: Path | None
    mcp: str | None  # "json:<url_key>", "toml", "claude-cli" or None
    mcp_file: Path | None = None
    always: bool = False

    def present(self) -> bool:
        return self.always or any(p.exists() for p in self.detect)


def harnesses(home: Path = HOME) -> list[Harness]:
    g = home / ".gemini"
    return [
        Harness("claude-code", (home / ".claude",), home / ".claude/skills", "claude-cli"),
        # Open Agent Skills path, read by Codex CLI and Gemini CLI (and others).
        Harness("agents-standard", (), home / ".agents/skills", None, always=True),
        Harness("codex", (home / ".codex",), None, "toml", home / ".codex/config.toml"),
        Harness("gemini-cli", (g / "settings.json",), None, "json:httpUrl", g / "settings.json"),
        Harness(
            "antigravity",
            (g / "config", g / "antigravity", g / "antigravity-cli"),
            g / "config/skills",
            "json:serverUrl",
            g / "config/mcp_config.json",
        ),
        Harness(
            "cursor",
            (home / ".cursor",),
            home / ".cursor/skills",
            "json:url",
            home / ".cursor/mcp.json",
        ),
    ]


# --------------------------------------------------------------------------- utilities


@dataclass
class Report:
    dry_run: bool
    done: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def act(self, msg: str, fn: Callable[[], object] | None = None) -> None:
        self.done.append(("[dry-run] " if self.dry_run else "") + msg)
        if fn is not None and not self.dry_run:
            fn()

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def read_yaml(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    items = data.get(key) or []
    if not isinstance(items, list):
        raise SystemExit(f"{path}: '{key}' must be a list")
    return items


def load_state() -> dict[str, Any]:
    if STATE_FILE.is_file():
        return dict(json.loads(STATE_FILE.read_text()))
    return {"mcp": {}, "plugins": []}


def save_state(state: dict[str, Any]) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def load_env(env_file: Path = ENV_FILE) -> dict[str, str]:
    env: dict[str, str] = {}
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    env.update(os.environ)
    return env


class MissingSecret(Exception):
    pass


_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def resolve(value: Any, env: dict[str, str]) -> Any:
    """Replace ${VAR} / ${VAR:-default} recursively. Raises MissingSecret."""
    if isinstance(value, str):

        def sub(m: re.Match[str]) -> str:
            name, default = m.group(1), m.group(2)
            if env.get(name):
                return env[name]
            if default is not None:
                return default
            raise MissingSecret(name)

        return _VAR.sub(sub, value)
    if isinstance(value, list):
        return [resolve(v, env) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, env) for k, v in value.items()}
    return value


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def backup_once(path: Path) -> None:
    bak = path.with_name(path.name + ".agent-toolkit.bak")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)


def github_token() -> str | None:
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    if shutil.which("gh"):
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
        if out.returncode == 0:
            return out.stdout.strip() or None
    return None


# --------------------------------------------------------------------------- skills


def fetch_skill(repo: str, ref: str, path: str, dest: Path) -> None:
    """Download repo@ref tarball and extract only `path` into dest (atomic replace)."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/tarball/{ref}",
        headers={"User-Agent": "agent-toolkit", "Accept": "application/vnd.github+json"},
    )
    if token := github_token():
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - fixed https host
        blob = resp.read()
    prefix = path.strip("/")
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        members = []
        for m in tar.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) < 2:
                continue
            rel = parts[1]
            if prefix and not (rel == prefix or rel.startswith(prefix + "/")):
                continue
            rel = rel[len(prefix) :].lstrip("/") if prefix else rel
            if not rel:
                continue
            m.name = rel
            members.append(m)
        if not any(m.name == "SKILL.md" for m in members):
            raise RuntimeError(f"{repo}@{ref[:7]}:{path} has no SKILL.md")
        out = Path(tmp) / "skill"
        tar.extractall(out, members=members, filter="data")
        (out / ".agent-toolkit-ref").write_text(ref + "\n")
        if dest.exists() or dest.is_symlink():
            _remove(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), dest)


def _remove(p: Path) -> None:
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)


def _is_ours(link: Path) -> bool:
    if not link.is_symlink():
        return False
    target = Path(os.readlink(link))
    if not target.is_absolute():
        target = (link.parent / target).resolve()
    return str(target).startswith(str(SKILL_STORE)) or str(target).startswith(
        str(REPO / "local-skills")
    )


def sync_skills(report: Report, hs: list[Harness]) -> None:
    upstream = read_yaml(REPO / "catalog/skills.yaml", "skills")
    local_dir = REPO / "local-skills"
    local = sorted(p.name for p in local_dir.iterdir() if (p / "SKILL.md").is_file())
    wanted: set[str] = set()

    for s in upstream:
        name, repo, ref, path = s["name"], s["repo"], s["ref"], s.get("path", "")
        if name in RESERVED_SKILL_NAMES or name in local:
            report.warn(f"skill '{name}': name reserved or clashes with a local skill; skipped")
            continue
        wanted.add(name)
        dest = SKILL_STORE / name
        marker = dest / ".agent-toolkit-ref"
        if marker.is_file() and marker.read_text().strip() == ref:
            continue
        try:
            report.act(
                f"skill {name}: install {repo}@{ref[:7]}",
                lambda: fetch_skill(repo, ref, path, dest),
            )
        except Exception as exc:  # noqa: BLE001 - report and continue with other skills
            report.warn(f"skill {name}: {exc}")
            wanted.discard(name)

    for name in local:
        wanted.add(name)
        dest, src = SKILL_STORE / name, local_dir / name
        if dest.is_symlink() and dest.resolve() == src.resolve():
            continue
        report.act(f"skill {name}: link local", partial(_relink, dest, src))

    if SKILL_STORE.is_dir():
        for p in SKILL_STORE.iterdir():
            if p.name not in wanted:
                report.act(f"skill {p.name}: remove from store", partial(_remove, p))

    for h in hs:
        if h.skills_dir is None or not h.present():
            continue
        d = h.skills_dir
        if not report.dry_run:
            d.mkdir(parents=True, exist_ok=True)
        for name in sorted(wanted):
            link, target = d / name, SKILL_STORE / name
            if link.is_symlink() and Path(os.readlink(link)) == target:
                continue
            if (link.exists() or link.is_symlink()) and not _is_ours(link):
                report.warn(f"{h.name}: {link} exists and is not managed by agent-toolkit; skipped")
                continue
            report.act(f"{h.name}: link skill {name}", partial(_relink, link, target))
        if d.is_dir():
            for link in d.iterdir():
                if link.name not in wanted and _is_ours(link):
                    report.act(f"{h.name}: unlink skill {link.name}", link.unlink)


def _relink(link: Path, target: Path) -> None:
    if link.exists() or link.is_symlink():
        _remove(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)


# --------------------------------------------------------------------------- MCP


def server_spec(s: dict[str, Any]) -> dict[str, Any]:
    if s.get("transport") == "http":
        return {"transport": "http", "url": s["url"], "headers": s.get("headers") or {}}
    return {
        "transport": "stdio",
        "command": s["command"],
        "args": s.get("args") or [],
        "env": s.get("env") or {},
    }


def to_json_entry(spec: dict[str, Any], url_key: str) -> dict[str, Any]:
    if spec["transport"] == "http":
        entry: dict[str, Any] = {url_key: spec["url"]}
        if spec["headers"]:
            entry["headers"] = spec["headers"]
        return entry
    entry = {"command": spec["command"], "args": spec["args"]}
    if spec["env"]:
        entry["env"] = spec["env"]
    return entry


def to_claude_entry(spec: dict[str, Any]) -> dict[str, Any]:
    if spec["transport"] == "http":
        return {"type": "http", "url": spec["url"], "headers": spec["headers"]}
    return {"type": "stdio", "command": spec["command"], "args": spec["args"], "env": spec["env"]}


def to_codex_entry(spec: dict[str, Any]) -> dict[str, Any]:
    if spec["transport"] == "http":
        entry: dict[str, Any] = {"url": spec["url"]}
        if spec["headers"]:
            entry["http_headers"] = spec["headers"]
        return entry
    entry = {"command": spec["command"], "args": spec["args"]}
    if spec["env"]:
        entry["env"] = spec["env"]
    return entry


def sync_mcp(report: Report, hs: list[Harness], state: dict[str, Any]) -> None:
    env = load_env()
    desired: dict[str, dict[str, Any]] = {}
    skipped: set[str] = set()
    for s in read_yaml(REPO / "catalog/mcp.yaml", "mcp"):
        try:
            desired[s["name"]] = resolve(server_spec(s), env)
        except MissingSecret as exc:
            skipped.add(s["name"])
            report.warn(f"mcp {s['name']}: set {exc} in ~/.agent-toolkit/.env to enable it")

    for h in hs:
        if h.mcp is None or not h.present():
            continue
        managed: dict[str, str] = state["mcp"].setdefault(h.name, {})
        if h.mcp == "claude-cli":
            _sync_claude(report, desired, skipped, managed)
        elif h.mcp == "toml" and h.mcp_file:
            _sync_file(report, h, desired, skipped, managed, toml=True)
        elif h.mcp.startswith("json:") and h.mcp_file:
            _sync_file(report, h, desired, skipped, managed, toml=False)


def _sync_file(
    report: Report,
    h: Harness,
    desired: dict[str, dict[str, Any]],
    skipped: set[str],
    managed: dict[str, str],
    toml: bool,
) -> None:
    assert h.mcp_file is not None and h.mcp is not None
    path = h.mcp_file
    if toml:
        doc: Any = tomlkit.parse(path.read_text()) if path.is_file() else tomlkit.document()
        table = doc.setdefault("mcp_servers", tomlkit.table())
    else:
        doc = json.loads(path.read_text() or "{}") if path.is_file() else {}
        table = doc.setdefault("mcpServers", {})
    changed = False
    for name, spec in desired.items():
        entry = to_codex_entry(spec) if toml else to_json_entry(spec, h.mcp.split(":", 1)[1])
        h_digest = digest(entry)
        if name in table and name not in managed:
            report.warn(f"{h.name}: MCP '{name}' already defined by you; left untouched")
            continue
        if managed.get(name) == h_digest and name in table:
            continue
        report.act(f"{h.name}: set MCP {name}")
        table[name] = entry
        managed[name] = h_digest
        changed = True
    for name in list(managed):
        if name not in desired and name not in skipped:
            report.act(f"{h.name}: remove MCP {name}")
            table.pop(name, None)
            managed.pop(name)
            changed = True
    if changed and not report.dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        backup_once(path)
        path.write_text(tomlkit.dumps(doc) if toml else json.dumps(doc, indent=2) + "\n")


def _claude(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["claude", *args], capture_output=True, text=True, check=False)


def _sync_claude(
    report: Report, desired: dict[str, dict[str, Any]], skipped: set[str], managed: dict[str, str]
) -> None:
    if not shutil.which("claude"):
        report.warn("claude-code: 'claude' CLI not on PATH; MCP servers not registered")
        return
    for name, spec in desired.items():
        entry = to_claude_entry(spec)
        h_digest = digest(entry)
        if managed.get(name) == h_digest:
            continue

        def apply(n: str = name, e: dict[str, Any] = entry) -> None:
            _claude("mcp", "remove", "-s", "user", n)
            res = _claude("mcp", "add-json", "-s", "user", n, json.dumps(e))
            if res.returncode != 0:
                raise RuntimeError(f"claude mcp add-json {n}: {res.stderr.strip()}")

        try:
            report.act(f"claude-code: set MCP {name}", apply)
            managed[name] = h_digest
        except RuntimeError as exc:
            report.warn(str(exc))
    for name in list(managed):
        if name not in desired and name not in skipped:
            report.act(
                f"claude-code: remove MCP {name}",
                partial(_claude, "mcp", "remove", "-s", "user", name),
            )
            managed.pop(name)


# --------------------------------------------------------------------------- plugins


def sync_plugins(report: Report, hs: list[Harness], state: dict[str, Any]) -> None:
    plugins = read_yaml(REPO / "catalog/plugins.yaml", "plugins")
    present = {h.name for h in hs if h.present()}
    installed: list[str] = state.setdefault("plugins", [])
    wanted: set[str] = set()
    for p in plugins:
        harness = p.get("harness", "claude-code")
        ident = f"{p['plugin']}@{p['marketplace_name']}"
        if harness != "claude-code":
            report.warn(
                f"plugin {p['name']}: install manually in {harness} ({p.get('install', '')})"
            )
            continue
        if harness not in present or not shutil.which("claude"):
            continue
        wanted.add(ident)
        if ident in installed:
            continue

        def apply(src: str = p["marketplace"], i: str = ident) -> None:
            _claude("plugin", "marketplace", "add", src)  # no-op if already added
            res = _claude("plugin", "install", i, "-s", "user")
            if res.returncode != 0:
                raise RuntimeError(f"claude plugin install {i}: {res.stderr.strip()}")

        try:
            report.act(f"claude-code: install plugin {ident}", apply)
            installed.append(ident)
        except RuntimeError as exc:
            report.warn(str(exc))
    for ident in list(installed):
        if ident not in wanted and shutil.which("claude"):
            report.act(
                f"claude-code: uninstall plugin {ident}",
                partial(_claude, "plugin", "uninstall", ident),
            )
            installed.remove(ident)


# --------------------------------------------------------------------------- main


HOOK = """#!/bin/sh
# Installed by agent-toolkit: re-sync skills/MCP/plugins after every pull or merge.
uv run --script "$(git rev-parse --show-toplevel)/local-skills/toolkit-sync/scripts/sync.py" \\
  || echo "agent-toolkit: sync failed (run it manually to see why)"
"""


def _write_hook(hook: Path) -> None:
    hook.write_text(HOOK)
    hook.chmod(0o755)


def install_hook(report: Report) -> None:
    hook = REPO / ".git/hooks/post-merge"
    report.act(f"install git hook {hook}", partial(_write_hook, hook))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    ap.add_argument("--install-hook", action="store_true", help="auto-run sync after git pull")
    args = ap.parse_args(argv)

    report = Report(dry_run=args.dry_run)
    hs = harnesses()
    state = load_state()
    if args.install_hook:
        install_hook(report)
    sync_skills(report, hs)
    sync_mcp(report, hs, state)
    sync_plugins(report, hs, state)
    if not args.dry_run:
        save_state(state)

    print("Harnesses found:", ", ".join(h.name for h in hs if h.present()))
    print("\n".join(f"  + {d}" for d in report.done) or "  nothing to change")
    for w in report.warnings:
        print(f"  ! {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
