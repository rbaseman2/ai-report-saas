
# server/db.py
import os
from sqlalchemy import create_engine

# Read from Render environment variable
url = os.getenv("DATABASE_URL")

# (Render may prefix it with postgres:// instead of postgresql://)
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

# Create SQLAlchemy engine
engine = create_engine(url, pool_pre_ping=True)
