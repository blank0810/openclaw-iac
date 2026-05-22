#!/usr/bin/env python
"""Root entrypoint for the orchestrator launch CLI. See
apps/orchestrator/client.py and docs/plans/2026-05-22-zc-launch-cli-design.md."""
import sys

from apps.orchestrator.client import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
