"""Persistent users and revocable, opaque cookie sessions; no signing secret required."""

import hashlib
import hmac
import secrets
import sqlite3
import time
from collections import deque
from threading import Lock

from sqlalchemy import Boolean, ForeignKey, Integer, String, create_engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.errors import AppError
from app.models import new_id

COOKIE = "study_session"


class AuthBase(DeclarativeBase):
    pass


class User(AuthBase):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    legacy_workspace: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class LoginSession(AuthBase):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=bytes.fromhex(salt), n=32768, r=8, p=3,
        maxmem=64 * 1024 * 1024,
    ).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password, stored):
    try:
        algorithm, salt, _ = stored.split("$")
        return algorithm == "scrypt" and hmac.compare_digest(hash_password(password, salt), stored)
    except (ValueError, TypeError):
        return False


def public_user(user):
    return {"id": user.id, "username": user.username}


class AuthService:
    def __init__(self, settings):
        self.settings = settings
        directory = settings.data_dir / "auth"
        directory.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{(directory / 'users.db').as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        AuthBase.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.lock = Lock()
        self.attempts = {}
        # A deliberately invalid digest still performs exactly the same KDF on missing users.
        self.dummy_hash = "scrypt$" + "0" * 32 + "$" + "0" * 128

    def has_users(self):
        with self.sessions() as session:
            return session.scalar(select(User.id).limit(1)) is not None

    def throttle(self, address):
        now = time.monotonic()
        with self.lock:
            # Bound memory even when many addresses try to create accounts.
            self.attempts = {k: v for k, v in self.attempts.items() if v[-1] > now - 300}
            if address not in self.attempts and len(self.attempts) >= 4096:
                raise AppError("auth_rate_limit", "请求过于频繁，请稍后再试", 429)
            attempts = self.attempts.setdefault(address, deque())
            while attempts and attempts[0] <= now - 300:
                attempts.popleft()
            if len(attempts) >= 15:
                raise AppError("auth_rate_limit", "尝试过于频繁，请五分钟后再试", 429)
            attempts.append(now)

    def remote_setup_allowed(self):
        if not self.settings.auth_allow_remote_setup:
            return False
        uploads = self.settings.data_dir / "uploads"
        if uploads.exists() and any(uploads.iterdir()):
            return False
        database = (self.settings.data_dir / "studyagent.db").resolve()
        if database.exists():
            try:
                with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
                    names = {row[0] for row in db.execute("select name from sqlite_master where type='table'")}
                    for name in ("courses", "documents", "conversations", "study_artifacts"):
                        if name in names and db.execute(f'SELECT 1 FROM "{name}" LIMIT 1').fetchone():
                            return False
            except sqlite3.Error:
                return False
        return True

    def register(self, username, password, local):
        password_hash = hash_password(password)
        with self.sessions() as session:
            # Serialize first-account creation across processes as well as threads.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            first = session.scalar(select(User.id).limit(1)) is None
            if first and not local and not self.remote_setup_allowed():
                raise AppError("setup_local_only", "请先在服务器本机创建首个账号", 403)
            if not first and not self.settings.auth_registration_enabled:
                raise AppError("registration_closed", "注册已关闭，请联系管理员", 403)
            user = User(username=username, password_hash=password_hash, legacy_workspace=first and local)
            session.add(user)
            try:
                session.commit()
            except IntegrityError as exc:
                raise AppError("username_taken", "该用户名已被使用", 409) from exc
            return user

    def login(self, username, password):
        with self.sessions() as session:
            user = session.scalar(select(User).where(User.username == username))
            valid = verify_password(password, user.password_hash if user else self.dummy_hash)
            if not user or not valid:
                raise AppError("invalid_credentials", "用户名或密码不正确", 401)
            return user

    def create_session(self, user, previous=None):
        token = secrets.token_urlsafe(32)
        with self.sessions() as session:
            session.execute(delete(LoginSession).where(LoginSession.expires_at <= int(time.time())))
            if previous:
                session.execute(delete(LoginSession).where(
                    LoginSession.token_hash == hashlib.sha256(previous.encode()).hexdigest()
                ))
            session.add(LoginSession(
                token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                expires_at=int(time.time()) + self.settings.auth_session_hours * 3600,
            ))
            session.commit()
        return token

    def authenticate(self, token):
        if not token or len(token) > 128:
            return None
        with self.sessions() as session:
            return session.scalar(select(User).join(LoginSession).where(
                LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                LoginSession.expires_at > int(time.time()),
            ))

    def logout(self, token):
        if token:
            with self.sessions() as session:
                session.execute(delete(LoginSession).where(
                    LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest()
                ))
                session.commit()
