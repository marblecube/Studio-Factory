import json
import subprocess
from pathlib import Path
from tqdm import tqdm
import re

# Load config
config_path = Path("config/config.json")
with open(config_path, 'r') as f:
    config = json.load(f)

FFMPEG = config['tools']['ffmpeg']
FFPROBE = config['tools']['ffprobe']


def init_project(video_path):
    """Phase 1: Initializes project structure and manifest.json."""
    project_root = Path("Projects") / video_path.stem
    structure = ["source", "process/frames_raw", "export", "logs", "metadata"]

    for sub in structure:
        (project_root / sub).mkdir(parents=True, exist_ok=True)

    manifest_path = project_root / "manifest.json"
    if not manifest_path.exists():
        manifest = {"name": video_path.stem, "status": "initialized"}
        with open(manifest_path, "w") as f:
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

    for video in videos:
        project_root = Path("Projects") / video.stem
        manifest_path = project_root / "manifest.json"

        # Smart skip: check if already verified
        if manifest_path.exists():
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            if manifest.get("status") == "verified":
                print(f"⏩ Skipping {video.name}: Already processed and verified.")
                continue

        print(f"\n{'='*50}")
        print(f"📦 Processing: {video.name}")
        print(f"{'='*50}")

        project_root = init_project(video)
        audit(video, project_root)
        anchor(video, project_root)
        explode(video, project_root)
        verify(project_root)


if __name__ == "__main__":
    process_queue()