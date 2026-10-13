from concurrent.futures import ThreadPoolExecutor

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
            results = list(pool.map(lambda _: client.post("https://model.example", json={}), range(8)))
        assert len(created) == 1 and len(results) == 8
        assert created[0].options == {"timeout": 12, "follow_redirects": False}
    assert created[0].closed
    with LazyHTTPClient(12):
        pass
    assert len(created) == 1
