# TradeZen: Behavioral Trading Scenario Coach

TradeZen is an educational simulation platform designed to help retail traders eliminate emotional biases (such as revenge trading, panic selling, FOMO buying, and averaging down) by comparing live decisions against deterministic risk rules and machine-learning mistake models.

---

## Architecture & Cross-Platform Design

- **Backend**: Python 3.10+ with FastAPI, SQLAlchemy, Alembic, and Argon2 password hashing.
- **Frontend**: React 18 with Vite, Tailwind CSS (dark mode), and Recharts.
- **Database**: PostgreSQL only (`DATABASE_URL`).
- **Portability**: All paths resolved dynamically using Python `pathlib.Path` relative to project root. No hardcoded drive letters, user home folders, or localhost addresses.
- **Network & Mobile Friendly**: Backend binds to `0.0.0.0`, Vite dev server allows network access, and frontend API client communicates via relative Vite proxy or environment variables. Any device (phone/tablet) on the same Wi-Fi network can open and use the application.

---

## Prerequisites

Before starting, ensure you have the following installed on your machine:
- **Python**: 3.10 or newer
- **Node.js**: 18.x or newer (with `npm`)
- **PostgreSQL**: 15 or newer (or Docker Desktop)
- **Git** (optional for version control)

---

## Quickstart (Windows PowerShell)

Open PowerShell and navigate to the project directory:

### 1. Database Setup
Ensure PostgreSQL is running locally. Open `psql` or run via PostgreSQL command line:
```powershell
# Create database 'tradezen'
psql -U postgres -c "CREATE DATABASE tradezen;"
```
*(Alternative: If using Docker, simply run `docker-compose up -d`)*

### 2. Configure Environment Variables
Copy the template configuration into `.env`:
```powershell
Copy-Item .env.example .env
```
Open `.env` and verify your PostgreSQL credentials in `DATABASE_URL` (default: `postgresql+psycopg2://postgres:postgres@localhost:5432/tradezen`).

### 3. Backend Setup
Create and activate a virtual environment, then install Python dependencies:
```powershell
# (Optional) If script execution is restricted in your PowerShell:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Create a local virtual environment (.venv is ignored by git)
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install pinned dependencies
pip install -r requirements.txt
```

### 4. Frontend Setup
Install frontend dependencies:
```powershell
cd frontend
npm install
cd ..
```

### 5. Initialize Database & Run Migrations
Run the database initialization script to create all tables and apply migrations:
```powershell
python -m app.db.init_db
```
Or run Alembic migrations directly:
```powershell
alembic upgrade head
```

### 6. Run Tests
Verify system portability, security, and functionality:
```powershell
pytest
```

### 7. Start Backend Server
```powershell
python -m app.main
```
Backend will start on `http://0.0.0.0:8000` (API docs at `http://localhost:8000/api/v1/docs`).

### 8. Start Frontend Development Server
In a new terminal:
```powershell
cd frontend
npm run dev
```
Frontend will be available at `http://localhost:5173`.

---

## Quickstart (macOS)

Open Terminal:

### 1. Install Prerequisites & Create Database
```bash
# Using Homebrew
brew install python node postgresql@16

# Start PostgreSQL service
brew services start postgresql@16

# Create the tradezen database
createdb tradezen
```

### 2. Environment Configuration
```bash
cp .env.example .env
```

### 3. Backend Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Frontend Setup
```bash
cd frontend
npm install
cd ..
```

### 5. Initialize Database
```bash
python3 -m app.db.init_db
```

### 6. Run Tests
```bash
pytest
```

### 7. Start Servers
Backend:
```bash
python3 -m app.main
```
Frontend (in a separate terminal):
```bash
cd frontend
npm run dev
```

---

## Quickstart (Linux / Ubuntu)

Open bash terminal:

### 1. Install Prerequisites & Create Database
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nodejs npm postgresql postgresql-contrib

# Start PostgreSQL service
sudo systemctl start postgresql

# Create database and user
sudo -u postgres psql -c "CREATE DATABASE tradezen;"
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"
```

### 2. Environment Configuration
```bash
cp .env.example .env
```

### 3. Backend Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Frontend Setup
```bash
cd frontend
npm install
cd ..
```

### 5. Initialize Database
```bash
python3 -m app.db.init_db
```

### 6. Run Tests
```bash
pytest
```

### 7. Start Applications
Backend:
```bash
python3 -m app.main
```
Frontend:
```bash
cd frontend
npm run dev
```

---

## Accessing from Another Device (Phone / Tablet on Same Wi-Fi)

TradeZen is designed to run seamlessly from any phone or browser on your local network:

1. Find your host machine's local IP address:
   - **Windows**: Run `ipconfig` (look for `IPv4 Address`, e.g., `192.168.1.45`)
   - **Mac/Linux**: Run `ifconfig` or `ip a` (look for `inet 192.168.x.x`)
2. Ensure both the computer running TradeZen and your phone are on the **same Wi-Fi network**.
3. On your phone's browser, navigate to:
   ```
   http://<YOUR_LAPTOP_IP>:5173
   ```
   (Example: `http://192.168.1.45:5173`)
4. The Vite dev server proxies API calls automatically to the backend on port 8000, and CORS is pre-configured via `ALLOWED_ORIGINS` in `.env`.

---

## Project Structure

```
TRADEZEN Scenario Simulation/
├── .env.example            # Configuration template (no secrets in git)
├── .gitattributes          # Enforces LF line endings across all platforms
├── .gitignore              # Ignores .venv, node_modules, .env, and ML models
├── alembic.ini             # Database migration configuration
├── docker-compose.yml      # Optional single-command PostgreSQL setup
├── requirements.txt        # Pinned cross-platform Python dependencies
├── pytest.ini              # Pytest configuration
├── README.md               # Cross-platform installation and setup guide
├── app/
│   ├── main.py             # FastAPI entrypoint (binds to 0.0.0.0)
│   ├── core/
│   │   ├── config.py       # Pydantic Settings reading strictly from .env
│   │   └── security.py     # Argon2 hashing + JWT token management
│   ├── db/
│   │   ├── base.py         # SQLAlchemy Base
│   │   ├── session.py      # PostgreSQL session generator
│   │   └── init_db.py      # Table creation and connection verification
│   ├── models/             # User, Rule, Scenario, Attempt, BotDecision, Prediction
│   ├── schemas/            # Pydantic input/output validation models
│   ├── services/           # Deterministic rule checking
│   └── api/v1/             # Auth, Rules, Scenarios, Decisions, Health
├── migrations/             # Alembic migration scripts
├── frontend/
│   ├── package.json        # Frontend scripts and pinned packages
│   ├── package-lock.json   # Reproducible dependency lock
│   ├── vite.config.js      # Network-accessible dev server with API proxy
│   ├── tailwind.config.js  # Theme mapped to CSS color tokens
│   └── src/
│       ├── api/client.js   # API client (no hard-coded localhost)
│       └── App.jsx         # Mobile-first responsive UI
└── tests/
    ├── conftest.py         # Pytest fixtures and test database isolation
    ├── test_portability.py # Automated check: fails on absolute paths or localhost
    ├── test_config.py      # Settings and PostgreSQL validation tests
    ├── test_auth.py        # Authentication & rate-limiting tests
    ├── test_rules.py       # Rules versioning and isolation tests
    ├── test_scenarios.py   # Scenarios, reveals, and decision feedback tests
    └── test_api.py         # Health, metadata, and CORS tests
```

---

## License & Disclaimer
TradeZen is an educational simulator for behavioral finance research and training. It does not provide financial or investment advice.
