# server/db.py
import os
from sqlalchemy import create_engine, text

# Render provides postgresql://, older libs sometimes still use postgres://
DATABASE_URL = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://")

# Keep pre_ping True so broken idle connections are refreshed
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Create the tables we need if they don't exist
_DDL = """
CREATE TABLE IF NOT EXISTS stripe_events (
  id          BIGSERIAL PRIMARY KEY,
  event_id    TEXT UNIQUE NOT NULL,
  type        TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload     JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id                   BIGSERIAL PRIMARY KEY,
  customer_id          TEXT NOT NULL,
  email                TEXT,
  subscription_id      TEXT UNIQUE NOT NULL,
  price_id             TEXT,
  status               TEXT,
  current_period_end   TIMESTAMPTZ
);
"""

def create_tables() -> None:
    # Run all DDL in a single transaction
    with engine.begin() as conn:
        conn.execute(text(_DDL))

# Quick connectivity test. You'll see 'Database connection successful' in logs.
def ping() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
