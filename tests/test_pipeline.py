"""Integration tests for the full pipeline — process_queue() and phase functions.

Covers:
- Fresh processing, resume, and skip (duplicate detection)
- Upscale retry logic
- Quality gate failure handling
- Batch packaging flow
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import orchestrator
from config_manager import ProductionProfile


def _make_video(path, content=None):
    """Creates a fake video file with unique content for hash identity."""
    if content is None:
        content = f"fake-video-{path.name}-{id(path)}"
    path.write_text(content)
    return path


def _default_profile(**kwargs):
    """Returns a ProductionProfile with sensible test defaults."""
    defaults = dict(
        resolution=["5k"],
        model="upscayl-standard-4x",
        scale=4,
        package_output=False,
        retry_limit=3,
        batch_mode=False,
    )
    defaults.update(kwargs)
    return ProductionProfile(**defaults)


# ---------------------------------------------------------------------------
# Full-pipeline integration tests
# ---------------------------------------------------------------------------

@patch("orchestrator.stitch")
@patch("orchestrator.verify_upscale", return_value=True)
@patch("orchestrator.sift")
@patch("orchestrator.upscale")
@patch("orchestrator.verify", return_value=True)
@patch("orchestrator.explode")
@patch("orchestrator.anchor")
@patch("orchestrator.audit")
@patch("orchestrator.configure_production_run")
@patch("orchestrator.pre_flight_report", return_value=True)
def test_full_pipeline_from_scratch(
    mock_preflight, mock_configure,
    mock_audit, mock_anchor, mock_explode,
    mock_verify, mock_upscale, mock_sift, mock_verify_up, mock_stitch,
    tmp_path, monkeypatch, mock_config
):
    """A new video should run through all phases."""
    monkeypatch.chdir(tmp_path)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_video(input_dir / "test_clip.mp4")
    (tmp_path / "Projects").mkdir()

    mock_configure.return_value = _default_profile()

    # stitch needs to write to the manifest so process_queue can read results
    def _fake_stitch(project_root, profile, config):
        manifest_path = project_root / "manifest.json"
        with open(manifest_path, "r") as f:
            m = json.load(f)
        m["status"] = "stitched"
        m["outputs"] = {"5K": str(project_root / "export" / "test_clip_5k_render.mp4")}
        with open(manifest_path, "w") as f:
            json.dump(m, f)
        return True

    mock_stitch.side_effect = _fake_stitch

    orchestrator.process_queue(mock_config)

    mock_audit.assert_called_once()
    mock_anchor.assert_called_once()
    mock_explode.assert_called_once()
    mock_upscale.assert_called_once()
    mock_stitch.assert_called_once()


def test_skip_already_stitched(tmp_path, monkeypatch, mock_config, capsys):
    """Videos with status 'stitched' and matching hash should be skipped entirely."""
    monkeypatch.chdir(tmp_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    video = _make_video(input_dir / "done_clip.mp4", content="done-video-bytes")

    source_hash = orchestrator.hash_file(video)

    project_dir = tmp_path / "Projects" / "done_clip"
    project_dir.mkdir(parents=True)
    manifest = {
        "name": "done_clip",
        "status": "stitched",
        "source_hash": source_hash,
        "outputs": {"5K": "Projects/done_clip/export/done_clip_5k_render.mp4"}
    }
    (project_dir / "manifest.json").write_text(json.dumps(manifest))

    orchestrator.process_queue(mock_config)
    captured = capsys.readouterr()
    assert "already processed" in captured.out
    assert "Nothing to do" in captured.out


def test_skip_renamed_duplicate(tmp_path, monkeypatch, mock_config, capsys):
    """A renamed video with the same content as a stitched project should be skipped."""
    monkeypatch.chdir(tmp_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    video = _make_video(input_dir / "new_name.mp4", content="same-video-bytes")

    source_hash = orchestrator.hash_file(video)

    project_dir = tmp_path / "Projects" / "original_name"
    project_dir.mkdir(parents=True)
    manifest = {
        "name": "original_name",
        "status": "stitched",
        "source_hash": source_hash,
        "outputs": {"1080p": "Projects/original_name/export/original_name_1080p_render.mp4"}
    }
    (project_dir / "manifest.json").write_text(json.dumps(manifest))

    orchestrator.process_queue(mock_config)
    captured = capsys.readouterr()
    assert "already processed" in captured.out
    assert "original_name" in captured.out


@patch("orchestrator.stitch")
@patch("orchestrator.verify_upscale", return_value=True)
@patch("orchestrator.sift")
@patch("orchestrator.upscale")
@patch("orchestrator.verify", return_value=True)
@patch("orchestrator.explode")
@patch("orchestrator.anchor")
@patch("orchestrator.audit")
@patch("orchestrator.configure_production_run")
@patch("orchestrator.pre_flight_report", return_value=True)
def test_resume_from_verified(
    mock_preflight, mock_configure,
    mock_audit, mock_anchor, mock_explode,
    mock_verify, mock_upscale, mock_sift, mock_verify_up, mock_stitch,
    tmp_path, monkeypatch, mock_config
):
    """A project with status 'verified' should skip to upscale phase."""
    monkeypatch.chdir(tmp_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    video = _make_video(input_dir / "resume_clip.mp4")

    source_hash = orchestrator.hash_file(video)

    project_dir = tmp_path / "Projects" / "resume_clip"
    for sub in ["process/frames_raw", "process/frames_upscaled", "export", "logs", "metadata"]:
        (project_dir / sub).mkdir(parents=True)

    manifest = {
        "name": "resume_clip",
        "status": "verified",
        "source_hash": source_hash,
        "expected_frame_count": 50,
        "actual_frame_count": 50,
        "fps": "30/1",
    }
    (project_dir / "manifest.json").write_text(json.dumps(manifest))

    mock_configure.return_value = _default_profile()

    def _fake_stitch(project_root, profile, config):
        manifest_path = project_root / "manifest.json"
        with open(manifest_path, "r") as f:
            m = json.load(f)
        m["status"] = "stitched"
        m["outputs"] = {}
        with open(manifest_path, "w") as f:
            json.dump(m, f)
        return True

    mock_stitch.side_effect = _fake_stitch

    orchestrator.process_queue(mock_config)

    # Should NOT have re-run audit, anchor, explode
    mock_audit.assert_not_called()
    mock_anchor.assert_not_called()
    mock_explode.assert_not_called()

    # Should have run upscale and stitch
    mock_upscale.assert_called_once()
    mock_stitch.assert_called_once()


def test_legacy_output_key_support(tmp_path, monkeypatch, mock_config, capsys):
    """Projects with legacy 'output' (singular) key should still be detected as done."""
    monkeypatch.chdir(tmp_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    video = _make_video(input_dir / "legacy_clip.mp4", content="legacy-bytes")

    source_hash = orchestrator.hash_file(video)

    project_dir = tmp_path / "Projects" / "legacy_clip"
    project_dir.mkdir(parents=True)
    manifest = {
        "name": "legacy_clip",
        "status": "stitched",
        "source_hash": source_hash,
        "output": "Projects/legacy_clip/export/final_render.mp4"
    }
    (project_dir / "manifest.json").write_text(json.dumps(manifest))

    orchestrator.process_queue(mock_config)
    captured = capsys.readouterr()
    assert "already processed" in captured.out


def test_no_videos_early_return(tmp_path, monkeypatch, mock_config, capsys):
    """process_queue() with an empty input/ should return early."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()

    orchestrator.process_queue(mock_config)
    captured = capsys.readouterr()
    assert "No videos found" in captured.out


def test_no_input_dir(tmp_path, monkeypatch, mock_config, capsys):
    """process_queue() without an input/ directory should report the error."""
    monkeypatch.chdir(tmp_path)

    orchestrator.process_queue(mock_config)
    captured = capsys.readouterr()
    assert "No input/ directory found" in captured.out


# ---------------------------------------------------------------------------
# Hash utility tests
# ---------------------------------------------------------------------------

def test_hash_file_deterministic(tmp_path):
    """hash_file should produce the same hash for identical content."""
    file_a = tmp_path / "a.mp4"
    file_b = tmp_path / "b.mp4"
    file_a.write_text("identical-content")
    file_b.write_text("identical-content")

    assert orchestrator.hash_file(file_a) == orchestrator.hash_file(file_b)


def test_hash_file_unique(tmp_path):
    """hash_file should produce different hashes for different content."""
    file_a = tmp_path / "a.mp4"
    file_b = tmp_path / "b.mp4"
    file_a.write_text("content-alpha")
    file_b.write_text("content-beta")

    assert orchestrator.hash_file(file_a) != orchestrator.hash_file(file_b)


# ---------------------------------------------------------------------------
# Retry logic tests
# ---------------------------------------------------------------------------

def test_upscale_succeeds_on_first_attempt(tmp_path, mock_config):
    """upscale() should call _run_upscale once when it succeeds immediately."""
    profile = _default_profile(retry_limit=3)

    with patch("orchestrator._run_upscale") as mock_run:
        orchestrator.upscale(tmp_path, profile)

    mock_run.assert_called_once_with(tmp_path, profile.model, profile.scale)


def test_upscale_retries_on_failure(tmp_path, mock_config, capsys):
    """upscale() should retry up to retry_limit times on CalledProcessError."""
    profile = _default_profile(retry_limit=3)

    with patch("orchestrator._run_upscale") as mock_run, \
         patch("orchestrator.time.sleep"):  # don't actually sleep
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "upscayl-bin"),
            subprocess.CalledProcessError(1, "upscayl-bin"),
            None,  # succeeds on third attempt
        ]
        orchestrator.upscale(tmp_path, profile)

    assert mock_run.call_count == 3
    captured = capsys.readouterr()
    assert "Retrying" in captured.out


def test_upscale_raises_after_all_retries_exhausted(tmp_path, mock_config):
    """upscale() should raise CalledProcessError after all retries are exhausted."""
    import pytest
    profile = _default_profile(retry_limit=2)

    with patch("orchestrator._run_upscale") as mock_run, \
         patch("orchestrator.time.sleep"):
        mock_run.side_effect = subprocess.CalledProcessError(1, "upscayl-bin")
        with pytest.raises(subprocess.CalledProcessError):
            orchestrator.upscale(tmp_path, profile)

    assert mock_run.call_count == 2


# ---------------------------------------------------------------------------
# Quality gate failure handling
# ---------------------------------------------------------------------------

@patch("orchestrator.quality_gate", return_value=(False, {"bitrate_mbps": 0.1}))
def test_stitch_marks_failed_quality_in_manifest(mock_qgate, tmp_path, mock_config, capsys):
    """stitch() should mark manifest status as 'failed_quality' on gate failure."""
    # Build a minimal project structure
    project_root = tmp_path / "bad_render"
    export_dir = project_root / "export"
    frames_dir = project_root / "process" / "frames_upscaled"
    metadata_dir = project_root / "metadata"
    for d in [export_dir, frames_dir, metadata_dir]:
        d.mkdir(parents=True)

    (metadata_dir / "audio_anchor.wav").touch()

    manifest = {
        "name": "bad_render",
        "status": "upscaled",
        "fps": "30/1",
        "actual_frame_count": 10,
        "outputs": {}
    }
    (project_root / "manifest.json").write_text(json.dumps(manifest))

    profile = _default_profile(resolution=["5k"])

    with patch("orchestrator.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.stdout.__iter__ = lambda self: iter(["frame=10\n", "progress=end\n"])
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        mock_popen.return_value = mock_proc

        # Create a fake output file so quality_gate can check it
        fake_render = export_dir / "bad_render_5k_render.mp4"
        fake_render.touch()

        result = orchestrator.stitch(project_root, profile, mock_config)

    assert result is False
    with open(project_root / "manifest.json") as f:
        m = json.load(f)
    assert m["status"] == "failed_quality"
    captured = capsys.readouterr()
    assert "FAILED_QUALITY" in captured.out


# ---------------------------------------------------------------------------
# Batch packaging
# ---------------------------------------------------------------------------

def test_package_delivery_creates_archive(tmp_path, mock_config):
    """package_delivery() should collect renders and create a .7z archive."""
    import py7zr
    import os

    # Create fake project exports
    project_a = tmp_path / "Projects" / "clip_a"
    project_b = tmp_path / "Projects" / "clip_b"
    for p in [project_a, project_b]:
        (p / "export").mkdir(parents=True)
        (p / "export" / f"{p.name}_5k_render.mp4").write_bytes(b"fake-render-data")

    (tmp_path / "batch_exports").mkdir()

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        archive_path = orchestrator.package_delivery(
            [project_a, project_b], batch_name="test_batch"
        )
        # Resolve to absolute BEFORE restoring cwd
        archive_abs = tmp_path / archive_path
    finally:
        os.chdir(orig)

    assert archive_path is not None
    assert archive_abs.exists()
    assert archive_abs.suffix == ".7z"

    # Verify archive contains both renders
    with py7zr.SevenZipFile(str(archive_abs), "r") as archive:
        names = archive.getnames()
    assert "clip_a_5k_render.mp4" in names
    assert "clip_b_5k_render.mp4" in names


def test_package_delivery_returns_none_for_empty_batch(tmp_path, capsys):
    """package_delivery() with no renders should return None gracefully."""
    import os
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = orchestrator.package_delivery([], batch_name="empty_batch")
    finally:
        os.chdir(orig)

    assert result is None
    captured = capsys.readouterr()
    assert "No renders found" in captured.out


# Helper — can't use monkeypatch in plain functions, use contextmanager instead
from contextlib import contextmanager
import os

@contextmanager
def monkeypatch_chdir(path):
    orig = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(orig)
