import os
from collections.abc import Generator
from pathlib import Path

from alembic.config import Config
from sqlalchemy import event, inspect
from sqlmodel import Session, create_engine

from alembic import command
from backend.core.config import settings

# Ensure data directory exists if accessible
db_url_path = settings.DATABASE_URL.replace("sqlite:///", "")
db_dir = os.path.dirname(os.path.abspath(db_url_path)) if db_url_path else None
if db_dir:
    try:
        os.makedirs(db_dir, exist_ok=True)
    except Exception:  # noqa: BLE001, S110
        pass

# Connect args for SQLite to allow multi-threading access
connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
)


# Enable WAL mode for SQLite performance and concurrent read/write support
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()


_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"
_ALEMBIC_DIR = _BACKEND_ROOT / "alembic"


def init_db() -> None:
    """Apply pending Alembic migrations.

    Schema changes are migration-owned (blueprint §28); SQLModel ``create_all`` is
    never used on startup. Databases created before Alembic adoption (which lack
    the ``alembic_version`` table) are stamped at head instead of replaying history.
    """
    cfg = Config(str(_ALEMBIC_INI))
    # Absolute script location keeps programmatic runs independent of the CWD.
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))

    existing_tables = inspect(engine).get_table_names()
    if existing_tables and "alembic_version" not in existing_tables:
        command.stamp(cfg, "head")

    command.upgrade(cfg, "head")


def get_session() -> Generator[Session, None, None]:
    """Dependency generator for FastAPI routes to get database session."""
    with Session(engine) as session:
        yield session
