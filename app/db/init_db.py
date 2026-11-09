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

        # Self-healing column synchronization for future model extensions
        from sqlalchemy import inspect
        with engine.begin() as sync_conn:
            inspector = inspect(sync_conn)
            existing_tables = set(inspector.get_table_names())
            for table_name, table in Base.metadata.tables.items():
                if table_name in existing_tables:
                    existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
                    for col in table.columns:
                        if col.name not in existing_cols:
                            col_type = col.type.compile(engine.dialect)
                            default_clause = ""
                            if col.server_default is not None:
                                default_clause = f" DEFAULT {col.server_default.arg}"
                            elif col.nullable:
                                default_clause = " DEFAULT NULL"
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause};"
                            logger.info("Self-healing schema migration: %s", sql)
                            sync_conn.execute(text(sql))

            # Ensure unique index for PostgreSQL upsert on raw_candles
            if engine.dialect.name == "postgresql" and "raw_candles" in existing_tables:
                sync_conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_candles_symbol_timestamp "
                    "ON raw_candles (symbol, timestamp);"
                ))

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
