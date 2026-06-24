"""Tests for quality_gate() in validator.

quality_report() was removed in the Phase B refactor and replaced by
quality_gate() in validator.py. These tests verify that the gate correctly
parses ffprobe output and enforces pass/fail thresholds.
"""
from unittest.mock import patch, MagicMock
from pathlib import Path
from validator import quality_gate


def _make_ffprobe_result(stdout_text, returncode=0):
    """Helper: creates a mock subprocess result."""
    result = MagicMock()
    result.stdout = stdout_text
    result.returncode = returncode
    return result


def _base_config():
    return {
        "tools": {"ffprobe": "/usr/bin/ffprobe"},
        "quality_thresholds": {
            "min_bitrate_mbps_5k": 8.0,
            "min_bitrate_mbps_1080p": 2.0,
            "min_file_size_mb": 1.0,
        }
    }


@patch("validator.subprocess.run")
def test_quality_report_parses_output(mock_run, tmp_path, capsys):
    """quality_gate() should parse ffprobe key=value output correctly."""
    render = tmp_path / "test_render.mp4"
    render.write_bytes(b"x" * (10 * 1024 * 1024))  # 10 MB

    mock_run.return_value = _make_ffprobe_result(
        "codec_name=h264\n"
        "width=3840\n"
        "height=2160\n"
        "r_frame_rate=30000/1001\n"
        "bit_rate=25000000\n"
    )

    passed, report = quality_gate(render, _base_config(), target_resolution="5k")
    captured = capsys.readouterr()

    assert passed is True
    assert "h264" in captured.out
    assert "3840" in captured.out
    assert "2160" in captured.out
    assert "25.0 Mbps" in captured.out


@patch("validator.subprocess.run")
def test_quality_report_handles_missing_bitrate(mock_run, tmp_path, capsys):
    """quality_gate() should handle missing or malformed bitrate gracefully."""
    render = tmp_path / "test_render.mp4"
    render.write_bytes(b"x" * (10 * 1024 * 1024))

    mock_run.return_value = _make_ffprobe_result(
        "codec_name=h264\n"
        "width=1920\n"
        "height=1080\n"
        "r_frame_rate=24/1\n"
        "bit_rate=N/A\n"
    )

    # Should not raise — bad bitrate means bitrate_mbps=0, which with N/A
    # raw value doesn't trigger the "missing bitrate" failure path
    passed, report = quality_gate(render, _base_config(), target_resolution="1080p")
    captured = capsys.readouterr()

    assert "h264" in captured.out
    assert "N/A" in captured.out


@patch("validator.subprocess.run", side_effect=Exception("ffprobe not found"))
def test_quality_report_handles_exception(mock_run, tmp_path, capsys):
    """quality_gate() should return False and print a warning on failure."""
    render = tmp_path / "bad_file.mp4"
    render.touch()

    passed, report = quality_gate(render, _base_config())
    captured = capsys.readouterr()

    assert passed is False
    assert "Quality gate error" in captured.out
