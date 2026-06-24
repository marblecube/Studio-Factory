"""Tests for quality_report()."""
from unittest.mock import patch, MagicMock
from pathlib import Path
import orchestrator


def _make_ffprobe_result(stdout_text, returncode=0):
    """Helper: creates a mock subprocess result."""
    result = MagicMock()
    result.stdout = stdout_text
    result.returncode = returncode
    return result


@patch("orchestrator.subprocess.run")
def test_quality_report_parses_output(mock_run, mock_config, capsys):
    """quality_report() should parse ffprobe key=value output correctly."""
    mock_run.return_value = _make_ffprobe_result(
        "codec_name=h264\n"
        "width=3840\n"
        "height=2160\n"
        "r_frame_rate=30000/1001\n"
        "bit_rate=25000000\n"
    )

    orchestrator.quality_report(Path("test_render.mp4"))
    captured = capsys.readouterr()

    assert "h264" in captured.out
    assert "3840" in captured.out
    assert "2160" in captured.out
    assert "25.0 Mbps" in captured.out


@patch("orchestrator.subprocess.run")
def test_quality_report_handles_missing_bitrate(mock_run, mock_config, capsys):
    """quality_report() should handle missing or malformed bitrate gracefully."""
    mock_run.return_value = _make_ffprobe_result(
        "codec_name=h264\n"
        "width=1920\n"
        "height=1080\n"
        "r_frame_rate=24/1\n"
        "bit_rate=N/A\n"
    )

    # Should not raise
    orchestrator.quality_report(Path("test_render.mp4"))
    captured = capsys.readouterr()

    assert "N/A" in captured.out
    assert "h264" in captured.out


@patch("orchestrator.subprocess.run", side_effect=Exception("ffprobe not found"))
def test_quality_report_handles_exception(mock_run, mock_config, capsys):
    """quality_report() should print a warning instead of crashing on failure."""
    orchestrator.quality_report(Path("bad_file.mp4"))
    captured = capsys.readouterr()

    assert "Quality report failed" in captured.out
