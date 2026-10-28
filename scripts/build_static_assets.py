"""Refresh content hashes for local static assets; no bundler or remote deps.

The CSS entry (``app.bundle.css``) is generated in memory from the six source
modules at request time, so there is no second stylesheet copy to keep in sync.
Run this after editing CSS or JS so index.html points at fresh URLs:

    .venv/Scripts/python.exe scripts/build_static_assets.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.static_bundle import (  # noqa: E402
    BUNDLE_NAME,
    STATIC,
    bundle_text,
    bundle_version,
    stamp,
)


def build():
    stamp()
    return {
        "bundle": BUNDLE_NAME,
        "version": bundle_version(),
        "bytes": len(bundle_text().encode("utf-8")),
        "sources": STATIC,
    }


if __name__ == "__main__":
    result = build()
    print(f"CSS bundle: {result['bundle']} v={result['version']} ({result['bytes']} bytes)")
    print("Static asset content hashes updated.")
