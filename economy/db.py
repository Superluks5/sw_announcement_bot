"""
Economy database engine/session setup.
------------------------------------------
SQLite, gitignored (per-machine, like your other *_data.json files) - lives
at economy/economy.db. Chosen over Postgres deliberately: this bot runs on
a 1GB Oracle Free Tier VM, single-server-at-a-time, and SQLite's own
transaction/locking model is more than sufficient at this scale. Models are
written against plain SQLAlchemy so a future move to Postgres (if this ever
runs across many servers) is a connection-string change, not a rewrite.

WAL mode is enabled so reads (dashboard) don't block writes (bot) and vice
versa - important since the bot and dashboard are separate processes both
touching this same file.
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DB_PATH = os.path.join(os.path.dirname(__file__), "economy.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False, future=True)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")  # wait up to 5s on lock contention instead of erroring immediately
    cursor.close()


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db():
    """Creates all tables that don't exist yet. Safe to call every startup -
    never drops or alters existing tables."""
    import economy.models  # noqa: F401 - ensures models are registered before create_all
    Base.metadata.create_all(engine)
