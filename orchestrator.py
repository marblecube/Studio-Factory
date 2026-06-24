import json
import hashlib
import subprocess
from pathlib import Path
from tqdm import tqdm
import re

# Module-level config (populated by load_config)
FFMPEG = None
FFPROBE = None
UPSCAYL_BIN = None
UPSCAYL_MODELS = None
DEFAULT_MODEL = None
DEFAULT_SCALE = None


def load_config(config_path=None):
    """Loads tool paths and defaults from config.json into module globals."""
    global FFMPEG, FFPROBE, UPSCAYL_BIN, UPSCAYL_MODELS, DEFAULT_MODEL, DEFAULT_SCALE
    if config_path is None:
        config_path = Path("config/config.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
    FFMPEG = config['tools']['ffmpeg']
    FFPROBE = config['tools']['ffprobe']
    UPSCAYL_BIN = Path(config['tools']['upscayl_bin'])
    UPSCAYL_MODELS = Path(config['tools']['upscayl_models'])
    DEFAULT_MODEL = config.get('default_model', 'upscayl-standard-4x')
    DEFAULT_SCALE = config.get('default_scale', 4)


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


def strategy_selector():
    """Prompts the user for render output resolution before processing."""
    print("\n🎛️  Render Strategy")
    print("=" * 40)
    print("  [1] 5K   — Native upscaled resolution (archival/master)")
    print("  [2] 1080p — Downscaled for YouTube delivery")
    print("  [3] Both  — Render 5K master + 1080p delivery copy")
    print("=" * 40)

    while True:
        choice = input("Select render strategy [1/2/3]: ").strip()
        if choice == "1":
            return ["5k"]
        elif choice == "2":
            return ["1080p"]
        elif choice == "3":
            return ["5k", "1080p"]
        else:
            print("  ⚠️  Invalid choice. Enter 1, 2, or 3.")


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


def process_queue():
    """Scans input/ for videos and runs the full pipeline."""
    input_dir = Path("input")

    if not input_dir.exists():
        print("❌ No input/ directory found.")
        return

    videos = list(input_dir.glob("*.mp4")) + list(input_dir.glob("*.mkv"))

    if not videos:
        print("No videos found in input/")
        return

    # Build registry of all known processed files by hash
    print("\n🔎 Scanning existing projects...")
    registry = _build_project_registry()

    # Pre-scan: hash each input video and classify as new, resumable, or done
    pending = []   # Videos that need processing
    skipped = []   # Videos already fully processed

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
            print(f"   🔄 {video.name} — resuming from '{existing['status']}' (project: {existing['project']})")
        else:
            pending.append(video)
            print(f"   🆕 {video.name} — new")

    if not pending:
        print("\n✅ All videos already processed. Nothing to do.")
        return

    print(f"\n📦 {len(pending)} video(s) to process, {len(skipped)} already done.")
    render_targets = strategy_selector()

    for video in pending:
        project_root = Path("Projects") / video.stem
        manifest_path = project_root / "manifest.json"

        print(f"\n{'='*50}")
        print(f"📦 Processing: {video.name}")
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
            upscale(project_root)
            sift(project_root)
            verify_upscale(project_root)
            status = "upscaled"

        if status == "upscaled":
            stitch(project_root, render_targets)

def upscale(project_root):
    """Phase 4: Upscale raw frames using Upscayl CLI (headless)."""
    input_dir = project_root / "process" / "frames_raw"
    output_dir = project_root / "process" / "frames_upscaled"
    output_dir.mkdir(exist_ok=True)
    manifest_path = project_root / "manifest.json"

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    total_frames = manifest.get("actual_frame_count", 0)

    print(f"🚀 Upscaling {total_frames} frames with {DEFAULT_MODEL} @ {DEFAULT_SCALE}x...")

    cmd = [
        str(UPSCAYL_BIN),
        "-i", str(input_dir),
        "-o", str(output_dir),
        "-m", str(UPSCAYL_MODELS),
        "-n", DEFAULT_MODEL,
        "-s", str(DEFAULT_SCALE),
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


def stitch(project_root, render_targets):
    """Phase 5: Recombines upscaled frames + audio anchor into final render(s)."""
    manifest_path = project_root / "manifest.json"
    frames_dir = project_root / "process" / "frames_upscaled"
    audio_path = project_root / "metadata" / "audio_anchor.wav"

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    fps = manifest["fps"]
    expected_frames = manifest["actual_frame_count"]
    outputs = {}

    for target in render_targets:
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
        quality_report(output_path)

    # Update manifest with all outputs
    manifest["status"] = "stitched"
    manifest["outputs"] = outputs
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=4)


def quality_report(video_path):
    """Runs ffprobe on a rendered file and prints the quality summary."""
    cmd = [
        FFPROBE, "-v", "error", "-hide_banner",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,bit_rate",
        "-of", "default=noprint_wrappers=1",
        str(video_path)
    ]

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

        # Convert bitrate to Mbps for readability
        try:
            bitrate_mbps = f"{int(bitrate_raw) / 1_000_000:.1f} Mbps"
        except (ValueError, TypeError):
            bitrate_mbps = "N/A"

        print(f"\n   📊 Quality Report: {video_path.name}")
        print(f"   ├── Codec:      {codec}")
        print(f"   ├── Resolution: {width}×{height}")
        print(f"   ├── FPS:        {fps}")
        print(f"   └── Bitrate:    {bitrate_mbps}")

    except Exception as e:
        print(f"   ⚠️  Quality report failed: {e}")


if __name__ == "__main__":
    load_config()
    process_queue()