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
                            # Add as nullable first to allow backfilling existing rows
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} DEFAULT NULL;"
                            logger.info("Self-healing schema migration: %s", sql)
                            sync_conn.execute(text(sql))

                            # Specific backfill for users.username if it was just added
                            if table_name == "users" and col.name == "username":
                                if engine.dialect.name == "postgresql":
                                    sync_conn.execute(text(
                                        "UPDATE users SET username = LOWER(REGEXP_REPLACE(SPLIT_PART(email, '@', 1), '[^a-zA-Z0-9_]', '_', 'g')) "
                                        "WHERE username IS NULL;"
                                    ))
                                    # Fallback in case any row had empty prefix
                                    sync_conn.execute(text(
                                        "UPDATE users SET username = 'user_' || id WHERE username IS NULL OR LENGTH(username) < 3;"
                                    ))
                                    sync_conn.execute(text("ALTER TABLE users ALTER COLUMN username SET NOT NULL;"))
                                    sync_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username);"))
                                else:
                                    sync_conn.execute(text(
                                        "UPDATE users SET username = 'user_' || id WHERE username IS NULL;"
                                    ))

                            # For other non-nullable columns, apply default if specified
                            elif not col.nullable and col.server_default is not None:
                                default_val = col.server_default.arg
                                sync_conn.execute(text(f"UPDATE {table_name} SET {col.name} = {default_val} WHERE {col.name} IS NULL;"))
                                if engine.dialect.name == "postgresql":
                                    sync_conn.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN {col.name} SET NOT NULL;"))

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
