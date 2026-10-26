"""Stamp local assets with content hashes; no bundler or remote dependencies."""

import hashlib
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def version(name):
    return hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]


def build():
    sheet = STATIC / "app.css"
    css = sheet.read_text(encoding="utf-8")
    css = re.sub(
        r'url\("([\w-]+\.css)(?:\?v=[^"\)]*)?"\)',
        lambda match: f'url("{match[1]}?v={version(match[1])}")', css,
    )
    sheet.write_text(css, encoding="utf-8", newline="\n")
    page = STATIC / "index.html"
    html = re.sub(
        r'((?:src|href)="/static/)([\w.-]+\.(?:js|css))(?:\?v=[^"]*)?(")',
        lambda match: f"{match[1]}{match[2]}?v={version(match[2])}{match[3]}",
        page.read_text(encoding="utf-8"),
    )
    page.write_text(html, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    build()
    print("Static asset content hashes updated.")
