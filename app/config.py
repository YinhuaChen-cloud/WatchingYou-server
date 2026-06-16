import sys
import yaml

_PLACEHOLDER = "your_api_key_here"


def load_config(path: str = "config.yaml") -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ERROR: config.yaml not found at '{path}'.", file=sys.stderr)
        print("Copy config.yaml.example to config.yaml and fill in your DeepSeek API key.", file=sys.stderr)
        sys.exit(1)

    key = (data or {}).get("deepseek_api_key", "")
    if not key or key == _PLACEHOLDER:
        print("ERROR: deepseek_api_key is missing or still set to the placeholder value.", file=sys.stderr)
        print("Edit config.yaml and set a real DeepSeek API key.", file=sys.stderr)
        sys.exit(1)

    return data
