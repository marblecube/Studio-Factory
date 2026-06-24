"""Tests for verify() and verify_upscale()."""
import json
from pathlib import Path
import orchestrator


def _create_fake_frames(directory, count):
    """Helper: creates N fake .png files in a directory."""
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (directory / f"frame_{i:05d}.png").touch()


def test_verify_passes_when_counts_match(project_dir, mock_config):
    """verify() returns True and updates status when frame count matches."""
    frames_dir = project_dir / "process" / "frames_raw"
    _create_fake_frames(frames_dir, 100)

    result = orchestrator.verify(project_dir)
    assert result is True

    manifest = json.loads((project_dir / "manifest.json").read_text())
    assert manifest["status"] == "verified"
    assert manifest["actual_frame_count"] == 100


def test_verify_fails_when_counts_mismatch(project_dir, mock_config):
    """verify() returns False when frame count doesn't match expected."""
    frames_dir = project_dir / "process" / "frames_raw"
    _create_fake_frames(frames_dir, 95)  # Expected 100

    result = orchestrator.verify(project_dir)
    assert result is False

    # Status should NOT advance
    manifest = json.loads((project_dir / "manifest.json").read_text())
    assert manifest["status"] != "verified"


def test_verify_upscale_passes(project_dir, mock_config):
    """verify_upscale() returns True when upscaled count matches raw count."""
    # Set manifest to have actual_frame_count
    manifest_path = project_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["actual_frame_count"] = 50
    manifest_path.write_text(json.dumps(manifest))

    upscaled_dir = project_dir / "process" / "frames_upscaled"
    _create_fake_frames(upscaled_dir, 50)

    result = orchestrator.verify_upscale(project_dir)
    assert result is True

    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "upscaled"


def test_verify_upscale_fails(project_dir, mock_config):
    """verify_upscale() returns False on count mismatch."""
    manifest_path = project_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["actual_frame_count"] = 50
    manifest_path.write_text(json.dumps(manifest))

    upscaled_dir = project_dir / "process" / "frames_upscaled"
    _create_fake_frames(upscaled_dir, 48)  # Missing 2

    result = orchestrator.verify_upscale(project_dir)
    assert result is False
