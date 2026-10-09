import sys

from .main import main

# Piped output (an agent reading stdout) is UTF-8 whatever the Windows code page says.
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

raise SystemExit(main())
