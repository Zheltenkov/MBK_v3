from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from mbk_refactor.dialogue_v3.debug_probe import probe_phrase


def parse_key_value(items: list[str]) -> dict[str, object]:
    """Parse repeated key=value CLI arguments into simple typed facts."""

    result: dict[str, object] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid --fact format: {item}. Use key=value.")

        key, raw_value = item.split("=", 1)
        value = raw_value.strip()
        lowered = value.lower()
        if lowered in {"true", "yes", "да"}:
            parsed: object = True
        elif lowered in {"false", "no", "нет"}:
            parsed = False
        elif value.isdigit():
            parsed = int(value)
        else:
            parsed = value
        result[key.strip()] = parsed
    return result


def main() -> None:
    """Run a one-phrase dialogue_v3 interpretation probe."""

    parser = argparse.ArgumentParser(
        description="Probe how dialogue_v3 interprets one user phrase.",
    )
    parser.add_argument(
        "text",
        help="User phrase to interpret.",
    )
    parser.add_argument(
        "--fact",
        action="append",
        default=[],
        help="Known fact before phrase, format key=value. Can be repeated.",
    )
    parser.add_argument(
        "--asked-slot",
        action="append",
        default=[],
        help="Previously asked slot. Can be repeated.",
    )
    parser.add_argument(
        "--no-route",
        action="store_true",
        help="Only run extraction/merge, skip route/session/move.",
    )
    args = parser.parse_args()

    known_facts = parse_key_value(args.fact)
    result = probe_phrase(
        args.text,
        known_facts=known_facts,
        asked_slots=args.asked_slot,
        run_route=not args.no_route,
    )
    print(
        json.dumps(
            asdict(result),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
