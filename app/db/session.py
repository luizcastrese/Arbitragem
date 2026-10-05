from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import database_connect_args, get_settings


DATABASE_URL = get_settings().database_url
connect_args = database_connect_args(DATABASE_URL)

if DATABASE_URL.startswith("sqlite:///./"):
    Path(DATABASE_URL.removeprefix("sqlite:///./")).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
