"""Tests for scripts/apply.py against a fake skillshare home, a fake repo and a recording runner."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/apply.py"
SHA_A = "a" * 40
SHA_B = "b" * 40


class Runner:
    def __init__(self, fail: str | None = None, status: str = "") -> None:
        self.calls: list[list[str]] = []
        self.fail, self.status = fail, status

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        if cmd[:2] == ["git", "-C"]:
            return subprocess.CompletedProcess(cmd, 0, self.status, "")
        code = 1 if self.fail and self.fail in " ".join(cmd) else 0
        return subprocess.CompletedProcess(cmd, code, "", "boom" if code else "")

    def joined(self) -> list[str]:
        return [" ".join(c) for c in self.calls]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path, Path]:
    home, repo = tmp_path / "home", tmp_path / "repo"
    ss = home / ".config/skillshare"
    (ss / "skills").mkdir(parents=True)
    (repo / "catalog").mkdir(parents=True)
    (repo / "local-skills/demo").mkdir(parents=True)
    (repo / "local-skills/demo/SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n")
    write(repo, "skills", [{"name": "up", "repo": "o/r", "path": "skills/up", "ref": SHA_A}])
    write(repo, "plugins", [])
    write(
        repo,
        "mcp",
        [
            {
                "name": "local",
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "p@1.0.0"],
                "env": {"TOKEN": "${DEMO_TOKEN}", "MODE": "fast"},
            },
            {
                "name": "remote",
                "transport": "http",
                "url": "https://x.example/mcp",
                "headers": {"Authorization": "Bearer ${REMOTE_KEY}", "X-Org": "${ORG}"},
            },
        ],
    )
    monkeypatch.setenv("AGENT_TOOLKIT_HOME", str(home))
    monkeypatch.delenv("SKILLSHARE_HOME", raising=False)
    spec = importlib.util.spec_from_file_location("apply_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apply_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "REPO", repo)
    return mod, home, repo


def write(repo: Path, kind: str, items: list[dict[str, object]]) -> None:
    key = "mcp" if kind == "mcp" else kind
    (repo / f"catalog/{kind}.yaml").write_text(yaml.safe_dump({key: items}))


def set_meta(home: Path, entries: dict[str, dict[str, str]]) -> None:
    meta = home / ".config/skillshare/skills/.metadata.json"
    meta.write_text(json.dumps({"version": 1, "entries": entries}))


def test_installs_missing_skills_mcp_and_pushes(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, _ = env
    run = Runner(status=" M mcp.yaml")
    assert mod.main([], run=run) == 0
    calls = run.joined()
    assert f"skillshare install o/r/skills/up --branch {SHA_A} --name up -g --json" in calls
    assert any(
        c.startswith("skillshare install ") and c.endswith("local-skills/demo -g --json --force")
        for c in calls
    )
    assert "skillshare sync --all --no-tui" in calls
    assert any(c.startswith("skillshare push -m Apply agent-toolkit catalog") for c in calls)
    servers = yaml.safe_load((home / ".config/skillshare/mcp.yaml").read_text())["servers"]
    assert servers["local"] == {
        "command": "npx",
        "args": ["-y", "p@1.0.0"],
        "env": {"TOKEN": {"fromEnv": "DEMO_TOKEN"}, "MODE": "fast"},
    }
    assert servers["remote"] == {
        "url": "https://x.example/mcp",
        "bearerToken": {"fromEnv": "REMOTE_KEY"},
        "headers": {"X-Org": {"fromEnv": "ORG"}},
    }
    state = json.loads((home / ".agent-toolkit/data/toolkit-apply/state.json").read_text())
    assert state == {"mcp": ["local", "remote"], "plugins": [], "skills": ["demo", "up"]}


def test_adopts_up_to_date_and_repins_changed(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, repo = env
    set_meta(home, {"up": {"commit": SHA_A}})
    run = Runner()
    mod.main(["--no-push"], run=run)
    assert not any("install o/r" in c for c in run.joined())
    write(repo, "skills", [{"name": "up", "repo": "o/r", "path": "skills/up", "ref": SHA_B}])
    run = Runner()
    mod.main(["--no-push"], run=run)
    assert f"skillshare install o/r/skills/up --branch {SHA_B} --name up -g --json --force" in (
        run.joined()
    )


def test_local_skill_copied_only_when_changed(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, repo = env
    dest = home / ".config/skillshare/skills/demo"
    dest.mkdir()
    (dest / "SKILL.md").write_text((repo / "local-skills/demo/SKILL.md").read_text())
    (dest / ".skillshare-meta.json").write_text("{}")  # ignored by the comparison
    run = Runner()
    mod.main(["--no-push"], run=run)
    assert not any("local-skills/demo" in c for c in run.joined())
    (repo / "local-skills/demo/extra.md").write_text("new")
    run = Runner()
    mod.main(["--no-push"], run=run)
    assert any("local-skills/demo" in c for c in run.joined())


def test_removes_only_what_it_installed(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, repo = env
    ss = home / ".config/skillshare"
    (ss / "mcp.yaml").write_text(yaml.safe_dump({"servers": {"mine": {"url": "https://m/mcp"}}}))
    mod.main(["--no-push"], run=Runner())
    write(repo, "skills", [])
    write(repo, "mcp", [])
    set_meta(home, {"handmade": {"commit": SHA_A}})
    run = Runner()
    mod.main(["--no-push"], run=run)
    assert "skillshare uninstall up -g --force --json" in run.joined()
    assert not any("uninstall handmade" in c for c in run.joined())
    servers = yaml.safe_load((ss / "mcp.yaml").read_text())["servers"]
    assert servers == {"mine": {"url": "https://m/mcp"}}


def test_dry_run_changes_nothing(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, _ = env
    run = Runner()
    assert mod.main(["--dry-run"], run=run) == 0
    assert [c for c in run.calls if c[0] != "git"] == []
    assert not (home / ".config/skillshare/mcp.yaml").exists()
    assert not (home / ".agent-toolkit/data/toolkit-apply/state.json").exists()


def test_failed_install_is_reported_and_not_tracked(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, _ = env
    assert mod.main(["--no-push"], run=Runner(fail="o/r/skills/up")) == 1
    state = json.loads((home / ".agent-toolkit/data/toolkit-apply/state.json").read_text())
    assert "up" not in state["skills"]


def test_plugins_install_and_import(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, repo = env
    write(
        repo,
        "plugins",
        [
            {
                "name": "lsp",
                "plugin": "lsp",
                "marketplace": "o/m",
                "marketplace_name": "m",
                "harness": "claude-code",
            },
            {
                "name": "other",
                "plugin": "x",
                "marketplace": "o/m",
                "marketplace_name": "m",
                "harness": "antigravity",
            },
        ],
    )
    run = Runner()
    assert mod.main(["--no-push"], run=run) == 1  # the antigravity plugin needs a manual step
    calls = run.joined()
    assert "claude plugin install lsp@m -s user" in calls
    assert "skillshare plugin import lsp@m --from claude --name lsp --no-tui" in calls
    (home / ".config/skillshare/config.yaml").write_text(
        yaml.safe_dump({"plugins": {"packages": {"lsp": {}}}})
    )
    write(repo, "plugins", [])
    run = Runner()
    mod.main(["--no-push"], run=run)
    assert not any("plugin install" in c for c in run.joined())


@pytest.mark.parametrize(
    ("kind", "items", "problem"),
    [
        ("skills", [{"name": "x", "repo": "o/r", "ref": "main"}], "full 40-character"),
        ("skills", [{"name": "x", "repo": "o/r"}], "needs name, repo and ref"),
        ("skills", [{"name": "demo", "repo": "o/r", "ref": SHA_A}], "clashes"),
        (
            "mcp",
            [{"name": "m", "transport": "http", "url": "u", "headers": {"X": "pre-${V}"}}],
            "whole value",
        ),
        ("mcp", [{"name": "m", "transport": "stdio"}], "need a command"),
        ("plugins", [{"name": "p"}], "needs name, plugin"),
    ],
)
def test_check_catalog(
    env: tuple[ModuleType, Path, Path], kind: str, items: list[dict[str, object]], problem: str
) -> None:
    mod, _, repo = env
    write(repo, kind, items)
    problems = mod.check_catalog(repo)
    assert any(problem in p for p in problems), problems
    assert mod.main(["--check"], run=Runner()) == 1


def test_check_ok_and_hook(env: tuple[ModuleType, Path, Path]) -> None:
    mod, _, repo = env
    assert mod.main(["--check"], run=Runner()) == 0
    (repo / ".git/hooks").mkdir(parents=True)
    hook = mod.install_hook(repo)
    assert "scripts/apply.py" in hook.read_text() and hook.stat().st_mode & 0o111


def test_secrets_env_reads_file(
    env: tuple[ModuleType, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    mod, home, _ = env
    (home / ".secrets").mkdir()
    (home / ".secrets/agent.env").write_text("# c\nexport A_KEY='v1'\nB=2\n")
    monkeypatch.setenv("B", "env-wins")
    e = mod.secrets_env()
    assert e["A_KEY"] == "v1" and e["B"] == "env-wins"
