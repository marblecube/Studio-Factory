import json
from pathlib import Path

def test_tools():
    config_path = Path("config/config.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
        print(f"FFMPEG found at: {config['tools']['ffmpeg']}")
        print(f"Upscayl found at: {config['tools']['upscayl']}")

if __name__ == "__main__":
    test_tools()	