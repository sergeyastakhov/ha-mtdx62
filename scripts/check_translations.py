"""Fail when the translation files drift from strings.json."""

from __future__ import annotations

import json
import pathlib
import sys
from collections.abc import Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "mtdx62"


def flat(node: dict[str, object], prefix: str = "") -> Iterator[str]:
    """Every leaf path of a translation tree."""
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from flat(value, path)
        else:
            yield path


def main() -> int:
    """Compare the source with the shipped languages."""
    source = set(flat(json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))))
    failed = False
    for language in ("en", "ru"):
        shipped = set(
            flat(
                json.loads((ROOT / "translations" / f"{language}.json").read_text(encoding="utf-8"))
            )
        )
        missing = sorted(source - shipped)
        extra = sorted(shipped - source)
        if missing or extra:
            failed = True
            print(f"{language}.json is out of step with strings.json")
            for key in missing:
                print(f"  missing: {key}")
            for key in extra:
                print(f"  unknown: {key}")
        else:
            print(f"{language}.json: {len(shipped)} keys, in step")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
