"""Tests for config_manager module."""
import json
from pathlib import Path
from unittest.mock import patch
import config_manager
from config_manager import ProductionProfile, load_config, get_available_models, configure_production_run


class TestProductionProfile:
    """Tests for the ProductionProfile dataclass."""

    def test_default_values(self):
        """Default profile should have sensible defaults."""
        profile = ProductionProfile()
        assert profile.resolution == ["5k"]
        assert profile.model == "upscayl-standard-4x"
        assert profile.scale == 4
        assert profile.package_output is False
        assert profile.retry_limit == 3
        assert profile.batch_mode is False

    def test_custom_values(self):
        """Profile should accept custom values."""
        profile = ProductionProfile(
            resolution=["1080p"],
            model="ultrasharp-4x",
            scale=2,
            package_output=True,
            retry_limit=5,
            batch_mode=True,
        )
        assert profile.resolution == ["1080p"]
        assert profile.model == "ultrasharp-4x"
        assert profile.scale == 2
        assert profile.package_output is True
        assert profile.retry_limit == 5
        assert profile.batch_mode is True

    def test_both_resolutions(self):
        """Profile should support dual resolution targets."""
        profile = ProductionProfile(resolution=["5k", "1080p"])
        assert len(profile.resolution) == 2
        assert "5k" in profile.resolution
        assert "1080p" in profile.resolution


class TestLoadConfig:
    """Tests for config loading."""

    def test_load_config_populates_globals(self, tmp_path):
        """load_config should populate module-level globals."""
        config_data = {
            "tools": {
                "ffmpeg": "/usr/bin/ffmpeg",
                "ffprobe": "/usr/bin/ffprobe",
                "upscayl_bin": "tools/upscayl/upscayl-bin",
                "upscayl_models": "tools/upscayl/models"
            },
            "default_model": "ultrasharp-4x",
            "default_scale": 2,
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        result = load_config(config_file)

        assert config_manager.FFMPEG == "/usr/bin/ffmpeg"
        assert config_manager.FFPROBE == "/usr/bin/ffprobe"
        assert config_manager.DEFAULT_MODEL == "ultrasharp-4x"
        assert config_manager.DEFAULT_SCALE == 2
        assert result == config_data

        # Cleanup globals
        config_manager.FFMPEG = None
        config_manager.FFPROBE = None
        config_manager.UPSCAYL_BIN = None
        config_manager.UPSCAYL_MODELS = None
        config_manager.DEFAULT_MODEL = None
        config_manager.DEFAULT_SCALE = None

    def test_load_config_returns_dict(self, tmp_path):
        """load_config should return the full config dict."""
        config_data = {
            "tools": {
                "ffmpeg": "/usr/bin/ffmpeg",
                "ffprobe": "/usr/bin/ffprobe",
                "upscayl_bin": "tools/upscayl/upscayl-bin",
                "upscayl_models": "tools/upscayl/models"
            },
            "default_model": "upscayl-standard-4x",
            "default_scale": 4,
            "models": {"upscayl-standard-4x": "Standard model."},
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        result = load_config(config_file)

        assert "models" in result
        assert result["models"]["upscayl-standard-4x"] == "Standard model."

        # Cleanup
        config_manager.FFMPEG = None
        config_manager.FFPROBE = None
        config_manager.UPSCAYL_BIN = None
        config_manager.UPSCAYL_MODELS = None
        config_manager.DEFAULT_MODEL = None
        config_manager.DEFAULT_SCALE = None

    def test_load_config_defaults(self, tmp_path):
        """Missing optional fields should get defaults."""
        config_data = {
            "tools": {
                "ffmpeg": "/usr/bin/ffmpeg",
                "ffprobe": "/usr/bin/ffprobe",
                "upscayl_bin": "tools/upscayl/upscayl-bin",
                "upscayl_models": "tools/upscayl/models"
            }
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        load_config(config_file)

        assert config_manager.DEFAULT_MODEL == "upscayl-standard-4x"
        assert config_manager.DEFAULT_SCALE == 4

        # Cleanup
        config_manager.FFMPEG = None
        config_manager.FFPROBE = None
        config_manager.UPSCAYL_BIN = None
        config_manager.UPSCAYL_MODELS = None
        config_manager.DEFAULT_MODEL = None
        config_manager.DEFAULT_SCALE = None


class TestGetAvailableModels:
    """Tests for model discovery."""

    def test_finds_installed_models(self, tmp_path):
        """Should discover models by scanning .param files on disk."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "ultrasharp-4x.param").touch()
        (models_dir / "ultrasharp-4x.bin").touch()
        (models_dir / "remacri-4x.param").touch()
        (models_dir / "remacri-4x.bin").touch()

        config = {
            "tools": {"upscayl_models": str(models_dir)},
            "models": {
                "ultrasharp-4x": "UltraSharp — Max detail.",
                "remacri-4x": "Remacri — Smooth look.",
                "upscayl-standard-4x": "Standard — Balanced.",
            }
        }

        installed, total_known = get_available_models(config)

        assert len(installed) == 2
        names = [name for name, _ in installed]
        assert "ultrasharp-4x" in names
        assert "remacri-4x" in names
        # Standard is described but not installed
        assert "upscayl-standard-4x" not in names
        assert total_known == 3

    def test_missing_models_dir(self, tmp_path):
        """Should return empty list if models directory doesn't exist."""
        config = {
            "tools": {"upscayl_models": str(tmp_path / "nonexistent")},
            "models": {"upscayl-standard-4x": "Standard."},
        }

        installed, total_known = get_available_models(config)

        assert len(installed) == 0
        assert total_known == 1

    def test_fallback_descriptions(self, tmp_path):
        """Should use built-in descriptions when config has no models block."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "ultrasharp-4x.param").touch()

        config = {"tools": {"upscayl_models": str(models_dir)}}

        installed, total_known = get_available_models(config)

        assert len(installed) == 1
        assert installed[0][0] == "ultrasharp-4x"
        assert "Maximum detail" in installed[0][1]
        assert total_known == len(config_manager._KNOWN_MODELS)

    def test_unknown_model_on_disk(self, tmp_path):
        """Models on disk not in descriptions should get a generic label."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "custom-model-4x.param").touch()

        config = {
            "tools": {"upscayl_models": str(models_dir)},
            "models": {"upscayl-standard-4x": "Standard."},
        }

        installed, total_known = get_available_models(config)

        assert len(installed) == 1
        assert installed[0][0] == "custom-model-4x"
        assert "No description available" in installed[0][1]


class TestConfigureProductionRun:
    """Tests for the interactive production run configuration."""

    @patch("builtins.input", side_effect=["1", "1"])
    def test_single_clip_5k(self, mock_input, tmp_path):
        """Single clip selecting 5K + first model should return correct profile."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "upscayl-standard-4x.param").touch()

        config = {
            "tools": {"upscayl_models": str(models_dir)},
            "default_model": "upscayl-standard-4x",
            "default_scale": 4,
            "models": {"upscayl-standard-4x": "Standard — Balanced."},
        }

        profile = configure_production_run(config, video_count=1)

        assert profile.resolution == ["5k"]
        assert profile.model == "upscayl-standard-4x"
        assert profile.batch_mode is False
        assert profile.package_output is False

    @patch("builtins.input", side_effect=["3", "1", "Y"])
    def test_batch_both_with_packaging(self, mock_input, tmp_path):
        """Batch with both resolutions + packaging should set all flags."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "ultrasharp-4x.param").touch()

        config = {
            "tools": {"upscayl_models": str(models_dir)},
            "default_model": "ultrasharp-4x",
            "default_scale": 4,
            "models": {"ultrasharp-4x": "UltraSharp."},
        }

        profile = configure_production_run(config, video_count=10)

        assert profile.resolution == ["5k", "1080p"]
        assert profile.batch_mode is True
        assert profile.package_output is True

    @patch("builtins.input", side_effect=["2", ""])
    def test_default_model_selection(self, mock_input, tmp_path):
        """Pressing enter with no input should select the default model."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "upscayl-standard-4x.param").touch()
        (models_dir / "ultrasharp-4x.param").touch()

        config = {
            "tools": {"upscayl_models": str(models_dir)},
            "default_model": "upscayl-standard-4x",
            "default_scale": 4,
            "models": {
                "upscayl-standard-4x": "Standard.",
                "ultrasharp-4x": "UltraSharp.",
            },
        }

        profile = configure_production_run(config, video_count=1)

        assert profile.model == "upscayl-standard-4x"

    @patch("builtins.input", side_effect=["2", "n"])
    def test_batch_decline_packaging(self, mock_input, tmp_path):
        """Declining packaging in batch mode should set package_output=False."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "upscayl-standard-4x.param").touch()

        config = {
            "tools": {"upscayl_models": str(models_dir)},
            "default_model": "upscayl-standard-4x",
            "default_scale": 4,
            "models": {"upscayl-standard-4x": "Standard."},
        }

        profile = configure_production_run(config, video_count=5)

        assert profile.resolution == ["1080p"]
        assert profile.batch_mode is True
        assert profile.package_output is False

    @patch("builtins.input", side_effect=["1", "1"])
    def test_no_models_on_disk(self, mock_input, tmp_path):
        """With no models on disk, should fall back to config default."""
        config = {
            "tools": {"upscayl_models": str(tmp_path / "nonexistent")},
            "default_model": "upscayl-standard-4x",
            "default_scale": 4,
        }

        profile = configure_production_run(config, video_count=1)

        assert profile.model == "upscayl-standard-4x"
