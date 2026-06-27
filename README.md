# Studio-Factory

A fully autonomous, CLI-driven video upscaling pipeline. Drop videos into `input/`, run the orchestrator, and get AI-upscaled renders with preserved audio sync — with pre-flight safety checks, retry resilience, and automated batch packaging.

## What It Does

```
Source Video (704×1280) → Explode → AI Upscale → Stitch → Final Render (2816×5120)
```

The pipeline runs in phases, each tracked in a `manifest.json` per project so you can resume if interrupted:

| Phase | Function | Description |
|-------|----------|-------------|
| 1. Init | `init_project()` | Creates standardized project directory tree |
| 2. Audit | `audit()` | Extracts source metadata, frame count, and FPS via ffprobe |
| 3. Anchor | `anchor()` | Locks the audio stream as a WAV before any video processing |
| 4. Explode | `explode()` | Extracts every frame as a lossless PNG |
| 5. Verify | `verify()` | Confirms extracted frame count matches source |
| 6. Upscale | `upscale()` | AI upscales all frames headlessly via upscayl-bin (GPU), with retry on failure |
| 6b. Sift | `sift()` | Flattens any nested subdirectories from the upscaler |
| 6c. Verify | `verify_upscale()` | Confirms upscaled frame count matches raw |
| 7. Stitch | `stitch()` | Recombines upscaled frames + audio into final render(s) + quality gate |

## Requirements

### System Dependencies

- **Python 3.10+**
- **FFmpeg / FFprobe** — usually at `/usr/bin/ffmpeg`
- **Vulkan-compatible GPU** — required for upscayl-bin

### Python Dependencies

```bash
pip install -r requirements.txt
```

Includes: `tqdm`, `py7zr` (for batch archive packaging), `pytest`.

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

The orchestrator detects which models are installed and only presents those at runtime. If fewer than 7 are found, it prints a download link for the missing ones.

| Model | Best For |
|-------|----------|
| `upscayl-standard-4x` | General purpose (default) |
| `upscayl-lite-4x` | Faster, lower VRAM |
| `high-fidelity-4x` | Maximum detail preservation |
| `ultrasharp-4x` | Sharp edges and text |
| `ultramix-balanced-4x` | Balanced quality/speed |
| `digital-art-4x` | Illustrations and digital art |
| `remacri-4x` | Photorealistic content |

## Usage

```bash
# 1. Drop your video(s) into the input folder
cp my_video.mp4 input/

# 2. Run the pipeline
python3 orchestrator.py
```

### What Happens At Runtime

```
🔎 Scanning existing projects...
📋 Found 3 video(s): 2 new, 1 resuming, 0 already done.

╔══════════════════════════════════════════════╗
║            PRE-FLIGHT REPORT                 ║
╠══════════════════════════════════════════════╣
║  📋 Clips:          3                        ║
║  🎞️  Total frames:   12,600                  ║
║  💾 Est. footprint:  84.0 GB (+ 20% margin)  ║
║  💿 Disk free:       380.0 GB                ║
║  ⏱️  Est. duration:   ~2h 5m                  ║
║  Status:            ✅ GO                     ║
╚══════════════════════════════════════════════╝

   Proceed with 3 clips? [Y/n]:

🎛️  Production Profile
══════════════════════════════════════════

📐 Resolution:
  [1] 5K    — Native upscaled resolution (archival/master)
  [2] 1080p — Downscaled for YouTube delivery
  [3] Both  — Render 5K master + 1080p delivery copy

🤖 Model (2 of 7 installed):
  [1] UltraSharp — Maximum detail. ★
  [2] Standard — Balanced speed and quality.

🎚️  Encoding Quality (CRF):
   CRF controls the trade-off between visual quality and file size.
   Lower number = better quality, larger file.
   Higher number = more compression, smaller file.

  [1] Archive (CRF 16)  — Near-lossless. Best for long-term storage. Largest files.
  [2] Production (CRF 18)  — Excellent quality. Recommended for most delivery work. ★
  [3] Streaming (CRF 23)  — Good quality. Noticeably smaller files, suitable for web.
  [4] Draft (CRF 28)  — Lower quality. Fast previews and review cuts only.

📦 Packaging (3 clips detected):
  Archive all exports to batch_exports/ on completion? [Y/n]
```

The orchestrator then:
1. **Fingerprints** each video (SHA-256) — skips duplicates even if renamed, and verifies output files actually exist on disk before trusting a prior result
2. **Resumes** interrupted projects from the last completed phase — including `failed_quality`, which re-runs only the stitch + quality gate without repeating the GPU upscale
3. **Retries** the upscale phase automatically on failure (exponential backoff: 5s → 10s → 20s)
4. **Quality gates** each render — checks bitrate and file size against configurable thresholds
5. **Archives** all renders to `batch_exports/<date>_batch.7z` if packaging was requested
6. **Encoding quality** is user-selectable per run (Archive / Production / Streaming / Draft), each preset maps to a CRF value passed to ffmpeg

### Outputs

**Individual job** renders land in `Projects/<video_name>/export/`:
- `<video_name>_5k_render.mp4`
- `<video_name>_1080p_render.mp4`

**Batch job** renders are copied to `batch_exports/<date>_batch/` after processing, and an archive is created:
- `batch_exports/2026-06-27_batch/clip_a_5k_render.mp4`
- `batch_exports/2026-06-27_batch.7z`

The delivery report for batch runs shows the `batch_exports/` paths as the canonical delivery location.

## Project Structure

```
Studio-Factory/              ← Logic repo (version controlled)
├── orchestrator.py          ← Pipeline brain
├── config_manager.py        ← ProductionProfile, model discovery, config loading
├── validator.py             ← Pre-flight disk checks, quality gate
├── config/
│   └── config.json          ← Tool paths, model defaults, quality thresholds
├── tools/
│   └── upscayl/             ← Headless upscaler binary + models
├── input/                   ← Drop source videos here
├── logs/                    ← Per-run log files (YYYY-MM-DD_HH-MM-SS_run.log)
├── batch_exports/           ← Delivery copies + 7z archives of completed batch runs
├── templates/               ← Project directory templates
└── Projects/                ← Output (one folder per video)
    └── <video_name>/
        ├── manifest.json        ← Central metadata + state + source hash
        ├── process/
        │   ├── frames_raw/      ← Extracted PNG frames
        │   └── frames_upscaled/ ← AI-upscaled PNG frames
        ├── export/
        │   ├── <name>_5k_render.mp4   ← 5K master (if selected)
        │   └── <name>_1080p_render.mp4 ← 1080p delivery (if selected)
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
  "encode_crf": 18,
  "models": {
    "upscayl-standard-4x": "Standard — Balanced speed and quality. Good default.",
    "ultrasharp-4x": "UltraSharp — Maximum detail. Best for live-action footage."
  },
  "quality_thresholds": {
    "min_bitrate_mbps_1080p": 2.0,
    "min_bitrate_mbps_5k": 8.0,
    "min_file_size_mb": 1.0
  }
}
```

**`encode_crf`** — default CRF value pre-selected in the encoding quality prompt. The ★ marker and Enter-key default both track this value. Must be one of the four named preset values (16, 18, 23, 28) for the default selection to be meaningful; other values fall back to Production (18).

**`models`** — descriptions shown in the production profile menu. Any model on disk but not in this list gets a generic label. Missing this block falls back to the built-in descriptions.

**`quality_thresholds`** — bitrate floors enforced after each render. Lower these if you're doing intentional low-bitrate or stylized encodes. Missing this block falls back to the defaults shown above.

## Testing

```bash
pytest tests/ -v
```

All external tools (ffmpeg, ffprobe, upscayl) are mocked — no GPU or system dependencies needed.

| Module | Tests | Coverage |
|--------|-------|----------|
| `test_config_manager.py` | 15 | ProductionProfile, load_config, model discovery, configure_production_run, encoding quality presets |
| `test_validator.py` | 13 | estimate_batch_requirements, check_disk_space, pre_flight_report, quality_gate |
| `test_pipeline.py` | 17 | Full run, duplicate detection, resume, retry logic, quality gate failure, CRF passthrough, batch archive |
| `test_strategy.py` | 4 | Resolution selection via configure_production_run |
| `test_quality_report.py` | 3 | quality_gate output parsing, missing bitrate, exception handling |
| `test_init.py` | 4 | Directory creation, manifest, idempotency, hash backfill |
| `test_audit.py` | 3 | Manifest enrichment, ffprobe calls, failure handling |
| `test_verify.py` | 4 | Pass/fail for raw and upscaled frame verification |
| `test_sift.py` | 3 | Flattening nested dirs, no-op, multiple subdirs |

**Total: 76 tests, 76 passing.**

## Credits

Built with AI pair-programming:

- **[Gemini 3.1 Flash-Lite](https://deepmind.google/technologies/gemini/)** — Design, architecture, and code generation
- **[Claude Sonnet 4.6](https://www.anthropic.com/claude)** — Code review, debugging, and pipeline hardening

## License

MIT
