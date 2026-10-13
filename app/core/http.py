from threading import Lock

import httpx


class LazyHTTPClient:
    """Create TLS contexts and connection pools only when a provider is actually called."""

    def __init__(self, timeout):
        self.timeout = timeout
        self._client = None
        self._lock = Lock()

    def post(self, url, **kwargs):
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(timeout=self.timeout, follow_redirects=False)
            client = self._client
        return client.post(url, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        with self._lock:
            if self._client is not None:
                self._client.close()
