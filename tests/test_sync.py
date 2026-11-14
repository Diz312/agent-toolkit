"""Tests for the sync script, run against a fake HOME and a fake repo."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import tomlkit

SCRIPT = Path(__file__).resolve().parents[1] / "local-skills/toolkit-sync/scripts/sync.py"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path, Path]:
    home, repo = tmp_path / "home", tmp_path / "repo"
    (repo / "catalog").mkdir(parents=True)
    (repo / "local-skills/demo").mkdir(parents=True)
    (repo / "local-skills/demo/SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n")
    (repo / "catalog/skills.yaml").write_text("skills: []\n")
    (repo / "catalog/plugins.yaml").write_text("plugins: []\n")
    (repo / "catalog/mcp.yaml").write_text(
        "mcp:\n"
        "  - name: local\n    transport: stdio\n    command: npx\n    args: [-y, pkg@1.0.0]\n"
        "    env: {TOKEN: '${DEMO_TOKEN}'}\n"
        "  - name: remote\n    transport: http\n    url: https://x.example/mcp\n"
    )
    for d in (".cursor", ".codex", ".gemini/config"):
        (home / d).mkdir(parents=True)
    monkeypatch.setenv("AGENT_TOOLKIT_HOME", str(home))
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")  # no claude / gh CLIs
    spec = importlib.util.spec_from_file_location("sync_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sync_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "REPO", repo)
    return mod, home, repo


def test_resolve_and_missing_secret(env: tuple[ModuleType, Path, Path]) -> None:
    mod, _, _ = env
    assert mod.resolve({"a": ["${X}", "${Y:-dflt}"]}, {"X": "1"}) == {"a": ["1", "dflt"]}
    with pytest.raises(mod.MissingSecret):
        mod.resolve("${NOPE}", {})


def test_full_sync(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, _ = env
    assert mod.main([]) == 0
    # local skill linked into store and into present harnesses
    assert (home / ".agent-toolkit/skills/demo/SKILL.md").is_file()
    for d in (".agents/skills", ".cursor/skills", ".gemini/config/skills"):
        assert (home / d / "demo").is_symlink()
    assert not (home / ".claude/skills").exists()  # claude not present
    # secret missing -> 'local' skipped, 'remote' written in each format
    cursor = json.loads((home / ".cursor/mcp.json").read_text())["mcpServers"]
    assert cursor == {"remote": {"url": "https://x.example/mcp"}}
    ag = json.loads((home / ".gemini/config/mcp_config.json").read_text())["mcpServers"]
    assert ag == {"remote": {"serverUrl": "https://x.example/mcp"}}
    codex = tomlkit.parse((home / ".codex/config.toml").read_text())
    assert codex["mcp_servers"]["remote"]["url"] == "https://x.example/mcp"


def test_secret_from_env_file_and_removal(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, repo = env
    (home / ".agent-toolkit").mkdir()
    (home / ".agent-toolkit/.env").write_text("DEMO_TOKEN=abc\n")
    mod.main([])
    cursor = json.loads((home / ".cursor/mcp.json").read_text())["mcpServers"]
    assert cursor["local"] == {
        "command": "npx",
        "args": ["-y", "pkg@1.0.0"],
        "env": {"TOKEN": "abc"},
    }
    # drop 'remote' from catalog -> removed; user's own entry untouched
    data = json.loads((home / ".cursor/mcp.json").read_text())
    data["mcpServers"]["mine"] = {"command": "x"}
    (home / ".cursor/mcp.json").write_text(json.dumps(data))
    (repo / "catalog/mcp.yaml").write_text("mcp: []\n")
    mod.main([])
    cursor = json.loads((home / ".cursor/mcp.json").read_text())["mcpServers"]
    assert cursor == {"mine": {"command": "x"}}
    assert (home / ".cursor/mcp.json.agent-toolkit.bak").is_file()


def test_user_owned_entries_not_overwritten(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, _ = env
    (home / ".cursor/mcp.json").write_text(json.dumps({"mcpServers": {"remote": {"url": "mine"}}}))
    (home / ".cursor/skills/demo").mkdir(parents=True)
    mod.main([])
    cursor = json.loads((home / ".cursor/mcp.json").read_text())["mcpServers"]
    assert cursor["remote"] == {"url": "mine"}
    assert not (home / ".cursor/skills/demo").is_symlink()


def test_dry_run_changes_nothing(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, _ = env
    mod.main(["--dry-run"])
    assert not (home / ".agent-toolkit").exists()
    assert not (home / ".cursor/mcp.json").exists()


def test_skill_removed_from_catalog_is_unlinked(env: tuple[ModuleType, Path, Path]) -> None:
    mod, home, repo = env
    mod.main([])
    (repo / "local-skills/demo/SKILL.md").unlink()
    mod.main([])
    assert not (home / ".cursor/skills/demo").exists()
    assert not (home / ".agent-toolkit/skills/demo").exists()
