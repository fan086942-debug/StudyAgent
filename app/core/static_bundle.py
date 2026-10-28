"""Single-request CSS delivery for the six cascade-layer stylesheets.

The design keeps ``tokens.css``, ``style.css`` and the rest as separate files for
maintenance, but a browser should not pay seven render-blocking requests for
them. ``bundle_text`` concatenates the modules inside the exact same cascade
layers declared by ``app.css``; ``bundle_version`` is the content hash used both
as the URL version and the ETag.

The bundle is generated in memory (once per process) instead of being committed
as a second copy, so it can never drift from the source files.
"""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
BUNDLE_NAME = "app.bundle.css"

IMPORT = re.compile(
    r'@import url\("([\w-]+\.css)(?:\?v=[^"\)]*)?"\) layer\(([\w-]+)\);'
)
LAYER_ORDER = re.compile(r"^@layer ([\w, ]+);\s*$", re.MULTILINE)
CHARSET = re.compile(r'^\ufeff?\s*@charset\s+"[^"]*";\s*', re.IGNORECASE)
ASSET_URL = re.compile(r'url\("([\w-]+\.css)(?:\?v=[^"\)]*)?"\)')
PAGE_ASSET = re.compile(
    r'((?:src|href)="/static/)([\w.-]+\.(?:js|css))(?:\?v=[^"]*)?(")'
)


def asset_version(name):
    return hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]


@lru_cache(maxsize=1)
def bundle_text():
    """Return the generated stylesheet, byte-for-byte reproducible."""
    source = (STATIC / "app.css").read_text(encoding="utf-8")
    order = LAYER_ORDER.search(source)
    imports = IMPORT.findall(source)
    if order is None or not imports:
        raise RuntimeError("app.css must declare @layer order and layer(@import url(...)) rules")
    parts = [order.group(0).strip()]
    for name, layer in imports:
        css = (STATIC / name).read_text(encoding="utf-8").lstrip("\ufeff")
        css = CHARSET.sub("", css, count=1).strip()
        parts.append(f"@layer {layer} {{\n{css}\n}}")
    return "\n\n".join(parts) + "\n"


@lru_cache(maxsize=1)
def bundle_version():
    return hashlib.sha256(bundle_text().encode("utf-8")).hexdigest()[:12]


def stamp():
    """Refresh ``?v=`` content hashes in app.css and index.html."""
    sheet = STATIC / "app.css"
    css = ASSET_URL.sub(
        lambda match: f'url("{match.group(1)}?v={asset_version(match.group(1))}")',
        sheet.read_text(encoding="utf-8"),
    )
    sheet.write_text(css, encoding="utf-8", newline="\n")

    def versioned(match):
        name = match.group(2)
        version = bundle_version() if name == BUNDLE_NAME else asset_version(name)
        return f"{match.group(1)}{name}?v={version}{match.group(3)}"

    page = STATIC / "index.html"
    html = PAGE_ASSET.sub(versioned, page.read_text(encoding="utf-8"))
    page.write_text(html, encoding="utf-8", newline="\n")
