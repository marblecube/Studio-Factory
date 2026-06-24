"""Integration tests for process_queue() resume logic."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import orchestrator


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
    (input_dir / "test_clip.mp4").touch()
    (tmp_path / "Projects").mkdir()

    orchestrator.process_queue()

    mock_audit.assert_called_once()
    mock_anchor.assert_called_once()
    mock_explode.assert_called_once()
    mock_upscale.assert_called_once()
    mock_stitch.assert_called_once()


@patch("orchestrator.strategy_selector", return_value=["5k"])
def test_skip_already_stitched(mock_strat, tmp_path, monkeypatch, mock_config, capsys):
    """Videos with status 'stitched' should be skipped entirely."""
    monkeypatch.chdir(tmp_path)

    # Set up input with a video
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "done_clip.mp4").touch()

    # Set up project with 'stitched' status
    project_dir = tmp_path / "Projects" / "done_clip"
    project_dir.mkdir(parents=True)
    manifest = {
        "name": "done_clip",
        "status": "stitched",
        "outputs": {"5K": "Projects/done_clip/export/done_clip_5k_render.mp4"}
    }
    (project_dir / "manifest.json").write_text(json.dumps(manifest))

    orchestrator.process_queue()
    captured = capsys.readouterr()
    assert "Skipping" in captured.out


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
    (input_dir / "resume_clip.mp4").touch()

    # Pre-create project at 'verified' status
    project_dir = tmp_path / "Projects" / "resume_clip"
    for sub in ["process/frames_raw", "process/frames_upscaled", "export", "logs", "metadata"]:
        (project_dir / sub).mkdir(parents=True)
    manifest = {"name": "resume_clip", "status": "verified", "expected_frame_count": 50}
    (project_dir / "manifest.json").write_text(json.dumps(manifest))

    orchestrator.process_queue()

    # Should NOT have re-run audit, anchor, explode
    mock_audit.assert_not_called()
    mock_anchor.assert_not_called()
    mock_explode.assert_not_called()

    # Should have run upscale and stitch
    mock_upscale.assert_called_once()
    mock_stitch.assert_called_once()


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
