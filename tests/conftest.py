"""Shared fixtures for Studio Factory tests."""
import json
import pytest
from pathlib import Path


@pytest.fixture
def mock_config(tmp_path):
    """Creates a temporary config.json and loads it into orchestrator globals."""
    import orchestrator

    config_data = {
        "tools": {
            "ffmpeg": "/usr/bin/ffmpeg",
            "ffprobe": "/usr/bin/ffprobe",
            "upscayl_bin": "tools/upscayl/upscayl-bin",
            "upscayl_models": "tools/upscayl/models"
        },
        "default_model": "upscayl-standard-4x",
        "default_scale": 4
    }

    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data))
    orchestrator.load_config(config_file)

    yield config_data

    # Reset globals after test
    orchestrator.FFMPEG = None
    orchestrator.FFPROBE = None
    orchestrator.UPSCAYL_BIN = None
    orchestrator.UPSCAYL_MODELS = None
    orchestrator.DEFAULT_MODEL = None
    orchestrator.DEFAULT_SCALE = None


@pytest.fixture
def project_dir(tmp_path):
    """Creates a full project skeleton with manifest, ready for phase tests."""
    project_root = tmp_path / "test_project"
    for sub in ["process/frames_raw", "process/frames_upscaled", "export", "logs", "metadata"]:
        (project_root / sub).mkdir(parents=True)

    manifest = {
        "name": "test_project",
        "status": "initialized",
        "expected_frame_count": 100,
        "actual_frame_count": 100,
        "fps": "30000/1001",
        "source_metadata": {}
    }

    manifest_path = project_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=4))

    return project_root


@pytest.fixture
def sample_manifest():
    """Returns a realistic manifest dict for assertion helpers."""
    return {
        "name": "test_project",
        "status": "audited",
        "expected_frame_count": 100,
        "actual_frame_count": 100,
        "fps": "30000/1001",
        "source_metadata": {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080
                }
            ],
            "format": {
                "duration": "3.337000",
                "bit_rate": "5000000"
            }
        }
    }
