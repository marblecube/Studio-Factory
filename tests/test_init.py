"""Tests for init_project()."""
import json
from pathlib import Path
import orchestrator


def test_init_creates_directory_structure(tmp_path, monkeypatch, mock_config):
    """init_project should create the full project skeleton."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Projects").mkdir()

    video_path = tmp_path / "fake_video.mp4"
    video_path.write_text("fake-video-content")
    project_root = orchestrator.init_project(video_path)

    assert project_root.exists()
    assert (project_root / "process" / "frames_raw").is_dir()
    assert (project_root / "export").is_dir()
    assert (project_root / "logs").is_dir()
    assert (project_root / "metadata").is_dir()


def test_init_creates_manifest(tmp_path, monkeypatch, mock_config):
    """init_project should write a manifest.json with status, source_hash, and source_file."""
    monkeypatch.chdir(tmp_path)

    video_path = tmp_path / "my_clip.mp4"
    video_path.write_text("my-clip-content")
    project_root = orchestrator.init_project(video_path)

    manifest_path = project_root / "manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text())
    assert manifest["name"] == "my_clip"
    assert manifest["status"] == "initialized"
    assert "source_hash" in manifest
    assert manifest["source_hash"] == orchestrator.hash_file(video_path)
    assert manifest["source_file"] == str(video_path)


def test_init_is_idempotent(tmp_path, monkeypatch, mock_config):
    """Running init_project twice should not overwrite an existing manifest."""
    monkeypatch.chdir(tmp_path)

    video_path = tmp_path / "rerun_test.mp4"
    video_path.write_text("rerun-content")

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


def test_init_backfills_hash_on_legacy_project(tmp_path, monkeypatch, mock_config):
    """init_project should backfill source_hash into legacy manifests that lack it."""
    monkeypatch.chdir(tmp_path)

    video_path = tmp_path / "legacy_vid.mp4"
    video_path.write_text("legacy-video-bytes")

    # Pre-create a legacy project without source_hash
    project_dir = tmp_path / "Projects" / "legacy_vid"
    for sub in ["process/frames_raw", "export", "logs", "metadata"]:
        (project_dir / sub).mkdir(parents=True)
    legacy_manifest = {"name": "legacy_vid", "status": "verified"}
    (project_dir / "manifest.json").write_text(json.dumps(legacy_manifest))

    orchestrator.init_project(video_path)

    manifest = json.loads((project_dir / "manifest.json").read_text())
    assert "source_hash" in manifest
    assert manifest["source_hash"] == orchestrator.hash_file(video_path)
    assert manifest["status"] == "verified"  # Should preserve existing status
