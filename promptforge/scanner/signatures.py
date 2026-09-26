"""Signatures de detection du scanner : fichiers, motifs et versions."""

import re

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
        version for operator, version in clauses if operator not in _UPPER_OR_EXCLUDING_OPERATORS
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
        "pattern": r"rocket\s*=",
        "category": "backend",
    },
    "Axum": {
        "files": ["Cargo.toml"],
        "pattern": r"axum\s*=",
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
