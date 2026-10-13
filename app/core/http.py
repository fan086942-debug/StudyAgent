import os
import ssl
from pathlib import Path
from threading import Lock

import certifi
import httpx


def provider_ssl_context():
    """Use HTTPX's trusted CA choices, loading PEM once in memory on Windows/removable drives."""
    cafile = os.environ.get("SSL_CERT_FILE")
    capath = os.environ.get("SSL_CERT_DIR")
    if not cafile and capath:
        return ssl.create_default_context(capath=capath)
    bundle = Path(cafile or certifi.where()).read_text(encoding="ascii")
    return ssl.create_default_context(cadata=bundle)


class LazyHTTPClient:
    """Create TLS contexts and connection pools only when a provider is actually called."""

    def __init__(self, timeout):
        self.timeout = timeout
        self._client = None
        self._lock = Lock()

    def post(self, url, **kwargs):
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    verify=provider_ssl_context(),
                    timeout=httpx.Timeout(
                        self.timeout, connect=min(10, self.timeout), pool=min(5, self.timeout)
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20, keepalive_expiry=60
                    ),
                    follow_redirects=False,
                )
            client = self._client
        return client.post(url, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        with self._lock:
            if self._client is not None:
                self._client.close()
