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

def anchor(video_path, output_dir):
    """Extracts audio from the video and saves it to the output directory."""
    video_path = Path(video_path)
    output_audio = Path(output_dir) / f"{video_path.stem}_audio.wav"
    
    print(f"⚓ Anchoring audio from {video_path.name}...")
    
    cmd = [FFMPEG, "-i", str(video_path), "-vn", "-acodec", "pcm_s16le", str(output_audio)]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✅ Audio anchored: {output_audio}")
        return output_audio
    except subprocess.CalledProcessError as e:
        print(f"❌ Audio extraction failed: {e.stderr.decode()}")
        return None

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
        anchor(video, project_folder)

if __name__ == "__main__":
    process_queue()