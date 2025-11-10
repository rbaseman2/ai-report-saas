# server/db.py
import os
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
url = url.replace("postgres://", "postgresql://", 1)

engine = create_engine(url, pool_pre_ping=True)

# 🔽 Add this block at the bottom
if __name__ == "__main__":
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Database connection successful")
    except Exception as e:
        print("❌ Database connection failed:", e)

