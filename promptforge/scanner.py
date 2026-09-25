"""
Project Scanner - Automatic project analysis and configuration generation.

This module provides functionality to scan a project directory and automatically
detect languages, frameworks, databases, code conventions, tests, and infrastructure.
It generates a comprehensive Markdown configuration file for PromptForge.

Security Features:
- CVE checking via OSV.dev API
- Language-specific security guidelines
- OWASP Top 10 reminders
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .security import (
    SecurityContext,
    CVEInfo,
    SecretFinding,
    get_security_guidelines,
    scan_directory_for_secrets,
    format_secret_alerts,
    OWASP_TOP_10,
    SECURITY_KEYWORDS,
)


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_IGNORE_PATTERNS = [
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    "htmlcov",
    ".idea",
    ".vscode",
    "*.egg-info",
    ".tox",
    ".nox",
    ".gradle",
    ".dart_tool",
    ".pub-cache",
]

LANGUAGE_EXTENSIONS = {
    "Python": [".py", ".pyw", ".pyi"],
    "TypeScript": [".ts", ".tsx"],
    "JavaScript": [".js", ".jsx", ".mjs", ".cjs"],
    "Go": [".go"],
    "Rust": [".rs"],
    "Java": [".java"],
    "Kotlin": [".kt", ".kts"],
    "C#": [".cs"],
    "C": [".c", ".h"],
    "C++": [".cpp", ".cc", ".cxx", ".hpp", ".hxx"],
    "Ruby": [".rb"],
    "PHP": [".php"],
    "Swift": [".swift"],
    "Scala": [".scala"],
    "Dart": [".dart"],
    "Vue": [".vue"],
    "Svelte": [".svelte"],
    "HTML": [".html", ".htm"],
    "CSS": [".css", ".scss", ".sass", ".less"],
    "SQL": [".sql"],
    "Shell": [".sh", ".bash", ".zsh"],
    "PowerShell": [".ps1", ".psm1"],
}


def _version_sort_key(version: str) -> tuple[int, ...]:
    """Ordonne deux versions pointees sur leurs composants numeriques."""
    return tuple(int(part) for part in version.split(".") if part.isdigit())


# Operateurs qui ne designent jamais une borne basse : ils plafonnent (`<`, `<=`)
# ou excluent (`!=`). La version qu'ils portent n'est pas une version du projet.
_UPPER_OR_EXCLUDING_OPERATORS = frozenset({"<", "<=", "!="})

# Un couple operateur/version. L'operateur est optionnel : une contrainte peut
# etre une version nue (`3.12.0`, `v18.14.2`). L'ordre des alternatives compte :
# `>=` doit etre tente avant `>`, `~=` avant `~`, sinon l'operateur long est
# tronque et sa moitie restante est lue comme un separateur.
_CONSTRAINT_CLAUSE_RE = re.compile(r"(>=|<=|!=|==|~=|\^|>|<|~|=)?\s*v?(\d+(?:\.\d+)*)")


def normalize_version_constraint(raw: str | None) -> str | None:
    """Extract the lower bound of a raw version constraint.

    Version files hold constraints, not versions: `>=3.11`, `^3.11`, `~=3.10`,
    `>=3.10,<3.13`, `v18.14.2`. Reporting the constraint verbatim is what makes a
    scanned project claim to run "version >=3.11", and what would feed a
    constraint string to a CVE lookup.

    What is returned is the **lower bound**, and only it. Every clause is read
    with its operator: `<` and `<=` only cap, `!=` only excludes, so none of them
    ever names a version the project runs on, and all three are dropped. When
    several clauses raise the floor, the highest floor wins. When no clause
    states a floor at all (`<4`, `!=3.9`), the result is None: turning a cap or
    an exclusion into a reported version is exactly the false positive this
    project forbids.

    Known approximation, deliberate and pinned by a test: `>3.10` is a strict
    lower bound, so 3.10 itself is excluded, yet 3.10 is returned. It is the
    closest floor the constraint states, and naming the next released version
    would require an index of releases that this scanner does not have and must
    not fetch.

    Args:
        raw: The raw captured string, possibly a constraint expression.

    Returns:
        The lowest version the constraint accepts, or the stripped input when it
        holds no number at all (`stable`, `latest`), or None when the input is
        empty or states no lower bound at all.
    """
    if raw is None:
        return None

    cleaned = raw.strip().strip("\"'")
    if not cleaned:
        return None

    clauses = _CONSTRAINT_CLAUSE_RE.findall(cleaned)
    if not clauses:
        # Pas de chiffre du tout : `stable`, `latest`, `nightly`. On rend la
        # valeur telle quelle plutot que None, c'est une information vraie.
        return cleaned

    lower_bounds = [
        version
        for operator, version in clauses
        if operator not in _UPPER_OR_EXCLUDING_OPERATORS
    ]
    if not lower_bounds:
        return None

    return max(lower_bounds, key=_version_sort_key)


# Fichiers porteurs d'une version de langage, par langage.
#
# Les motifs capturent la chaine brute, contrainte comprise (`>=3.11`, `^3.11`,
# `~=3.10`) ; c'est `normalize_version_constraint` qui en extrait la version.
VERSION_FILES = {
    "Python": [
        # Le lookbehind empeche ce motif Poetry de capturer aussi le `python` de la
        # cle PEP 621 `requires-python`. Effet mesure, sur un fichier portant les
        # deux cles avec des valeurs distinctes : avec lookbehind -> `^3.9` (la
        # vraie cle Poetry), sans lookbehind -> `>=3.11` (rencontre plus tot).
        # Verrou : tests/test_scanner.py::TestPythonVersionDetection::
        # test_poetry_key_wins_over_requires_python_when_both_are_present.
        ("pyproject.toml", r'(?<![\w-])python\s*=\s*["\']([^"\']+)["\']'),
        ("pyproject.toml", r'requires-python\s*=\s*["\']([^"\']+)["\']'),
        (".python-version", r"^(\d+\.\d+(?:\.\d+)?)"),
        ("runtime.txt", r"python-(\d+\.\d+(?:\.\d+)?)"),
    ],
    "Node.js": [
        ("package.json", r'"node"\s*:\s*["\']([^"\']+)["\']'),
        (".nvmrc", r"^v?(\d+(?:\.\d+)*)"),
        (".node-version", r"^v?(\d+(?:\.\d+)*)"),
    ],
    "Go": [
        ("go.mod", r"^go\s+(\d+\.\d+)"),
    ],
    "Rust": [
        ("rust-toolchain.toml", r'channel\s*=\s*["\']([^"\']+)["\']'),
        ("rust-toolchain", r"^(\d+\.\d+(?:\.\d+)?)"),
    ],
    "Java": [
        ("pom.xml", r"<java\.version>(\d+(?:\.\d+)*)</java\.version>"),
        ("build.gradle", r"sourceCompatibility\s*=\s*['\"]?(\d+(?:\.\d+)*)['\"]?"),
    ],
}

FRAMEWORK_SIGNATURES = {
    # Python Backend
    "FastAPI": {
        "files": ["requirements.txt", "pyproject.toml", "setup.py"],
        "pattern": r"fastapi",
        "category": "backend",
    },
    "Django": {
        "files": ["requirements.txt", "pyproject.toml", "manage.py"],
        "pattern": r"django(?!-)",
        "category": "backend",
    },
    "Flask": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"flask(?!-)",
        "category": "backend",
    },
    "Starlette": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"starlette",
        "category": "backend",
    },
    # Python UI/Web Frameworks
    "Gradio": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"gradio",
        "category": "ui",
    },
    "Streamlit": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"streamlit",
        "category": "ui",
    },
    "Panel": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"panel(?!-)",
        "category": "ui",
    },
    "Dash": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"dash(?!-)",
        "category": "ui",
    },
    "Nicegui": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"nicegui",
        "category": "ui",
    },
    # Python ORM
    "SQLAlchemy": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"sqlalchemy",
        "category": "orm",
    },
    "Tortoise ORM": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"tortoise-orm",
        "category": "orm",
    },
    "Peewee": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"peewee",
        "category": "orm",
    },
    # Python Libraries (common)
    "Pydantic": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"pydantic",
        "category": "validation",
    },
    "httpx": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"httpx",
        "category": "http",
    },
    "requests": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"requests(?!-)",
        "category": "http",
    },
    "aiohttp": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"aiohttp",
        "category": "http",
    },
    "Celery": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"celery",
        "category": "task-queue",
    },
    "RQ": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"rq(?!-)",
        "category": "task-queue",
    },
    "Dramatiq": {
        "files": ["requirements.txt", "pyproject.toml"],
        "pattern": r"dramatiq",
        "category": "task-queue",
    },
    # JavaScript/TypeScript Frontend
    "React": {
        "files": ["package.json"],
        "pattern": r'"react"\s*:',
        "category": "frontend",
    },
    "Vue": {
        "files": ["package.json"],
        "pattern": r'"vue"\s*:',
        "category": "frontend",
    },
    "Angular": {
        "files": ["package.json", "angular.json"],
        "pattern": r'"@angular/core"',
        "category": "frontend",
    },
    "Svelte": {
        "files": ["package.json"],
        "pattern": r'"svelte"\s*:',
        "category": "frontend",
    },
    "Next.js": {
        "files": ["package.json", "next.config.js", "next.config.mjs", "next.config.ts"],
        "pattern": r'"next"\s*:',
        "category": "frontend",
    },
    "Nuxt": {
        "files": ["package.json", "nuxt.config.ts", "nuxt.config.js"],
        "pattern": r'"nuxt"\s*:',
        "category": "frontend",
    },
    "Astro": {
        "files": ["package.json", "astro.config.mjs"],
        "pattern": r'"astro"\s*:',
        "category": "frontend",
    },
    # JavaScript/TypeScript Backend
    "Express": {
        "files": ["package.json"],
        "pattern": r'"express"\s*:',
        "category": "backend",
    },
    "NestJS": {
        "files": ["package.json"],
        "pattern": r'"@nestjs/core"',
        "category": "backend",
    },
    "Fastify": {
        "files": ["package.json"],
        "pattern": r'"fastify"\s*:',
        "category": "backend",
    },
    "Koa": {
        "files": ["package.json"],
        "pattern": r'"koa"\s*:',
        "category": "backend",
    },
    # Go
    "Gin": {
        "files": ["go.mod"],
        "pattern": r"github\.com/gin-gonic/gin",
        "category": "backend",
    },
    "Echo": {
        "files": ["go.mod"],
        "pattern": r"github\.com/labstack/echo",
        "category": "backend",
    },
    "Fiber": {
        "files": ["go.mod"],
        "pattern": r"github\.com/gofiber/fiber",
        "category": "backend",
    },
    # Rust
    "Actix Web": {
        "files": ["Cargo.toml"],
        "pattern": r"actix-web",
        "category": "backend",
    },
    "Rocket": {
        "files": ["Cargo.toml"],
        "pattern": r'rocket\s*=',
        "category": "backend",
    },
    "Axum": {
        "files": ["Cargo.toml"],
        "pattern": r'axum\s*=',
        "category": "backend",
    },
    # CSS/UI
    "TailwindCSS": {
        "files": ["tailwind.config.js", "tailwind.config.ts", "tailwind.config.cjs"],
        "pattern": None,
        "category": "ui",
    },
    "Bootstrap": {
        "files": ["package.json"],
        "pattern": r'"bootstrap"\s*:',
        "category": "ui",
    },
    "Material UI": {
        "files": ["package.json"],
        "pattern": r'"@mui/material"',
        "category": "ui",
    },
    "Chakra UI": {
        "files": ["package.json"],
        "pattern": r'"@chakra-ui/react"',
        "category": "ui",
    },
    # State Management
    "Redux": {
        "files": ["package.json"],
        "pattern": r'"redux"|"@reduxjs/toolkit"',
        "category": "state",
    },
    "Zustand": {
        "files": ["package.json"],
        "pattern": r'"zustand"\s*:',
        "category": "state",
    },
    "Pinia": {
        "files": ["package.json"],
        "pattern": r'"pinia"\s*:',
        "category": "state",
    },
    "MobX": {
        "files": ["package.json"],
        "pattern": r'"mobx"\s*:',
        "category": "state",
    },
    # Dart/Flutter
    "Flutter": {
        "files": ["pubspec.yaml"],
        "pattern": r"flutter:",
        "category": "mobile",
    },
    # Prisma
    # Une seule entree : deux cles "Prisma" dans ce dict faisaient que la
    # seconde (JS) ecrasait silencieusement la premiere (Python, prisma-client-py).
    "Prisma": {
        "files": ["schema.prisma", "package.json", "requirements.txt", "pyproject.toml"],
        "pattern": r'(?m)"prisma"|"@prisma/client"|prisma-client|^\s*prisma\b',
        "category": "orm",
    },
}

DATABASE_SIGNATURES = {
    "PostgreSQL": {
        "docker": ["postgres", "postgresql"],
        "env_patterns": [r"POSTGRES_", r"DATABASE_URL.*postgres"],
        "packages": ["psycopg2", "psycopg", "asyncpg", "pg", "postgres"],
    },
    "MySQL": {
        "docker": ["mysql", "mariadb"],
        "env_patterns": [r"MYSQL_", r"DATABASE_URL.*mysql"],
        "packages": ["mysql-connector", "pymysql", "mysql2", "mysqlclient"],
    },
    "SQLite": {
        "files": ["*.sqlite", "*.db", "*.sqlite3"],
        "packages": ["sqlite3", "better-sqlite3"],
    },
    "MongoDB": {
        "docker": ["mongo", "mongodb"],
        "env_patterns": [r"MONGO_", r"MONGODB_URI"],
        "packages": ["pymongo", "mongoose", "mongodb", "motor"],
    },
    "Redis": {
        "docker": ["redis"],
        "env_patterns": [r"REDIS_"],
        "packages": ["redis", "ioredis", "aioredis"],
    },
    "Elasticsearch": {
        "docker": ["elasticsearch"],
        "packages": ["elasticsearch", "@elastic/elasticsearch"],
    },
}

# Manifestes partages par tout un ecosysteme : leur simple presence ne prouve
# rien sur un outil donne, il faut y chercher le motif. A l'inverse, un fichier de
# configuration dedie (`vitest.config.ts`, `pytest.ini`, `.mocharc.json`) porte le
# nom de son outil : son existence est la preuve, et exiger en plus un motif de
# contenu revient a exiger qu'un fichier de config se declare lui-meme comme une
# dependance, ce qu'il ne fait jamais.
SHARED_MANIFEST_FILES = {
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "Gemfile",
    "requirements.txt",
}

TEST_SIGNATURES = {
    "pytest": {
        "files": ["pytest.ini", "conftest.py", "pyproject.toml"],
        "dirs": ["tests", "test"],
        "pattern": r"\[tool\.pytest|pytest",
        "category": "python",
    },
    "unittest": {
        "dirs": ["tests", "test"],
        "pattern": r"import unittest|from unittest",
        "category": "python",
    },
    "Jest": {
        "files": ["jest.config.js", "jest.config.ts", "jest.config.cjs", "package.json"],
        "dirs": ["__tests__", "tests"],
        "pattern": r'"jest"\s*:|"@types/jest"',
        "category": "javascript",
    },
    "Vitest": {
        "files": ["vitest.config.ts", "vitest.config.js", "package.json"],
        "pattern": r'"vitest"\s*:',
        "category": "javascript",
    },
    "Mocha": {
        "files": [".mocharc.js", ".mocharc.json", "package.json"],
        "pattern": r'"mocha"\s*:',
        "category": "javascript",
    },
    "Cypress": {
        "files": ["cypress.config.js", "cypress.config.ts", "cypress.json"],
        "dirs": ["cypress"],
        "pattern": r'"cypress"\s*:',
        "category": "e2e",
    },
    "Playwright": {
        "files": ["playwright.config.ts", "playwright.config.js"],
        "pattern": r'"@playwright/test"',
        "category": "e2e",
    },
    "Go Test": {
        "files": ["*_test.go"],
        "pattern": None,
        "category": "go",
    },
    "Cargo Test": {
        "files": ["Cargo.toml"],
        "dirs": ["tests"],
        "pattern": r"\[dev-dependencies\]",
        "category": "rust",
    },
}

CONVENTION_FILES = {
    # Python
    "pyproject.toml": {"tools": ["black", "ruff", "isort", "mypy"]},
    ".flake8": {"linter": "flake8"},
    "setup.cfg": {"tools": ["flake8", "mypy"]},
    ".pylintrc": {"linter": "pylint"},
    "ruff.toml": {"linter": "ruff"},
    ".ruff.toml": {"linter": "ruff"},
    ".mypy.ini": {"typechecker": "mypy"},
    # JavaScript/TypeScript
    ".prettierrc": {"formatter": "prettier"},
    ".prettierrc.json": {"formatter": "prettier"},
    ".prettierrc.js": {"formatter": "prettier"},
    ".prettierrc.cjs": {"formatter": "prettier"},
    "prettier.config.js": {"formatter": "prettier"},
    ".eslintrc": {"linter": "eslint"},
    ".eslintrc.json": {"linter": "eslint"},
    ".eslintrc.js": {"linter": "eslint"},
    ".eslintrc.cjs": {"linter": "eslint"},
    "eslint.config.js": {"linter": "eslint"},
    "eslint.config.mjs": {"linter": "eslint"},
    "biome.json": {"formatter": "biome", "linter": "biome"},
    "biome.jsonc": {"formatter": "biome", "linter": "biome"},
    # Go
    ".golangci.yml": {"linter": "golangci-lint"},
    ".golangci.yaml": {"linter": "golangci-lint"},
    # Rust
    "rustfmt.toml": {"formatter": "rustfmt"},
    ".rustfmt.toml": {"formatter": "rustfmt"},
    "clippy.toml": {"linter": "clippy"},
    # Editor
    ".editorconfig": {"editor": "editorconfig"},
}

CICD_SIGNATURES = {
    "GitHub Actions": {
        "path": ".github/workflows",
        "pattern": "*.yml",
    },
    "GitLab CI": {
        "files": [".gitlab-ci.yml"],
    },
    "CircleCI": {
        "path": ".circleci",
        "files": ["config.yml"],
    },
    "Jenkins": {
        "files": ["Jenkinsfile"],
    },
    "Azure Pipelines": {
        "files": ["azure-pipelines.yml"],
    },
    "Travis CI": {
        "files": [".travis.yml"],
    },
    "Bitbucket Pipelines": {
        "files": ["bitbucket-pipelines.yml"],
    },
}


# =============================================================================
# DATACLASSES
# =============================================================================


@dataclass
class DetectedLanguage:
    """Represents a detected programming language."""

    name: str
    extensions: list[str]
    file_count: int
    percentage: float
    version: Optional[str] = None


@dataclass
class DetectedFramework:
    """Represents a detected framework or library."""

    name: str
    category: str
    version: Optional[str] = None
    config_file: Optional[str] = None


@dataclass
class DetectedDatabase:
    """Represents detected database configuration."""

    name: str
    detected_from: str
    orm: Optional[str] = None


@dataclass
class CodeConventions:
    """Detected code conventions."""

    formatter: Optional[str] = None
    linter: Optional[str] = None
    typechecker: Optional[str] = None
    line_length: Optional[int] = None
    config_files: list[str] = field(default_factory=list)


@dataclass
class TestSetup:
    """Detected test configuration."""

    framework: Optional[str] = None
    category: Optional[str] = None
    test_dirs: list[str] = field(default_factory=list)
    config_file: Optional[str] = None


@dataclass
class DockerSetup:
    """Detected Docker configuration."""

    has_dockerfile: bool = False
    has_compose: bool = False
    services: list[str] = field(default_factory=list)
    compose_file: Optional[str] = None


@dataclass
class CICDSetup:
    """Detected CI/CD configuration."""

    provider: Optional[str] = None
    config_files: list[str] = field(default_factory=list)
    workflows: list[str] = field(default_factory=list)


@dataclass
class ProjectStructure:
    """Directory tree representation."""

    root_name: str
    directories: list[str]
    tree_string: str
    total_dirs: int = 0
    total_files: int = 0


@dataclass
class KeyFile:
    """Important project file."""
    path: str
    category: str  # entry_point, config, main, api, etc.
    description: str = ""


@dataclass
class DevCommand:
    """Development command."""
    name: str
    command: str
    source: str  # Makefile, package.json, pyproject.toml


@dataclass
class EnvVariable:
    """Environment variable."""
    name: str
    example: str = ""
    required: bool = True
    description: str = ""


@dataclass
class DetectedPackage:
    """Detected package dependency."""
    ecosystem: str  # PyPI, npm, crates.io
    name: str
    version: str  # Version effective (installed si dispo, sinon declared)
    source_file: str = ""
    declared_version: str = ""  # Version dans le fichier de config
    installed_version: str = ""  # Version réellement installée
    version_source: str = "declared"  # "installed" ou "declared"


@dataclass
class SecurityAlert:
    """Security vulnerability alert."""
    cve_id: str
    package: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    summary: str = ""
    fixed_version: Optional[str] = None
    references: list[str] = field(default_factory=list)  # Links to advisories


@dataclass
class ScanResult:
    """Complete scan result."""

    languages: list[DetectedLanguage] = field(default_factory=list)
    frameworks: list[DetectedFramework] = field(default_factory=list)
    databases: list[DetectedDatabase] = field(default_factory=list)
    structure: Optional[ProjectStructure] = None
    conventions: Optional[CodeConventions] = None
    tests: list[TestSetup] = field(default_factory=list)
    docker: Optional[DockerSetup] = None
    cicd: Optional[CICDSetup] = None
    readme_description: Optional[str] = None
    project_name_suggestion: Optional[str] = None
    scan_duration_ms: int = 0
    files_scanned: int = 0
    errors: list[str] = field(default_factory=list)
    # Nouvelles détections
    key_files: list[KeyFile] = field(default_factory=list)
    dev_commands: list[DevCommand] = field(default_factory=list)
    env_variables: list[EnvVariable] = field(default_factory=list)
    # Security
    packages: list[DetectedPackage] = field(default_factory=list)
    security_alerts: list[SecurityAlert] = field(default_factory=list)
    secret_findings: list[SecretFinding] = field(default_factory=list)


# =============================================================================
# PROJECT SCANNER
# =============================================================================


class ProjectScanner:
    """
    Scans a project directory and detects languages, frameworks, and configurations.
    """

    def __init__(
        self,
        max_depth: int = 3,
        max_files: int = 10000,
        timeout_seconds: int = 30,
        ignore_patterns: Optional[list[str]] = None,
    ):
        """
        Initialize the scanner.

        Args:
            max_depth: Maximum directory depth to scan
            max_files: Maximum number of files to scan
            timeout_seconds: Maximum scan duration
            ignore_patterns: Patterns to ignore (defaults to DEFAULT_IGNORE_PATTERNS)
        """
        self.max_depth = max_depth
        self.max_files = max_files
        self.timeout_seconds = timeout_seconds
        self.ignore_patterns = ignore_patterns or DEFAULT_IGNORE_PATTERNS

        self._files_scanned = 0
        self._start_time: Optional[float] = None
        self._errors: list[str] = []
        self._file_cache: dict[str, str] = {}

    def scan(self, path: Path) -> ScanResult:
        """
        Scan a project directory and return results.

        Args:
            path: Path to the project directory

        Returns:
            ScanResult with all detected information
        """
        self._start_time = time.time()
        self._files_scanned = 0
        self._errors = []
        self._file_cache = {}

        path = Path(path).resolve()

        if not path.exists():
            raise ValueError(f"Path does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        result = ScanResult()
        result.project_name_suggestion = path.name

        # Scan in order of importance
        result.structure = self._scan_structure(path)
        result.languages = self._scan_languages(path)
        result.frameworks = self._scan_frameworks(path)
        result.databases = self._scan_databases(path)
        result.conventions = self._scan_conventions(path)
        result.tests = self._scan_tests(path)
        result.docker = self._scan_docker(path)
        result.cicd = self._scan_cicd(path)
        result.readme_description = self._extract_description(path)

        # New detections for richer config
        result.key_files = self._detect_key_files(path)
        result.dev_commands = self._detect_dev_commands(path)
        result.env_variables = self._detect_env_variables(path)
        result.packages = self._detect_packages(path)

        # Secret detection (API keys, passwords, tokens)
        result.secret_findings = scan_directory_for_secrets(path)

        # Final stats
        result.files_scanned = self._files_scanned
        result.scan_duration_ms = int((time.time() - self._start_time) * 1000)
        result.errors = self._errors

        return result

    def _should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored."""
        name = path.name
        for pattern in self.ignore_patterns:
            if pattern.startswith("*"):
                if name.endswith(pattern[1:]):
                    return True
            elif name == pattern:
                return True
        return False

    def _should_continue(self) -> bool:
        """Check if scanning should continue."""
        if self._files_scanned >= self.max_files:
            return False
        if self._start_time and (time.time() - self._start_time) > self.timeout_seconds:
            return False
        return True

    def _safe_read_file(self, path: Path, max_size: int = 1024 * 1024) -> Optional[str]:
        """Read file safely with error handling."""
        str_path = str(path)
        if str_path in self._file_cache:
            return self._file_cache[str_path]

        try:
            if path.stat().st_size > max_size:
                return None
            content = path.read_text(encoding="utf-8", errors="ignore")
            self._file_cache[str_path] = content
            return content
        except PermissionError:
            self._errors.append(f"Permission denied: {path}")
            return None
        except Exception as e:
            self._errors.append(f"Error reading {path}: {e}")
            return None

    def _walk_files(self, path: Path, depth: int = 0):
        """Walk directory yielding files."""
        if depth > self.max_depth or not self._should_continue():
            return

        try:
            for item in path.iterdir():
                if self._should_ignore(item):
                    continue

                if item.is_file():
                    self._files_scanned += 1
                    yield item
                elif item.is_dir():
                    yield from self._walk_files(item, depth + 1)
        except PermissionError:
            self._errors.append(f"Permission denied: {path}")

    def _scan_structure(self, path: Path) -> ProjectStructure:
        """Scan and build directory structure."""
        directories = []
        total_files = 0
        total_dirs = 0

        def build_tree(p: Path, prefix: str = "", depth: int = 0) -> list[str]:
            nonlocal total_files, total_dirs
            lines = []

            if depth > self.max_depth:
                return lines

            try:
                items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
                items = [i for i in items if not self._should_ignore(i)]

                for i, item in enumerate(items):
                    is_last = i == len(items) - 1
                    connector = "└── " if is_last else "├── "
                    extension = "    " if is_last else "│   "

                    if item.is_dir():
                        total_dirs += 1
                        lines.append(f"{prefix}{connector}{item.name}/")
                        if depth == 0:
                            directories.append(item.name)
                        lines.extend(build_tree(item, prefix + extension, depth + 1))
                    else:
                        total_files += 1
                        lines.append(f"{prefix}{connector}{item.name}")

            except PermissionError:
                pass

            return lines

        tree_lines = build_tree(path)
        tree_string = f"{path.name}/\n" + "\n".join(tree_lines[:100])  # Limit output

        if len(tree_lines) > 100:
            tree_string += f"\n... et {len(tree_lines) - 100} autres fichiers/dossiers"

        return ProjectStructure(
            root_name=path.name,
            directories=directories,
            tree_string=tree_string,
            total_dirs=total_dirs,
            total_files=total_files,
        )

    def _scan_languages(self, path: Path) -> list[DetectedLanguage]:
        """Detect programming languages used."""
        extension_counts: dict[str, int] = {}

        for file in self._walk_files(path):
            ext = file.suffix.lower()
            if ext:
                extension_counts[ext] = extension_counts.get(ext, 0) + 1

        # Map extensions to languages
        language_counts: dict[str, tuple[list[str], int]] = {}

        for lang, exts in LANGUAGE_EXTENSIONS.items():
            count = sum(extension_counts.get(ext, 0) for ext in exts)
            if count > 0:
                found_exts = [ext for ext in exts if extension_counts.get(ext, 0) > 0]
                language_counts[lang] = (found_exts, count)

        # Calculate percentages and detect versions
        total_files = sum(count for _, count in language_counts.values())
        languages = []

        for lang, (exts, count) in sorted(
            language_counts.items(), key=lambda x: x[1][1], reverse=True
        ):
            percentage = (count / total_files * 100) if total_files > 0 else 0
            version = self._detect_language_version(path, lang)

            languages.append(
                DetectedLanguage(
                    name=lang,
                    extensions=exts,
                    file_count=count,
                    percentage=round(percentage, 1),
                    version=version,
                )
            )

        return languages

    def _detect_language_version(self, path: Path, language: str) -> Optional[str]:
        """Try to detect language version from config files."""
        if language not in VERSION_FILES:
            return None

        for filename, pattern in VERSION_FILES[language]:
            file_path = path / filename
            if file_path.exists():
                content = self._safe_read_file(file_path)
                if content:
                    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
                    if match:
                        normalized = normalize_version_constraint(match.group(1))
                        if normalized:
                            return normalized
        return None

    def _scan_frameworks(self, path: Path) -> list[DetectedFramework]:
        """Detect frameworks and libraries."""
        frameworks = []

        for fw_name, signature in FRAMEWORK_SIGNATURES.items():
            detected = False
            config_file = None

            # Check for signature files
            for filename in signature.get("files", []):
                file_path = path / filename
                if file_path.exists():
                    if signature.get("pattern"):
                        content = self._safe_read_file(file_path)
                        if content and re.search(
                            signature["pattern"], content, re.IGNORECASE
                        ):
                            detected = True
                            config_file = filename
                            break
                    else:
                        # File existence is enough
                        detected = True
                        config_file = filename
                        break

            if detected:
                frameworks.append(
                    DetectedFramework(
                        name=fw_name,
                        category=signature.get("category", "other"),
                        config_file=config_file,
                    )
                )

        return frameworks

    def _scan_databases(self, path: Path) -> list[DetectedDatabase]:
        """Detect database configurations."""
        databases = []
        detected_orms = []

        # First, detect ORMs from frameworks
        for fw in self._scan_frameworks(path):
            if fw.category == "orm":
                detected_orms.append(fw.name)

        # Check docker-compose for database services
        compose_files = ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
        for compose_file in compose_files:
            compose_path = path / compose_file
            if compose_path.exists():
                content = self._safe_read_file(compose_path)
                if content:
                    for db_name, signature in DATABASE_SIGNATURES.items():
                        for docker_name in signature.get("docker", []):
                            if docker_name in content.lower():
                                databases.append(
                                    DetectedDatabase(
                                        name=db_name,
                                        detected_from=compose_file,
                                        orm=detected_orms[0] if detected_orms else None,
                                    )
                                )
                                break

        # Check .env files
        env_files = [".env", ".env.example", ".env.local", ".env.development"]
        for env_file in env_files:
            env_path = path / env_file
            if env_path.exists():
                content = self._safe_read_file(env_path)
                if content:
                    for db_name, signature in DATABASE_SIGNATURES.items():
                        if db_name not in [d.name for d in databases]:
                            for pattern in signature.get("env_patterns", []):
                                if re.search(pattern, content, re.IGNORECASE):
                                    databases.append(
                                        DetectedDatabase(
                                            name=db_name,
                                            detected_from=env_file,
                                            orm=detected_orms[0] if detected_orms else None,
                                        )
                                    )
                                    break

        # Check package files for database packages
        package_files = {
            "requirements.txt": None,
            "pyproject.toml": None,
            "package.json": None,
            "Cargo.toml": None,
            "go.mod": None,
        }

        for pkg_file in package_files:
            pkg_path = path / pkg_file
            if pkg_path.exists():
                content = self._safe_read_file(pkg_path)
                if content:
                    for db_name, signature in DATABASE_SIGNATURES.items():
                        if db_name not in [d.name for d in databases]:
                            for pkg in signature.get("packages", []):
                                if pkg.lower() in content.lower():
                                    databases.append(
                                        DetectedDatabase(
                                            name=db_name,
                                            detected_from=pkg_file,
                                            orm=detected_orms[0] if detected_orms else None,
                                        )
                                    )
                                    break

        return databases

    def _scan_conventions(self, path: Path) -> CodeConventions:
        """Detect code conventions and formatting tools."""
        conventions = CodeConventions()
        config_files = []

        for filename, info in CONVENTION_FILES.items():
            file_path = path / filename
            if file_path.exists():
                config_files.append(filename)

                if "formatter" in info and not conventions.formatter:
                    conventions.formatter = info["formatter"]
                if "linter" in info and not conventions.linter:
                    conventions.linter = info["linter"]
                if "typechecker" in info and not conventions.typechecker:
                    conventions.typechecker = info["typechecker"]

        # Parse pyproject.toml for more details
        pyproject_path = path / "pyproject.toml"
        if pyproject_path.exists():
            content = self._safe_read_file(pyproject_path)
            if content:
                if "[tool.black]" in content:
                    conventions.formatter = "black"
                    # Try to extract line-length
                    match = re.search(r"line-length\s*=\s*(\d+)", content)
                    if match:
                        conventions.line_length = int(match.group(1))
                if "[tool.ruff]" in content:
                    conventions.linter = "ruff"
                if "[tool.isort]" in content and not conventions.formatter:
                    conventions.formatter = "isort"
                if "[tool.mypy]" in content:
                    conventions.typechecker = "mypy"

        conventions.config_files = config_files
        return conventions

    def _scan_tests(self, path: Path) -> list[TestSetup]:
        """Detect test frameworks and configuration."""
        tests = []

        for test_name, signature in TEST_SIGNATURES.items():
            detected = False
            config_file = None
            test_dirs = []

            # Check for test directories
            for dir_name in signature.get("dirs", []):
                dir_path = path / dir_name
                if dir_path.exists() and dir_path.is_dir():
                    test_dirs.append(dir_name)
                    detected = True

            # Check for config files
            for filename in signature.get("files", []):
                if "*" in filename:
                    # Glob pattern
                    for file_path in path.glob(filename):
                        detected = True
                        config_file = file_path.name
                        break
                else:
                    file_path = path / filename
                    if file_path.exists():
                        # Un manifeste partage (package.json, pyproject.toml) doit
                        # contenir le motif ; un fichier de config dedie se suffit.
                        needs_pattern = (
                            filename in SHARED_MANIFEST_FILES
                            and signature.get("pattern") is not None
                        )
                        if needs_pattern:
                            content = self._safe_read_file(file_path)
                            if content and re.search(
                                signature["pattern"], content, re.IGNORECASE
                            ):
                                detected = True
                                config_file = filename
                        else:
                            detected = True
                            config_file = filename

            if detected:
                tests.append(
                    TestSetup(
                        framework=test_name,
                        category=signature.get("category"),
                        test_dirs=test_dirs,
                        config_file=config_file,
                    )
                )

        return tests

    def _scan_docker(self, path: Path) -> DockerSetup:
        """Detect Docker configuration."""
        docker = DockerSetup()

        # Check for Dockerfile
        dockerfile_variants = ["Dockerfile", "dockerfile"]
        for variant in dockerfile_variants:
            if (path / variant).exists():
                docker.has_dockerfile = True
                break

        # Also check for Dockerfile.* variants
        for file in path.glob("Dockerfile.*"):
            docker.has_dockerfile = True
            break

        # Check for docker-compose
        compose_files = ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
        for compose_file in compose_files:
            compose_path = path / compose_file
            if compose_path.exists():
                docker.has_compose = True
                docker.compose_file = compose_file

                # Extract services
                content = self._safe_read_file(compose_path)
                if content:
                    # Simple service extraction
                    services_match = re.findall(
                        r"^\s{2}(\w[\w-]*):\s*$", content, re.MULTILINE
                    )
                    if services_match:
                        docker.services = services_match
                break

        return docker

    def _scan_cicd(self, path: Path) -> CICDSetup:
        """Detect CI/CD configuration."""
        cicd = CICDSetup()

        for provider, signature in CICD_SIGNATURES.items():
            detected = False
            config_files = []
            workflows = []

            # Check path-based configs (like .github/workflows/)
            if "path" in signature:
                cicd_path = path / signature["path"]
                if cicd_path.exists() and cicd_path.is_dir():
                    detected = True
                    pattern = signature.get("pattern", "*")
                    for file in cicd_path.glob(pattern):
                        config_files.append(str(file.relative_to(path)))
                        workflows.append(file.stem)

            # Check file-based configs
            for filename in signature.get("files", []):
                file_path = path / filename
                if file_path.exists():
                    detected = True
                    config_files.append(filename)

            if detected:
                cicd.provider = provider
                cicd.config_files = config_files
                cicd.workflows = workflows
                break

        return cicd

    def _extract_description(self, path: Path) -> Optional[str]:
        """Try to extract project description from README."""
        readme_files = ["README.md", "README.rst", "README.txt", "README"]

        for readme_file in readme_files:
            readme_path = path / readme_file
            if readme_path.exists():
                content = self._safe_read_file(readme_path)
                if content:
                    # Skip badges and title
                    lines = content.split("\n")
                    description_lines = []
                    in_description = False
                    skip_next = False

                    for line in lines:
                        # Skip badges
                        if "![" in line or "[![" in line:
                            continue
                        # Skip title
                        if line.startswith("# "):
                            skip_next = True
                            continue
                        if skip_next and not line.strip():
                            skip_next = False
                            continue

                        # Start collecting description
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#"):
                            in_description = True
                            description_lines.append(stripped)
                        elif in_description and not stripped:
                            # End of first paragraph
                            break

                        if len(description_lines) >= 3:
                            break

                    if description_lines:
                        return " ".join(description_lines[:3])

        return None

    def _detect_key_files(self, path: Path) -> list[KeyFile]:
        """Detect important project files."""
        key_files = []

        # Entry points and main files
        entry_points = [
            ("main.py", "entry_point", "Point d'entrée Python"),
            ("app.py", "entry_point", "Application principale"),
            ("index.py", "entry_point", "Point d'entrée"),
            ("__main__.py", "entry_point", "Module executable"),
            ("cli.py", "entry_point", "Interface CLI"),
            ("server.py", "entry_point", "Serveur"),
            ("manage.py", "entry_point", "Django manage"),
            ("index.ts", "entry_point", "Point d'entrée TypeScript"),
            ("index.js", "entry_point", "Point d'entrée JavaScript"),
            ("main.ts", "entry_point", "Point d'entrée TypeScript"),
            ("main.go", "entry_point", "Point d'entrée Go"),
            ("main.rs", "entry_point", "Point d'entrée Rust"),
        ]

        # Config files
        config_files = [
            ("pyproject.toml", "config", "Config Python/projet"),
            ("package.json", "config", "Config Node.js"),
            ("tsconfig.json", "config", "Config TypeScript"),
            ("Cargo.toml", "config", "Config Rust"),
            ("go.mod", "config", "Config Go"),
            ("docker-compose.yml", "config", "Config Docker Compose"),
            ("docker-compose.yaml", "config", "Config Docker Compose"),
            ("Dockerfile", "config", "Image Docker"),
            (".env.example", "config", "Variables d'environnement"),
            ("Makefile", "config", "Commandes Make"),
        ]

        # Check entry points in root and common subdirs
        for filename, category, desc in entry_points + config_files:
            if (path / filename).exists():
                key_files.append(KeyFile(filename, category, desc))

            # Check in common subdirs
            for subdir in ["src", "app", "lib", "pkg"]:
                subpath = path / subdir / filename
                if subpath.exists():
                    key_files.append(KeyFile(f"{subdir}/{filename}", category, desc))

        return key_files[:15]  # Limit to 15 most important

    def _detect_dev_commands(self, path: Path) -> list[DevCommand]:
        """Detect development commands from Makefile, package.json, pyproject.toml."""
        commands = []

        # Makefile
        makefile = path / "Makefile"
        if makefile.exists():
            content = self._safe_read_file(makefile)
            if content:
                # Find targets (lines starting with name:)
                for match in re.finditer(r'^([a-zA-Z_-]+):\s*(?:.*)?$', content, re.MULTILINE):
                    target = match.group(1)
                    if not target.startswith('.') and target not in ['all', 'clean', 'help']:
                        commands.append(DevCommand(target, f"make {target}", "Makefile"))

        # package.json
        pkg_json = path / "package.json"
        if pkg_json.exists():
            content = self._safe_read_file(pkg_json)
            if content:
                try:
                    import json
                    data = json.loads(content)
                    scripts = data.get("scripts", {})
                    for name, cmd in list(scripts.items())[:10]:
                        commands.append(DevCommand(name, f"npm run {name}", "package.json"))
                except:
                    pass

        # pyproject.toml scripts
        pyproject = path / "pyproject.toml"
        if pyproject.exists():
            content = self._safe_read_file(pyproject)
            if content:
                # Look for [tool.poetry.scripts] or [project.scripts]
                in_scripts = False
                for line in content.split("\n"):
                    if "[tool.poetry.scripts]" in line or "[project.scripts]" in line:
                        in_scripts = True
                        continue
                    if in_scripts:
                        if line.startswith("["):
                            break
                        match = re.match(r'(\w+)\s*=', line)
                        if match:
                            name = match.group(1)
                            commands.append(DevCommand(name, name, "pyproject.toml"))

        return commands[:15]

    def _detect_env_variables(self, path: Path) -> list[EnvVariable]:
        """Detect environment variables from .env.example, docker-compose, etc."""
        env_vars = []
        seen = set()

        # .env.example or .env.sample
        for env_file in [".env.example", ".env.sample", ".env.template"]:
            env_path = path / env_file
            if env_path.exists():
                content = self._safe_read_file(env_path)
                if content:
                    for line in content.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            parts = line.split("=", 1)
                            name = parts[0].strip()
                            value = parts[1].strip() if len(parts) > 1 else ""
                            if name and name not in seen:
                                seen.add(name)
                                env_vars.append(EnvVariable(name, value))

        # docker-compose.yml environment section
        for compose_file in ["docker-compose.yml", "docker-compose.yaml"]:
            compose_path = path / compose_file
            if compose_path.exists():
                content = self._safe_read_file(compose_path)
                if content:
                    # Simple regex to find environment variables
                    for match in re.finditer(r'^\s*-?\s*([A-Z][A-Z0-9_]+)(?:=|\s*:)', content, re.MULTILINE):
                        name = match.group(1)
                        if name not in seen and not name.startswith("COMPOSE"):
                            seen.add(name)
                            env_vars.append(EnvVariable(name, "", True, "docker-compose"))

        return env_vars[:20]

    def _get_installed_packages(self) -> dict[str, str]:
        """
        Get actually installed Python package versions using importlib.metadata.
        Returns dict mapping package_name (lowercase) -> version.
        """
        installed = {}
        try:
            from importlib.metadata import distributions
            for dist in distributions():
                name = dist.metadata.get("Name", "").lower()
                version = dist.metadata.get("Version", "")
                if name and version:
                    installed[name] = version
                    # Also add with underscores replaced by hyphens and vice versa
                    installed[name.replace("-", "_")] = version
                    installed[name.replace("_", "-")] = version
        except Exception:
            pass
        return installed

    def _parse_npm_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse package-lock.json for installed npm package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}
        lockfile = path / "package-lock.json"
        if not lockfile.exists():
            return installed

        content = self._safe_read_file(lockfile)
        if not content:
            return installed

        try:
            import json
            data = json.loads(content)

            # package-lock.json v2/v3 format (packages field)
            if "packages" in data:
                for pkg_path, pkg_info in data["packages"].items():
                    if pkg_path.startswith("node_modules/"):
                        name = pkg_path.replace("node_modules/", "").split("/")[0]
                        # Handle scoped packages (@org/pkg)
                        if name.startswith("@") and "/" in pkg_path.replace("node_modules/", ""):
                            parts = pkg_path.replace("node_modules/", "").split("/")
                            name = f"{parts[0]}/{parts[1]}"
                        version = pkg_info.get("version", "")
                        if name and version:
                            installed[name.lower()] = version

            # package-lock.json v1 format (dependencies field)
            elif "dependencies" in data:
                for name, info in data["dependencies"].items():
                    version = info.get("version", "")
                    if version:
                        installed[name.lower()] = version
        except Exception:
            pass

        return installed

    def _parse_cargo_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse Cargo.lock for installed Rust crate versions.
        Returns dict mapping crate_name -> version.
        """
        installed = {}
        lockfile = path / "Cargo.lock"
        if not lockfile.exists():
            return installed

        content = self._safe_read_file(lockfile)
        if not content:
            return installed

        # Parse TOML-like format: [[package]] name = "x" version = "y"
        current_name = None
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("name = "):
                current_name = line.split('"')[1] if '"' in line else None
            elif line.startswith("version = ") and current_name:
                version = line.split('"')[1] if '"' in line else None
                if version:
                    installed[current_name.lower()] = version
                current_name = None

        return installed

    def _parse_go_sum(self, path: Path) -> dict[str, str]:
        """
        Parse go.sum for Go module versions.
        Returns dict mapping module_path -> version.
        """
        installed = {}
        sumfile = path / "go.sum"
        if not sumfile.exists():
            return installed

        content = self._safe_read_file(sumfile)
        if not content:
            return installed

        for line in content.split("\n"):
            parts = line.strip().split()
            if len(parts) >= 2:
                module = parts[0]
                version = parts[1].lstrip("v").split("/")[0]  # Remove v prefix and /go.mod suffix
                if module and version and not version.endswith("/go.mod"):
                    # Use last part of module path as name
                    name = module.split("/")[-1] if "/" in module else module
                    installed[name.lower()] = version
                    installed[module.lower()] = version  # Also store full path

        return installed

    def _parse_composer_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse composer.lock for PHP package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}
        lockfile = path / "composer.lock"
        if not lockfile.exists():
            return installed

        content = self._safe_read_file(lockfile)
        if not content:
            return installed

        try:
            import json
            data = json.loads(content)

            for pkg in data.get("packages", []):
                name = pkg.get("name", "")
                version = pkg.get("version", "").lstrip("v")
                if name and version:
                    installed[name.lower()] = version
                    # Also store just the package name without vendor
                    if "/" in name:
                        installed[name.split("/")[1].lower()] = version

            for pkg in data.get("packages-dev", []):
                name = pkg.get("name", "")
                version = pkg.get("version", "").lstrip("v")
                if name and version:
                    installed[name.lower()] = version
        except Exception:
            pass

        return installed

    def _parse_gemfile_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse Gemfile.lock for Ruby gem versions.
        Returns dict mapping gem_name -> version.
        """
        installed = {}
        lockfile = path / "Gemfile.lock"
        if not lockfile.exists():
            return installed

        content = self._safe_read_file(lockfile)
        if not content:
            return installed

        # Parse GEM section
        in_specs = False
        for line in content.split("\n"):
            if "specs:" in line:
                in_specs = True
                continue
            if in_specs:
                if line and not line.startswith(" "):
                    in_specs = False
                    continue
                # Match "    gem_name (version)"
                match = re.match(r'^\s{4}([a-zA-Z0-9_-]+)\s+\(([0-9.]+)', line)
                if match:
                    name = match.group(1)
                    version = match.group(2)
                    installed[name.lower()] = version

        return installed

    def _parse_nuget_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse packages.lock.json or *.csproj for .NET package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}

        # Try packages.lock.json first (NuGet lock file)
        lockfile = path / "packages.lock.json"
        if lockfile.exists():
            content = self._safe_read_file(lockfile)
            if content:
                try:
                    import json
                    data = json.loads(content)
                    for framework, deps in data.get("dependencies", {}).items():
                        for name, info in deps.items():
                            version = info.get("resolved", "")
                            if version:
                                installed[name.lower()] = version
                except Exception:
                    pass

        # Also try parsing .csproj files for PackageReference
        for csproj in path.glob("*.csproj"):
            content = self._safe_read_file(csproj)
            if content:
                for match in re.finditer(
                    r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"',
                    content
                ):
                    name = match.group(1)
                    version = match.group(2)
                    if name and version:
                        installed[name.lower()] = version

        return installed

    def _parse_gradle_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse gradle.lockfile or build.gradle for Java/Kotlin dependency versions.
        Returns dict mapping artifact_name -> version.
        """
        installed = {}

        # Try gradle.lockfile
        lockfile = path / "gradle.lockfile"
        if lockfile.exists():
            content = self._safe_read_file(lockfile)
            if content:
                for line in content.split("\n"):
                    # Format: group:artifact:version=hash
                    if ":" in line and "=" in line:
                        parts = line.split("=")[0].split(":")
                        if len(parts) >= 3:
                            artifact = parts[1]
                            version = parts[2]
                            installed[artifact.lower()] = version

        # Also try build.gradle
        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            gradle_path = path / gradle_file
            if gradle_path.exists():
                content = self._safe_read_file(gradle_path)
                if content:
                    # Match implementation 'group:artifact:version'
                    for match in re.finditer(
                        r"(?:implementation|api|compile)\s*['\"]([^:]+):([^:]+):([^'\"]+)['\"]",
                        content
                    ):
                        artifact = match.group(2)
                        version = match.group(3)
                        installed[artifact.lower()] = version

        return installed

    def _parse_maven_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse pom.xml for Maven dependency versions.
        Returns dict mapping artifact_name -> version.
        """
        installed = {}
        pom_file = path / "pom.xml"
        if not pom_file.exists():
            return installed

        content = self._safe_read_file(pom_file)
        if not content:
            return installed

        # Simple regex parsing for <dependency> blocks
        # Match <artifactId>xxx</artifactId> followed by <version>yyy</version>
        for match in re.finditer(
            r'<artifactId>([^<]+)</artifactId>\s*<version>([^<]+)</version>',
            content,
            re.DOTALL
        ):
            artifact = match.group(1).strip()
            version = match.group(2).strip()
            # Skip version variables like ${project.version}
            if version and not version.startswith("$"):
                installed[artifact.lower()] = version

        return installed

    def _parse_conan_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse conan.lock for C/C++ Conan package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}

        # Try conan.lock (Conan 2.x format - JSON)
        lockfile = path / "conan.lock"
        if lockfile.exists():
            content = self._safe_read_file(lockfile)
            if content:
                try:
                    import json
                    data = json.loads(content)
                    # Conan 2.x format: {"requires": ["pkg/version@...", ...]}
                    for req in data.get("requires", []):
                        # Format: "package/version@user/channel" or "package/version"
                        if "/" in req:
                            parts = req.split("/")
                            name = parts[0]
                            version = parts[1].split("@")[0] if "@" in parts[1] else parts[1]
                            installed[name.lower()] = version
                except Exception:
                    pass

        # Try conanfile.lock (Conan 1.x format)
        lockfile_v1 = path / "conanfile.lock"
        if lockfile_v1.exists():
            content = self._safe_read_file(lockfile_v1)
            if content:
                try:
                    import json
                    data = json.loads(content)
                    # Conan 1.x: graph_lock.nodes
                    nodes = data.get("graph_lock", {}).get("nodes", {})
                    for node_id, node_info in nodes.items():
                        ref = node_info.get("ref", "")
                        if "/" in ref:
                            parts = ref.split("/")
                            name = parts[0]
                            version = parts[1].split("@")[0] if "@" in parts[1] else parts[1]
                            installed[name.lower()] = version
                except Exception:
                    pass

        return installed

    def _parse_vcpkg_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse vcpkg.json and vcpkg-configuration.json for C/C++ vcpkg package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}

        # vcpkg.json manifest
        manifest = path / "vcpkg.json"
        if manifest.exists():
            content = self._safe_read_file(manifest)
            if content:
                try:
                    import json
                    data = json.loads(content)

                    # Dependencies can be strings or objects
                    for dep in data.get("dependencies", []):
                        if isinstance(dep, str):
                            # Simple dependency: "boost"
                            installed[dep.lower()] = "latest"
                        elif isinstance(dep, dict):
                            # Object: {"name": "boost", "version>=": "1.80.0"}
                            name = dep.get("name", "")
                            version = dep.get("version>=", dep.get("version", "latest"))
                            if name:
                                installed[name.lower()] = str(version)

                    # Check overrides for pinned versions
                    for override in data.get("overrides", []):
                        name = override.get("name", "")
                        version = override.get("version", "")
                        if name and version:
                            installed[name.lower()] = version
                except Exception:
                    pass

        # Also check vcpkg_installed directory for actual versions
        vcpkg_installed = path / "vcpkg_installed"
        if vcpkg_installed.exists():
            # Look for status file
            for status_file in vcpkg_installed.glob("*/status"):
                content = self._safe_read_file(status_file)
                if content:
                    current_pkg = None
                    for line in content.split("\n"):
                        if line.startswith("Package: "):
                            current_pkg = line.split(": ", 1)[1].strip()
                        elif line.startswith("Version: ") and current_pkg:
                            version = line.split(": ", 1)[1].strip()
                            installed[current_pkg.lower()] = version
                            current_pkg = None

        return installed

    def _parse_swift_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse Package.resolved for Swift package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}

        # Package.resolved (Swift Package Manager)
        resolved = path / "Package.resolved"
        if not resolved.exists():
            # Also check in .build directory
            resolved = path / ".build" / "Package.resolved"

        if not resolved.exists():
            return installed

        content = self._safe_read_file(resolved)
        if not content:
            return installed

        try:
            import json
            data = json.loads(content)

            # Version 2 format (Swift 5.6+)
            if "pins" in data:
                for pin in data.get("pins", []):
                    identity = pin.get("identity", "")
                    state = pin.get("state", {})
                    version = state.get("version", state.get("revision", "")[:8])
                    if identity and version:
                        installed[identity.lower()] = version

            # Version 1 format (older Swift)
            elif "object" in data:
                pins = data.get("object", {}).get("pins", [])
                for pin in pins:
                    name = pin.get("package", "")
                    state = pin.get("state", {})
                    version = state.get("version", state.get("revision", "")[:8])
                    if name and version:
                        installed[name.lower()] = version
        except Exception:
            pass

        return installed

    def _parse_cmake_packages(self, path: Path) -> dict[str, str]:
        """
        Parse CMakeLists.txt for find_package and FetchContent dependencies.
        Returns dict mapping package_name -> version (or 'detected').
        """
        installed = {}

        cmake_file = path / "CMakeLists.txt"
        if not cmake_file.exists():
            return installed

        content = self._safe_read_file(cmake_file)
        if not content:
            return installed

        # find_package(PackageName VERSION x.y.z)
        for match in re.finditer(
            r'find_package\s*\(\s*(\w+)(?:\s+(\d+(?:\.\d+)*))?',
            content,
            re.IGNORECASE
        ):
            name = match.group(1)
            version = match.group(2) or "detected"
            installed[name.lower()] = version

        # FetchContent_Declare with GIT_TAG
        for match in re.finditer(
            r'FetchContent_Declare\s*\(\s*(\w+).*?GIT_TAG\s+["\']?v?(\d+\.\d+(?:\.\d+)?)["\']?',
            content,
            re.IGNORECASE | re.DOTALL
        ):
            name = match.group(1)
            version = match.group(2)
            installed[name.lower()] = version

        return installed

    def _detect_packages(self, path: Path) -> list[DetectedPackage]:
        """
        Detect package dependencies from manifest files.
        Uses installed versions when available for accurate CVE checking.
        """
        packages = []

        # Get installed packages for version verification
        installed_packages = self._get_installed_packages()

        def make_package(ecosystem: str, name: str, declared_version: str, source_file: str) -> DetectedPackage:
            """Helper to create package with installed version if available."""
            name_lower = name.lower()
            installed_version = installed_packages.get(name_lower, "")

            # Use installed version if available, otherwise declared
            if installed_version:
                effective_version = installed_version
                version_source = "installed"
            else:
                effective_version = declared_version
                version_source = "declared"

            return DetectedPackage(
                ecosystem=ecosystem,
                name=name_lower,
                version=effective_version,
                source_file=source_file,
                declared_version=declared_version,
                installed_version=installed_version,
                version_source=version_source
            )

        # Python: requirements.txt
        req_files = ["requirements.txt", "requirements-dev.txt", "requirements-prod.txt"]
        for req_file in req_files:
            req_path = path / req_file
            if req_path.exists():
                content = self._safe_read_file(req_path)
                if content:
                    for line in content.split("\n"):
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("-"):
                            continue
                        # Match package==version or package>=version
                        match = re.match(r"^([a-zA-Z0-9_-]+)\s*[=><]+\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)", line)
                        if match:
                            packages.append(make_package(
                                "PyPI",
                                match.group(1),
                                match.group(2),
                                req_file
                            ))

        # Python: pyproject.toml
        # Only scan runtime dependencies, NOT build-system.requires
        pyproject = path / "pyproject.toml"
        if pyproject.exists():
            content = self._safe_read_file(pyproject)
            if content:
                # Extract only dependencies sections, skip [build-system]
                # Look for [project.dependencies] and [project.optional-dependencies.*]
                deps_sections = []

                # Find dependencies = [...] after [project]
                project_match = re.search(r'\[project\].*?(?=\n\[|$)', content, re.DOTALL)
                if project_match:
                    deps_sections.append(project_match.group(0))

                # Find [project.optional-dependencies.*] sections
                for match in re.finditer(r'\[project\.optional-dependencies[^\]]*\].*?(?=\n\[|$)', content, re.DOTALL):
                    deps_sections.append(match.group(0))

                # Parse dependencies from these sections only
                deps_content = '\n'.join(deps_sections)
                for match in re.finditer(r'"([a-zA-Z0-9_-]+)(?:\[[\w,]+\])?\s*[=><]+\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)"', deps_content):
                    pkg_name = match.group(1).lower()
                    # Skip build tools that might appear
                    if pkg_name not in ['setuptools', 'wheel', 'pip', 'build']:
                        packages.append(make_package(
                            "PyPI",
                            match.group(1),
                            match.group(2),
                            "pyproject.toml"
                        ))

        # Node.js: package.json with package-lock.json for installed versions
        npm_installed = self._parse_npm_lockfile(path)
        package_json = path / "package.json"
        if package_json.exists():
            content = self._safe_read_file(package_json)
            if content:
                for match in re.finditer(r'"([a-zA-Z0-9@/_-]+)"\s*:\s*"[\^~]?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"', content):
                    pkg_name = match.group(1)
                    declared_version = match.group(2)
                    if not pkg_name.startswith("@types/"):
                        installed_version = npm_installed.get(pkg_name.lower(), "")
                        packages.append(DetectedPackage(
                            ecosystem="npm",
                            name=pkg_name,
                            version=installed_version or declared_version,
                            source_file="package.json",
                            declared_version=declared_version,
                            installed_version=installed_version,
                            version_source="installed" if installed_version else "declared"
                        ))

        # Rust: Cargo.toml with Cargo.lock for installed versions
        cargo_installed = self._parse_cargo_lockfile(path)
        cargo_toml = path / "Cargo.toml"
        if cargo_toml.exists():
            content = self._safe_read_file(cargo_toml)
            if content and "[dependencies]" in content:
                deps_section = content.split("[dependencies]")[1].split("[")[0]
                for match in re.finditer(r'^([a-zA-Z0-9_-]+)\s*=\s*"([0-9]+\.[0-9]+(?:\.[0-9]+)?)"', deps_section, re.MULTILINE):
                    pkg = match.group(1)
                    declared_version = match.group(2)
                    if pkg not in ["version", "edition", "name"]:
                        installed_version = cargo_installed.get(pkg.lower(), "")
                        packages.append(DetectedPackage(
                            ecosystem="crates.io",
                            name=pkg,
                            version=installed_version or declared_version,
                            source_file="Cargo.toml",
                            declared_version=declared_version,
                            installed_version=installed_version,
                            version_source="installed" if installed_version else "declared"
                        ))

        # Go: go.mod with go.sum for installed versions
        go_installed = self._parse_go_sum(path)
        go_mod = path / "go.mod"
        if go_mod.exists():
            content = self._safe_read_file(go_mod)
            if content:
                for match in re.finditer(r'^\s*([a-zA-Z0-9._/-]+)\s+v([0-9]+\.[0-9]+(?:\.[0-9]+)?)', content, re.MULTILINE):
                    module = match.group(1)
                    declared_version = match.group(2)
                    name = module.split("/")[-1] if "/" in module else module
                    installed_version = go_installed.get(name.lower(), "") or go_installed.get(module.lower(), "")
                    packages.append(DetectedPackage(
                        ecosystem="Go",
                        name=name,
                        version=installed_version or declared_version,
                        source_file="go.mod",
                        declared_version=declared_version,
                        installed_version=installed_version,
                        version_source="installed" if installed_version else "declared"
                    ))

        # PHP: composer.json with composer.lock for installed versions
        composer_installed = self._parse_composer_lockfile(path)
        composer_json = path / "composer.json"
        if composer_json.exists():
            content = self._safe_read_file(composer_json)
            if content:
                try:
                    import json
                    data = json.loads(content)
                    for section in ["require", "require-dev"]:
                        for pkg_name, version_constraint in data.get(section, {}).items():
                            if pkg_name != "php" and not pkg_name.startswith("ext-"):
                                # Extract version from constraint (e.g., "^8.0" -> "8.0")
                                declared = re.search(r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)', version_constraint)
                                declared_version = declared.group(1) if declared else ""
                                installed_version = composer_installed.get(pkg_name.lower(), "")
                                short_name = pkg_name.split("/")[-1] if "/" in pkg_name else pkg_name
                                packages.append(DetectedPackage(
                                    ecosystem="Packagist",
                                    name=short_name,
                                    version=installed_version or declared_version,
                                    source_file="composer.json",
                                    declared_version=declared_version,
                                    installed_version=installed_version,
                                    version_source="installed" if installed_version else "declared"
                                ))
                except Exception:
                    pass

        # Ruby: Gemfile with Gemfile.lock for installed versions
        gem_installed = self._parse_gemfile_lockfile(path)
        gemfile = path / "Gemfile"
        if gemfile.exists():
            content = self._safe_read_file(gemfile)
            if content:
                for match in re.finditer(r"gem\s+['\"]([a-zA-Z0-9_-]+)['\"](?:\s*,\s*['\"]([~>=<\s0-9.]+)['\"])?", content):
                    gem_name = match.group(1)
                    version_constraint = match.group(2) or ""
                    declared = re.search(r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)', version_constraint)
                    declared_version = declared.group(1) if declared else ""
                    installed_version = gem_installed.get(gem_name.lower(), "")
                    packages.append(DetectedPackage(
                        ecosystem="RubyGems",
                        name=gem_name,
                        version=installed_version or declared_version,
                        source_file="Gemfile",
                        declared_version=declared_version,
                        installed_version=installed_version,
                        version_source="installed" if installed_version else "declared"
                    ))

        # C#/.NET: *.csproj with packages.lock.json for installed versions
        nuget_installed = self._parse_nuget_lockfile(path)
        for csproj in path.glob("*.csproj"):
            content = self._safe_read_file(csproj)
            if content:
                for match in re.finditer(r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"', content):
                    pkg_name = match.group(1)
                    declared_version = match.group(2)
                    installed_version = nuget_installed.get(pkg_name.lower(), "")
                    packages.append(DetectedPackage(
                        ecosystem="NuGet",
                        name=pkg_name,
                        version=installed_version or declared_version,
                        source_file=csproj.name,
                        declared_version=declared_version,
                        installed_version=installed_version,
                        version_source="installed" if installed_version else "declared"
                    ))

        # Java Maven: pom.xml
        maven_installed = self._parse_maven_lockfile(path)
        pom_file = path / "pom.xml"
        if pom_file.exists():
            content = self._safe_read_file(pom_file)
            if content:
                for match in re.finditer(r'<dependency>.*?<artifactId>([^<]+)</artifactId>.*?<version>([^<]+)</version>.*?</dependency>', content, re.DOTALL):
                    artifact = match.group(1).strip()
                    declared_version = match.group(2).strip()
                    if not declared_version.startswith("$"):
                        installed_version = maven_installed.get(artifact.lower(), "")
                        packages.append(DetectedPackage(
                            ecosystem="Maven",
                            name=artifact,
                            version=installed_version or declared_version,
                            source_file="pom.xml",
                            declared_version=declared_version,
                            installed_version=installed_version,
                            version_source="installed" if installed_version else "declared"
                        ))

        # Java Gradle: build.gradle
        gradle_installed = self._parse_gradle_lockfile(path)
        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            gradle_path = path / gradle_file
            if gradle_path.exists():
                content = self._safe_read_file(gradle_path)
                if content:
                    for match in re.finditer(r"(?:implementation|api|compile)\s*['\"]([^:]+):([^:]+):([^'\"]+)['\"]", content):
                        artifact = match.group(2)
                        declared_version = match.group(3)
                        installed_version = gradle_installed.get(artifact.lower(), "")
                        packages.append(DetectedPackage(
                            ecosystem="Maven",
                            name=artifact,
                            version=installed_version or declared_version,
                            source_file=gradle_file,
                            declared_version=declared_version,
                            installed_version=installed_version,
                            version_source="installed" if installed_version else "declared"
                        ))

        # C/C++ Conan: conanfile.txt or conanfile.py
        conan_installed = self._parse_conan_lockfile(path)
        for conan_file in ["conanfile.txt", "conanfile.py"]:
            conan_path = path / conan_file
            if conan_path.exists():
                content = self._safe_read_file(conan_path)
                if content:
                    # conanfile.txt: package/version
                    for match in re.finditer(r'^([a-zA-Z0-9_-]+)/(\d+\.\d+(?:\.\d+)?)', content, re.MULTILINE):
                        pkg_name = match.group(1)
                        declared_version = match.group(2)
                        installed_version = conan_installed.get(pkg_name.lower(), "")
                        packages.append(DetectedPackage(
                            ecosystem="Conan",
                            name=pkg_name,
                            version=installed_version or declared_version,
                            source_file=conan_file,
                            declared_version=declared_version,
                            installed_version=installed_version,
                            version_source="installed" if installed_version else "declared"
                        ))
                    # conanfile.py: requires = ["package/version"]
                    for match in re.finditer(r'["\']([a-zA-Z0-9_-]+)/(\d+\.\d+(?:\.\d+)?)', content):
                        pkg_name = match.group(1)
                        declared_version = match.group(2)
                        if pkg_name.lower() not in [p.name.lower() for p in packages]:
                            installed_version = conan_installed.get(pkg_name.lower(), "")
                            packages.append(DetectedPackage(
                                ecosystem="Conan",
                                name=pkg_name,
                                version=installed_version or declared_version,
                                source_file=conan_file,
                                declared_version=declared_version,
                                installed_version=installed_version,
                                version_source="installed" if installed_version else "declared"
                            ))

        # C/C++ vcpkg: vcpkg.json
        vcpkg_installed = self._parse_vcpkg_lockfile(path)
        vcpkg_json = path / "vcpkg.json"
        if vcpkg_json.exists():
            content = self._safe_read_file(vcpkg_json)
            if content:
                try:
                    import json
                    data = json.loads(content)
                    for dep in data.get("dependencies", []):
                        if isinstance(dep, str):
                            pkg_name = dep
                            declared_version = ""
                        else:
                            pkg_name = dep.get("name", "")
                            declared_version = dep.get("version>=", dep.get("version", ""))
                        if pkg_name:
                            installed_version = vcpkg_installed.get(pkg_name.lower(), "")
                            packages.append(DetectedPackage(
                                ecosystem="vcpkg",
                                name=pkg_name,
                                version=installed_version or declared_version or "latest",
                                source_file="vcpkg.json",
                                declared_version=declared_version,
                                installed_version=installed_version,
                                version_source="installed" if installed_version else "declared"
                            ))
                except Exception:
                    pass

        # Swift: Package.swift
        swift_installed = self._parse_swift_lockfile(path)
        package_swift = path / "Package.swift"
        if package_swift.exists():
            content = self._safe_read_file(package_swift)
            if content:
                # Match .package(url: "...", from: "version") or .exact("version")
                for match in re.finditer(
                    r'\.package\s*\([^)]*url:\s*["\']https?://[^"\']*?/([^/"\']+)(?:\.git)?["\'][^)]*(?:from:|exact:)\s*["\'](\d+\.\d+(?:\.\d+)?)["\']',
                    content
                ):
                    # L'URL se termine par `.git` dans la quasi-totalite des
                    # Package.swift. Sans ce retrait, le nom vaut `Alamofire.git`
                    # alors que Package.resolved indexe sur l'identite `alamofire` :
                    # la jointure echoue en silence et la version declaree est
                    # remontee a la place de la version resolue.
                    pkg_name = match.group(1)
                    if pkg_name.lower().endswith(".git"):
                        pkg_name = pkg_name[: -len(".git")]
                    declared_version = match.group(2)
                    installed_version = swift_installed.get(pkg_name.lower(), "")
                    packages.append(DetectedPackage(
                        ecosystem="SwiftPM",
                        name=pkg_name,
                        version=installed_version or declared_version,
                        source_file="Package.swift",
                        declared_version=declared_version,
                        installed_version=installed_version,
                        version_source="installed" if installed_version else "declared"
                    ))

        # CMake: CMakeLists.txt (for C/C++ projects using CMake)
        cmake_packages = self._parse_cmake_packages(path)
        cmake_file = path / "CMakeLists.txt"
        if cmake_file.exists() and cmake_packages:
            for pkg_name, version in cmake_packages.items():
                # Only add if not already detected via Conan/vcpkg
                if pkg_name.lower() not in [p.name.lower() for p in packages]:
                    packages.append(DetectedPackage(
                        ecosystem="CMake",
                        name=pkg_name,
                        version=version,
                        source_file="CMakeLists.txt",
                        declared_version=version if version != "detected" else "",
                        installed_version="",
                        version_source="declared"
                    ))

        return packages[:100]  # Increased limit for multi-language projects

    def check_security(self, result: ScanResult) -> list[SecurityAlert]:
        """Check detected packages for known vulnerabilities via OSV.dev.

        Effet de bord assume : quand la verification est incomplete, un message
        est ajoute a `result.errors`. C'est le seul canal deja rendu a
        l'utilisateur (`generate_config` ecrit une section « Erreurs de scan »)
        et il ne demande aucun changement de contrat. Sans lui, une API
        injoignable et un projet sain rendent tous deux une liste vide.
        """
        if not result.packages:
            return []

        from .security import check_cve_osv_detailed

        dependencies = [
            (pkg.ecosystem, pkg.name, pkg.version)
            for pkg in result.packages
        ]

        outcome = check_cve_osv_detailed(dependencies)

        message = outcome.summary()
        if message and message not in result.errors:
            result.errors.append(message)

        alerts = []
        for cve in outcome.cves:
            alerts.append(SecurityAlert(
                cve_id=cve.id,
                package=cve.package,
                severity=cve.severity,
                summary=cve.summary[:150] if cve.summary else "",
                fixed_version=cve.fixed_version,
                references=cve.references[:3] if cve.references else []
            ))

        return alerts

    def _build_security_context(self, result: ScanResult) -> SecurityContext:
        """
        Build a SecurityContext from scan results for security guidelines generation.

        This converts the scanner's detection results into the format expected by
        the security module's get_security_guidelines() function.
        """
        context = SecurityContext()

        # Map detected languages to security module format
        language_mapping = {
            "Python": "python",
            "TypeScript": "typescript",
            "JavaScript": "javascript",
            "Go": "go",
            "Rust": "rust",
            "Java": "java",
            "Kotlin": "java",  # Kotlin uses Java security patterns
            "C#": "csharp",
            "PHP": "php",
            "Ruby": "ruby",
            "Swift": "swift",
            "C": "c",
            "C++": "cpp",
        }

        for lang in result.languages:
            mapped = language_mapping.get(lang.name)
            if mapped and mapped not in context.languages:
                context.languages.append(mapped)

        # Detect security-relevant keywords from frameworks and databases
        security_triggers = []

        # Framework categories that imply security concerns
        for fw in result.frameworks:
            name_lower = fw.name.lower()
            category = fw.category.lower()

            if category in ["backend", "orm"]:
                security_triggers.extend(["api", "database"])
            if "auth" in name_lower or "jwt" in name_lower:
                security_triggers.append("auth")
            if "oauth" in name_lower:
                security_triggers.extend(["auth", "oauth"])

        # Databases imply DB security concerns
        if result.databases:
            security_triggers.extend(["database", "sql", "query"])

        # File/upload detection from key files
        for kf in result.key_files:
            path_lower = kf.path.lower()
            if "upload" in path_lower or "file" in path_lower:
                security_triggers.append("file")
            if "auth" in path_lower or "login" in path_lower:
                security_triggers.append("auth")
            if "api" in path_lower or "route" in path_lower:
                security_triggers.append("api")

        # Detect from env variables
        for ev in result.env_variables:
            name_lower = ev.name.lower()
            if any(kw in name_lower for kw in ["secret", "key", "password", "token", "jwt"]):
                security_triggers.extend(["auth", "credentials"])

        # Deduplicate and add to context
        context.security_keywords_found = list(set(security_triggers))

        # Convert CVE alerts to CVEInfo if present
        if result.security_alerts:
            context.cves = [
                CVEInfo(
                    id=alert.cve_id,
                    summary=alert.summary,
                    severity=alert.severity,
                    package=alert.package,
                    affected_versions="detected",
                    fixed_version=alert.fixed_version,
                )
                for alert in result.security_alerts
            ]

        # Determine if dev context
        context.is_dev = len(context.languages) > 0

        # Determine security level based on findings
        cve_critical = sum(1 for a in result.security_alerts if a.severity == "CRITICAL")
        cve_high = sum(1 for a in result.security_alerts if a.severity == "HIGH")

        if cve_critical > 0 or len(context.security_keywords_found) >= 5:
            context.security_level = "critical"
        elif cve_high > 0 or len(context.security_keywords_found) >= 3:
            context.security_level = "elevated"
        else:
            context.security_level = "standard"

        return context

    def generate_config(
        self,
        result: ScanResult,
        project_name: str,
        description: Optional[str] = None,
    ) -> str:
        """
        Generate a Markdown configuration file from scan results.

        Args:
            result: The ScanResult from scanning
            project_name: Name for the project
            description: Optional description (uses README extraction if not provided)

        Returns:
            Markdown string ready to save
        """
        lines = [f"# {project_name}"]
        lines.append("")

        # Description
        desc = description or result.readme_description or "Description du projet."
        lines.append("## Description")
        lines.append("")
        lines.append(desc)
        lines.append("")

        # Stack Technique
        lines.append("---")
        lines.append("")
        lines.append("## Stack Technique")
        lines.append("")

        # Languages
        if result.languages:
            lines.append("### Langages")
            lines.append("")
            lines.append("| Langage | Version | Fichiers | % |")
            lines.append("|---------|---------|----------|---|")
            for lang in result.languages[:5]:
                version = lang.version or "-"
                lines.append(
                    f"| **{lang.name}** | {version} | {lang.file_count} | {lang.percentage}% |"
                )
            lines.append("")

        # Frameworks by category
        if result.frameworks:
            by_category: dict[str, list[DetectedFramework]] = {}
            for fw in result.frameworks:
                by_category.setdefault(fw.category, []).append(fw)

            category_labels = {
                "backend": "Backend",
                "frontend": "Frontend",
                "orm": "ORM / Base de donnees",
                "ui": "UI / Styling",
                "state": "State Management",
                "mobile": "Mobile",
                "other": "Autres",
            }

            for category, fws in by_category.items():
                label = category_labels.get(category, category.title())
                lines.append(f"### {label}")
                lines.append("")
                for fw in fws:
                    lines.append(f"- **{fw.name}**")
                lines.append("")

        # Databases
        if result.databases:
            lines.append("### Base de donnees")
            lines.append("")
            for db in result.databases:
                orm_str = f" (ORM: {db.orm})" if db.orm else ""
                lines.append(f"- **{db.name}**{orm_str}")
            lines.append("")

        # Infrastructure
        if result.docker and (result.docker.has_dockerfile or result.docker.has_compose):
            lines.append("### Infrastructure")
            lines.append("")
            if result.docker.has_dockerfile:
                lines.append("- Docker: Oui")
            if result.docker.has_compose:
                services_str = ", ".join(result.docker.services[:5]) if result.docker.services else ""
                lines.append(f"- Docker Compose: {result.docker.compose_file}")
                if services_str:
                    lines.append(f"- Services: {services_str}")
            lines.append("")

        # CI/CD
        if result.cicd and result.cicd.provider:
            lines.append("### CI/CD")
            lines.append("")
            lines.append(f"- Provider: **{result.cicd.provider}**")
            if result.cicd.workflows:
                lines.append(f"- Workflows: {', '.join(result.cicd.workflows[:5])}")
            lines.append("")

        # Structure
        lines.append("---")
        lines.append("")
        lines.append("## Structure du Projet")
        lines.append("")
        lines.append("```")
        if result.structure:
            lines.append(result.structure.tree_string)
        lines.append("```")
        lines.append("")

        # Conventions
        if result.conventions:
            lines.append("---")
            lines.append("")
            lines.append("## Conventions de Code")
            lines.append("")
            if result.conventions.formatter:
                lines.append(f"- **Formatter**: {result.conventions.formatter}")
            if result.conventions.linter:
                lines.append(f"- **Linter**: {result.conventions.linter}")
            if result.conventions.typechecker:
                lines.append(f"- **Type Checker**: {result.conventions.typechecker}")
            if result.conventions.line_length:
                lines.append(f"- **Longueur de ligne**: {result.conventions.line_length}")
            if result.conventions.config_files:
                lines.append(f"- **Fichiers de config**: {', '.join(result.conventions.config_files)}")
            lines.append("")

        # Tests
        if result.tests:
            lines.append("---")
            lines.append("")
            lines.append("## Tests")
            lines.append("")
            for test in result.tests:
                dirs_str = f" ({', '.join(test.test_dirs)})" if test.test_dirs else ""
                lines.append(f"- **{test.framework}**{dirs_str}")
            lines.append("")

        # Key Files (nouveau)
        if result.key_files:
            lines.append("---")
            lines.append("")
            lines.append("## Fichiers Clés")
            lines.append("")
            lines.append("| Fichier | Type | Description |")
            lines.append("|---------|------|-------------|")
            for kf in result.key_files[:10]:
                lines.append(f"| `{kf.path}` | {kf.category} | {kf.description} |")
            lines.append("")

        # Dev Commands (nouveau)
        if result.dev_commands:
            lines.append("---")
            lines.append("")
            lines.append("## Commandes de Développement")
            lines.append("")
            lines.append("| Commande | Source |")
            lines.append("|----------|--------|")
            for cmd in result.dev_commands[:10]:
                lines.append(f"| `{cmd.command}` | {cmd.source} |")
            lines.append("")

        # Environment Variables (nouveau)
        if result.env_variables:
            lines.append("---")
            lines.append("")
            lines.append("## Variables d'Environnement")
            lines.append("")
            lines.append("| Variable | Exemple |")
            lines.append("|----------|---------|")
            for ev in result.env_variables[:15]:
                example = ev.example if ev.example else "*à définir*"
                lines.append(f"| `{ev.name}` | {example} |")
            lines.append("")

        # =================================================================
        # SECURITY SECTION - Guidelines + CVE Alerts
        # =================================================================
        security_context = self._build_security_context(result)

        if security_context.is_dev:
            lines.append("---")
            lines.append("")
            lines.append("## Directives de Sécurité")
            lines.append("")

            # Security level indicator
            level_indicators = {
                "critical": "🔴 **CRITIQUE** - Attention requise immédiatement",
                "elevated": "🟠 **ÉLEVÉ** - Vigilance accrue recommandée",
                "standard": "🟢 **STANDARD** - Bonnes pratiques à appliquer",
            }
            lines.append(f"> Niveau de sécurité: {level_indicators.get(security_context.security_level, 'STANDARD')}")
            lines.append("")

            # Language-specific guidelines
            if security_context.languages:
                lines.append("### Bonnes Pratiques par Langage")
                lines.append("")

                if "python" in security_context.languages:
                    lines.append("#### Python")
                    lines.append("- Utiliser `secrets` au lieu de `random` pour tokens/mots de passe")
                    lines.append("- Requêtes SQL paramétrées (pas de f-string dans les queries)")
                    lines.append("- Valider les inputs avec Pydantic ou dataclasses")
                    lines.append("- `bcrypt` ou `argon2` pour le hashing de mots de passe")
                    lines.append("- Éviter les fonctions d'évaluation dynamique avec données utilisateur")
                    lines.append("")

                if "javascript" in security_context.languages or "typescript" in security_context.languages:
                    lines.append("#### JavaScript/TypeScript")
                    lines.append("- Échapper les outputs HTML (prévention XSS)")
                    lines.append("- Requêtes paramétrées pour les bases de données")
                    lines.append("- Valider les inputs côté serveur (ne jamais faire confiance au client)")
                    lines.append("- Configurer CORS correctement")
                    lines.append("- Utiliser `helmet.js` pour les headers de sécurité")
                    lines.append("")

                if "rust" in security_context.languages:
                    lines.append("#### Rust")
                    lines.append("- Préférer les types sûrs (`Option`, `Result`) aux valeurs nulles")
                    lines.append("- Utiliser `sqlx` avec requêtes paramétrées pour SQL")
                    lines.append("- `argon2` pour le hashing de mots de passe")
                    lines.append("- Éviter `unsafe` sauf si absolument nécessaire")
                    lines.append("")

                if "go" in security_context.languages:
                    lines.append("#### Go")
                    lines.append("- Utiliser `prepared statements` pour SQL")
                    lines.append("- Échapper les templates HTML avec `html/template`")
                    lines.append("- Valider les inputs avec `go-playground/validator`")
                    lines.append("- Ne jamais logger les secrets/mots de passe")
                    lines.append("")

                if "java" in security_context.languages:
                    lines.append("#### Java")
                    lines.append("- Utiliser `PreparedStatement` pour toutes les requêtes SQL")
                    lines.append("- Valider les inputs avec Bean Validation (JSR 380)")
                    lines.append("- Spring Security pour l'authentification")
                    lines.append("- Éviter la désérialisation de données non fiables")
                    lines.append("")

                if "csharp" in security_context.languages:
                    lines.append("#### C# / .NET")
                    lines.append("- Utiliser les requêtes paramétrées avec Entity Framework ou Dapper")
                    lines.append("- ASP.NET Core Identity pour l'authentification")
                    lines.append("- Anti-forgery tokens pour les formulaires")
                    lines.append("- Encoder les outputs HTML avec `HtmlEncoder`")
                    lines.append("")

                if "php" in security_context.languages:
                    lines.append("#### PHP")
                    lines.append("- PDO avec requêtes préparées pour SQL")
                    lines.append("- `password_hash()` / `password_verify()` pour les mots de passe")
                    lines.append("- `htmlspecialchars()` pour l'échappement HTML")
                    lines.append("- Valider les uploads avec vérification MIME réelle")
                    lines.append("")

                if "ruby" in security_context.languages:
                    lines.append("#### Ruby")
                    lines.append("- ActiveRecord avec requêtes paramétrées (where avec placeholders)")
                    lines.append("- `has_secure_password` pour le hashing de mots de passe")
                    lines.append("- Strong Parameters dans Rails pour filtrer les inputs")
                    lines.append("- Protection CSRF activée par défaut dans Rails")
                    lines.append("")

                if "swift" in security_context.languages:
                    lines.append("#### Swift / iOS")
                    lines.append("- Keychain pour stocker les credentials (pas UserDefaults)")
                    lines.append("- App Transport Security (ATS) activé")
                    lines.append("- Certificate pinning pour les connexions sensibles")
                    lines.append("- Valider les inputs avant traitement")
                    lines.append("")

                if "c" in security_context.languages or "cpp" in security_context.languages:
                    lines.append("#### C/C++")
                    lines.append("- Éviter les fonctions non-sécurisées: gets, strcpy, sprintf")
                    lines.append("- Utiliser fgets, strncpy, snprintf avec vérification des bornes")
                    lines.append("- Toujours initialiser les variables avant utilisation")
                    lines.append("- RAII en C++ pour la gestion mémoire automatique")
                    lines.append("- Compiler avec: -fstack-protector -D_FORTIFY_SOURCE=2 -fPIE")
                    lines.append("- Utiliser AddressSanitizer/MemorySanitizer pour le debug")
                    lines.append("")

            # Context-specific recommendations
            if security_context.security_keywords_found:
                lines.append("### Recommandations Spécifiques")
                lines.append("")

                if any(k in security_context.security_keywords_found for k in ["auth", "login", "password", "jwt", "token", "credentials"]):
                    lines.append("#### 🔐 Authentification")
                    lines.append("- Implémenter rate limiting sur les endpoints d'auth")
                    lines.append("- HTTPS uniquement pour toutes les communications")
                    lines.append("- JWT: expiration courte, refresh tokens, signature forte (RS256)")
                    lines.append("- Stocker les mots de passe avec bcrypt/argon2 (jamais MD5/SHA1)")
                    lines.append("- Protection CSRF sur tous les formulaires")
                    lines.append("")

                if any(k in security_context.security_keywords_found for k in ["sql", "database", "query"]):
                    lines.append("#### 🗄️ Base de Données")
                    lines.append("- **TOUJOURS** utiliser des requêtes paramétrées (prepared statements)")
                    lines.append("- Principe du moindre privilège pour les accès DB")
                    lines.append("- Chiffrer les données sensibles au repos")
                    lines.append("- Valider et sanitizer les inputs avant insertion")
                    lines.append("")

                if any(k in security_context.security_keywords_found for k in ["file", "upload"]):
                    lines.append("#### 📁 Fichiers & Uploads")
                    lines.append("- Valider le type MIME et l'extension des fichiers uploadés")
                    lines.append("- Limiter la taille des uploads")
                    lines.append("- Stocker hors du webroot avec noms générés")
                    lines.append("- Éviter les path traversal (../../)")
                    lines.append("")

                if any(k in security_context.security_keywords_found for k in ["api", "endpoint", "route"]):
                    lines.append("#### 🌐 API Security")
                    lines.append("- Authentification sur tous les endpoints sensibles")
                    lines.append("- Rate limiting et throttling")
                    lines.append("- Validation des inputs (schema validation)")
                    lines.append("- Headers de sécurité (CORS, CSP, X-Frame-Options)")
                    lines.append("- Logging des accès et erreurs")
                    lines.append("")

            # OWASP Top 10 Reminder
            lines.append("### Rappel OWASP Top 10 (2021)")
            lines.append("")
            lines.append("Vérifier que le code n'est pas vulnérable à:")
            lines.append("")
            lines.append("| # | Vulnérabilité | Points clés |")
            lines.append("|---|---------------|-------------|")
            lines.append("| A01 | Broken Access Control | Contrôle d'accès, permissions |")
            lines.append("| A02 | Cryptographic Failures | Chiffrement, hashing, secrets |")
            lines.append("| A03 | Injection | SQL, Command, XSS, LDAP |")
            lines.append("| A04 | Insecure Design | Architecture sécurisée |")
            lines.append("| A05 | Security Misconfiguration | Configs par défaut, debug |")
            lines.append("| A06 | Vulnerable Components | Dépendances à jour |")
            lines.append("| A07 | Auth Failures | Sessions, mots de passe |")
            lines.append("| A08 | Integrity Failures | CI/CD, désérialisation |")
            lines.append("| A09 | Logging Failures | Monitoring, alerting |")
            lines.append("| A10 | SSRF | Requêtes serveur-side |")
            lines.append("")

        # Verification CVE incomplete : elle doit se voir, sinon l'absence de
        # section « Alertes de Securite » se lit comme « aucune vulnerabilite »
        # alors qu'elle veut dire « on ne sait pas ».
        from .security import CVE_CHECK_INCOMPLETE_PREFIX

        cve_check_warnings = [
            error for error in result.errors
            if error.startswith(CVE_CHECK_INCOMPLETE_PREFIX)
        ]
        if cve_check_warnings:
            lines.append("---")
            lines.append("")
            lines.append("## Verification des Vulnerabilites : INCOMPLETE")
            lines.append("")
            lines.append(
                "L'absence d'alerte ci-dessous ne signifie PAS que le projet est sain : "
                "une partie des dependances n'a pas pu etre verifiee."
            )
            lines.append("")
            for warning in cve_check_warnings:
                lines.append(f"- {warning}")
            lines.append("")

        # Security Alerts (if any)
        if result.security_alerts:
            lines.append("---")
            lines.append("")
            lines.append("## Alertes de Sécurité")
            lines.append("")
            lines.append("⚠️ **Des vulnérabilités ont été détectées dans les dépendances:**")
            lines.append("")

            # Group by severity
            critical = [a for a in result.security_alerts if a.severity == "CRITICAL"]
            high = [a for a in result.security_alerts if a.severity == "HIGH"]
            medium = [a for a in result.security_alerts if a.severity == "MEDIUM"]

            def format_cve_link(cve_id: str) -> str:
                """Generate clickable link for CVE."""
                if cve_id.startswith("CVE-"):
                    return f"[{cve_id}](https://nvd.nist.gov/vuln/detail/{cve_id})"
                elif cve_id.startswith("GHSA-"):
                    return f"[{cve_id}](https://github.com/advisories/{cve_id})"
                elif cve_id.startswith("PYSEC-"):
                    return f"[{cve_id}](https://osv.dev/vulnerability/{cve_id})"
                else:
                    return f"[{cve_id}](https://osv.dev/vulnerability/{cve_id})"

            if critical:
                lines.append("### 🔴 CRITIQUES - Action immédiate requise")
                lines.append("")
                for alert in critical:
                    cve_link = format_cve_link(alert.cve_id)
                    lines.append(f"#### {cve_link} - `{alert.package}`")
                    lines.append("")
                    if alert.summary:
                        lines.append(f"**Description:** {alert.summary}")
                    if alert.fixed_version:
                        lines.append(f"")
                        lines.append(f"**Remediation:** Mettre à jour vers `{alert.fixed_version}` ou version supérieure")
                    else:
                        lines.append(f"")
                        lines.append(f"**Remediation:** Vérifier si une version corrigée existe ou envisager une alternative")
                    if alert.references:
                        lines.append("")
                        lines.append("**Références:**")
                        for ref in alert.references[:2]:
                            lines.append(f"- {ref}")
                    lines.append("")

            if high:
                lines.append("### 🟠 ÉLEVÉES - Correction recommandée rapidement")
                lines.append("")
                for alert in high[:5]:
                    cve_link = format_cve_link(alert.cve_id)
                    fix_str = f" → Mettre à jour vers `{alert.fixed_version}`" if alert.fixed_version else ""
                    lines.append(f"- {cve_link}: `{alert.package}`{fix_str}")
                    if alert.references:
                        lines.append(f"  - Ref: {alert.references[0]}")
                if len(high) > 5:
                    lines.append(f"- ... et {len(high) - 5} autres vulnérabilités élevées")
                lines.append("")

            if medium:
                lines.append(f"### 🟡 MOYENNES ({len(medium)}) - À planifier")
                lines.append("")
                for alert in medium[:3]:
                    cve_link = format_cve_link(alert.cve_id)
                    fix_str = f" → `{alert.fixed_version}`" if alert.fixed_version else ""
                    lines.append(f"- {cve_link}: `{alert.package}`{fix_str}")
                if len(medium) > 3:
                    lines.append(f"- ... et {len(medium) - 3} autres")
                lines.append("")

            # Add remediation commands section
            lines.append("### Commandes de Remediation")
            lines.append("")
            # Group by ecosystem
            ecosystems_fixes = {}
            for alert in result.security_alerts:
                if alert.fixed_version:
                    # Find the package ecosystem
                    for pkg in result.packages:
                        if pkg.name.lower() == alert.package.lower():
                            eco = pkg.ecosystem
                            if eco not in ecosystems_fixes:
                                ecosystems_fixes[eco] = []
                            ecosystems_fixes[eco].append((alert.package, alert.fixed_version))
                            break

            if ecosystems_fixes:
                lines.append("```bash")
                if "PyPI" in ecosystems_fixes:
                    fixes = ecosystems_fixes["PyPI"]
                    lines.append("# Python - mettre à jour les packages vulnérables:")
                    for pkg, ver in fixes[:5]:
                        lines.append(f"pip install '{pkg}>={ver}'")
                    lines.append("")
                if "npm" in ecosystems_fixes:
                    fixes = ecosystems_fixes["npm"]
                    lines.append("# Node.js - mettre à jour les packages vulnérables:")
                    for pkg, ver in fixes[:5]:
                        lines.append(f"npm install {pkg}@^{ver}")
                    lines.append("")
                if "crates.io" in ecosystems_fixes:
                    fixes = ecosystems_fixes["crates.io"]
                    lines.append("# Rust - mettre à jour Cargo.toml puis:")
                    lines.append("cargo update")
                    lines.append("")
                if "RubyGems" in ecosystems_fixes:
                    fixes = ecosystems_fixes["RubyGems"]
                    lines.append("# Ruby - mettre à jour les gems:")
                    for pkg, ver in fixes[:5]:
                        lines.append(f"gem install {pkg} -v '>= {ver}'")
                    lines.append("")
                if "NuGet" in ecosystems_fixes:
                    lines.append("# .NET - mettre à jour les packages:")
                    lines.append("dotnet restore")
                    lines.append("")
                if "Maven" in ecosystems_fixes:
                    lines.append("# Java Maven - mettre à jour pom.xml puis:")
                    lines.append("mvn dependency:resolve")
                    lines.append("")
                if "Packagist" in ecosystems_fixes:
                    lines.append("# PHP - mettre à jour composer.json puis:")
                    lines.append("composer update")
                    lines.append("")
                lines.append("```")
                lines.append("")
            else:
                lines.append("Aucune commande de remediation automatique disponible.")
                lines.append("Vérifier manuellement les versions des packages affectés.")
                lines.append("")

        # Secret Findings (API keys, passwords, tokens)
        if result.secret_findings:
            lines.append("---")
            lines.append("")
            secret_alert_text = format_secret_alerts(result.secret_findings)
            lines.append(secret_alert_text)

        # Footer
        lines.append("---")
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        lines.append(f"- Configuration generee automatiquement par PromptForge Scanner")
        lines.append(f"- Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"- Fichiers scannes: {result.files_scanned}")
        lines.append(f"- Duree du scan: {result.scan_duration_ms}ms")

        if result.errors:
            lines.append("")
            lines.append("### Erreurs de scan")
            lines.append("")
            for error in result.errors[:5]:
                lines.append(f"- {error}")

        return "\n".join(lines)


# =============================================================================
# PUBLIC API
# =============================================================================


def scan_directory(
    path: str | Path,
    max_depth: int = 3,
    max_files: int = 10000,
) -> ScanResult:
    """
    Convenience function to scan a directory.

    Args:
        path: Directory path to scan
        max_depth: Maximum directory depth (default: 3)
        max_files: Maximum files to scan (default: 10000)

    Returns:
        ScanResult with all detected information
    """
    scanner = ProjectScanner(max_depth=max_depth, max_files=max_files)
    return scanner.scan(Path(path))
