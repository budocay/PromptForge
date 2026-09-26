"""Dataclasses produites par le scanner."""

from dataclasses import dataclass, field

from ..security import (
    SecretFinding,
)

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
    version: str | None = None


@dataclass
class DetectedFramework:
    """Represents a detected framework or library."""

    name: str
    category: str
    version: str | None = None
    config_file: str | None = None


@dataclass
class DetectedDatabase:
    """Represents detected database configuration."""

    name: str
    detected_from: str
    orm: str | None = None


@dataclass
class CodeConventions:
    """Detected code conventions."""

    formatter: str | None = None
    linter: str | None = None
    typechecker: str | None = None
    line_length: int | None = None
    config_files: list[str] = field(default_factory=list)


@dataclass
class TestSetup:
    """Detected test configuration."""

    framework: str | None = None
    category: str | None = None
    test_dirs: list[str] = field(default_factory=list)
    config_file: str | None = None


@dataclass
class DockerSetup:
    """Detected Docker configuration."""

    has_dockerfile: bool = False
    has_compose: bool = False
    services: list[str] = field(default_factory=list)
    compose_file: str | None = None


@dataclass
class CICDSetup:
    """Detected CI/CD configuration."""

    provider: str | None = None
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
    fixed_version: str | None = None
    references: list[str] = field(default_factory=list)  # Links to advisories


@dataclass
class ScanResult:
    """Complete scan result."""

    languages: list[DetectedLanguage] = field(default_factory=list)
    frameworks: list[DetectedFramework] = field(default_factory=list)
    databases: list[DetectedDatabase] = field(default_factory=list)
    structure: ProjectStructure | None = None
    conventions: CodeConventions | None = None
    tests: list[TestSetup] = field(default_factory=list)
    docker: DockerSetup | None = None
    cicd: CICDSetup | None = None
    readme_description: str | None = None
    project_name_suggestion: str | None = None
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
