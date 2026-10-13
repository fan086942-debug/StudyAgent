"""Each account owns its SQL database, files, vector index and model configuration."""

from threading import Lock
from types import SimpleNamespace

from pydantic import SecretStr

from app.db.session import make_database
from app.rag.embedding import APIEmbedding, DemoEmbedding
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
from app.services.connection import ModelConnection


def initialize_workspace(state, settings, http, *, private_model=False):
    engine, sessions = make_database(settings.data_dir)
    vectors = None
    try:
        state.sessions, state.http, state.engine = sessions, http, engine
        embeddings = (DemoEmbedding(settings) if settings.study_mode == "demo"
                      else APIEmbedding(settings, http))
        vectors = VectorStore(settings, embeddings.fingerprint)
        state.embeddings, state.vectors = embeddings, vectors
        state.retriever = Retriever(settings, sessions, embeddings, vectors)
        state.embedding_settings = settings
        model_defaults = settings.model_copy(update={
            "study_mode": "demo", "llm_api_key": SecretStr(""), "llm_model": "",
        }) if private_model else settings
        state.connection = ModelConnection(state, model_defaults)
        state.exams.recover_interrupted()
        state.ingestion.recover_interrupted()
        state.ingestion.mark_stale()
        return state
    except Exception:
        if vectors:
            vectors.close()
        engine.dispose()
        raise


class Workspaces:
    def __init__(self, settings, http, legacy_state=None):
        self.settings, self.http = settings, http
        self.legacy_state = legacy_state
        self.states = {}
        self.lock = Lock()

    def get(self, user):
        with self.lock:
            key = "legacy" if user.legacy_workspace else user.id
            if key not in self.states:
                if key == "legacy" and self.legacy_state is not None:
                    self.states[key] = self.legacy_state
                else:
                    directory = (self.settings.data_dir if key == "legacy"
                                 else self.settings.data_dir / "users" / user.id)
                    settings = self.settings.model_copy(update={"data_dir": directory})
                    state = SimpleNamespace()
                    initialize_workspace(state, settings, self.http, private_model=key != "legacy")
                    self.states[key] = state
            return self.states[key]

    def close(self):
        for state in self.states.values():
            state.vectors.close()
            state.engine.dispose()
