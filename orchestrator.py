import json
import subprocess
from pathlib import Path
import os
import shutil

# Load config
config_path = Path("config/config.json")
with open(config_path, 'r') as f:
    config = json.load(f)

FFMPEG = config['tools']['ffmpeg']
FFPROBE = config['tools'].get('ffprobe', 'ffprobe')  # Falls back to PATH if not in config

def audit(video_path, project_folder):
    """Logs source metadata and frame count for quality comparison."""
    print(f"🔍 Auditing source: {video_path.name}")
    
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
    
    try:
        # Get metadata
        res_meta = subprocess.run(cmd_meta, capture_output=True, text=True)
        metadata = json.loads(res_meta.stdout)
        
        # Get frame count
        res_count = subprocess.run(cmd_count, capture_output=True, text=True)
        frame_count = res_count.stdout.strip()
        
        # Save to audit_report.json
        report_path = Path(project_folder) / "audit_report.json"
        audit_data = {
            "metadata": metadata,
            "expected_frame_count": frame_count
        }
        
        with open(report_path, "w") as f:
            json.dump(audit_data, f, indent=4)
            
        print(f"✅ Audit report saved: {report_path} (Expected frames: {frame_count})")
        
    except Exception as e:
        print(f"❌ Audit failed: {e}")

def anchor(video_path, output_dir):
    """Extracts audio from the video and saves it to the output directory."""
    video_path = Path(video_path)
    output_audio = Path(output_dir) / f"{video_path.stem}_audio.wav"
    
    print(f"⚓ Anchoring audio from {video_path.name}...")
    
    cmd = [FFMPEG, "-y", "-i", str(video_path), "-vn", "-acodec", "pcm_s16le", str(output_audio)]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✅ Audio anchored: {output_audio}")
        return output_audio
    except subprocess.CalledProcessError as e:
        print(f"❌ Audio extraction failed: {e.stderr.decode()}")
        return None

def explode(video_path, project_folder):
    """Explodes the video into individual PNG frames in a raw_frames folder."""
    video_path = Path(video_path)
    frames_dir = Path(project_folder) / "raw_frames"
    frames_dir.mkdir(exist_ok=True)
    
    print(f"💥 Exploding {video_path.name} into frames...")
    
    # ffmpeg command to extract frames as pngs
    cmd = [
        FFMPEG, "-y", "-i", str(video_path), 
        "-q:v", "2", 
        str(frames_dir / "frame_%05d.png")
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✅ Raw frames extracted to: {frames_dir}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Frame extraction failed: {e.stderr.decode()}")

def process_queue():
    input_dir = Path("input")
    working_base = Path("working")
    
    working_base.mkdir(exist_ok=True)
    
    videos = list(input_dir.glob("*.mp4")) + list(input_dir.glob("*.mkv"))
    
    if not videos:
        print("No videos found in input/")
        return

    for video in videos:
        project_folder = working_base / video.stem
        project_folder.mkdir(exist_ok=True)
        
        print(f"Processing: {video.name}")
        audit(video, project_folder)
        anchor(video, project_folder)
        explode(video, project_folder)

if __name__ == "__main__":
    process_queue()