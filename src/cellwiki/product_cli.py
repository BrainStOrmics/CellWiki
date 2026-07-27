"""Product command-line interface for the Agentic CellWiki desktop runtime.

Legacy knowledge-base commands intentionally live behind the separate
``cellwiki-legacy`` entry point. Keeping this Module small prevents the desktop
runtime from importing the legacy graph and projection implementations.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from cellwiki.config import settings
from cellwiki.dev_runtime import DevelopmentRuntime


def build_parser() -> argparse.ArgumentParser:
    """Build the stable product CLI without importing legacy command Modules."""

    parser = argparse.ArgumentParser(
        prog="cellwiki",
        description="Agentic CellWiki desktop development tools",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    development = subcommands.add_parser(
        "dev",
        help="Start the Product API, Agent Runtime, and Tauri desktop application",
    )
    development.add_argument(
        "--no-agent",
        action="store_true",
        help="Start without the Agent Runtime",
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
    return parser


def _run_development_runtime(arguments: argparse.Namespace) -> None:
    """Run the owned development processes selected by product CLI flags."""

    DevelopmentRuntime(
        settings.project_root,
        include_agent=not arguments.no_agent,
        include_desktop=not arguments.no_desktop,
        reuse_ports=arguments.reuse_ports,
    ).run()


def main(argv: Sequence[str] | None = None) -> None:
    """Parse product arguments and dispatch to the selected command."""

    arguments = build_parser().parse_args(argv)
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
