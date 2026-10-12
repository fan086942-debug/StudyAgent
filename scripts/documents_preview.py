"""Isolated demo server for upload/delete browser acceptance."""

from pathlib import Path

import uvicorn

from app.core.config import Settings
from app.main import create_app

if __name__ == "__main__":
    uvicorn.run(
        create_app(Settings(_env_file=None, data_dir=Path("data/documents-browser-check"))),
        host="127.0.0.1",
        port=8767,
    )
