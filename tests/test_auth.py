import time

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.config import Settings
from app.db.session import make_database
from app.main import create_app
from app.models import Course
from app.services.auth import COOKIE, LoginSession, User
from tests.test_exams import exam_bytes


def settings(path, **kwargs):
    return Settings(_env_file=None, data_dir=path, auth_enabled=True, **kwargs)


def register(client, name="student_one"):
    response = client.post("/api/auth/register", json={
        "username": name, "password": "correct horse battery staple",
    })
    assert response.status_code == 201, response.text
    return response


def test_login_persistence_cookie_expiry_and_logout(tmp_path):
    config = settings(tmp_path)
    app = create_app(config)
    with TestClient(app) as client:
        assert client.get("/api/courses").status_code == 401
        response = register(client, "Student_One")
        assert response.json()["user"]["username"] == "student_one"
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        token = client.cookies.get(COOKIE)
        with app.state.auth.sessions() as db:
            user = db.scalar(select(User))
            login = db.scalar(select(LoginSession))
            assert "correct horse" not in user.password_hash
            assert login.token_hash != token
        course = client.post("/api/courses", json={"name": "My course"}).json()
        assert client.post("/api/auth/logout").status_code == 200
        client.cookies.set(COOKIE, token)
        assert client.get("/api/courses").status_code == 401
        assert client.post("/api/auth/login", json={
            "username": "student_one", "password": "wrong password",
        }).status_code == 401
        client.cookies.clear()
        assert client.post("/api/auth/login", json={
            "username": "student_one", "password": "correct horse battery staple",
        }).status_code == 200
        persisted = client.cookies.get(COOKIE)
    with TestClient(create_app(config)) as client:
        client.cookies.set(COOKIE, persisted)
        assert client.get("/api/auth/me").json()["user"]["username"] == "student_one"
        assert client.get("/api/courses").json()[0]["id"] == course["id"]
        with client.app.state.auth.sessions() as db:
            db.execute(update(LoginSession).values(expires_at=int(time.time()) - 1))
            db.commit()
        assert client.get("/api/courses").status_code == 401


def test_tenant_files_model_config_and_course_isolation(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as owner:
        register(owner)
        course = owner.post("/api/courses", json={"name": "Private"}).json()["id"]
        response = owner.post(f"/api/courses/{course}/documents", files={
            "file": ("notes.docx", exam_bytes("A* search uses g+h.")),
        }, data={"document_type": "notes"})
        assert response.status_code == 201, response.text
        doc = response.json()["id"]
        assert owner.put("/api/connection", json={
            "mode": "api", "base_url": "https://model.example/v1",
            "model": "private-model", "api_key": "private-key",
        }).status_code == 200
        owner_token = owner.cookies.get(COOKIE)
        # Independent browser cookie jar, same live application/lifespan.
        owner.cookies.clear()
        register(owner, "student_two")
        assert owner.get("/api/courses").json() == []
        assert owner.get(f"/api/courses/{course}/documents").status_code == 404
        assert owner.delete(f"/api/courses/{course}").status_code == 404
        assert owner.get(f"/api/documents/{doc}/file").status_code == 404
        assert owner.delete(f"/api/documents/{doc}").status_code == 404
        profile = owner.get("/api/connection").json()
        assert profile["has_api_key"] is False and profile["mode"] == "demo"
        second = owner.post("/api/courses", json={"name": "Second"}).json()["id"]
        owner.cookies.clear()
        owner.cookies.set(COOKIE, owner_token)
        assert [c["id"] for c in owner.get("/api/courses").json()] == [course]
        assert owner.get(f"/api/courses/{second}/documents").status_code == 404
        assert owner.get("/api/connection").json()["model"] == "private-model"


def test_first_local_account_preserves_existing_database(tmp_path):
    engine, sessions = make_database(tmp_path)
    with sessions() as db:
        db.add(Course(name="Existing course"))
        db.commit()
    engine.dispose()
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get("/api/auth/me").json()["setup_required"] is True
        register(client)
        assert client.get("/api/courses").json()[0]["name"] == "Existing course"


def test_csrf_validation_duplicate_registration_and_registration_switch(tmp_path):
    with TestClient(create_app(settings(tmp_path, auth_registration_enabled=False))) as client:
        assert client.post("/api/auth/register", json={
            "username": "first", "password": "long enough password",
        }, headers={"origin": "https://attacker.example"}).status_code == 403
        register(client)
        assert client.get("/api/auth/me").json()["registration_enabled"] is False
        assert client.post("/api/auth/register", json={
            "username": "second", "password": "long enough password",
        }).status_code == 403
        assert client.post("/api/courses", json={"name": "Cross site"}, headers={
            "sec-fetch-site": "cross-site",
        }).status_code == 403
        assert client.post("/api/auth/login", json={
            "username": "bad name", "password": "short",
        }).status_code == 422
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.post("/api/auth/register", json={
            "username": "STUDENT_ONE", "password": "long enough password",
        }).status_code == 409


def test_remote_bootstrap_secure_cookie_and_rate_limit(tmp_path):
    with TestClient(create_app(settings(tmp_path)), base_url="https://study.example",
                    client=("192.0.2.1", 1234)) as client:
        assert client.post("/api/auth/register", json={
            "username": "remote", "password": "long enough password",
        }).status_code == 403
    with TestClient(create_app(settings(tmp_path, auth_cookie_secure=True)),
                    base_url="https://localhost", client=("127.0.0.1", 1234)) as client:
        assert "Secure" in register(client).headers["set-cookie"]
        for _ in range(14):
            response = client.post("/api/auth/login", json={
                "username": "student_one", "password": "wrong password",
            })
            assert response.status_code == 401
        assert client.post("/api/auth/login", json={
            "username": "student_one", "password": "wrong password",
        }).status_code == 429


def test_lazy_startup_and_authentication_do_not_open_vector_store(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        assert not app.state.workspaces.states
        assert client.get("/health").json()["startup_ms"] >= 0
        register(client)
        assert not app.state.workspaces.states
        client.get("/api/courses")
        state = app.state.workspaces.states["legacy"]
        assert state.vectors._client is None
        assert not (tmp_path / "chroma").exists()
    assert not (tmp_path / "chroma").exists()


def test_guest_shell_is_public_and_agent_operations_require_login(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/auth.js").status_code == 200
        for route in ["/api/agent", "/api/chat", "/api/generate", "/api/search"]:
            assert client.post(route, json={}).status_code == 401
        for route in ["/api/agent/tools", "/api/courses", "/api/connection"]:
            assert client.get(route).status_code == 401
        assert not client.app.state.workspaces.states
