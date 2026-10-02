"""Run OpenWoven without changing the legacy CLI or storage format."""

from adaptive_companion.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
