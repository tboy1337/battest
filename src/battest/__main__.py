"""Allow python -m battest."""

import multiprocessing

from battest.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
