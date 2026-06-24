"""Tests for sift()."""
import orchestrator


def test_sift_flattens_nested_dirs(project_dir, mock_config):
    """sift() should move PNGs from subdirectories to the parent and remove empty subdirs."""
    upscaled_dir = project_dir / "process" / "frames_upscaled"

    # Create nested structure (mimics upscayl output)
    nested = upscaled_dir / "frames_raw"
    nested.mkdir(parents=True)

    for i in range(1, 6):
        (nested / f"frame_{i:05d}.png").touch()

    orchestrator.sift(project_dir)

    # Files should be in upscaled_dir root now
    flat_files = list(upscaled_dir.glob("*.png"))
    assert len(flat_files) == 5

    # Nested directory should be removed
    assert not nested.exists()


def test_sift_noop_when_already_flat(project_dir, mock_config):
    """sift() should do nothing when directory is already flat."""
    upscaled_dir = project_dir / "process" / "frames_upscaled"

    for i in range(1, 4):
        (upscaled_dir / f"frame_{i:05d}.png").touch()

    orchestrator.sift(project_dir)

    # Same files, no crash
    flat_files = list(upscaled_dir.glob("*.png"))
    assert len(flat_files) == 3


def test_sift_handles_multiple_subdirs(project_dir, mock_config):
    """sift() should handle multiple nested subdirectories."""
    upscaled_dir = project_dir / "process" / "frames_upscaled"

    for sub_name in ["sub_a", "sub_b"]:
        sub = upscaled_dir / sub_name
        sub.mkdir()
        for i in range(1, 3):
            (sub / f"{sub_name}_frame_{i:05d}.png").touch()

    orchestrator.sift(project_dir)

    flat_files = list(upscaled_dir.glob("*.png"))
    assert len(flat_files) == 4
    assert not (upscaled_dir / "sub_a").exists()
    assert not (upscaled_dir / "sub_b").exists()
