# Copyright (c) 2026 Novain Shibu. AGPL-3.0-or-later, or a commercial licence (see COMMERCIAL.md).
import sys


def main():
    sys.argv = [sys.argv[0]] + sys.argv[1:]
    import runpy
    runpy.run_module("seenread.core", run_name="__main__")


if __name__ == "__main__":
    main()
