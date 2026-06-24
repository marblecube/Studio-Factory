"""Tests for strategy/resolution selection via configure_production_run().

strategy_selector() was removed in the Phase A refactor and replaced by
configure_production_run() in config_manager. These tests verify that the
new function correctly maps user input to ProductionProfile.resolution.
"""
from unittest.mock import patch
from config_manager import configure_production_run


def _make_config(tmp_path):
    """Helper: builds a minimal config with one model on disk."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "upscayl-standard-4x.param").touch()
    return {
        "tools": {"upscayl_models": str(models_dir)},
        "default_model": "upscayl-standard-4x",
        "default_scale": 4,
        "models": {"upscayl-standard-4x": "Standard — Balanced."},
    }


@patch("builtins.input", side_effect=["1", ""])  # resolution=5k, crf=default
def test_strategy_5k(mock_input, tmp_path):
    """Selecting '1' returns 5K resolution."""
    config = _make_config(tmp_path)
    profile = configure_production_run(config, video_count=1)
    assert profile.resolution == ["5k"]


@patch("builtins.input", side_effect=["2", ""])  # resolution=1080p, crf=default
def test_strategy_1080p(mock_input, tmp_path):
    """Selecting '2' returns 1080p resolution."""
    config = _make_config(tmp_path)
    profile = configure_production_run(config, video_count=1)
    assert profile.resolution == ["1080p"]


@patch("builtins.input", side_effect=["3", ""])  # resolution=both, crf=default
def test_strategy_both(mock_input, tmp_path):
    """Selecting '3' returns both resolution targets."""
    config = _make_config(tmp_path)
    profile = configure_production_run(config, video_count=1)
    assert profile.resolution == ["5k", "1080p"]


@patch("builtins.input", side_effect=["x", "abc", "2", ""])  # invalid, invalid, resolution=1080p, crf=default
def test_strategy_retries_on_invalid_input(mock_input, tmp_path):
    """Invalid inputs should prompt again until a valid choice is given."""
    config = _make_config(tmp_path)
    profile = configure_production_run(config, video_count=1)
    assert profile.resolution == ["1080p"]
