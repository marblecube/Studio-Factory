"""Tests for audit()."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess
import pytest
import orchestrator


def _mock_subprocess_run(cmd, **kwargs):
    """Routes mocked subprocess.run calls based on the ffprobe arguments."""
    cmd_str = " ".join(str(c) for c in cmd)

    result = MagicMock()
    result.returncode = 0

    if "-show_streams" in cmd_str:
        # Metadata query
        result.stdout = json.dumps({
            "streams": [{"codec_type": "video", "codec_name": "h264",
                         "width": 1920, "height": 1080}],
            "format": {"duration": "3.337", "bit_rate": "5000000"}
        })
    elif "nb_frames" in cmd_str:
        # Frame count query
        result.stdout = "100\n"
    elif "r_frame_rate" in cmd_str:
        # FPS query
        result.stdout = "30000/1001\n"
    else:
        result.stdout = ""

    return result


@patch("orchestrator.subprocess.run", side_effect=_mock_subprocess_run)
def test_audit_updates_manifest(mock_run, project_dir, mock_config):
    """audit() should enrich manifest with metadata, frame count, and fps."""
    video_path = Path("fake_video.mp4")

    orchestrator.audit(video_path, project_dir)

    manifest = json.loads((project_dir / "manifest.json").read_text())
    assert manifest["expected_frame_count"] == 100
    assert manifest["fps"] == "30000/1001"
    assert manifest["status"] == "audited"
    assert "streams" in manifest["source_metadata"]


@patch("orchestrator.subprocess.run", side_effect=_mock_subprocess_run)
def test_audit_calls_ffprobe_three_times(mock_run, project_dir, mock_config):
    """audit() should make exactly 3 ffprobe calls (metadata, count, fps)."""
    video_path = Path("fake_video.mp4")
    orchestrator.audit(video_path, project_dir)
    assert mock_run.call_count == 3


@patch("orchestrator.subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffprobe"))
def test_audit_raises_on_ffprobe_failure(mock_run, project_dir, mock_config):
    """audit() should propagate errors when ffprobe fails."""
    video_path = Path("fake_video.mp4")
    with pytest.raises(Exception):
        orchestrator.audit(video_path, project_dir)
