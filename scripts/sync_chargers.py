"""Backwards-compatible shim — delegates to ``ev_mcp.sync``.

Phase 7 moved the sync logic into the installable package so that
``pip install ev-mcp`` exposes it as the ``ev-mcp-sync`` console script.
This script remains for repo-local invocations
(``python scripts/sync_chargers.py``) without an editable install.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a checkout without `pip install -e .`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ev_mcp.sync import main

if __name__ == "__main__":
    main()
