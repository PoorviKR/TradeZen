"""Cross-platform script to start the TradeZen FastAPI server."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.main import start_server

if __name__ == "__main__":
    start_server()
