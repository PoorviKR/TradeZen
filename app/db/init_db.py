"""Database table creation and migration helper.

Run with:
    python -m app.db.init_db
"""

import sys
import logging
from sqlalchemy import text
from app.db.base import Base
from app.db.session import engine
from app.core.config import settings

# Import all models to ensure they are registered with Base.metadata
import app.models  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tradezen.init_db")


def init_db() -> bool:
    """Creates all tables defined in SQLAlchemy models if they do not exist."""
    logger.info("Initializing PostgreSQL database...")
    logger.info("Checking connection to PostgreSQL...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();")).scalar()
            logger.info("Connected to PostgreSQL successfully: %s", result)

        logger.info("Creating all database tables via SQLAlchemy metadata...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully!")
        return True
    except Exception as exc:
        logger.error("Failed to initialize database: %s", exc)
        logger.error("Ensure PostgreSQL is running and DATABASE_URL is correctly configured in .env.")
        logger.error("You can start PostgreSQL via Docker: docker-compose up -d")
        return False


if __name__ == "__main__":
    success = init_db()
    sys.exit(0 if success else 1)
