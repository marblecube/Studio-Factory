import json
import hashlib
import subprocess
import time
import shutil
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
import re

from config_manager import (
    ProductionProfile,
    load_config,
    configure_production_run,
)
from validator import pre_flight_report, quality_gate

# Module-level config (populated by load_config via config_manager)
FFMPEG = None
FFPROBE = None
UPSCAYL_BIN = None
UPSCAYL_MODELS = None
DEFAULT_MODEL = None
DEFAULT_SCALE = None


def _sync_globals():
    """Syncs module-level globals from config_manager after load_config()."""
    global FFMPEG, FFPROBE, UPSCAYL_BIN, UPSCAYL_MODELS, DEFAULT_MODEL, DEFAULT_SCALE
    import config_manager
    FFMPEG = config_manager.FFMPEG
    FFPROBE = config_manager.FFPROBE
    UPSCAYL_BIN = config_manager.UPSCAYL_BIN
    UPSCAYL_MODELS = config_manager.UPSCAYL_MODELS
    DEFAULT_MODEL = config_manager.DEFAULT_MODEL
    DEFAULT_SCALE = config_manager.DEFAULT_SCALE


def hash_file(filepath, algorithm="sha256"):
    """Computes a hash digest of a file for identity tracking."""
    h = hashlib.new(algorithm)
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def init_project(video_path):
    """Phase 1: Initializes project structure and manifest.json."""
    project_root = Path("Projects") / video_path.stem
    structure = ["process/frames_raw", "export", "logs", "metadata"]

    for sub in structure:
        (project_root / sub).mkdir(parents=True, exist_ok=True)

    manifest_path = project_root / "manifest.json"
    if not manifest_path.exists():
        source_hash = hash_file(video_path)
        manifest = {
            "name": video_path.stem,
            "status": "initialized",
            "source_file": str(video_path),
            "source_hash": source_hash
        }
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=4)
    else:
        # Backfill source_hash for legacy projects that lack it
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        if "source_hash" not in manifest:
            manifest["source_hash"] = hash_file(video_path)
            manifest["source_file"] = str(video_path)
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=4)

    print(f"📁 Project initialized: {project_root}")
    return project_root


def audit(video_path, project_root):
    """Enriches manifest.json with source metadata and expected frame count."""
    print(f"🔍 Auditing source: {video_path.name}")
    manifest_path = project_root / "manifest.json"

    # 1. Get detailed stream/format metadata
    cmd_meta = [
        FFPROBE, "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(video_path)
    ]

    # 2. Get frame count
    cmd_count = [
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames", "-of", "default=nokey=1:noprint_wrappers=1",
        str(video_path)
    ]

    # 3. Get FPS
    cmd_fps = [
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate", "-of", "default=nokey=1:noprint_wrappers=1",
        str(video_path)
    ]

    try:
        res_meta = subprocess.run(cmd_meta, capture_output=True, text=True, check=True)
        metadata = json.loads(res_meta.stdout)

        res_count = subprocess.run(cmd_count, capture_output=True, text=True, check=True)
        frame_count = int(res_count.stdout.strip())

        res_fps = subprocess.run(cmd_fps, capture_output=True, text=True, check=True)
        fps = res_fps.stdout.strip()

        # Update manifest with audit data
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)

        manifest["source_metadata"] = metadata
        manifest["expected_frame_count"] = frame_count
        manifest["fps"] = fps
        manifest["status"] = "audited"

        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=4)

        print(f"✅ Audit complete: {frame_count} expected frames @ {fps} fps")

    except Exception as e:
        print(f"❌ Audit failed: {e}")
        raise


def anchor(video_path, project_root):
    """Phase 2: Extracts audio to metadata/audio_anchor.wav."""
    output_audio = project_root / "metadata" / "audio_anchor.wav"
    print(f"⚓ Anchoring audio from {video_path.name}...")

    cmd = [FFMPEG, "-y", "-i", str(video_path), "-vn", "-acodec", "pcm_s16le", str(output_audio)]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✅ Audio anchored: {output_audio}")
        return output_audio
    except subprocess.CalledProcessError as e:
        print(f"❌ Audio extraction failed: {e.stderr.decode()}")
        raise


def explode(video_path, project_root):
    """Phase 3: Explodes video into individual PNG frames with progress tracking."""
    frames_dir = project_root / "process" / "frames_raw"
    manifest_path = project_root / "manifest.json"

    # Read expected frame count from manifest for the progress bar
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    expected_frames = manifest.get("expected_frame_count", 0)

    print(f"💥 Exploding {video_path.name} into frames...")

    cmd = [
        FFMPEG, "-y", "-i", str(video_path),
        "-pix_fmt", "rgb24",
        "-progress", "pipe:1",
        str(frames_dir / "frame_%05d.png")
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    with tqdm(total=expected_frames, unit="frame", desc="Extracting") as pbar:
        last_frame = 0
        for line in process.stdout:
            match = re.search(r"frame=(\d+)", line)
            if match:
                current_frame = int(match.group(1))
                pbar.update(current_frame - last_frame)
                last_frame = current_frame

    process.wait()

    if process.returncode != 0:
        stderr = process.stderr.read()
        print(f"❌ Frame extraction failed: {stderr}")
        raise subprocess.CalledProcessError(process.returncode, cmd)

    print(f"✅ Raw frames extracted to: {frames_dir}")


def verify(project_root):
    """Verifies extracted frame count matches the source audit."""
    manifest_path = project_root / "manifest.json"
    frames_dir = project_root / "process" / "frames_raw"

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    expected = manifest["expected_frame_count"]

    actual = len(list(frames_dir.glob("*.png")))

    if actual == expected:
        print(f"✅ Verification passed: {actual}/{expected} frames")
        manifest["actual_frame_count"] = actual
        manifest["status"] = "verified"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=4)
        return True
    else:
        print(f"❌ Verification failed: Expected {expected}, got {actual}")
        return False


def _build_project_registry():
    """Scans all existing projects and builds a lookup of source_hash → project info.
    
    Returns a dict mapping source_hash to (project_name, status, outputs).
    """
    registry = {}
    projects_dir = Path("Projects")
    if not projects_dir.exists():
        return registry

    for manifest_path in projects_dir.glob("*/manifest.json"):
        try:
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            source_hash = manifest.get("source_hash")
            if source_hash:
                registry[source_hash] = {
                    "project": manifest_path.parent.name,
                    "status": manifest.get("status", "unknown"),
                    # Support both legacy "output" (singular) and current "outputs" (plural)
                    "outputs": manifest.get("outputs") or manifest.get("output", {}),
                }
        except (json.JSONDecodeError, OSError):
            continue

    return registry


def _run_upscale(project_root, model, scale):
    """Internal: runs the upscayl-bin subprocess for a single upscale pass."""
    input_dir = project_root / "process" / "frames_raw"
    output_dir = project_root / "process" / "frames_upscaled"
    output_dir.mkdir(exist_ok=True)
    manifest_path = project_root / "manifest.json"

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    total_frames = manifest.get("actual_frame_count", 0)

    print(f"🚀 Upscaling {total_frames} frames with {model} @ {scale}x...")

    cmd = [
        str(UPSCAYL_BIN),
        "-i", str(input_dir),
        "-o", str(output_dir),
        "-m", str(UPSCAYL_MODELS),
        "-n", model,
        "-s", str(scale),
        "-f", "png"
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    # upscayl-bin reports 0-100% per frame, so count completed frames
    with tqdm(total=total_frames, unit="frame", desc="Upscaling") as pbar:
        for line in process.stdout:
            match = re.search(r"(\d+\.?\d*)%", line)
            if match:
                pct = float(match.group(1))
                if pct >= 100.0:
                    pbar.update(1)

    process.wait()

    if process.returncode != 0:
        print(f"❌ Upscale failed (exit code {process.returncode})")
        raise subprocess.CalledProcessError(process.returncode, cmd)

    print(f"✅ Upscale complete: {output_dir}")


def upscale(project_root, profile):
    """Phase 4: Upscale raw frames with retry logic.

    Wraps _run_upscale() with exponential backoff retry. On failure,
    waits progressively longer (5s, 10s, 20s) before retrying.

    Args:
        project_root: Path to the project directory.
        profile: ProductionProfile with model, scale, and retry_limit.
    """
    for attempt in range(1, profile.retry_limit + 1):
        try:
            _run_upscale(project_root, profile.model, profile.scale)
            return
        except subprocess.CalledProcessError:
            if attempt < profile.retry_limit:
                wait = 5 * (2 ** (attempt - 1))  # 5s, 10s, 20s
                print(f"⚠️  Upscale attempt {attempt}/{profile.retry_limit} failed. "
                      f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"❌ Upscale failed after {profile.retry_limit} attempts.")
                raise


def sift(project_root):
    """Phase 4b: Flattens nested subdirectories created by the upscale engine."""
    upscaled_dir = project_root / "process" / "frames_upscaled"
    moved = 0

    for sub in list(upscaled_dir.iterdir()):
        if sub.is_dir():
            for img in sub.glob("*.png"):
                dest = upscaled_dir / img.name
                img.rename(dest)
                moved += 1
            sub.rmdir()

    if moved > 0:
        print(f"🧹 Sift: Flattened {moved} files from nested subdirectories.")
    else:
        print(f"🧹 Sift: Directory already flat — no action needed.")


def verify_upscale(project_root):
    """Verifies that the number of upscaled frames matches the raw count."""
    manifest_path = project_root / "manifest.json"
    upscaled_dir = project_root / "process" / "frames_upscaled"

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    raw_count = manifest['actual_frame_count']
    upscaled_count = len(list(upscaled_dir.glob("*.png")))

    if upscaled_count == raw_count:
        print(f"✅ Upscale verified: {upscaled_count}/{raw_count} frames")
        manifest['status'] = 'upscaled'
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=4)
        return True
    else:
        print(f"❌ Upscale verification failed: Expected {raw_count}, got {upscaled_count}")
        return False


def stitch(project_root, profile, config):
    """Phase 5: Recombines upscaled frames + audio anchor into final render(s).

    After each render, runs quality_gate() to enforce pass/fail thresholds.
    If a render fails the quality gate, the manifest is marked 'failed_quality'
    but the batch continues processing.

    Args:
        project_root: Path to the project directory.
        profile: ProductionProfile with resolution targets.
        config: Parsed config dict (passed to quality_gate for thresholds).

    Returns:
        bool: True if all renders passed quality gate, False if any failed.
    """
    manifest_path = project_root / "manifest.json"
    frames_dir = project_root / "process" / "frames_upscaled"
    audio_path = project_root / "metadata" / "audio_anchor.wav"

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    fps = manifest["fps"]
    expected_frames = manifest["actual_frame_count"]
    outputs = {}
    all_passed = True

    for target in profile.resolution:
        if target == "5k":
            label = "5K"
            output_path = project_root / "export" / f"{project_root.name}_5k_render.mp4"
            scale_filter = []
        else:
            label = "1080p"
            output_path = project_root / "export" / f"{project_root.name}_1080p_render.mp4"
            # -2 preserves aspect ratio, lanczos for sharp downscale
            scale_filter = ["-vf", "scale=-2:1080:flags=lanczos+accurate_rnd+full_chroma_inp"]

        print(f"\n🎬 Stitching {label}: {expected_frames} frames @ {fps} fps...")

        cmd = [
            FFMPEG, "-y",
            "-framerate", fps,
            "-i", str(frames_dir / "frame_%05d.png"),
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
        ] + scale_filter + [
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-fflags", "+genpts",
            "-progress", "pipe:1",
            str(output_path)
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        with tqdm(total=expected_frames, unit="frame", desc=f"Stitching {label}") as pbar:
            last_frame = 0
            for line in process.stdout:
                match = re.search(r"frame=(\d+)", line)
                if match:
                    current_frame = int(match.group(1))
                    pbar.update(current_frame - last_frame)
                    last_frame = current_frame

        process.wait()

        if process.returncode != 0:
            stderr = process.stderr.read()
            print(f"❌ Stitch failed ({label}): {stderr}")
            raise subprocess.CalledProcessError(process.returncode, cmd)

        outputs[label] = str(output_path)
        print(f"✅ {label} render: {output_path}")

        # Quality gate — replaces quality_report()
        passed, report = quality_gate(output_path, config, target_resolution=target)

        if not passed:
            all_passed = False
            print(f"\n⚠️  {project_root.name} marked as FAILED_QUALITY — review output manually.")
            print(f"   Render is preserved at: {output_path}")

    # Update manifest
    if all_passed:
        manifest["status"] = "stitched"
    else:
        manifest["status"] = "failed_quality"
    manifest["outputs"] = outputs
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=4)

    return all_passed


def package_delivery(completed_projects, batch_name=None):
    """Collects all rendered exports and archives them into a 7z file.

    Copies rendered files from individual Projects/*/export/ directories
    into batch_exports/<batch_name>/ and compresses with py7zr.

    Args:
        completed_projects: List of project root Paths that have renders.
        batch_name: Optional name for the archive (defaults to date-stamped).

    Returns:
        Path to the created .7z archive, or None if no files to package.
    """
    import py7zr

    if batch_name is None:
        batch_name = f"{datetime.now().strftime('%Y-%m-%d')}_batch"

    batch_dir = Path("batch_exports") / batch_name
    batch_dir.mkdir(parents=True, exist_ok=True)

    collected = 0
    print(f"\n📦 Packaging batch exports...")

    for project_root in completed_projects:
        export_dir = project_root / "export"
        if not export_dir.exists():
            continue
        for render_file in export_dir.glob("*.mp4"):
            dest = batch_dir / render_file.name
            shutil.copy2(render_file, dest)
            print(f"   Collecting {render_file.name}...")
            collected += 1

    if collected == 0:
        print("   ⚠️  No renders found to package.")
        return None

    archive_path = Path("batch_exports") / f"{batch_name}.7z"
    print(f"   Compressing {collected} render(s) → {archive_path}...")

    with py7zr.SevenZipFile(str(archive_path), 'w') as archive:
        for render_file in batch_dir.glob("*.mp4"):
            archive.write(render_file, render_file.name)

    # Report archive size
    archive_size_mb = archive_path.stat().st_size / (1024 * 1024)
    if archive_size_mb > 1024:
        size_str = f"{archive_size_mb / 1024:.1f} GB"
    else:
        size_str = f"{archive_size_mb:.1f} MB"

    print(f"   ✅ Archive complete: {size_str} → {archive_path}")

    return archive_path


def delivery_report(profile, results, elapsed_seconds):
    """Prints a clear final summary of the completed workflow.

    Args:
        profile: ProductionProfile used for this run.
        results: List of dicts with keys: name, status, outputs, project_root.
        elapsed_seconds: Total wall-clock time for the run.
    """
    # Format elapsed time
    hours = int(elapsed_seconds // 3600)
    minutes = int((elapsed_seconds % 3600) // 60)
    if hours > 0:
        duration_str = f"{hours}h {minutes}m"
    else:
        duration_str = f"{minutes} minutes"

    total = len(results)
    successes = sum(1 for r in results if r["status"] == "stitched")
    failures = sum(1 for r in results if r["status"] == "failed_quality")
    failed_names = [r["name"] for r in results if r["status"] == "failed_quality"]

    print(f"\n{'═' * 50}")

    if profile.batch_mode:
        print("✅ Batch Workflow Complete")
        print(f"{'─' * 50}")
        print(f"   Clips processed:   {successes}/{total}")
        if failures > 0:
            print(f"   Quality failures:  {failures} ({', '.join(failed_names)} — review manually)")
        print(f"   Model:             {profile.model} @ {profile.scale}x")
        print(f"   Resolution:        {', '.join(r.upper() for r in profile.resolution)}")

        if profile.package_output:
            # Archive path is printed by package_delivery() already
            print(f"   📦 See batch_exports/ for archived delivery.")

        # List each clip's output
        print(f"\n   Outputs:")
        for r in results:
            status_icon = "✅" if r["status"] == "stitched" else "⚠️"
            print(f"   {status_icon} {r['name']}:")
            if isinstance(r.get("outputs"), dict):
                for label, path in r["outputs"].items():
                    print(f"      ✨ {label} → {path}")
    else:
        # Single clip
        r = results[0] if results else {}
        status_icon = "✅" if r.get("status") == "stitched" else "⚠️"
        print(f"{status_icon} Workflow Complete")
        print(f"{'─' * 50}")
        print(f"   Clip:       {r.get('name', '?')}")
        print(f"   Model:      {profile.model} @ {profile.scale}x")
        print(f"   Resolution: {', '.join(r_.upper() for r_ in profile.resolution)}")
        if isinstance(r.get("outputs"), dict):
            print(f"   Renders:")
            for label, path in r["outputs"].items():
                print(f"     ✨ {label} → {path}")

    print(f"   Duration:   {duration_str}")
    print(f"{'═' * 50}\n")


def process_queue(config=None):
    """Scans input/ for videos and runs the full pipeline.

    Orchestrates the complete flow: scan → pre-flight → approval →
    configure → process → package → deliver.

    Args:
        config: Optional pre-loaded config dict. If None, loads from default path.
    """
    if config is None:
        config = load_config()
        _sync_globals()

    input_dir = Path("input")

    if not input_dir.exists():
        print("❌ No input/ directory found.")
        return

    videos = list(input_dir.glob("*.mp4")) + list(input_dir.glob("*.mkv"))

    if not videos:
        print("No videos found in input/")
        return

    # Step 1: Build registry of all known processed files by hash
    print("\n🔎 Scanning existing projects...")
    registry = _build_project_registry()

    # Step 2: Pre-scan — hash each input video and classify
    pending = []   # Videos that need processing
    skipped = []   # Videos already fully processed
    resuming = []  # Videos with partial progress

    print(f"\n📋 Found {len(videos)} video(s) in input/:")
    for video in videos:
        video_hash = hash_file(video)
        existing = registry.get(video_hash)

        if existing and existing["status"] == "stitched":
            skipped.append((video, existing))
            outputs = existing["outputs"]
            project_name = existing["project"]
            print(f"   ⏩ {video.name} — already processed (project: {project_name})")
            if isinstance(outputs, dict):
                for label, path in outputs.items():
                    print(f"      ✨ {label} → {path}")
            elif isinstance(outputs, str):
                print(f"      ✨ render → {outputs}")
        elif existing:
            pending.append(video)
            resuming.append(video.name)
            print(f"   🔄 {video.name} — resuming from '{existing['status']}' "
                  f"(project: {existing['project']})")
        else:
            pending.append(video)
            print(f"   🆕 {video.name} — new")

    if not pending:
        print("\n✅ All videos already processed. Nothing to do.")
        return

    # Step 3: Summary
    new_count = len(pending) - len(resuming)
    print(f"\n📦 {len(pending)} video(s) to process "
          f"({new_count} new, {len(resuming)} resuming), "
          f"{len(skipped)} already done.")

    # Step 4: Pre-flight check
    print("\n🛫 Running pre-flight checks...")
    preflight_ok = pre_flight_report(pending, config)

    if not preflight_ok:
        print("\n❌ Pre-flight check failed. Aborting to prevent disk space issues.")
        print("   Free up space or reduce the batch size and try again.")
        return

    # Step 5: User approval for batch jobs
    if len(pending) > 1:
        confirm = input(f"\n   Proceed with {len(pending)} clips? [Y/n]: ").strip()
        if confirm.lower() == 'n':
            print("   Batch aborted by user.")
            return

    # Step 6: Configure production run
    profile = configure_production_run(config, video_count=len(pending))

    # Step 7: Processing loop
    start_time = time.time()
    results = []
    completed_projects = []

    for i, video in enumerate(pending, 1):
        project_root = Path("Projects") / video.stem
        manifest_path = project_root / "manifest.json"

        print(f"\n{'='*50}")
        print(f"📦 Processing clip {i}/{len(pending)}: {video.name}")
        print(f"{'='*50}")

        project_root = init_project(video)

        # Read current status to resume where we left off
        with open(project_root / "manifest.json", 'r') as f:
            status = json.load(f).get("status", "initialized")

        if status == "initialized":
            audit(video, project_root)
            status = "audited"

        if status == "audited":
            anchor(video, project_root)
            explode(video, project_root)
            verify(project_root)
            status = "verified"

        if status == "verified":
            upscale(project_root, profile)
            sift(project_root)
            verify_upscale(project_root)
            status = "upscaled"

        if status == "upscaled":
            all_passed = stitch(project_root, profile, config)

            # Read final manifest for results
            with open(project_root / "manifest.json", 'r') as f:
                final_manifest = json.load(f)

            results.append({
                "name": video.stem,
                "status": final_manifest.get("status", "unknown"),
                "outputs": final_manifest.get("outputs", {}),
                "project_root": project_root,
            })

            if final_manifest.get("status") == "stitched":
                completed_projects.append(project_root)

    # Step 8: Batch packaging
    if profile.package_output and completed_projects:
        package_delivery(completed_projects)

    # Step 9: Delivery report
    elapsed = time.time() - start_time
    delivery_report(profile, results, elapsed)


if __name__ == "__main__":
    config = load_config()
    _sync_globals()
    process_queue(config)