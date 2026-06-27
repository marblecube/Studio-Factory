"""Pre-flight validation and quality gating for Studio Factory.

Provides disk space estimation, batch requirement analysis, and
quality gate checks that enforce pass/fail on rendered output.
"""
import shutil
import subprocess
import json
from pathlib import Path


def estimate_batch_requirements(videos, config):
    """Estimates total frames and disk space for a batch of videos.

    Probes each video with ffprobe to get frame count and resolution,
    then calculates the storage footprint for raw PNGs, upscaled PNGs,
    and final renders.

    Args:
        videos: List of Path objects pointing to input video files.
        config: Parsed config dict (needs tools.ffprobe and default_scale).

    Returns:
        tuple: (total_frames, estimated_bytes) for the entire batch.
    """
    ffprobe = config['tools']['ffprobe']
    scale = config.get('default_scale', 4)
    total_frames = 0
    total_bytes = 0

    print(f"\n🔍 Probing {len(videos)} video(s)...")

    for video in videos:
        try:
            # Get frame count
            cmd_count = [
                ffprobe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=nb_frames",
                "-of", "default=nokey=1:noprint_wrappers=1",
                str(video)
            ]
            res_count = subprocess.run(cmd_count, capture_output=True, text=True, check=True)
            frames = int(res_count.stdout.strip())

            # Get resolution
            cmd_res = [
                ffprobe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                str(video)
            ]
            res_dims = subprocess.run(cmd_res, capture_output=True, text=True, check=True)
            parts = res_dims.stdout.strip().split("x")
            width, height = int(parts[0]), int(parts[1])

            print(f"   {video.name} — {width}×{height}, {frames:,} frames")

            # Calculate storage: raw PNGs + upscaled PNGs + ~10% for renders
            raw_bytes = frames * width * height * 3  # RGB PNG (uncompressed estimate)
            upscaled_bytes = frames * (width * scale) * (height * scale) * 3
            render_bytes = int(upscaled_bytes * 0.10)  # compressed MP4 ~10% of raw

            total_frames += frames
            total_bytes += raw_bytes + upscaled_bytes + render_bytes

        except Exception as e:
            print(f"   ⚠️  {video.name} — probe failed: {e}")
            continue

    return total_frames, total_bytes


def check_disk_space(required_bytes, target_path="/"):
    """Checks if sufficient disk space is available with 20% safety margin.

    Args:
        required_bytes: Estimated bytes needed for the job.
        target_path: Path on the target volume to check (default: root).

    Returns:
        tuple: (ok, free_bytes, required_with_margin_bytes)
    """
    total, used, free = shutil.disk_usage(target_path)
    required_with_margin = int(required_bytes * 1.2)  # 20% safety margin

    return free >= required_with_margin, free, required_with_margin


def _format_bytes(byte_count):
    """Formats byte count to human-readable GB string."""
    gb = byte_count / (1024 ** 3)
    return f"{gb:.1f} GB"


def _display_width(text):
    """Returns the visual display width of a string in a terminal.

    Emoji and CJK characters occupy 2 columns; most others occupy 1.
    Uses unicodedata.east_asian_width for accurate measurement.
    """
    import unicodedata
    width = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        width += 2 if eaw in ('W', 'F') else 1
    return width


def _box_line(content, inner_width=46):
    """Builds a fixed-width box line padded to inner_width display columns.

    Compensates for double-width characters (emoji, CJK) so the right
    border ║ always stays aligned regardless of emoji content.
    """
    padding = inner_width - _display_width(content)
    return f"\u2551{content}{' ' * max(0, padding)}\u2551"


def _estimate_duration_hours(total_frames):
    """Rough duration estimate based on typical processing speed.

    Assumes ~2 frames/second for upscale (GPU-bound, varies widely)
    plus ~30 fps for extraction and stitching.
    """
    # Upscale dominates: ~2 fps average for 4x upscale on consumer GPU
    upscale_seconds = total_frames / 2.0
    # Extraction + stitching: ~30 fps each, two passes
    other_seconds = (total_frames / 30.0) * 2
    total_seconds = upscale_seconds + other_seconds
    hours = total_seconds / 3600
    return hours


def pre_flight_report(videos, config):
    """Runs pre-flight checks and prints a formatted report.

    Estimates disk usage, checks available space, and provides
    a go/no-go recommendation.

    Args:
        videos: List of Path objects for input videos.
        config: Parsed config dict.

    Returns:
        bool: True if pre-flight passes (GO), False if it fails (NO-GO).
    """
    total_frames, required_bytes = estimate_batch_requirements(videos, config)

    if total_frames == 0:
        print("\n⚠️  Could not estimate requirements — no valid video probes.")
        return False

    # Check disk space on the volume where Projects/ will live
    projects_path = Path("Projects")
    projects_path.mkdir(exist_ok=True)
    ok, free_bytes, required_with_margin = check_disk_space(
        required_bytes, str(projects_path)
    )

    est_hours = _estimate_duration_hours(total_frames)

    # Format duration
    if est_hours < 1:
        duration_str = f"~{int(est_hours * 60)} minutes"
    else:
        hours = int(est_hours)
        minutes = int((est_hours - hours) * 60)
        duration_str = f"~{hours}h {minutes}m"

    # Print report (use _box_line so emoji don't break right-border alignment)
    W = 46  # inner display width of the box
    print("\n\u2554" + "\u2550" * W + "\u2557")
    print(_box_line("          PRE-FLIGHT REPORT", W))
    print("\u2560" + "\u2550" * W + "\u2563")
    print(_box_line(f"  \U0001f4cb Clips:          {len(videos)}", W))
    print(_box_line(f"  \U0001f39e\ufe0f  Total frames:  {total_frames:>13,}", W))
    print(_box_line(f"  \U0001f4be Est. footprint: {_format_bytes(required_with_margin)}", W))
    print(_box_line( "     (incl. 20% safety margin)", W))
    print(_box_line(f"  \U0001f4ff Disk free:      {_format_bytes(free_bytes)}", W))
    print(_box_line(f"  \u23f1\ufe0f  Est. duration:  {duration_str}", W))

    if ok:
        print(_box_line("  Status:          \u2705 GO", W))
    else:
        print(_box_line("  Status:          \u274c NO-GO", W))
        print(_box_line(
            f"  \u26a0\ufe0f  Need {_format_bytes(required_with_margin)}, "
            f"only {_format_bytes(free_bytes)} free.", W
        ))

    print("\u255a" + "\u2550" * W + "\u255d")

    return ok


def quality_gate(video_path, config, target_resolution="5k"):
    """Runs quality checks on a rendered video and enforces pass/fail.

    Replaces quality_report() — prints the same quality summary AND
    checks against configurable thresholds from config.json.

    Args:
        video_path: Path to the rendered video file.
        config: Parsed config dict (needs tools.ffprobe and quality_thresholds).
        target_resolution: "5k" or "1080p" — determines which threshold to apply.

    Returns:
        tuple: (passed, report_dict) where passed is bool and report_dict
               contains the parsed quality metrics.
    """
    ffprobe = config['tools']['ffprobe']
    thresholds = config.get('quality_thresholds', {
        'min_bitrate_mbps_1080p': 2.0,
        'min_bitrate_mbps_5k': 8.0,
        'min_file_size_mb': 1.0,
    })

    cmd = [
        ffprobe, "-v", "error", "-hide_banner",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,bit_rate",
        "-of", "default=noprint_wrappers=1",
        str(video_path)
    ]

    report = {}
    failures = []

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        fields = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                key, val = line.split("=", 1)
                fields[key] = val

        codec = fields.get("codec_name", "?")
        width = fields.get("width", "?")
        height = fields.get("height", "?")
        fps = fields.get("r_frame_rate", "?")
        bitrate_raw = fields.get("bit_rate", "0")

        # Convert bitrate to Mbps
        try:
            bitrate_mbps = int(bitrate_raw) / 1_000_000
            bitrate_display = f"{bitrate_mbps:.1f} Mbps"
        except (ValueError, TypeError):
            bitrate_mbps = 0.0
            bitrate_display = "N/A"

        report = {
            "codec": codec,
            "width": width,
            "height": height,
            "fps": fps,
            "bitrate_mbps": bitrate_mbps,
        }

        # Print quality report (same format the user is used to)
        print(f"\n   📊 Quality Report: {Path(video_path).name}")
        print(f"   ├── Codec:      {codec}")
        print(f"   ├── Resolution: {width}×{height}")
        print(f"   ├── FPS:        {fps}")
        print(f"   └── Bitrate:    {bitrate_display}")

        # --- Quality gate checks ---

        # 1. Bitrate check
        if target_resolution == "5k":
            min_bitrate = thresholds.get('min_bitrate_mbps_5k', 8.0)
        else:
            min_bitrate = thresholds.get('min_bitrate_mbps_1080p', 2.0)

        if bitrate_mbps < min_bitrate and bitrate_mbps > 0:
            failures.append(
                f"Bitrate {bitrate_mbps:.1f} Mbps is below minimum "
                f"{min_bitrate} Mbps for {target_resolution.upper()} renders. "
                f"This may indicate a corrupt or black-frame encode."
            )

        # 2. File size check
        min_file_mb = thresholds.get('min_file_size_mb', 1.0)
        try:
            file_size_mb = Path(video_path).stat().st_size / (1024 * 1024)
            report["file_size_mb"] = file_size_mb
            if file_size_mb < min_file_mb:
                failures.append(
                    f"File size {file_size_mb:.2f} MB is below minimum "
                    f"{min_file_mb} MB. Output may be empty or corrupt."
                )
        except OSError:
            failures.append("Could not read file size — file may not exist.")

        # 3. Bitrate completely missing (N/A)
        if bitrate_mbps == 0.0 and bitrate_raw not in ("0", "N/A"):
            failures.append("Bitrate could not be determined — possible probe failure.")

        # Report gate result
        if failures:
            print(f"\n   ⚠️  QUALITY GATE FAILED:")
            for fail in failures:
                print(f"      └── {fail}")
            return False, report
        else:
            print(f"   ✅ Quality gate: PASSED")
            return True, report

    except Exception as e:
        print(f"   ⚠️  Quality gate error: {e}")
        report["error"] = str(e)
        return False, report
