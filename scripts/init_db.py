"""Cross-platform script to initialize database tables."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.init_db import init_db

if __name__ == "__main__":
    success = init_db()
    sys.exit(0 if success else 1)
