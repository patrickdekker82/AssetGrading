"""Small maintenance commands: `python -m app.cli check-config` and `python -m app.cli lock-model`."""

import sys

from app.glossary import load_glossary
from app.modelconfig import ModelConfigError, load_model_config
from app.modelconfig.loader import write_lock
from app.settings import get_settings


def main(argv: list[str]) -> int:
    settings = get_settings()
    model_dir = settings.config_dir / "model"
    command = argv[0] if argv else "check-config"
    try:
        if command == "check-config":
            config = load_model_config(model_dir)
            load_glossary(settings.config_dir / "glossary.nl.yaml")
            print(f"OK: model {config.version}, {len(config.templates)} templates, hash {config.config_hash[:12]}")
        elif command == "lock-model":
            config = load_model_config(model_dir, check_lock=False)
            write_lock(config, model_dir)
            print(f"Locked model {config.version} -> {config.config_hash[:12]}")
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except ModelConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
