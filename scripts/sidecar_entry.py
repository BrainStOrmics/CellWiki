"""PyInstaller entry kept separate so package imports resolve exactly like release."""

from cellwiki.sidecar import main


if __name__ == "__main__":
    main()

