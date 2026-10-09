import sys

from .main import main


def _configure_streams(streams=None):
    """Piped output (an agent reading stdout) is UTF-8 whatever the Windows code page says,
    and each line reaches it as it is printed instead of when the process exits."""
    for stream in streams or (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


if __name__ == "__main__":
    _configure_streams()
    raise SystemExit(main())
