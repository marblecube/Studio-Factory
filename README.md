# Studio-Factory

A fully autonomous, CLI-driven video upscaling pipeline. Drop a video into `input/`, run the orchestrator, and get an AI-upscaled render with preserved audio sync.

## What It Does

```
Source Video (704×1280) → Explode → AI Upscale → Stitch → Final Render (2816×5120)
```

The pipeline runs in 6 phases, each tracked in a `manifest.json` so you can resume if interrupted:

| Phase | Function | Description |
|-------|----------|-------------|
| 1. Init | `init_project()` | Creates standardized project directory tree |
| 2. Audit | `audit()` | Extracts source metadata, frame count, and FPS via ffprobe |
| 3. Anchor | `anchor()` | Locks the audio stream as a WAV before any video processing |
| 4. Explode | `explode()` | Extracts every frame as a lossless PNG |
| 5. Verify | `verify()` | Confirms extracted frame count matches source |
| 6. Upscale | `upscale()` | AI upscales all frames headlessly via upscayl-bin (GPU) |
| 6b. Sift | `sift()` | Flattens any nested subdirectories from the upscaler |
| 6c. Verify | `verify_upscale()` | Confirms upscaled frame count matches raw |
| 7. Stitch | `stitch()` | Recombines upscaled frames + audio into final render |

## Requirements

### System Dependencies   

- **Python 3.10+**
- **FFmpeg / FFprobe** — usually at `/usr/bin/ffmpeg`
- **Vulkan-compatible GPU** — required for upscayl-bin

### Python Dependencies

```bash
pip install -r requirements.txt
```

### Upscayl CLI Setup

The upscaler runs headlessly using `upscayl-bin`, extracted from the Upscayl AppImage:

```bash
# Download the AppImage
wget -O /tmp/upscayl.AppImage \
  https://github.com/upscayl/upscayl/releases/download/v2.15.0/upscayl-2.15.0-linux.AppImage

# Extract the CLI binary and models
chmod +x /tmp/upscayl.AppImage
cd /tmp && ./upscayl.AppImage --appimage-extract

# Copy into Studio-Factory
mkdir -p ~/Studio-Factory/tools/upscayl
cp squashfs-root/resources/bin/upscayl-bin ~/Studio-Factory/tools/upscayl/
cp -r squashfs-root/resources/models ~/Studio-Factory/tools/upscayl/

# Verify the binary is executable
ls -l ~/Studio-Factory/tools/upscayl/upscayl-bin

# Cleanup
rm -rf /tmp/squashfs-root /tmp/upscayl.AppImage
```

### Available Upscale Models

| Model | Best For |
|-------|----------|
| `upscayl-standard-4x` | General purpose (default) |
| `upscayl-lite-4x` | Faster, lower VRAM |
| `high-fidelity-4x` | Maximum detail preservation |
| `ultrasharp-4x` | Sharp edges and text |
| `ultramix-balanced-4x` | Balanced quality/speed |
| `digital-art-4x` | Illustrations and digital art |
| `remacri-4x` | Photorealistic content |

Change the model in `config/config.json` → `"default_model"`.

### Render Strategy

After scanning `input/`, the orchestrator prompts you to choose an output resolution:

| Option | Output | Use Case |
|--------|--------|----------|
| **5K** | Native upscaled resolution (e.g. 2816×5120) | Archival / master copy |
| **1080p** | Downscaled via lanczos filter | YouTube / delivery |
| **Both** | 5K master + 1080p delivery copy | Full production workflow |

The 5K resolution is the natural result of the 4x upscale (e.g. 1280p × 4 = 5120p). It is not a separate upscale model — all models listed above are 4x scalers.

## Usage

```bash
# 1. Drop your video into the input folder
cp my_video.mp4 input/

# 2. Run the pipeline
python3 orchestrator.py
```

The orchestrator will:
1. **Fingerprint** each video (SHA-256) and check if it's already been processed
2. **Skip** duplicates — even if the file has been renamed
3. **Resume** interrupted projects from the last completed phase
4. **Prompt** for render strategy (5K / 1080p / Both) before processing

Outputs land in `Projects/<video_name>/export/`:
- `<video_name>_5k_render.mp4`
- `<video_name>_1080p_render.mp4`

## Project Structure

```
Studio-Factory/              ← Logic repo (version controlled)
├── orchestrator.py          ← Pipeline brain
├── config/
│   └── config.json          ← Tool paths, model, scale settings
├── tools/
│   └── upscayl/             ← Headless upscaler binary + models
├── input/                   ← Drop source videos here
├── templates/               ← Project directory templates
└── Projects/                ← Output (one folder per video)
    └── <video_name>/
        ├── manifest.json    ← Central metadata + state tracking + source hash
        ├── process/
        │   ├── frames_raw/      ← Extracted PNG frames
        │   └── frames_upscaled/ ← AI-upscaled PNG frames
        ├── export/
        │   ├── <name>_5k_render.mp4   ← 5K master (if selected)
        │   └── <name>_1080p_render.mp4 ← 1080p delivery (if selected)
        ├── logs/
        └── metadata/
            └── audio_anchor.wav ← Locked audio stream
```

## Configuration

Edit `config/config.json`:

```json
{
  "tools": {
    "ffmpeg": "/usr/bin/ffmpeg",
    "ffprobe": "/usr/bin/ffprobe",
    "upscayl_bin": "tools/upscayl/upscayl-bin",
    "upscayl_models": "tools/upscayl/models"
  },
  "default_model": "upscayl-standard-4x",
  "default_scale": 4,
  "log_level": "INFO"
}
```

## Testing

Run the full test suite with:

```bash
pytest tests/ -v
```

All external tools (ffmpeg, ffprobe, upscayl) are mocked — no GPU or system dependencies needed to run tests.

| Module | Tests | Coverage |
|--------|-------|----------|
| `test_init.py` | 4 | Project directory creation, manifest, idempotency, hash backfill |
| `test_audit.py` | 3 | Manifest enrichment, ffprobe calls, failure handling |
| `test_verify.py` | 4 | Pass/fail for raw and upscaled frame verification |
| `test_sift.py` | 3 | Flattening nested dirs, no-op, multiple subdirs |
| `test_strategy.py` | 4 | All render choices + invalid input retry |
| `test_quality_report.py` | 3 | Output parsing, missing bitrate, exception handling |
| `test_pipeline.py` | 9 | Full run, duplicate detection, resume, legacy support, hash identity |

## Credits

Built with AI pair-programming:

- **[Gemini 3.1 Flash-Lite](https://deepmind.google/technologies/gemini/)** — Design, architecture, and code generation
- **[Claude Opus 4.6](https://www.anthropic.com/claude)** — Code review, debugging, and pipeline hardening

## License

MIT
