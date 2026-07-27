"""Compatibility import for the explicit legacy command-line interface."""

from cellwiki.legacy.cli import main


__all__ = ["main"]


if __name__ == "__main__":
    main()
