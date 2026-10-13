import ssl
from concurrent.futures import ThreadPoolExecutor

import certifi
import httpx

from app.core.http import LazyHTTPClient


def test_lazy_http_initializes_once_and_closes(monkeypatch):
    created = []

    class Client:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.closed = False
            created.append(self)

        def post(self, url, **kwargs):
            return url, kwargs

        def close(self):
            self.closed = True

    monkeypatch.setattr("app.core.http.httpx.Client", Client)
    with LazyHTTPClient(12) as client:
        assert not created
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(lambda _: client.post("https://model.example", json={}), range(8))
            )
        assert len(created) == 1 and len(results) == 8
        options = created[0].options
        assert options["follow_redirects"] is False
        assert options["verify"].check_hostname
        assert options["verify"].verify_mode == ssl.CERT_REQUIRED
        assert options["timeout"].read == 12 and options["timeout"].connect == 10
        assert options["limits"].keepalive_expiry == 60
    assert created[0].closed
    with LazyHTTPClient(12):
        pass
    assert len(created) == 1


def test_ca_bundle_and_directory_configuration_are_preserved(monkeypatch, tmp_path):
    from app.core.http import provider_ssl_context

    captured = []
    monkeypatch.setattr(
        "app.core.http.ssl.create_default_context", lambda **kwargs: captured.append(kwargs)
    )
    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    provider_ssl_context()
    assert "BEGIN CERTIFICATE" in captured[-1]["cadata"]
    assert "capath" not in captured[-1]
    monkeypatch.delenv("SSL_CERT_FILE")
    provider_ssl_context()
    assert captured[-1] == {"capath": str(tmp_path)}


def test_provider_ssl_remains_verified_for_all_proxy_transports(monkeypatch):
    from app.core.http import provider_ssl_context

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    context = provider_ssl_context()
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert context.cert_store_stats()["x509_ca"] > 0
    with httpx.Client(verify=context) as client:
        assert client._transport._pool._ssl_context is context
        for transport in client._mounts.values():
            if transport is not None:
                assert transport._pool._ssl_context is context
