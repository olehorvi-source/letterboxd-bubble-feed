from __future__ import annotations

import argparse
from pathlib import Path

from .aggregator import run_aggregation, validate_json_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="letterboxd-rss-aggregator",
        description="Fetch, normalize, archive, and publish public Letterboxd RSS data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Fetch feeds and update docs artifacts.")
    run_parser.add_argument(
        "--output-dir",
        default="docs",
        help="Directory where entries.json, status.json, and index.html are written.",
    )
    run_parser.add_argument(
        "--user-agent",
        default="letterboxd-rss-aggregator/0.1 (+https://github.com/YOUR_GITHUB_USERNAME/letterboxd-rss-aggregator)",
        help="Explicit HTTP user agent for feed requests.",
    )
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Per-request timeout in seconds.",
    )

    validate_parser = subparsers.add_parser("validate", help="Validate JSON artifacts.")
    validate_parser.add_argument("paths", nargs="+", help="JSON file paths to validate.")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        return run_aggregation(
            output_dir=Path(args.output_dir),
            user_agent=args.user_agent,
            timeout=args.timeout,
        )

    if args.command == "validate":
        validate_json_files([Path(path) for path in args.paths])
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2
