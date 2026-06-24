"""Tests for init_project()."""
import json
from pathlib import Path
import orchestrator


def test_init_creates_directory_structure(tmp_path, monkeypatch, mock_config):
    """init_project should create the full project skeleton."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Projects").mkdir()

    video_path = Path("fake_video.mp4")
    project_root = orchestrator.init_project(video_path)

    assert project_root.exists()
    assert (project_root / "process" / "frames_raw").is_dir()
    assert (project_root / "export").is_dir()
    assert (project_root / "logs").is_dir()
    assert (project_root / "metadata").is_dir()


def test_init_creates_manifest(tmp_path, monkeypatch, mock_config):
    """init_project should write a manifest.json with status 'initialized'."""
    monkeypatch.chdir(tmp_path)

    video_path = Path("my_clip.mp4")
    project_root = orchestrator.init_project(video_path)

    manifest_path = project_root / "manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text())
    assert manifest["name"] == "my_clip"
    assert manifest["status"] == "initialized"


def test_init_is_idempotent(tmp_path, monkeypatch, mock_config):
    """Running init_project twice should not overwrite an existing manifest."""
    monkeypatch.chdir(tmp_path)

    video_path = Path("rerun_test.mp4")

    # First init
    project_root = orchestrator.init_project(video_path)
    manifest_path = project_root / "manifest.json"

    # Modify manifest to simulate pipeline progress
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = "audited"
    manifest_path.write_text(json.dumps(manifest))

    # Second init — should NOT overwrite
    orchestrator.init_project(video_path)
    manifest_after = json.loads(manifest_path.read_text())
    assert manifest_after["status"] == "audited"
