"""Tests for validator module."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import validator
from validator import (
    estimate_batch_requirements,
    check_disk_space,
    pre_flight_report,
    quality_gate,
    _format_bytes,
    _estimate_duration_hours,
)


def _mock_ffprobe_result(stdout, returncode=0):
    """Helper: creates a mock subprocess.CompletedProcess."""
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    return result


class TestEstimateBatchRequirements:
    """Tests for batch disk space estimation."""

    @patch("validator.subprocess.run")
    def test_estimates_single_video(self, mock_run, tmp_path):
        """Should calculate frame count and byte estimate for one video."""
        video = tmp_path / "clip.mp4"
        video.touch()

        # ffprobe calls: frame count, then resolution
        mock_run.side_effect = [
            _mock_ffprobe_result("100\n"),    # 100 frames
            _mock_ffprobe_result("1920x1080\n"),  # resolution
        ]

        config = {"tools": {"ffprobe": "/usr/bin/ffprobe"}, "default_scale": 4}
        total_frames, total_bytes = estimate_batch_requirements([video], config)

        assert total_frames == 100
        assert total_bytes > 0

    @patch("validator.subprocess.run")
    def test_estimates_multiple_videos(self, mock_run, tmp_path):
        """Should sum estimates across multiple videos."""
        v1 = tmp_path / "clip_a.mp4"
        v2 = tmp_path / "clip_b.mp4"
        v1.touch()
        v2.touch()

        mock_run.side_effect = [
            _mock_ffprobe_result("100\n"),
            _mock_ffprobe_result("1920x1080\n"),
            _mock_ffprobe_result("200\n"),
            _mock_ffprobe_result("1920x1080\n"),
        ]

        config = {"tools": {"ffprobe": "/usr/bin/ffprobe"}, "default_scale": 4}
        total_frames, total_bytes = estimate_batch_requirements([v1, v2], config)

        assert total_frames == 300

    @patch("validator.subprocess.run", side_effect=Exception("ffprobe not found"))
    def test_handles_probe_failure(self, mock_run, tmp_path):
        """Should skip videos that fail to probe without crashing."""
        video = tmp_path / "bad.mp4"
        video.touch()

        config = {"tools": {"ffprobe": "/usr/bin/ffprobe"}, "default_scale": 4}
        total_frames, total_bytes = estimate_batch_requirements([video], config)

        assert total_frames == 0
        assert total_bytes == 0


class TestCheckDiskSpace:
    """Tests for disk space validation."""

    @patch("validator.shutil.disk_usage")
    def test_sufficient_space(self, mock_usage):
        """Should return ok=True when free space exceeds requirement + margin."""
        # 500 GB free, need 100 GB → 120 GB with margin → plenty
        mock_usage.return_value = (500 * 1024**3, 0, 500 * 1024**3)

        ok, free, required = check_disk_space(100 * 1024**3)

        assert ok is True
        assert free == 500 * 1024**3
        assert required == int(100 * 1024**3 * 1.2)

    @patch("validator.shutil.disk_usage")
    def test_insufficient_space(self, mock_usage):
        """Should return ok=False when free space is below requirement + margin."""
        # 50 GB free, need 100 GB → 120 GB with margin → not enough
        mock_usage.return_value = (500 * 1024**3, 450 * 1024**3, 50 * 1024**3)

        ok, free, required = check_disk_space(100 * 1024**3)

        assert ok is False

    @patch("validator.shutil.disk_usage")
    def test_margin_is_20_percent(self, mock_usage):
        """Should apply exactly 20% safety margin."""
        mock_usage.return_value = (1000, 0, 1000)

        _, _, required = check_disk_space(100)

        assert required == 120  # 100 * 1.2


class TestPreFlightReport:
    """Tests for the pre-flight report."""

    @patch("validator.check_disk_space", return_value=(True, 500 * 1024**3, 120 * 1024**3))
    @patch("validator.estimate_batch_requirements", return_value=(5000, 100 * 1024**3))
    def test_go_report(self, mock_est, mock_disk, tmp_path, monkeypatch, capsys):
        """Should print GO status and return True when space is sufficient."""
        monkeypatch.chdir(tmp_path)

        config = {"tools": {"ffprobe": "/usr/bin/ffprobe"}, "default_scale": 4}
        video = tmp_path / "clip.mp4"
        video.touch()

        result = pre_flight_report([video], config)
        captured = capsys.readouterr()

        assert result is True
        assert "GO" in captured.out
        assert "5,000" in captured.out

    @patch("validator.check_disk_space", return_value=(False, 50 * 1024**3, 120 * 1024**3))
    @patch("validator.estimate_batch_requirements", return_value=(5000, 100 * 1024**3))
    def test_no_go_report(self, mock_est, mock_disk, tmp_path, monkeypatch, capsys):
        """Should print NO-GO status and return False when space is insufficient."""
        monkeypatch.chdir(tmp_path)

        config = {"tools": {"ffprobe": "/usr/bin/ffprobe"}, "default_scale": 4}
        video = tmp_path / "clip.mp4"
        video.touch()

        result = pre_flight_report([video], config)
        captured = capsys.readouterr()

        assert result is False
        assert "NO-GO" in captured.out

    @patch("validator.estimate_batch_requirements", return_value=(0, 0))
    def test_zero_frames_returns_false(self, mock_est, tmp_path, monkeypatch, capsys):
        """Should return False if no frames could be estimated."""
        monkeypatch.chdir(tmp_path)

        config = {"tools": {"ffprobe": "/usr/bin/ffprobe"}, "default_scale": 4}
        result = pre_flight_report([], config)

        assert result is False


class TestQualityGate:
    """Tests for the quality gate (replaces quality_report)."""

    @patch("validator.subprocess.run")
    def test_pass_healthy_render(self, mock_run, tmp_path):
        """A healthy render should pass the quality gate."""
        render = tmp_path / "test_5k_render.mp4"
        render.write_bytes(b"x" * (10 * 1024 * 1024))  # 10 MB file

        mock_run.return_value = _mock_ffprobe_result(
            "codec_name=h264\n"
            "width=7680\n"
            "height=4320\n"
            "r_frame_rate=30000/1001\n"
            "bit_rate=25000000\n"
        )

        config = {
            "tools": {"ffprobe": "/usr/bin/ffprobe"},
            "quality_thresholds": {
                "min_bitrate_mbps_5k": 8.0,
                "min_bitrate_mbps_1080p": 2.0,
                "min_file_size_mb": 1.0,
            }
        }

        passed, report = quality_gate(render, config, target_resolution="5k")

        assert passed is True
        assert report["codec"] == "h264"
        assert report["bitrate_mbps"] == 25.0

    @patch("validator.subprocess.run")
    def test_fail_low_bitrate(self, mock_run, tmp_path, capsys):
        """A render with bitrate below threshold should fail."""
        render = tmp_path / "test_5k_render.mp4"
        render.write_bytes(b"x" * (10 * 1024 * 1024))  # 10 MB

        mock_run.return_value = _mock_ffprobe_result(
            "codec_name=h264\n"
            "width=7680\n"
            "height=4320\n"
            "r_frame_rate=30/1\n"
            "bit_rate=300000\n"  # 0.3 Mbps — way below 8.0 threshold
        )

        config = {
            "tools": {"ffprobe": "/usr/bin/ffprobe"},
            "quality_thresholds": {
                "min_bitrate_mbps_5k": 8.0,
                "min_bitrate_mbps_1080p": 2.0,
                "min_file_size_mb": 1.0,
            }
        }

        passed, report = quality_gate(render, config, target_resolution="5k")
        captured = capsys.readouterr()

        assert passed is False
        assert "QUALITY GATE FAILED" in captured.out
        assert "below minimum" in captured.out

    @patch("validator.subprocess.run")
    def test_fail_tiny_file(self, mock_run, tmp_path, capsys):
        """A render with file size below threshold should fail."""
        render = tmp_path / "test_1080p_render.mp4"
        render.write_bytes(b"x" * 100)  # 100 bytes — way below 1 MB threshold

        mock_run.return_value = _mock_ffprobe_result(
            "codec_name=h264\n"
            "width=1920\n"
            "height=1080\n"
            "r_frame_rate=24/1\n"
            "bit_rate=5000000\n"
        )

        config = {
            "tools": {"ffprobe": "/usr/bin/ffprobe"},
            "quality_thresholds": {
                "min_bitrate_mbps_1080p": 2.0,
                "min_file_size_mb": 1.0,
            }
        }

        passed, report = quality_gate(render, config, target_resolution="1080p")
        captured = capsys.readouterr()

        assert passed is False
        assert "QUALITY GATE FAILED" in captured.out

    @patch("validator.subprocess.run")
    def test_1080p_uses_correct_threshold(self, mock_run, tmp_path):
        """1080p renders should use the 1080p bitrate threshold."""
        render = tmp_path / "test_1080p.mp4"
        render.write_bytes(b"x" * (5 * 1024 * 1024))

        mock_run.return_value = _mock_ffprobe_result(
            "codec_name=h264\n"
            "width=1920\n"
            "height=1080\n"
            "r_frame_rate=30/1\n"
            "bit_rate=3000000\n"  # 3 Mbps — above 2.0 threshold
        )

        config = {
            "tools": {"ffprobe": "/usr/bin/ffprobe"},
            "quality_thresholds": {
                "min_bitrate_mbps_1080p": 2.0,
                "min_bitrate_mbps_5k": 8.0,
                "min_file_size_mb": 1.0,
            }
        }

        passed, _ = quality_gate(render, config, target_resolution="1080p")

        assert passed is True

    @patch("validator.subprocess.run", side_effect=Exception("ffprobe crash"))
    def test_handles_probe_exception(self, mock_run, tmp_path, capsys):
        """Should return False and report error on ffprobe failure."""
        render = tmp_path / "bad.mp4"
        render.touch()

        config = {"tools": {"ffprobe": "/usr/bin/ffprobe"}}

        passed, report = quality_gate(render, config)
        captured = capsys.readouterr()

        assert passed is False
        assert "error" in report
        assert "Quality gate error" in captured.out

    @patch("validator.subprocess.run")
    def test_missing_thresholds_uses_defaults(self, mock_run, tmp_path):
        """Config without quality_thresholds should fall back to defaults."""
        render = tmp_path / "test_5k.mp4"
        render.write_bytes(b"x" * (5 * 1024 * 1024))

        mock_run.return_value = _mock_ffprobe_result(
            "codec_name=h264\n"
            "width=7680\n"
            "height=4320\n"
            "r_frame_rate=30/1\n"
            "bit_rate=25000000\n"
        )

        # No quality_thresholds block — should use defaults
        config = {"tools": {"ffprobe": "/usr/bin/ffprobe"}}

        passed, _ = quality_gate(render, config, target_resolution="5k")

        assert passed is True


class TestHelpers:
    """Tests for utility functions."""

    def test_format_bytes(self):
        """Should convert bytes to human-readable GB."""
        assert _format_bytes(1024 ** 3) == "1.0 GB"
        assert _format_bytes(0) == "0.0 GB"
        assert _format_bytes(1.5 * 1024 ** 3) == "1.5 GB"

    def test_estimate_duration(self):
        """Should return a positive duration for any frame count."""
        hours = _estimate_duration_hours(10000)
        assert hours > 0
        # 10000 frames / 2fps = 5000s for upscale alone = ~1.4 hours minimum
        assert hours > 1.0
