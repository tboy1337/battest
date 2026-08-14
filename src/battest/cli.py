"""Command-line interface for battest."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from battest._version import __version__
from battest.constants import DEFAULT_MAX_DIFF, DEFAULT_TIMEOUT_SECONDS
from battest.discover import default_root, discover_cases
from battest.engine import EngineError, execute_cases, require_windows
from battest.logging_config import configure_logging, get_logger
from battest.models import EngineConfig
from battest.report import exit_status, render_console, write_junit_xml
from battest.schema import SchemaError

LOGGER = get_logger("cli")


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
        help="fixture file or directory (default: ./tests or cwd)",
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
        LOGGER.error("%s", exc)
        print(str(exc), file=sys.stderr)
        return 2
    root = Path(args.path).resolve() if args.path else default_root()
    LOGGER.info(
        "battest run path=%s jobs=%s timeout=%s safe_defaults=%s",
        root,
        args.jobs,
        args.timeout,
        args.safe_defaults,
    )
    if args.timeout <= 0:
        message = "--timeout must be positive"
        LOGGER.error("%s", message)
        print(message, file=sys.stderr)
        return 2
    if args.jobs < 1:
        message = "--jobs must be at least 1"
        LOGGER.error("%s", message)
        print(message, file=sys.stderr)
        return 2
    try:
        cases = discover_cases(root, include_spec_exec=args.include_spec_exec)
    except SchemaError as exc:
        LOGGER.error("schema error: %s", exc)
        print(str(exc), file=sys.stderr)
        return 2
    if not cases:
        message = f"no battest fixtures found under {root}"
        LOGGER.error("%s", message)
        print(message, file=sys.stderr)
        return 2
    config = EngineConfig(
        safe_defaults=args.safe_defaults,
        max_diff=args.max_diff,
        jobs=args.jobs,
        default_timeout_seconds=args.timeout,
    )
    try:
        results = execute_cases(cases, config)
    except EngineError as exc:
        LOGGER.error("%s", exc)
        print(str(exc), file=sys.stderr)
        return 2
    render_console(results, sys.stdout)
    if args.junit_xml:
        write_junit_xml(results, Path(args.junit_xml))
    return exit_status(results)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the battest console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 2
    return _run_command(args)
