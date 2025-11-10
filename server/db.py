# server/db.py
import os
from sqlalchemy import create_engine

url = os.environ.get("DATABASE_URL", "")
if not url:
    raise RuntimeError("DATABASE_URL not set")

# Render may give postgres:// – normalize it
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

# Tell SQLAlchemy to use psycopg v3
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, pool_pre_ping=True)

