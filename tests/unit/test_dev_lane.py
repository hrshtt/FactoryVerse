import json
import subprocess
import sys
from pathlib import Path

import pytest

from FactoryVerse.dev.lane import (
    LaneError,
    build_codex_command,
    create_lane,
    lane_environment,
    lane_status,
    list_lanes,
    load_lane,
    retire_lane,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "FactoryVerse"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "lanes@example.invalid")
    _git(repo, "config", "user.name", "Lane Tests")
    (repo / "README.md").write_text("lane test\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".fv-output/\n", encoding="utf-8")
    _git(repo, "add", "README.md", ".gitignore")
    _git(repo, "commit", "-qm", "baseline")
    return repo


def test_create_lane_resolves_relative_paths_and_registers_worktree(tmp_path):
    repo = _repository(tmp_path)
    baseline = _git(repo, "rev-parse", "HEAD")

    lane = create_lane(
        "harness-a",
        start=repo,
        lanes_root="../FactoryVerse-lanes",
        development_slot=4,
        objective="Test Codex harness integration.",
        codex_model="gpt-test",
    )

    expected = (tmp_path / "FactoryVerse-lanes" / "harness-a").resolve()
    assert lane.worktree_path == str(expected)
    assert lane.output_dir == str(expected / ".fv-output")
    assert lane.base_commit == baseline
    assert lane.branch == "research/lane-harness-a"
    assert lane.development_slot == 4
    assert (repo / ".git" / "factoryverse-lanes" / "harness-a.json").is_file()
    assert _git(expected, "branch", "--show-current") == lane.branch

    loaded = load_lane("harness-a", start=expected)
    assert loaded == lane
    assert list_lanes(start=expected) == [lane]
    status = lane_status(lane, start=repo)
    assert status["healthy"] is True
    assert status["registered_worktree"] is True
    assert status["head"] == baseline
    assert status["dirty"] is False


def test_create_lane_auto_assigns_slots_and_rejects_duplicates(tmp_path):
    repo = _repository(tmp_path)
    first = create_lane("first", start=repo, lanes_root="../lanes")
    second = create_lane("second", start=repo, lanes_root="../lanes")

    assert first.development_slot == 0
    assert second.development_slot == 1
    with pytest.raises(LaneError, match="already assigned"):
        create_lane(
            "collision",
            start=repo,
            lanes_root="../lanes",
            development_slot=1,
        )


def test_concurrent_lane_creation_allocates_distinct_slots(tmp_path):
    repo = _repository(tmp_path)
    script = (
        "from FactoryVerse.dev.lane import create_lane; "
        "import pathlib, sys; "
        "lane = create_lane(sys.argv[1], start=pathlib.Path(sys.argv[2]), "
        "lanes_root='../lanes'); "
        "print(lane.development_slot)"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, name, str(repo)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for name in ("parallel-a", "parallel-b")
    ]
    results = [process.communicate(timeout=10) for process in processes]

    for process, (_, stderr) in zip(processes, results, strict=True):
        assert process.returncode == 0, stderr
    assert {int(stdout.strip()) for stdout, _ in results} == {0, 1}


def test_create_lane_rejects_output_escape_before_creating_branch(tmp_path):
    repo = _repository(tmp_path)

    with pytest.raises(LaneError, match="must resolve inside"):
        create_lane(
            "escape",
            start=repo,
            lanes_root="../lanes",
            output_dir="../shared-output",
        )

    assert not (tmp_path / "lanes" / "escape").exists()
    assert (
        subprocess.run(
            ["git", "show-ref", "--verify", "refs/heads/research/lane-escape"],
            cwd=repo,
            capture_output=True,
            check=False,
        ).returncode
        != 0
    )


def test_codex_command_and_environment_encode_lane_boundary(tmp_path):
    repo = _repository(tmp_path)
    env_file = repo / "lane.env"
    env_file.write_text(
        "FV_RCON_PORT_BASE=31000\nUNRELATED_SECRET=do-not-import\n",
        encoding="utf-8",
    )
    lane = create_lane(
        "interactive",
        start=repo,
        lanes_root="../lanes",
        env_file=env_file,
        codex_executable="codex-test",
        codex_model="gpt-test",
        strict_config=True,
    )

    command = build_codex_command(
        lane,
        additional_prompt="Investigate instruction routing.",
        search=True,
    )
    assert command[:3] == ["codex-test", "-C", lane.worktree_path]
    assert ["--sandbox", "workspace-write"] == command[3:5]
    assert "--ask-for-approval" in command
    assert "--no-alt-screen" in command
    assert "--strict-config" in command
    assert ["--model", "gpt-test"] == command[-4:-2]
    assert command[-2] == "--search"
    assert "--slot 0" in command[-1]
    assert "Investigate instruction routing." in command[-1]

    environment = lane_environment(
        lane,
        base={"KEEP": "yes", "FV_GAME_PORT_BASE": "should-not-leak"},
    )
    assert environment["KEEP"] == "yes"
    assert environment["FV_RCON_PORT_BASE"] == "31000"
    assert "FV_GAME_PORT_BASE" not in environment
    assert "UNRELATED_SECRET" not in environment
    assert environment["FV_OUTPUT_DIR"] == lane.output_dir
    assert environment["FACTORYVERSE_LANE_NAME"] == "interactive"
    assert environment["FACTORYVERSE_LANE_DEVELOPMENT_SLOT"] == "0"


def test_lane_status_summarizes_campaigns_and_detects_branch_drift(tmp_path):
    repo = _repository(tmp_path)
    lane = create_lane("status", start=repo, lanes_root="../lanes")
    campaign = Path(lane.output_dir) / "freeplay" / "status-campaign"
    campaign.mkdir(parents=True)
    (campaign / "state.json").write_text(
        json.dumps({"status": "paused", "active_session_id": None}),
        encoding="utf-8",
    )

    status = lane_status(lane, start=repo)
    assert status["campaigns"] == [
        {
            "campaign_id": "status-campaign",
            "status": "paused",
            "active_session_id": None,
        }
    ]

    _git(Path(lane.worktree_path), "checkout", "--detach", "-q")
    drifted = lane_status(lane, start=repo)
    assert drifted["healthy"] is False
    assert "branch mismatch" in drifted["errors"][0]


def test_retire_lane_refuses_dirty_worktree_and_preserves_artifacts(tmp_path):
    repo = _repository(tmp_path)
    lane = create_lane("guarded", start=repo, lanes_root="../lanes")
    worktree = Path(lane.worktree_path)
    dirty_file = worktree / "notes.txt"
    dirty_file.write_text("unreviewed\n", encoding="utf-8")

    with pytest.raises(LaneError, match="worktree is dirty"):
        retire_lane(lane, start=repo)
    assert worktree.is_dir()
    assert load_lane("guarded", start=repo) == lane

    dirty_file.unlink()
    artifact = Path(lane.output_dir) / "freeplay" / "evidence" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    with pytest.raises(LaneError, match="output contains artifacts"):
        retire_lane(lane, start=repo)
    assert artifact.is_file()
    assert load_lane("guarded", start=repo) == lane


def test_retire_lane_removes_clean_worktree_but_preserves_branch(tmp_path):
    repo = _repository(tmp_path)
    lane = create_lane("finished", start=repo, lanes_root="../lanes")

    result = retire_lane(lane, start=repo)

    assert result["preserved_branch"] == lane.branch
    assert not Path(lane.worktree_path).exists()
    with pytest.raises(LaneError, match="unknown lane"):
        load_lane("finished", start=repo)
    assert _git(repo, "show-ref", "--verify", f"refs/heads/{lane.branch}")
    replacement = create_lane("replacement", start=repo, lanes_root="../lanes")
    assert replacement.development_slot == 0


def test_cli_creates_inspects_and_dry_runs_lane(tmp_path, monkeypatch, capsys):
    from FactoryVerse.cli import main

    repo = _repository(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fv",
            "lane",
            "create",
            "cli-lane",
            "--root",
            "../lanes",
            "--slot",
            "3",
            "--objective",
            "Review the harness interactively.",
            "--json",
        ],
    )
    main()
    created = json.loads(capsys.readouterr().out)
    assert created["name"] == "cli-lane"
    assert created["development_slot"] == 3

    monkeypatch.setattr(
        sys,
        "argv",
        ["fv", "lane", "status", "cli-lane", "--json"],
    )
    main()
    status = json.loads(capsys.readouterr().out)
    assert status["healthy"] is True

    monkeypatch.setattr(
        sys,
        "argv",
        ["fv", "lane", "enter", "cli-lane", "--dry-run"],
    )
    main()
    command = capsys.readouterr().out
    assert "codex -C" in command
    assert created["worktree_path"] in command
    assert "default to --slot 3" in command
    assert "S2 experiment" in command

    monkeypatch.setattr(sys, "argv", ["fv", "lane", "path", "cli-lane"])
    main()
    assert capsys.readouterr().out.strip() == created["worktree_path"]

    monkeypatch.setattr(
        sys,
        "argv",
        ["fv", "lane", "retire", "cli-lane", "--json"],
    )
    main()
    retired = json.loads(capsys.readouterr().out)
    assert retired["preserved_branch"] == created["branch"]
    assert not Path(created["worktree_path"]).exists()
