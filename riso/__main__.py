"""``python -m riso`` — same entry point as the installed ``riso`` command."""

from riso.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
