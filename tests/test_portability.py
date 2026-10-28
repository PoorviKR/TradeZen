"""Portability, cleanliness, and configuration test suite.

Fails if any absolute path, drive letter, user home/OneDrive folder,
or hard-coded localhost appears anywhere in the source code.
Also validates .gitignore, .gitattributes, and .env.example specifications.
"""

import re
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories to scan for hardcoded paths or localhost
SOURCE_DIRS = [
    PROJECT_ROOT / "app",
    PROJECT_ROOT / "scripts",
    PROJECT_ROOT / "frontend" / "src",
    PROJECT_ROOT / "migrations",
]

# Forbidden path patterns
FORBIDDEN_PATTERNS = [
    # Windows drive letters: C:\, D:/, etc.
    (re.compile(r'\b[a-zA-Z]:[\\/]'), "Hard-coded Windows drive letter detected"),
    # Home directory paths
    (re.compile(r'/Users/[a-zA-Z0-9_-]+'), "Mac/Unix user home path detected"),
    (re.compile(r'/home/[a-zA-Z0-9_-]+'), "Linux user home path detected"),
    (re.compile(r'[\\/]Users[\\/][a-zA-Z0-9_-]+'), "Windows user folder path detected"),
    # OneDrive / Desktop specific paths
    (re.compile(r'OneDrive', re.IGNORECASE), "OneDrive path fragment detected"),
    # Hardcoded localhost in production code (should come from env / settings / proxy)
    (re.compile(r'https?://localhost(?::\d+)?', re.IGNORECASE), "Hard-coded localhost URL detected"),
    (re.compile(r'https?://127\.0\.0\.1(?::\d+)?'), "Hard-coded 127.0.0.1 URL detected"),
]

# File extensions to check
ALLOWED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".html"}

# Ignored files (e.g. package-lock.json with external registry URLs)
IGNORED_FILES = {"package-lock.json"}


def test_no_absolute_paths_or_hardcoded_localhost():
    """Ensure no hard-coded machine-specific paths or localhost exist in source code."""
    violations = []

    for source_dir in SOURCE_DIRS:
        if not source_dir.exists():
            continue

        for file_path in source_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix not in ALLOWED_EXTENSIONS:
                continue
            if file_path.name in IGNORED_FILES:
                continue
            # Skip python cache
            if "__pycache__" in file_path.parts:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                violations.append(f"Could not read {file_path}: {e}")
                continue

            for line_no, line in enumerate(content.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("/*"):
                    continue

                for pattern, desc in FORBIDDEN_PATTERNS:
                    if pattern.search(line):
                        rel_path = file_path.relative_to(PROJECT_ROOT)
                        violations.append(
                            f"{rel_path}:{line_no} - {desc}\n  Line: {stripped}"
                        )

    assert not violations, "Portability test failed! Found machine-specific paths or localhost:\n" + "\n".join(violations)


def test_gitignore_contains_required_rules():
    """Verify .gitignore properly blocks .venv, node_modules, __pycache__, .env, and models."""
    gitignore_path = PROJECT_ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore file must exist"

    content = gitignore_path.read_text(encoding="utf-8")
    required_entries = [".venv", "node_modules", "__pycache__", ".env", "*.joblib"]

    for entry in required_entries:
        assert entry in content, f".gitignore is missing required pattern: {entry}"


def test_gitattributes_exists_and_enforces_lf():
    """Verify .gitattributes enforces cross-platform consistent line endings."""
    gitattributes_path = PROJECT_ROOT / ".gitattributes"
    assert gitattributes_path.exists(), ".gitattributes file must exist"

    content = gitattributes_path.read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in content or "eol=lf" in content


def test_env_example_contains_all_required_variables():
    """Verify .env.example contains all required environment variable keys."""
    env_example = PROJECT_ROOT / ".env.example"
    assert env_example.exists(), ".env.example must exist"

    content = env_example.read_text(encoding="utf-8")
    required_vars = [
        "DATABASE_URL",
        "UPSTOX_ANALYTICS_TOKEN",
        "JWT_SECRET",
        "ALLOWED_ORIGINS",
        "API_BASE_URL",
        "HOST",
        "PORT",
    ]
    for var in required_vars:
        assert f"{var}=" in content, f".env.example is missing required variable: {var}"


def test_docker_compose_postgresql_configuration():
    """Verify docker-compose.yml configures PostgreSQL correctly."""
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist"

    content = compose_path.read_text(encoding="utf-8")
    assert "postgres" in content.lower()
    assert "5432:5432" in content
    assert "pgdata:" in content
