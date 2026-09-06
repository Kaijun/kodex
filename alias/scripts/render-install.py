#!/usr/bin/env python3
"""Render the standalone installer from the active alias configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    alias = json.loads(args.config.read_text())
    values = {
        "DISPLAY_NAME": alias["display_name"],
        "BINARY_NAME": alias["binary_name"],
        "REPOSITORY": alias["repository"],
        "RELEASE_PREFIX": alias["release_prefix"],
    }
    rendered = args.template.read_text()
    for key, value in values.items():
        rendered = rendered.replace(f"@@{key}@@", value)
    if "@@" in rendered:
        raise RuntimeError("unresolved installer template placeholder")
    args.output.write_text(rendered)
    args.output.chmod(0o755)


if __name__ == "__main__":
    main()
