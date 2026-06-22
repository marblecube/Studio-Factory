#!/bin/bash

# --- 1. Count Images ---
echo "🔍 Counting PNG files..."
IMG_COUNT=$(ls -1 *.png 2>/dev/null | wc -l)

if [ "$IMG_COUNT" -eq 0 ]; then
    echo "❌ ERROR: No PNG images found!"
    exit 1
fi
echo "✅ Found $IMG_COUNT images."

# --- 2. Dynamic Video Hunt ---
VIDEO=""
for dir in "." ".." "../.." "../../.." "$HOME"; do
    FOUND=$(find "$dir" -maxdepth 1 -type f \( -name "*.mp4" -o -name "*.mkv" -o -name "*.mov" -o -name "*.avi" \) | head -n 1)
    if [ -n "$FOUND" ]; then
        VIDEO="$FOUND"
        break
    fi
done

if [ -z "$VIDEO" ]; then
    echo "⚠️  No original video found. Defaulting to 30 FPS."
    FPS="30"
    AUDIO_OPTS=""
else
    echo "🎬 Found reference video: $VIDEO"
    
    # --- 3. Robust FPS Detector ---
    # We use ffprobe to get the exact fractional rate to prevent speed-up bugs
    FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$VIDEO")
    
    if [ -n "$FPS" ]; then
        echo "⏱  Reference Rate: $FPS"
    else
        FPS="30"
        echo "⚠️  Could not read framerate. Defaulting to 30."
    fi

    AUDIO_OPTS="-i $VIDEO -map 0:v:0 -map 1:a:0?"
fi

# --- 4. Stitching ---
echo "🔨 Stitching..."

# We use -framerate before the input to ensure timing matches the source video
ffmpeg -framerate "$FPS" \
-pattern_type glob -i "*.png" \
$AUDIO_OPTS \
-c:v libx264 -pix_fmt yuv420p \
-c:a copy \
-shortest \
"render_$(date +%s).mp4"

echo "✅ DONE."