"""Configuration management and production profile for Studio Factory.

Handles config loading, model discovery, and interactive production run setup.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


# Module-level tool paths (populated by load_config)
FFMPEG = None
FFPROBE = None
UPSCAYL_BIN = None
UPSCAYL_MODELS = None
DEFAULT_MODEL = None
DEFAULT_SCALE = None

# Known models with descriptions — used when config doesn't have a models block
_KNOWN_MODELS = {
    "upscayl-standard-4x": "Standard — Balanced speed and quality. Good default.",
    "ultrasharp-4x": "UltraSharp — Maximum detail. Best for live-action footage.",
    "ultramix-balanced-4x": "UltraMix — Balanced sharpness/smoothness. Versatile.",
    "remacri-4x": "Remacri — Smooth, natural look. Good for portraits.",
    "digital-art-4x": "Digital Art — Optimized for illustrations and digital art.",
    "high-fidelity-4x": "High Fidelity — Faithful reproduction with minimal artifacts.",
    "upscayl-lite-4x": "Lite — Fastest. Lower quality, good for previews/drafts.",
}

_MODELS_DOWNLOAD_URL = "https://github.com/upscayl/upscayl/tree/main/models"


@dataclass
class ProductionProfile:
    """Consolidated settings for a production run.

    Carries resolution, model, encoding quality, retry, and packaging
    preferences through the entire pipeline so functions don't need a
    dozen arguments.
    """
    resolution: list = field(default_factory=lambda: ["5k"])
    model: str = "upscayl-standard-4x"
    scale: int = 4
    package_output: bool = False
    retry_limit: int = 3
    batch_mode: bool = False
    encode_crf: int = 18


# Encoding quality presets: (label, CRF, description)
# CRF (Constant Rate Factor) controls the quality-vs-filesize trade-off.
# Lower CRF = higher quality + larger file. Range: 0 (lossless) to 51 (worst).
_ENCODE_PRESETS = [
    ("Archive",    16, "Near-lossless. Best for long-term storage. Largest files."),
    ("Production", 18, "Excellent quality. Recommended for most delivery work."),
    ("Streaming",  23, "Good quality. Noticeably smaller files, suitable for web."),
    ("Draft",      28, "Lower quality. Fast previews and review cuts only."),
]


def load_config(config_path=None):
    """Loads tool paths and defaults from config.json.

    Populates module-level globals and returns the full config dict
    so callers can access extended fields (models, thresholds, etc).
    """
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

    return config


def get_available_models(config):
    """Discovers installed models and returns them with descriptions.

    Scans the upscayl_models directory for .param files to determine
    which models are actually installed. Cross-references with known
    descriptions from config or the built-in map.

    Returns:
        tuple: (installed_models, total_known) where installed_models is
               a list of (model_name, description) tuples, sorted by name.
    """
    models_dir = Path(config['tools']['upscayl_models'])
    descriptions = config.get('models', _KNOWN_MODELS)

    # Find what's actually on disk
    installed_names = set()
    if models_dir.exists():
        for param_file in models_dir.glob("*.param"):
            installed_names.add(param_file.stem)

    # Build list of installed models with descriptions
    installed = []
    for name in sorted(installed_names):
        desc = descriptions.get(name, f"{name} — No description available.")
        installed.append((name, desc))

    total_known = len(descriptions)

    return installed, total_known


def configure_production_run(config, video_count):
    """Interactive prompt to configure a production run.

    Asks the user for resolution, model, and (for batches) packaging
    preference. Returns a fully populated ProductionProfile.

    Args:
        config: The parsed config dict from load_config().
        video_count: Number of videos to process (affects batch detection).

    Returns:
        ProductionProfile with all settings for this run.
    """
    batch_mode = video_count > 1

    print("\n🎛️  Production Profile")
    print("═" * 50)

    # --- Resolution ---
    print("\n📐 Resolution:")
    print("  [1] 5K    — Native upscaled resolution (archival/master)")
    print("  [2] 1080p — Downscaled for YouTube delivery")
    print("  [3] Both  — Render 5K master + 1080p delivery copy")

    while True:
        choice = input("\n  Select resolution [1/2/3]: ").strip()
        if choice == "1":
            resolution = ["5k"]
            break
        elif choice == "2":
            resolution = ["1080p"]
            break
        elif choice == "3":
            resolution = ["5k", "1080p"]
            break
        else:
            print("  ⚠️  Invalid choice. Enter 1, 2, or 3.")

    # --- Model ---
    installed, total_known = get_available_models(config)

    if not installed:
        print("\n⚠️  No models found on disk. Using default: "
              f"{config.get('default_model', 'upscayl-standard-4x')}")
        model = config.get('default_model', 'upscayl-standard-4x')
    elif len(installed) == 1:
        # Only one model — auto-select, don't waste the user's time
        model = installed[0][0]
        print(f"\n🤖 Model: {installed[0][1]} (only model installed — auto-selected)")
        if total_known > 1:
            missing_count = total_known - 1
            print(f"\n  ℹ️  {missing_count} additional model(s) available at:")
            print(f"     {_MODELS_DOWNLOAD_URL}")
    else:
        print(f"\n🤖 Model ({len(installed)} of {total_known} installed):")
        for i, (name, desc) in enumerate(installed, 1):
            marker = " ★" if name == config.get('default_model') else ""
            print(f"  [{i}] {desc}{marker}")

        if len(installed) < total_known:
            missing_count = total_known - len(installed)
            print(f"\n  ℹ️  {missing_count} additional model(s) available at:")
            print(f"     {_MODELS_DOWNLOAD_URL}")

        while True:
            default_idx = None
            for i, (name, _) in enumerate(installed, 1):
                if name == config.get('default_model'):
                    default_idx = i
                    break

            prompt = f"\n  Select model [1-{len(installed)}]"
            if default_idx:
                prompt += f" (default: {default_idx})"
            prompt += ": "

            raw = input(prompt).strip()
            if raw == "" and default_idx:
                model = installed[default_idx - 1][0]
                break
            try:
                idx = int(raw)
                if 1 <= idx <= len(installed):
                    model = installed[idx - 1][0]
                    break
            except ValueError:
                pass
            print(f"  ⚠️  Invalid choice. Enter a number from 1 to {len(installed)}.")

    # --- Encoding Quality ---
    print("\n🎚️  Encoding Quality (CRF):")
    print("   CRF controls the trade-off between visual quality and file size.")
    print("   Lower number = better quality, larger file.")
    print("   Higher number = more compression, smaller file.")
    print()
    default_crf = config.get('encode_crf', 18)
    # Derive the default preset index from the config value so Enter-key and ★ stay in sync.
    # Falls back to 2 (Production) if encode_crf is a custom value not in the preset list.
    default_preset_idx = next(
        (i for i, (_, crf, _) in enumerate(_ENCODE_PRESETS, 1) if crf == default_crf),
        2,
    )
    for i, (label, crf, desc) in enumerate(_ENCODE_PRESETS, 1):
        marker = " ★" if crf == default_crf else ""
        print(f"  [{i}] {label} (CRF {crf})  — {desc}{marker}")

    while True:
        raw = input(f"\n  Select quality [1-{len(_ENCODE_PRESETS)}] (default: {default_preset_idx}): ").strip()
        if raw == "":
            encode_crf = _ENCODE_PRESETS[default_preset_idx - 1][1]
            break
        try:
            idx = int(raw)
            if 1 <= idx <= len(_ENCODE_PRESETS):
                encode_crf = _ENCODE_PRESETS[idx - 1][1]
                break
        except ValueError:
            pass
        print(f"  ⚠️  Invalid choice. Enter a number from 1 to {len(_ENCODE_PRESETS)}.")

    # --- Packaging (batch only) ---
    if batch_mode:
        print(f"\n📦 Packaging ({video_count} clips detected):")
        pkg_choice = input("  Archive all exports to batch_exports/ on completion? [Y/n]: ").strip()
        package_output = pkg_choice.lower() != 'n'
    else:
        package_output = False

    print("═" * 50)

    profile = ProductionProfile(
        resolution=resolution,
        model=model,
        scale=config.get('default_scale', 4),
        package_output=package_output,
        retry_limit=3,
        batch_mode=batch_mode,
        encode_crf=encode_crf,
    )

    # Confirm selection
    print(f"\n  📐 Resolution: {', '.join(r.upper() for r in profile.resolution)}")
    print(f"  🤖 Model:      {profile.model} @ {profile.scale}x")
    print(f"  🎚️  Quality:    CRF {profile.encode_crf}")
    if batch_mode:
        pkg_status = "Yes" if profile.package_output else "No"
        print(f"  📦 Archive:    {pkg_status}")
    print()

    return profile
