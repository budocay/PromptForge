"""
Tests pour le module scanner (ProjectScanner).
"""

from pathlib import Path

import pytest

from promptforge.scanner import (
    DEFAULT_IGNORE_PATTERNS,
    DetectedFramework,
    DetectedLanguage,
    ProjectScanner,
    ScanResult,
    normalize_version_constraint,
    scan_directory,
)


class TestDataclasses:
    """Tests pour les dataclasses."""

    def test_detected_language(self):
        """Test DetectedLanguage dataclass."""
        lang = DetectedLanguage(
            name="Python",
            extensions=[".py"],
            file_count=10,
            percentage=50.0,
            version="3.12",
        )
        assert lang.name == "Python"
        assert lang.file_count == 10
        assert lang.version == "3.12"

    def test_detected_framework(self):
        """Test DetectedFramework dataclass."""
        fw = DetectedFramework(
            name="FastAPI",
            category="backend",
            version="0.100.0",
            config_file="requirements.txt",
        )
        assert fw.name == "FastAPI"
        assert fw.category == "backend"

    def test_scan_result_defaults(self):
        """Test ScanResult avec valeurs par défaut."""
        result = ScanResult()
        assert result.languages == []
        assert result.frameworks == []
        assert result.databases == []
        assert result.files_scanned == 0
        assert result.errors == []


class TestProjectScannerInit:
    """Tests pour l'initialisation du scanner."""

    def test_init_defaults(self):
        """Test des valeurs par défaut."""
        scanner = ProjectScanner()
        assert scanner.max_depth == 3
        assert scanner.max_files == 10000
        assert scanner.timeout_seconds == 30
        assert scanner.ignore_patterns == DEFAULT_IGNORE_PATTERNS

    def test_init_custom_values(self):
        """Test avec valeurs personnalisées."""
        scanner = ProjectScanner(
            max_depth=5,
            max_files=5000,
            timeout_seconds=60,
            ignore_patterns=["custom"],
        )
        assert scanner.max_depth == 5
        assert scanner.max_files == 5000
        assert scanner.ignore_patterns == ["custom"]


class TestScanValidation:
    """Tests pour la validation du scan."""

    def test_scan_nonexistent_path(self, temp_dir):
        """Test avec chemin inexistant."""
        scanner = ProjectScanner()
        with pytest.raises(ValueError, match="does not exist"):
            scanner.scan(Path(temp_dir) / "nonexistent")

    def test_scan_file_instead_of_dir(self, temp_dir):
        """Test avec fichier au lieu de répertoire."""
        file_path = Path(temp_dir) / "file.txt"
        file_path.write_text("content")

        scanner = ProjectScanner()
        with pytest.raises(ValueError, match="not a directory"):
            scanner.scan(file_path)


class TestLanguageDetection:
    """Tests pour la détection des langages."""

    def test_detect_python(self, temp_dir):
        """Test détection Python."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "utils.py").write_text("def helper(): pass")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert len(result.languages) == 1
        assert result.languages[0].name == "Python"
        assert result.languages[0].file_count == 2
        assert result.languages[0].percentage == 100.0

    def test_detect_multiple_languages(self, temp_dir):
        """Test détection de plusieurs langages."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()

        # Python files
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "utils.py").write_text("def helper(): pass")

        # JavaScript files
        (project_dir / "app.js").write_text("console.log('hello')")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert len(result.languages) == 2
        lang_names = [lang.name for lang in result.languages]
        assert "Python" in lang_names
        assert "JavaScript" in lang_names

        # Python should be first (more files)
        assert result.languages[0].name == "Python"
        assert result.languages[0].file_count == 2

    def test_detect_python_version(self, temp_dir):
        """Test détection version Python."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.11"\n')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.languages[0].version == "3.11"

    def test_detect_python_version_from_python_version_file(self, temp_dir):
        """Test détection version depuis .python-version."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / ".python-version").write_text("3.12.0\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.languages[0].version == "3.12.0"


class TestVersionNormalization:
    """Tests pour normalize_version_constraint (F-005)."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (">=3.11", "3.11"),
            (">= 3.11", "3.11"),
            ("^3.11", "3.11"),
            ("~=3.10", "3.10"),
            ("~3.10.2", "3.10.2"),
            (">=3.10,<3.13", "3.10"),  # on garde la borne basse, seule garantie
            ("3.12.0", "3.12.0"),
            ("v18.14.2", "18.14.2"),
            ("==2.0", "2.0"),
            ("  1.75  ", "1.75"),
            ('"3.11"', "3.11"),
        ],
    )
    def test_extracts_concrete_version(self, raw, expected):
        assert normalize_version_constraint(raw) == expected

    @pytest.mark.parametrize("raw", ["stable", "latest", "nightly"])
    def test_keeps_non_numeric_channels_verbatim(self, raw):
        """Un canal sans chiffre est une information vraie : on la garde."""
        assert normalize_version_constraint(raw) == raw

    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_returns_none_on_empty(self, raw):
        assert normalize_version_constraint(raw) is None

    def test_no_constraint_operator_leaks_into_result(self):
        """Aucun operateur de contrainte ne doit survivre a la normalisation."""
        for raw in [">=3.11", "^3.11", "~=3.10", ">=3.10,<3.13", "==2.0"]:
            result = normalize_version_constraint(raw)
            assert not any(c in result for c in "><=^~,")

    @pytest.mark.parametrize(
        "raw",
        [
            "<4",  # rendait "4", une borne HAUTE
            "<=3.12",  # meme famille
            "!=3.9",  # rendait "3.9", une version EXCLUE
        ],
    )
    def test_returns_none_when_no_clause_states_a_lower_bound(self, raw):
        """Contre-exemples mesures par le SECURITY GATE, corriges.

        L'implementation precedente prenait le premier nombre rencontre et
        rendait donc une borne haute ou une version explicitement exclue. Aucune
        des deux n'est une version du projet ; None est la seule reponse vraie.
        """
        assert normalize_version_constraint(raw) is None

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("<3.13,>=3.10", "3.10"),  # rendait "3.13", la borne HAUTE
            ("!=3.9,>=3.11", "3.11"),  # rendait "3.9", la version EXCLUE
            (">=3.10,<3.13", "3.10"),  # deja correct, verrouille dans l'autre ordre
            ("!=3.9,!=3.10,>=3.8", "3.8"),
        ],
    )
    def test_reads_the_operator_not_the_position(self, raw, expected):
        """L'ordre d'ecriture des clauses ne doit plus changer le resultat."""
        assert normalize_version_constraint(raw) == expected

    def test_clause_order_is_irrelevant(self):
        """Meme contrainte, deux ecritures : meme reponse."""
        assert normalize_version_constraint(">=3.10,<3.13") == normalize_version_constraint(
            "<3.13,>=3.10"
        )

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (">=3.10,>=3.11", "3.11"),
            (">=3.9,>=3.11,>=3.10", "3.11"),
            (">=3.9,>=3.10.2", "3.10.2"),
        ],
    )
    def test_highest_floor_wins(self, raw, expected):
        """Plusieurs planchers : le plus haut est le seul qui contraigne."""
        assert normalize_version_constraint(raw) == expected

    def test_strict_lower_bound_is_an_accepted_approximation(self):
        """`>3.10` exclut 3.10, et 3.10 est pourtant rendu.

        Approximation assumee et documentee dans la docstring : nommer la
        version suivante demanderait un index des versions publiees, que le
        scanner n'a pas et ne doit pas aller chercher.
        """
        assert normalize_version_constraint(">3.10") == "3.10"


class TestPythonVersionDetection:
    """Tests de non-regression sur la lecture de version Python (F-005)."""

    def test_poetry_python_constraint(self, temp_dir):
        """La cle Poetry `python = "^3.10"` est lue et normalisee."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "pyproject.toml").write_text(
            '[tool.poetry.dependencies]\npython = "^3.10"\n'
        )

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.languages[0].version == "3.10"

    def test_requires_python_alone_is_normalized(self, temp_dir):
        """Un `pyproject.toml` PEP 621 seul rend la borne basse normalisee.

        Test de non-regression sur la normalisation, PAS sur le lookbehind : les
        deux motifs Python rendent ici le meme resultat, donc retirer le
        lookbehind laisse ce test vert. Le cas discriminant est ci-dessous.
        """
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.10,<3.13"\n')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.languages[0].version == "3.10"

    def test_poetry_key_wins_over_requires_python_when_both_are_present(self, temp_dir):
        r"""Le lookbehind de VERSION_FILES["Python"][0] est ici le seul discriminant.

        Les deux cles coexistent avec des valeurs *distinctes*, et
        `requires-python` precede la cle Poetry dans le fichier :

            [project]
            requires-python = ">=3.11"

            [tool.poetry.dependencies]
            python = "^3.9"

        Le motif Poetry est premier dans VERSION_FILES et gagne donc la
        detection. Avec le lookbehind `(?<![\w-])` il ne peut matcher que la
        vraie cle Poetry, donc `3.9`. Sans lui, il matche le `python` de
        `requires-python`, rencontre plus tot dans le fichier, et rend `3.11`.

        Recette du verrou : retirer `(?<![\w-])` du motif doit faire virer ce
        test au rouge sur `assert "3.9" == "3.11"`.
        """
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "pyproject.toml").write_text(
            "[project]\n"
            'requires-python = ">=3.11"\n'
            "\n"
            "[tool.poetry.dependencies]\n"
            'python = "^3.9"\n'
        )

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.languages[0].version == "3.9"


class TestFrameworkDetection:
    """Tests pour la détection des frameworks."""

    def test_detect_fastapi(self, temp_dir):
        """Test détection FastAPI."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("from fastapi import FastAPI")
        (project_dir / "requirements.txt").write_text("fastapi==0.100.0\nuvicorn\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        fw_names = [f.name for f in result.frameworks]
        assert "FastAPI" in fw_names

        fastapi = next(f for f in result.frameworks if f.name == "FastAPI")
        assert fastapi.category == "backend"

    def test_detect_react(self, temp_dir):
        """Test détection React."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "app.tsx").write_text("import React from 'react'")
        (project_dir / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        fw_names = [f.name for f in result.frameworks]
        assert "React" in fw_names

    def test_detect_tailwind_by_config_file(self, temp_dir):
        """Test détection TailwindCSS par fichier de config."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "app.js").write_text("console.log('hello')")
        (project_dir / "tailwind.config.js").write_text(
            "module.exports = { content: ['./src/**/*.{js,ts}'] }"
        )

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        fw_names = [f.name for f in result.frameworks]
        assert "TailwindCSS" in fw_names

    def test_detect_multiple_frameworks(self, temp_dir):
        """Test détection de plusieurs frameworks."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "requirements.txt").write_text("fastapi\nsqlalchemy\npytest\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        fw_names = [f.name for f in result.frameworks]
        assert "FastAPI" in fw_names
        assert "SQLAlchemy" in fw_names


class TestDatabaseDetection:
    """Tests pour la détection des bases de données."""

    def test_detect_postgres_from_docker_compose(self, temp_dir):
        """Test détection PostgreSQL via docker-compose."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "docker-compose.yml").write_text("""
version: '3.8'
services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: mydb
  app:
    build: .
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        db_names = [d.name for d in result.databases]
        assert "PostgreSQL" in db_names

    def test_detect_postgres_from_env(self, temp_dir):
        """Test détection PostgreSQL via .env."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / ".env").write_text("DATABASE_URL=postgresql://user:pass@localhost/db\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        db_names = [d.name for d in result.databases]
        assert "PostgreSQL" in db_names

    def test_detect_redis_from_packages(self, temp_dir):
        """Test détection Redis via packages."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("import redis")
        (project_dir / "requirements.txt").write_text("redis\nfastapi\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        db_names = [d.name for d in result.databases]
        assert "Redis" in db_names


class TestConventionDetection:
    """Tests pour la détection des conventions de code."""

    def test_detect_black_from_pyproject(self, temp_dir):
        """Test détection black via pyproject.toml."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "pyproject.toml").write_text("""
[tool.black]
line-length = 100
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.conventions is not None
        assert result.conventions.formatter == "black"
        assert result.conventions.line_length == 100

    def test_detect_ruff_from_pyproject(self, temp_dir):
        """Test détection ruff via pyproject.toml."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "pyproject.toml").write_text("""
[tool.ruff]
select = ["E", "F"]
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.conventions is not None
        assert result.conventions.linter == "ruff"

    def test_detect_prettier_from_file(self, temp_dir):
        """Test détection prettier via fichier de config."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "app.js").write_text("console.log('hello')")
        (project_dir / ".prettierrc").write_text('{"semi": true}')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.conventions is not None
        assert result.conventions.formatter == "prettier"

    def test_detect_eslint_from_file(self, temp_dir):
        """Test détection eslint via fichier de config."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "app.js").write_text("console.log('hello')")
        (project_dir / ".eslintrc.json").write_text('{"rules": {}}')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.conventions is not None
        assert result.conventions.linter == "eslint"


class TestTestDetection:
    """Tests pour la détection des tests."""

    def test_detect_pytest(self, temp_dir):
        """Test détection pytest."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "pytest.ini").write_text("[pytest]\n")
        tests_dir = project_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_main.py").write_text("def test_example(): pass")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        test_names = [t.framework for t in result.tests]
        assert "pytest" in test_names

        pytest_setup = next(t for t in result.tests if t.framework == "pytest")
        assert "tests" in pytest_setup.test_dirs

    def test_detect_jest(self, temp_dir):
        """Test détection Jest."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "app.js").write_text("console.log('hello')")
        (project_dir / "package.json").write_text('{"devDependencies": {"jest": "^29.0.0"}}')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        test_names = [t.framework for t in result.tests]
        assert "Jest" in test_names

    def test_detect_vitest(self, temp_dir):
        """Test détection Vitest."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "app.ts").write_text("console.log('hello')")
        (project_dir / "vitest.config.ts").write_text("export default { test: { } }")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        test_names = [t.framework for t in result.tests]
        assert "Vitest" in test_names

    def test_detect_vitest_from_package_json(self, temp_dir):
        """Vitest declare dans package.json est detecte par le motif de contenu."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "app.ts").write_text("console.log('hello')")
        (project_dir / "package.json").write_text('{"devDependencies": {"vitest": "^1.0.0"}}')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        test_names = [t.framework for t in result.tests]
        assert "Vitest" in test_names

    def test_shared_manifest_without_the_tool_is_not_a_detection(self, temp_dir):
        """Un package.json sans vitest ne doit pas faire detecter Vitest.

        Pendant de test_detect_vitest : assouplir la preuve pour les fichiers de
        config dedies ne doit pas assouplir celle des manifestes partages.
        """
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "app.ts").write_text("console.log('hello')")
        (project_dir / "package.json").write_text('{"devDependencies": {"typescript": "^5.0.0"}}')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        test_names = [t.framework for t in result.tests]
        assert "Vitest" not in test_names
        assert "Jest" not in test_names
        assert "Mocha" not in test_names

    def test_detect_mocha_from_dedicated_config(self, temp_dir):
        """`.mocharc.json` se suffit a lui-meme, comme vitest.config.ts."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "app.js").write_text("console.log('hello')")
        (project_dir / ".mocharc.json").write_text('{"spec": "test/**/*.spec.js"}')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        test_names = [t.framework for t in result.tests]
        assert "Mocha" in test_names


class TestDockerDetection:
    """Tests pour la détection Docker."""

    def test_detect_dockerfile(self, temp_dir):
        """Test détection Dockerfile."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "Dockerfile").write_text("FROM python:3.12\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.docker is not None
        assert result.docker.has_dockerfile is True

    def test_detect_docker_compose(self, temp_dir):
        """Test détection docker-compose."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "docker-compose.yml").write_text("""
version: '3.8'
services:
  app:
    build: .
  redis:
    image: redis
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.docker is not None
        assert result.docker.has_compose is True
        assert result.docker.compose_file == "docker-compose.yml"
        assert "app" in result.docker.services
        assert "redis" in result.docker.services


class TestCICDDetection:
    """Tests pour la détection CI/CD."""

    def test_detect_github_actions(self, temp_dir):
        """Test détection GitHub Actions."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")

        workflows_dir = project_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "ci.yml").write_text("name: CI\non: push\n")
        (workflows_dir / "deploy.yml").write_text("name: Deploy\non: release\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.cicd is not None
        assert result.cicd.provider == "GitHub Actions"
        assert "ci" in result.cicd.workflows
        assert "deploy" in result.cicd.workflows

    def test_detect_gitlab_ci(self, temp_dir):
        """Test détection GitLab CI."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / ".gitlab-ci.yml").write_text("stages:\n  - test\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.cicd is not None
        assert result.cicd.provider == "GitLab CI"


class TestReadmeExtraction:
    """Tests pour l'extraction de description du README."""

    def test_extract_description_from_readme(self, temp_dir):
        """Test extraction description."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "README.md").write_text("""# My Project

This is a wonderful project that does amazing things.
It helps developers be more productive.

## Installation
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.readme_description is not None
        assert "wonderful project" in result.readme_description

    def test_skip_badges_in_readme(self, temp_dir):
        """Test que les badges sont ignorés."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "README.md").write_text("""# My Project

![Build Status](https://img.shields.io/badge/build-passing-green)
[![Coverage](https://codecov.io/badge.svg)](https://codecov.io/)

This is the actual description.

## Installation
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.readme_description is not None
        assert "actual description" in result.readme_description
        assert "badge" not in result.readme_description.lower()


class TestIgnorePatterns:
    """Tests pour les patterns ignorés."""

    def test_ignore_node_modules(self, temp_dir):
        """Test que node_modules est ignoré."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")

        node_modules = project_dir / "node_modules"
        node_modules.mkdir()
        (node_modules / "package.js").write_text("// ignored")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        # Only main.py should be detected
        assert len(result.languages) == 1
        assert result.languages[0].name == "Python"

    def test_ignore_pycache(self, temp_dir):
        """Test que __pycache__ est ignoré."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")

        pycache = project_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "main.cpython-312.pyc").write_bytes(b"compiled")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        # pycache files should not be counted
        assert result.languages[0].file_count == 1


class TestStructureDetection:
    """Tests pour la détection de structure."""

    def test_scan_structure(self, temp_dir):
        """Test scan de la structure."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")

        src = project_dir / "src"
        src.mkdir()
        (src / "app.py").write_text("# app")

        tests = project_dir / "tests"
        tests.mkdir()
        (tests / "test_main.py").write_text("# tests")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.structure is not None
        assert result.structure.root_name == "project"
        assert "src" in result.structure.directories
        assert "tests" in result.structure.directories
        assert result.structure.total_files >= 3
        assert result.structure.total_dirs >= 2


class TestConfigGeneration:
    """Tests pour la génération de configuration."""

    def test_generate_basic_config(self, temp_dir):
        """Test génération de config basique."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "requirements.txt").write_text("fastapi\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)
        config = scanner.generate_config(result, "my-project", "Test description")

        assert "# my-project" in config
        assert "Test description" in config
        assert "Python" in config
        assert "FastAPI" in config

    def test_generate_config_with_readme_description(self, temp_dir):
        """Test génération avec description du README."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "README.md").write_text("""# My App

A fantastic application for testing.
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)
        config = scanner.generate_config(result, "my-app")

        assert "fantastic application" in config

    def test_generate_config_structure(self, temp_dir):
        """Test que la structure est incluse."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        src = project_dir / "src"
        src.mkdir()
        (src / "app.py").write_text("# app")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)
        config = scanner.generate_config(result, "my-project")

        assert "## Structure du Projet" in config
        assert "```" in config

    def test_generate_config_footer(self, temp_dir):
        """Test que le footer est présent."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)
        config = scanner.generate_config(result, "my-project")

        assert "PromptForge Scanner" in config
        assert "Fichiers scannes" in config


class TestConvenienceFunction:
    """Tests pour la fonction de convenance."""

    def test_scan_directory_function(self, temp_dir):
        """Test scan_directory()."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")

        result = scan_directory(project_dir)

        assert isinstance(result, ScanResult)
        assert len(result.languages) == 1

    def test_scan_directory_with_options(self, temp_dir):
        """Test scan_directory() avec options."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")

        result = scan_directory(project_dir, max_depth=1, max_files=100)

        assert isinstance(result, ScanResult)


class TestErrorHandling:
    """Tests pour la gestion des erreurs."""

    def test_scan_duration_recorded(self, temp_dir):
        """Test que la durée est enregistrée."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.scan_duration_ms > 0

    def test_files_scanned_count(self, temp_dir):
        """Test que le compte de fichiers est correct."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "file1.py").write_text("# 1")
        (project_dir / "file2.py").write_text("# 2")
        (project_dir / "file3.py").write_text("# 3")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.files_scanned >= 3

    def test_project_name_suggestion(self, temp_dir):
        """Test suggestion de nom de projet."""
        project_dir = Path(temp_dir) / "my-awesome-project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        assert result.project_name_suggestion == "my-awesome-project"


class TestPrismaDetection:
    """Une seule signature Prisma couvre JS et Python.

    Deux cles "Prisma" coexistaient dans FRAMEWORK_SIGNATURES : la seconde
    ecrasait la premiere et un projet Python (prisma-client-py) n'etait plus
    detecte.
    """

    @pytest.mark.parametrize(
        "filename,content",
        [
            ("package.json", '{"dependencies": {"@prisma/client": "5.0.0"}}'),
            ("requirements.txt", "fastapi==0.110\nprisma==0.13.1\n"),
            ("schema.prisma", 'generator client {\n  provider = "prisma-client-js"\n}\n'),
        ],
    )
    def test_prisma_is_detected(self, temp_dir, filename, content):
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / filename).write_text(content)

        result = ProjectScanner().scan(project_dir)

        assert "Prisma" in [fw.name for fw in result.frameworks]

    def test_similar_package_name_is_not_prisma(self, temp_dir):
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "requirements.txt").write_text("prismatic==1.0\n")

        result = ProjectScanner().scan(project_dir)

        assert "Prisma" not in [fw.name for fw in result.frameworks]
