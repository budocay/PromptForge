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
from pathlib import Path

from ..security import (
    CVEInfo,
    SecurityContext,
    scan_directory_for_secrets,
)
from .config_generator import ConfigGeneratorMixin
from .lockfiles import LockfileParsersMixin
from .models import (
    CICDSetup,
    CodeConventions,
    DetectedDatabase,
    DetectedFramework,
    DetectedLanguage,
    DetectedPackage,
    DevCommand,
    DockerSetup,
    EnvVariable,
    KeyFile,
    ProjectStructure,
    ScanResult,
    SecurityAlert,
    TestSetup,
)
from .signatures import (
    CICD_SIGNATURES,
    CONVENTION_FILES,
    DATABASE_SIGNATURES,
    DEFAULT_IGNORE_PATTERNS,
    FRAMEWORK_SIGNATURES,
    LANGUAGE_EXTENSIONS,
    SHARED_MANIFEST_FILES,
    TEST_SIGNATURES,
    VERSION_FILES,
    normalize_version_constraint,
)

# =============================================================================
# PROJECT SCANNER
# =============================================================================


class ProjectScanner(LockfileParsersMixin, ConfigGeneratorMixin):
    """
    Scans a project directory and detects languages, frameworks, and configurations.
    """

    def __init__(
        self,
        max_depth: int = 3,
        max_files: int = 10000,
        timeout_seconds: int = 30,
        ignore_patterns: list[str] | None = None,
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
        self._start_time: float | None = None
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

    def _safe_read_file(self, path: Path, max_size: int = 1024 * 1024) -> str | None:
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

    def _detect_language_version(self, path: Path, language: str) -> str | None:
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
                        if content and re.search(signature["pattern"], content, re.IGNORECASE):
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
                            if content and re.search(signature["pattern"], content, re.IGNORECASE):
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
                    services_match = re.findall(r"^\s{2}(\w[\w-]*):\s*$", content, re.MULTILINE)
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

    def _extract_description(self, path: Path) -> str | None:
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
                for match in re.finditer(r"^([a-zA-Z_-]+):\s*(?:.*)?$", content, re.MULTILINE):
                    target = match.group(1)
                    if not target.startswith(".") and target not in ["all", "clean", "help"]:
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
                except (ValueError, AttributeError):
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
                        match = re.match(r"(\w+)\s*=", line)
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
                    for match in re.finditer(
                        r"^\s*-?\s*([A-Z][A-Z0-9_]+)(?:=|\s*:)", content, re.MULTILINE
                    ):
                        name = match.group(1)
                        if name not in seen and not name.startswith("COMPOSE"):
                            seen.add(name)
                            env_vars.append(EnvVariable(name, "", True, "docker-compose"))

        return env_vars[:20]

    def _detect_packages(self, path: Path) -> list[DetectedPackage]:
        """
        Detect package dependencies from manifest files.
        Uses installed versions when available for accurate CVE checking.
        """
        packages = []

        # Get installed packages for version verification
        installed_packages = self._get_installed_packages()

        def make_package(
            ecosystem: str, name: str, declared_version: str, source_file: str
        ) -> DetectedPackage:
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
                version_source=version_source,
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
                        match = re.match(
                            r"^([a-zA-Z0-9_-]+)\s*[=><]+\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)", line
                        )
                        if match:
                            packages.append(
                                make_package("PyPI", match.group(1), match.group(2), req_file)
                            )

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
                project_match = re.search(r"\[project\].*?(?=\n\[|$)", content, re.DOTALL)
                if project_match:
                    deps_sections.append(project_match.group(0))

                # Find [project.optional-dependencies.*] sections
                for match in re.finditer(
                    r"\[project\.optional-dependencies[^\]]*\].*?(?=\n\[|$)", content, re.DOTALL
                ):
                    deps_sections.append(match.group(0))

                # Parse dependencies from these sections only
                deps_content = "\n".join(deps_sections)
                for match in re.finditer(
                    r'"([a-zA-Z0-9_-]+)(?:\[[\w,]+\])?\s*[=><]+\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)"',
                    deps_content,
                ):
                    pkg_name = match.group(1).lower()
                    # Skip build tools that might appear
                    if pkg_name not in ["setuptools", "wheel", "pip", "build"]:
                        packages.append(
                            make_package("PyPI", match.group(1), match.group(2), "pyproject.toml")
                        )

        # Node.js: package.json with package-lock.json for installed versions
        npm_installed = self._parse_npm_lockfile(path)
        package_json = path / "package.json"
        if package_json.exists():
            content = self._safe_read_file(package_json)
            if content:
                for match in re.finditer(
                    r'"([a-zA-Z0-9@/_-]+)"\s*:\s*"[\^~]?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"', content
                ):
                    pkg_name = match.group(1)
                    declared_version = match.group(2)
                    if not pkg_name.startswith("@types/"):
                        installed_version = npm_installed.get(pkg_name.lower(), "")
                        packages.append(
                            DetectedPackage(
                                ecosystem="npm",
                                name=pkg_name,
                                version=installed_version or declared_version,
                                source_file="package.json",
                                declared_version=declared_version,
                                installed_version=installed_version,
                                version_source="installed" if installed_version else "declared",
                            )
                        )

        # Rust: Cargo.toml with Cargo.lock for installed versions
        cargo_installed = self._parse_cargo_lockfile(path)
        cargo_toml = path / "Cargo.toml"
        if cargo_toml.exists():
            content = self._safe_read_file(cargo_toml)
            if content and "[dependencies]" in content:
                deps_section = content.split("[dependencies]")[1].split("[")[0]
                for match in re.finditer(
                    r'^([a-zA-Z0-9_-]+)\s*=\s*"([0-9]+\.[0-9]+(?:\.[0-9]+)?)"',
                    deps_section,
                    re.MULTILINE,
                ):
                    pkg = match.group(1)
                    declared_version = match.group(2)
                    if pkg not in ["version", "edition", "name"]:
                        installed_version = cargo_installed.get(pkg.lower(), "")
                        packages.append(
                            DetectedPackage(
                                ecosystem="crates.io",
                                name=pkg,
                                version=installed_version or declared_version,
                                source_file="Cargo.toml",
                                declared_version=declared_version,
                                installed_version=installed_version,
                                version_source="installed" if installed_version else "declared",
                            )
                        )

        # Go: go.mod with go.sum for installed versions
        go_installed = self._parse_go_sum(path)
        go_mod = path / "go.mod"
        if go_mod.exists():
            content = self._safe_read_file(go_mod)
            if content:
                for match in re.finditer(
                    r"^\s*([a-zA-Z0-9._/-]+)\s+v([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
                    content,
                    re.MULTILINE,
                ):
                    module = match.group(1)
                    declared_version = match.group(2)
                    name = module.split("/")[-1] if "/" in module else module
                    installed_version = go_installed.get(name.lower(), "") or go_installed.get(
                        module.lower(), ""
                    )
                    packages.append(
                        DetectedPackage(
                            ecosystem="Go",
                            name=name,
                            version=installed_version or declared_version,
                            source_file="go.mod",
                            declared_version=declared_version,
                            installed_version=installed_version,
                            version_source="installed" if installed_version else "declared",
                        )
                    )

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
                                declared = re.search(
                                    r"([0-9]+\.[0-9]+(?:\.[0-9]+)?)", version_constraint
                                )
                                declared_version = declared.group(1) if declared else ""
                                installed_version = composer_installed.get(pkg_name.lower(), "")
                                short_name = (
                                    pkg_name.split("/")[-1] if "/" in pkg_name else pkg_name
                                )
                                packages.append(
                                    DetectedPackage(
                                        ecosystem="Packagist",
                                        name=short_name,
                                        version=installed_version or declared_version,
                                        source_file="composer.json",
                                        declared_version=declared_version,
                                        installed_version=installed_version,
                                        version_source=(
                                            "installed" if installed_version else "declared"
                                        ),
                                    )
                                )
                except Exception:
                    pass

        # Ruby: Gemfile with Gemfile.lock for installed versions
        gem_installed = self._parse_gemfile_lockfile(path)
        gemfile = path / "Gemfile"
        if gemfile.exists():
            content = self._safe_read_file(gemfile)
            if content:
                for match in re.finditer(
                    r"gem\s+['\"]([a-zA-Z0-9_-]+)['\"](?:\s*,\s*['\"]([~>=<\s0-9.]+)['\"])?",
                    content,
                ):
                    gem_name = match.group(1)
                    version_constraint = match.group(2) or ""
                    declared = re.search(r"([0-9]+\.[0-9]+(?:\.[0-9]+)?)", version_constraint)
                    declared_version = declared.group(1) if declared else ""
                    installed_version = gem_installed.get(gem_name.lower(), "")
                    packages.append(
                        DetectedPackage(
                            ecosystem="RubyGems",
                            name=gem_name,
                            version=installed_version or declared_version,
                            source_file="Gemfile",
                            declared_version=declared_version,
                            installed_version=installed_version,
                            version_source="installed" if installed_version else "declared",
                        )
                    )

        # C#/.NET: *.csproj with packages.lock.json for installed versions
        nuget_installed = self._parse_nuget_lockfile(path)
        for csproj in path.glob("*.csproj"):
            content = self._safe_read_file(csproj)
            if content:
                for match in re.finditer(
                    r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"', content
                ):
                    pkg_name = match.group(1)
                    declared_version = match.group(2)
                    installed_version = nuget_installed.get(pkg_name.lower(), "")
                    packages.append(
                        DetectedPackage(
                            ecosystem="NuGet",
                            name=pkg_name,
                            version=installed_version or declared_version,
                            source_file=csproj.name,
                            declared_version=declared_version,
                            installed_version=installed_version,
                            version_source="installed" if installed_version else "declared",
                        )
                    )

        # Java Maven: pom.xml
        maven_installed = self._parse_maven_lockfile(path)
        pom_file = path / "pom.xml"
        if pom_file.exists():
            content = self._safe_read_file(pom_file)
            if content:
                for match in re.finditer(
                    r"<dependency>.*?<artifactId>([^<]+)</artifactId>.*?<version>([^<]+)</version>.*?</dependency>",
                    content,
                    re.DOTALL,
                ):
                    artifact = match.group(1).strip()
                    declared_version = match.group(2).strip()
                    if not declared_version.startswith("$"):
                        installed_version = maven_installed.get(artifact.lower(), "")
                        packages.append(
                            DetectedPackage(
                                ecosystem="Maven",
                                name=artifact,
                                version=installed_version or declared_version,
                                source_file="pom.xml",
                                declared_version=declared_version,
                                installed_version=installed_version,
                                version_source="installed" if installed_version else "declared",
                            )
                        )

        # Java Gradle: build.gradle
        gradle_installed = self._parse_gradle_lockfile(path)
        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            gradle_path = path / gradle_file
            if gradle_path.exists():
                content = self._safe_read_file(gradle_path)
                if content:
                    for match in re.finditer(
                        r"(?:implementation|api|compile)\s*['\"]([^:]+):([^:]+):([^'\"]+)['\"]",
                        content,
                    ):
                        artifact = match.group(2)
                        declared_version = match.group(3)
                        installed_version = gradle_installed.get(artifact.lower(), "")
                        packages.append(
                            DetectedPackage(
                                ecosystem="Maven",
                                name=artifact,
                                version=installed_version or declared_version,
                                source_file=gradle_file,
                                declared_version=declared_version,
                                installed_version=installed_version,
                                version_source="installed" if installed_version else "declared",
                            )
                        )

        # C/C++ Conan: conanfile.txt or conanfile.py
        conan_installed = self._parse_conan_lockfile(path)
        for conan_file in ["conanfile.txt", "conanfile.py"]:
            conan_path = path / conan_file
            if conan_path.exists():
                content = self._safe_read_file(conan_path)
                if content:
                    # conanfile.txt: package/version
                    for match in re.finditer(
                        r"^([a-zA-Z0-9_-]+)/(\d+\.\d+(?:\.\d+)?)", content, re.MULTILINE
                    ):
                        pkg_name = match.group(1)
                        declared_version = match.group(2)
                        installed_version = conan_installed.get(pkg_name.lower(), "")
                        packages.append(
                            DetectedPackage(
                                ecosystem="Conan",
                                name=pkg_name,
                                version=installed_version or declared_version,
                                source_file=conan_file,
                                declared_version=declared_version,
                                installed_version=installed_version,
                                version_source="installed" if installed_version else "declared",
                            )
                        )
                    # conanfile.py: requires = ["package/version"]
                    for match in re.finditer(
                        r'["\']([a-zA-Z0-9_-]+)/(\d+\.\d+(?:\.\d+)?)', content
                    ):
                        pkg_name = match.group(1)
                        declared_version = match.group(2)
                        if pkg_name.lower() not in [p.name.lower() for p in packages]:
                            installed_version = conan_installed.get(pkg_name.lower(), "")
                            packages.append(
                                DetectedPackage(
                                    ecosystem="Conan",
                                    name=pkg_name,
                                    version=installed_version or declared_version,
                                    source_file=conan_file,
                                    declared_version=declared_version,
                                    installed_version=installed_version,
                                    version_source="installed" if installed_version else "declared",
                                )
                            )

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
                            packages.append(
                                DetectedPackage(
                                    ecosystem="vcpkg",
                                    name=pkg_name,
                                    version=installed_version or declared_version or "latest",
                                    source_file="vcpkg.json",
                                    declared_version=declared_version,
                                    installed_version=installed_version,
                                    version_source="installed" if installed_version else "declared",
                                )
                            )
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
                    content,
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
                    packages.append(
                        DetectedPackage(
                            ecosystem="SwiftPM",
                            name=pkg_name,
                            version=installed_version or declared_version,
                            source_file="Package.swift",
                            declared_version=declared_version,
                            installed_version=installed_version,
                            version_source="installed" if installed_version else "declared",
                        )
                    )

        # CMake: CMakeLists.txt (for C/C++ projects using CMake)
        cmake_packages = self._parse_cmake_packages(path)
        cmake_file = path / "CMakeLists.txt"
        if cmake_file.exists() and cmake_packages:
            for pkg_name, version in cmake_packages.items():
                # Only add if not already detected via Conan/vcpkg
                if pkg_name.lower() not in [p.name.lower() for p in packages]:
                    packages.append(
                        DetectedPackage(
                            ecosystem="CMake",
                            name=pkg_name,
                            version=version,
                            source_file="CMakeLists.txt",
                            declared_version=version if version != "detected" else "",
                            installed_version="",
                            version_source="declared",
                        )
                    )

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

        from ..security import check_cve_osv_detailed

        dependencies = [(pkg.ecosystem, pkg.name, pkg.version) for pkg in result.packages]

        outcome = check_cve_osv_detailed(dependencies)

        message = outcome.summary()
        if message and message not in result.errors:
            result.errors.append(message)

        alerts = []
        for cve in outcome.cves:
            alerts.append(
                SecurityAlert(
                    cve_id=cve.id,
                    package=cve.package,
                    severity=cve.severity,
                    summary=cve.summary[:150] if cve.summary else "",
                    fixed_version=cve.fixed_version,
                    references=cve.references[:3] if cve.references else [],
                )
            )

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
