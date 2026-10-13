"""Product command-line interface for the Agentic CellWiki runtime."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Build the stable product CLI: TUI, daemon, and desktop development."""

    parser = argparse.ArgumentParser(
        prog="cellwiki",
        description="Agentic CellWiki terminal and daemon runtime",
    )
    subcommands = parser.add_subparsers(dest="command", required=False)

    development = subcommands.add_parser(
        "dev",
        help="Start the Product API and Tauri desktop application",
    )
    development.add_argument(
        "--no-desktop",
        action="store_true",
        help="Start only backend services",
    )
    development.add_argument(
        "--reuse-ports",
        action="store_true",
        help="Reuse already occupied development ports after explicit approval",
    )
    development.set_defaults(handler=_run_development_runtime)

    serve = subcommands.add_parser(
        "serve",
        help="Run the local CellWiki daemon for one workspace",
    )
    serve.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Knowledge-base workspace (default: current directory)",
    )
    serve.add_argument(
        "--detach",
        action="store_true",
        help="Start in the background and return once healthy",
    )
    serve.add_argument(
        "--log-level",
        default=None,
        help="Override the workspace log level",
    )
    serve.set_defaults(handler=_run_serve)

    daemon = subcommands.add_parser(
        "daemon",
        help="Manage the local CellWiki daemon",
    )
    daemon_commands = daemon.add_subparsers(dest="daemon_command", required=True)
    for name, help_text in (
        ("status", "Show daemon status for one workspace"),
        ("stop", "Stop the daemon for one workspace"),
        ("restart", "Restart the daemon for one workspace"),
    ):
        command = daemon_commands.add_parser(name, help=help_text)
        command.add_argument(
            "--workspace",
            type=Path,
            default=None,
            help="Knowledge-base workspace (default: current directory)",
        )
        command.set_defaults(handler=_run_daemon_command)

    parser.set_defaults(handler=_run_tui)
    return parser


def _workspace_from(arguments: argparse.Namespace) -> Path:
    return Path(arguments.workspace or Path.cwd()).expanduser().resolve()


def _run_development_runtime(arguments: argparse.Namespace) -> None:
    """Run the owned development processes selected by product CLI flags."""

    from cellwiki.config import settings
    from cellwiki.dev_runtime import DevelopmentRuntime

    DevelopmentRuntime(
        settings.project_root,
        include_desktop=not arguments.no_desktop,
        reuse_ports=arguments.reuse_ports,
    ).run()


def _run_serve(arguments: argparse.Namespace) -> None:
    """Run the local daemon in the foreground or detach it."""

    from cellwiki.services.local_daemon import DaemonError, ensure_daemon, run_daemon

    workspace = _workspace_from(arguments)
    try:
        if arguments.detach:
            coordinates = ensure_daemon(workspace)
            print(
                "CellWiki daemon is running at "
                f"http://127.0.0.1:{coordinates.port} (pid {coordinates.pid})"
            )
        else:
            run_daemon(workspace, log_level=arguments.log_level)
    except DaemonError as error:
        raise SystemExit(f"cellwiki serve: {error}") from None


def _run_daemon_command(arguments: argparse.Namespace) -> None:
    """Dispatch one daemon lifecycle subcommand."""

    from cellwiki.services.local_daemon import daemon_status, restart_daemon, stop_daemon

    workspace = _workspace_from(arguments)
    if arguments.daemon_command == "status":
        print(json.dumps(daemon_status(workspace), ensure_ascii=False, indent=2))
    elif arguments.daemon_command == "stop":
        stopped = stop_daemon(workspace)
        print(
            "CellWiki daemon stopped."
            if stopped
            else "No CellWiki daemon is registered for this workspace."
        )
    else:
        coordinates = restart_daemon(workspace)
        print(
            "CellWiki daemon restarted at "
            f"http://127.0.0.1:{coordinates.port} (pid {coordinates.pid})"
        )


def _run_tui(arguments: argparse.Namespace) -> None:
    """Start the terminal client for the current directory."""

    from cellwiki.tui.app import run_tui

    run_tui(Path.cwd())


def main(argv: Sequence[str] | None = None) -> None:
    """Parse product arguments and dispatch to the selected command."""

    arguments = build_parser().parse_args(argv)
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
