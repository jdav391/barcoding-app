from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Migration for Phase 2: add mode and template_id columns to existing jobs table
    with engine.connect() as conn:
        result = conn.exec_driver_sql("PRAGMA table_info('jobs')")
        existing_cols = [row[1] for row in result]
        if "mode" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE jobs ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'PRESET'")
        if "template_id" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE jobs ADD COLUMN template_id INTEGER REFERENCES templates(id)")
        if "session_fk" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE jobs ADD COLUMN session_fk INTEGER REFERENCES sessions(id)")
        if "error_message" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE jobs ADD COLUMN error_message TEXT")
        result2 = conn.exec_driver_sql("PRAGMA table_info('sessions')")
        session_cols = [row[1] for row in result2]
        if "status" not in session_cols:
            conn.exec_driver_sql("ALTER TABLE sessions ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'")
        if "wizard_state" not in session_cols:
            conn.exec_driver_sql("ALTER TABLE sessions ADD COLUMN wizard_state TEXT")
        conn.commit()
