#!/bin/bash

# --- CONFIGURATION ---
APP_PATH="$HOME/upscayl-2.15.0-linux.AppImage"

# --- STEP 1: FIND VIDEO ---
VIDEO=$(ls *.mp4 *.mkv *.avi *.mov 2>/dev/null | head -n 1)

if [ -z "$VIDEO" ]; then
    echo "❌ No video file found in this folder."
    exit 1
fi

echo "🎬 Found video: $VIDEO"

# --- STEP 2: PREP FOLDERS ---
rm -rf frames_raw frames_upscaled
mkdir -p frames_raw
mkdir -p frames_upscaled

# --- STEP 3: EXPLODE ---
echo "💥 Blowing video into images..."
# Added -pix_fmt rgb24 for better quality during upscale
ffmpeg -i "$VIDEO" -pix_fmt rgb24 "frames_raw/frame_%08d.png" -hide_banner -loglevel error

echo "✅ Extraction complete."
echo "---------------------------------------------------"
echo "📂 Input Folder:  $(pwd)/frames_raw"
echo "📂 Output Folder: $(pwd)/frames_upscaled"
echo "---------------------------------------------------"

# --- STEP 4: LAUNCH GUI ---
if [ -f "$APP_PATH" ]; then
    echo "🚀 Launching Upscayl..."
    "$APP_PATH" --no-sandbox
else
    echo "❌ Error: Could not find the AppImage at $APP_PATH"
fi