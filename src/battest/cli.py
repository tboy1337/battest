"""Command-line interface for battest."""

from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
import sys

from pydantic import ValidationError

from battest._version import __version__
from battest.constants import DEFAULT_MAX_DIFF, DEFAULT_TIMEOUT_SECONDS, MAX_JOBS
from battest.discover import default_root, discover_cases
from battest.engine import EngineError, execute_cases, require_windows
from battest.logging_config import configure_logging, get_logger
from battest.models import EngineConfig
from battest.report import (
    exit_status,
    render_console,
    write_junit_xml,
    write_usage_junit,
)
from battest.schema import SchemaError

LOGGER = get_logger("cli")


def _usage_failure(args: argparse.Namespace, message: str) -> int:
    """Print a usage/schema error, optionally write JUnit, and return exit 2."""
    LOGGER.error("%s", message)
    print(message, file=sys.stderr)
    if not args.junit_xml:
        return 2
    try:
        write_usage_junit(Path(args.junit_xml), message)
    except OSError as exc:
        LOGGER.error("failed to write junit xml: %s", exc)
        print(f"failed to write junit xml: {exc}", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    """Build the battest argument parser."""
    parser = argparse.ArgumentParser(
        prog="battest",
        description="Runtime test runner for Windows batch files",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="discover and execute test cases")
    run_parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="fixture file or directory (default: ./tests with fixtures, else cwd)",
    )
    run_parser.add_argument("--junit-xml", dest="junit_xml", default=None)
    run_parser.add_argument("--jobs", type=int, default=1)
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="default timeout in seconds for cases that omit timeout_seconds",
    )
    run_parser.add_argument(
        "--max-diff", dest="max_diff", type=int, default=DEFAULT_MAX_DIFF
    )
    run_parser.add_argument(
        "--safe-defaults",
        dest="safe_defaults",
        action="store_true",
        default=False,
    )
    run_parser.add_argument(
        "--no-safe-defaults",
        dest="safe_defaults",
        action="store_false",
    )
    run_parser.add_argument(
        "--include-spec-exec",
        dest="include_spec_exec",
        action="store_true",
        default=False,
        help="also discover vendor/batch-spec/corpus/exec when present",
    )
    run_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="enable debug logging",
    )
    return parser


def _run_command(args: argparse.Namespace) -> int:
    level = logging.DEBUG if args.verbose else logging.INFO
    configure_logging(level)
    try:
        require_windows()
    except EngineError as exc:
        return _usage_failure(args, str(exc))
    root = Path(args.path).resolve() if args.path else default_root()
    LOGGER.info(
        "battest run path=%s jobs=%s timeout=%s safe_defaults=%s",
        root,
        args.jobs,
        args.timeout,
        args.safe_defaults,
    )
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        return _usage_failure(args, "--timeout must be a finite number greater than 0")
    if args.jobs < 1:
        return _usage_failure(args, "--jobs must be at least 1")
    if args.jobs > MAX_JOBS:
        return _usage_failure(args, f"--jobs must be at most {MAX_JOBS}")
    if args.max_diff < 1:
        return _usage_failure(args, "--max-diff must be at least 1")
    try:
        cases = discover_cases(root, include_spec_exec=args.include_spec_exec)
    except SchemaError as exc:
        return _usage_failure(args, str(exc))
    if not cases:
        return _usage_failure(args, f"no battest fixtures found under {root}")
    try:
        config = EngineConfig(
            safe_defaults=args.safe_defaults,
            max_diff=args.max_diff,
            jobs=args.jobs,
            default_timeout_seconds=args.timeout,
        )
    except ValidationError as exc:
        return _usage_failure(args, str(exc))
    try:
        results = execute_cases(cases, config)
    except EngineError as exc:
        return _usage_failure(args, str(exc))
    render_console(results, sys.stdout)
    if args.junit_xml:
        try:
            write_junit_xml(results, Path(args.junit_xml))
        except OSError as exc:
            LOGGER.error("failed to write junit xml: %s", exc)
            print(f"failed to write junit xml: {exc}", file=sys.stderr)
            ran_status = exit_status(results)
            if ran_status == 1:
                return 1
            return 2
    return exit_status(results)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the battest console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 2
    return _run_command(args)
