"""Integration tests for process_queue() resume logic and duplicate detection."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import orchestrator


def _make_video(path, content=None):
    """Creates a fake video file with unique content for hash identity."""
    if content is None:
        content = f"fake-video-{path.name}-{id(path)}"
    path.write_text(content)
    return path


@patch("orchestrator.stitch")
@patch("orchestrator.verify_upscale", return_value=True)
@patch("orchestrator.sift")
@patch("orchestrator.upscale")
@patch("orchestrator.verify", return_value=True)
@patch("orchestrator.explode")
@patch("orchestrator.anchor")
@patch("orchestrator.audit")
@patch("orchestrator.strategy_selector", return_value=["1080p"])
def test_full_pipeline_from_scratch(
    mock_strat, mock_audit, mock_anchor, mock_explode,
    mock_verify, mock_upscale, mock_sift, mock_verify_up, mock_stitch,
    tmp_path, monkeypatch, mock_config
):
    """A new video should run through all phases."""
    monkeypatch.chdir(tmp_path)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_video(input_dir / "test_clip.mp4")
    (tmp_path / "Projects").mkdir()

    orchestrator.process_queue()

    mock_audit.assert_called_once()
    mock_anchor.assert_called_once()
    mock_explode.assert_called_once()
    mock_upscale.assert_called_once()
    mock_stitch.assert_called_once()


def test_skip_already_stitched(tmp_path, monkeypatch, mock_config, capsys):
    """Videos with status 'stitched' and matching hash should be skipped entirely."""
    monkeypatch.chdir(tmp_path)

    # Set up input with a video
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    video = _make_video(input_dir / "done_clip.mp4", content="done-video-bytes")

    # Compute the hash the same way the pipeline would
    source_hash = orchestrator.hash_file(video)

    # Set up project with 'stitched' status and matching hash
    project_dir = tmp_path / "Projects" / "done_clip"
    project_dir.mkdir(parents=True)
    manifest = {
        "name": "done_clip",
        "status": "stitched",
        "source_hash": source_hash,
        "outputs": {"5K": "Projects/done_clip/export/done_clip_5k_render.mp4"}
    }
    (project_dir / "manifest.json").write_text(json.dumps(manifest))

    orchestrator.process_queue()
    captured = capsys.readouterr()
    assert "already processed" in captured.out
    assert "Nothing to do" in captured.out


def test_skip_renamed_duplicate(tmp_path, monkeypatch, mock_config, capsys):
    """A renamed video with the same content as a stitched project should be skipped."""
    monkeypatch.chdir(tmp_path)

    # Set up input with a video under a DIFFERENT name
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    video = _make_video(input_dir / "new_name.mp4", content="same-video-bytes")

    source_hash = orchestrator.hash_file(video)

    # Existing project under original name, already stitched
    project_dir = tmp_path / "Projects" / "original_name"
    project_dir.mkdir(parents=True)
    manifest = {
        "name": "original_name",
        "status": "stitched",
        "source_hash": source_hash,
        "outputs": {"1080p": "Projects/original_name/export/original_name_1080p_render.mp4"}
    }
    (project_dir / "manifest.json").write_text(json.dumps(manifest))

    orchestrator.process_queue()
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
@patch("orchestrator.strategy_selector", return_value=["1080p"])
def test_resume_from_verified(
    mock_strat, mock_audit, mock_anchor, mock_explode,
    mock_verify, mock_upscale, mock_sift, mock_verify_up, mock_stitch,
    tmp_path, monkeypatch, mock_config
):
    """A project with status 'verified' should skip to upscale phase."""
    monkeypatch.chdir(tmp_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    video = _make_video(input_dir / "resume_clip.mp4")

    source_hash = orchestrator.hash_file(video)

    # Pre-create project at 'verified' status with matching hash
    project_dir = tmp_path / "Projects" / "resume_clip"
    for sub in ["process/frames_raw", "process/frames_upscaled", "export", "logs", "metadata"]:
        (project_dir / sub).mkdir(parents=True)
    manifest = {
        "name": "resume_clip",
        "status": "verified",
        "source_hash": source_hash,
        "expected_frame_count": 50
    }
    (project_dir / "manifest.json").write_text(json.dumps(manifest))

    orchestrator.process_queue()

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

    orchestrator.process_queue()
    captured = capsys.readouterr()
    assert "already processed" in captured.out


def test_no_videos_early_return(tmp_path, monkeypatch, mock_config, capsys):
    """process_queue() with an empty input/ should return early."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()

    orchestrator.process_queue()
    captured = capsys.readouterr()
    assert "No videos found" in captured.out


def test_no_input_dir(tmp_path, monkeypatch, mock_config, capsys):
    """process_queue() without an input/ directory should report the error."""
    monkeypatch.chdir(tmp_path)

    orchestrator.process_queue()
    captured = capsys.readouterr()
    assert "No input/ directory found" in captured.out


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
