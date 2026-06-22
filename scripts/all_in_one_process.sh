#!/bin/bash
# --- CONFIGURATION ---
RIFE_BIN="$HOME/rife-ncnn-vulkan-20221029-ubuntu/rife-ncnn-vulkan"
UPSCAYL_PATH="$HOME/upscayl-2.15.0-linux.AppImage"

# --- 1. FIND INPUT ---
VIDEO=$(ls *.mp4 *.mkv *.avi *.mov 2>/dev/null | head -n 1)
if [ -z "$VIDEO" ]; then echo "❌ No video found!"; exit 1; fi
BASENAME=$(basename "$VIDEO" | cut -d. -f1)
WORK_DIR="WORK_${BASENAME}"

# Create all needed folders including original_frames
mkdir -p "$WORK_DIR/original_frames" "$WORK_DIR/interpolated" "$WORK_DIR/upscaled"

# --- 2. GET FPS ---
FPS_STRING=$(ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of default=noprint_wrappers=1:nokey=1 "$VIDEO")
FPS=$(echo "scale=2; $FPS_STRING" | bc | cut -d. -f1)
if [ -z "$FPS" ] || [ "$FPS" -eq 0 ]; then FPS=30; fi
echo "🎬 Found $VIDEO ($FPS original fps)"

# --- 3. RIFE INTERPOLATION ---
echo "🧠 Extracting frames from video..."
ffmpeg -i "$VIDEO" -pix_fmt rgb24 "$WORK_DIR/original_frames/%08d.png" -hide_banner -loglevel error

echo "✨ Running RIFE AI Interpolation..."
"$RIFE_BIN" -i "$WORK_DIR/original_frames" -o "$WORK_DIR/interpolated" -m rife-v4

INT_COUNT=$(ls -1 "$WORK_DIR/interpolated" | wc -l)
echo "✅ Done. You now have $INT_COUNT smoothed frames."

# --- 4. UPSCAYL (MANUAL GUI STEP) ---
echo "-------------------------------------------------------"
echo "🚀 Launching Upscayl..."
echo "👉 INPUT FOLDER:  $(pwd)/$WORK_DIR/interpolated"
echo "👉 OUTPUT FOLDER: $(pwd)/$WORK_DIR/upscaled"
echo "-------------------------------------------------------"
"$UPSCAYL_PATH" --no-sandbox
echo "-------------------------------------------------------"
read -p "⏸️  Wait! Did Upscayl finish? Press [ENTER] to stitch."
echo "-------------------------------------------------------"

# --- 5. STITCH FINAL VIDEO ---
echo "🔨 Stitching final render..."
IMG_PATH=$(find "$WORK_DIR/upscaled" -name "*.png" | head -n 1)
IMG_DIR=$(dirname "$IMG_PATH")

FINAL_FPS=$FPS
echo "🚀 Target Playback Rate: $FINAL_FPS fps"

ffmpeg -framerate "$FINAL_FPS" -pattern_type glob -i "$IMG_DIR/*.png" \
    -i "$VIDEO" -map 0:v:0 -map 1:a? \
    -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -c:a copy \
    "${BASENAME}_ULTRA.mp4"

echo "✅ ALL DONE: ${BASENAME}_ULTRA.mp4"