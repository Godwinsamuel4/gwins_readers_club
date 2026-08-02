"""
Create/update the database schema for Gwin's Readers Club.

Behavior depends on which database RC_DATABASE_URL / DATABASE_URL points at
(see app/database.py):

  * PostgreSQL (the real deployment target): runs Base.metadata.create_all(),
    which is non-destructive — it creates any tables that don't exist yet
    and leaves existing tables/data alone. It does NOT alter existing
    tables' columns; for that you'd want a real migration tool (Alembic) if
    the schema changes after you have production data. For now, since this
    project has no Alembic migrations yet, this script is enough to get a
    fresh Postgres database up to date.

  * SQLite (local fallback only): SQLite can't retrofit constraints (unique,
    check, ON DELETE rules) onto an existing table, so for that case only
    this script backs up and rebuilds the local .db file from scratch, then
    reseeds demo data.

Run from the backend/ directory, venv active:
    python migrate_db.py
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from app.database import Base, engine, SQLALCHEMY_DATABASE_URL  # noqa: E402
from app import models  # noqa: F401,E402  (registers models on Base.metadata)


def _rebuild_sqlite():
    db_path = os.path.join(BACKEND_DIR, "readers_club.db")
    if os.path.exists(db_path):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{db_path}.bak-{stamp}"
        shutil.copy2(db_path, backup_path)
        print(f"Backed up existing database to {os.path.basename(backup_path)}")
        os.remove(db_path)
        for suffix in ("-wal", "-shm"):
            side_file = db_path + suffix
            if os.path.exists(side_file):
                os.remove(side_file)
    else:
        print("No existing SQLite database found — creating a fresh one.")

    Base.metadata.create_all(bind=engine)
    print("Created tables with the current schema.")

    if os.environ.get("SKIP_SEED") == "1":
        print("SKIP_SEED=1 set — not reseeding demo data.")
        return
    print("Reseeding demo data...")
    subprocess.run([sys.executable, os.path.join(BACKEND_DIR, "seed.py")], check=True)


def _create_postgres_tables():
    print(f"Connecting to: {SQLALCHEMY_DATABASE_URL.split('@')[-1]}")  # don't print credentials
    Base.metadata.create_all(bind=engine)
    print("Postgres schema is up to date (existing tables/data were left alone).")

    if os.environ.get("SEED") == "1":
        print("SEED=1 set — running seed.py (skips automatically if demo data already exists)...")
        subprocess.run([sys.executable, os.path.join(BACKEND_DIR, "seed.py")], check=True)
    else:
        print("Tip: run with SEED=1 if you want demo data seeded (python seed.py also works directly).")


def main():
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        _rebuild_sqlite()
    else:
        _create_postgres_tables()


if __name__ == "__main__":
    main()
