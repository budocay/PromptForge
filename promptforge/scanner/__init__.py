"""
Project Scanner - analyse automatique d'un projet et generation de sa config.

Le paquet est decoupe par responsabilite :

- `signatures` : fichiers, motifs et versions reconnus (donnees pures)
- `models` : dataclasses du resultat (`ScanResult` et ses composants)
- `lockfiles` : lecture des manifestes et lockfiles, par ecosysteme
- `config_generator` : rendu Markdown de la configuration PromptForge
- `core` : `ProjectScanner`, qui assemble le tout, et `scan_directory`

L'API publique reste celle de l'ancien module `promptforge.scanner`.
"""

from .core import ProjectScanner, scan_directory
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

__all__ = [
    "CICD_SIGNATURES",
    "CONVENTION_FILES",
    "DATABASE_SIGNATURES",
    "DEFAULT_IGNORE_PATTERNS",
    "FRAMEWORK_SIGNATURES",
    "LANGUAGE_EXTENSIONS",
    "SHARED_MANIFEST_FILES",
    "TEST_SIGNATURES",
    "VERSION_FILES",
    "CICDSetup",
    "CodeConventions",
    "DetectedDatabase",
    "DetectedFramework",
    "DetectedLanguage",
    "DetectedPackage",
    "DevCommand",
    "DockerSetup",
    "EnvVariable",
    "KeyFile",
    "ProjectScanner",
    "ProjectStructure",
    "ScanResult",
    "SecurityAlert",
    "TestSetup",
    "normalize_version_constraint",
    "scan_directory",
]
