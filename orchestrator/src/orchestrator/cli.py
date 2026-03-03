"""CLI entry point for the orchestrator.

Provides commands for:
  - Running the web server (uvicorn)
  - Seeding the database
  - Starting a test run (created -> validating)
  - Running a test programmatically
  - Database migrations

Usage:
    python -m orchestrator.cli serve [--host 0.0.0.0] [--port 8000]
    python -m orchestrator.cli seed [--config config/orchestrator.yaml]
    python -m orchestrator.cli start <test_run_id>
    python -m orchestrator.cli run-test <test_run_id> [--config config/orchestrator.yaml]
"""

import argparse
import logging
import sys

from orchestrator.logging_config import setup_logging


def cmd_serve(args):
    """Start the FastAPI web server."""
    import uvicorn
    setup_logging(level=args.log_level, json_format=args.json_logs, log_dir=args.log_dir)
    uvicorn.run(
        "orchestrator.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level.lower(),
    )


def cmd_seed(args):
    """Seed the database with initial data."""
    setup_logging(level=args.log_level)
    from orchestrator.config.settings import load_config
    from orchestrator.models.database import init_db, get_session
    from orchestrator.seed import seed_all

    config = load_config(args.config)
    init_db(config.database.url, echo=config.database.echo)

    session_gen = get_session()
    session = next(session_gen)
    try:
        seed_all(session)
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


def cmd_start(args):
    """Start a test run: transition from 'created' to 'validating'."""
    setup_logging(level=args.log_level)
    from orchestrator.config.settings import load_config
    from orchestrator.models.database import init_db, get_session
    from orchestrator.models.enums import TestRunState
    from orchestrator.models.orm import TestRunORM, TestRunTargetORM, TestRunLoadProfileORM

    config = load_config(args.config)
    init_db(config.database.url, echo=config.database.echo)

    session_gen = get_session()
    session = next(session_gen)
    try:
        test_run = session.get(TestRunORM, args.test_run_id)
        if not test_run:
            print(f"ERROR: Test run {args.test_run_id} not found")
            sys.exit(1)
        if test_run.state != TestRunState.created:
            print(f"ERROR: Test run {args.test_run_id} is in state '{test_run.state.value}', expected 'created'")
            sys.exit(1)

        targets = session.query(TestRunTargetORM).filter(
            TestRunTargetORM.test_run_id == args.test_run_id
        ).count()
        profiles = session.query(TestRunLoadProfileORM).filter(
            TestRunLoadProfileORM.test_run_id == args.test_run_id
        ).count()
        if targets == 0:
            print("ERROR: No targets configured for this test run")
            sys.exit(1)
        if profiles == 0:
            print("ERROR: No load profiles selected for this test run")
            sys.exit(1)

        test_run.state = TestRunState.validating
        session.commit()
        print(f"Test run {args.test_run_id}: created -> validating  ({targets} target(s), {profiles} profile(s))")
        print(f"Now run:  python -m orchestrator run-test {args.test_run_id}")
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


def cmd_run_test(args):
    """Run a test by ID (programmatic, non-web execution)."""
    # Always log to file for test runs — default to logs/ if not specified
    log_dir = args.log_dir or "logs"
    setup_logging(level=args.log_level, json_format=args.json_logs, log_dir=log_dir)
    from orchestrator.config.credentials import CredentialsStore
    from orchestrator.config.settings import load_config
    from orchestrator.core.orchestrator import Orchestrator
    from orchestrator.logging_config import get_test_run_logger
    from orchestrator.models.database import init_db, get_session

    config = load_config(args.config)
    init_db(config.database.url, echo=config.database.echo)
    credentials = CredentialsStore(config.credentials_path)

    # Set up per-test-run log file
    get_test_run_logger(args.test_run_id, log_dir)

    orchestrator = Orchestrator(config, credentials)

    session_gen = get_session()
    session = next(session_gen)
    try:
        orchestrator.run(session, args.test_run_id)
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Agent Performance Testing Orchestrator",
        prog="orchestrator",
    )
    parser.add_argument("--config", default="config/orchestrator.yaml", help="Config file path")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--json-logs", action="store_true", help="Use JSON log format")
    parser.add_argument("--log-dir", default=None, help="Directory for log files")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start the web server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    serve_parser.add_argument("--port", type=int, default=8000, help="Bind port")
    serve_parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")

    # seed
    subparsers.add_parser("seed", help="Seed the database")

    # start
    start_parser = subparsers.add_parser("start", help="Start a test run (created -> validating)")
    start_parser.add_argument("test_run_id", type=int, help="Test run ID to start")

    # run-test
    run_parser = subparsers.add_parser("run-test", help="Run a test by ID (from validating state onward)")
    run_parser.add_argument("test_run_id", type=int, help="Test run ID to execute")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "seed":
        cmd_seed(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "run-test":
        cmd_run_test(args)


if __name__ == "__main__":
    main()
