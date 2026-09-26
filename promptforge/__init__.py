"""
PromptForge - Reformateur intelligent de prompts avec contexte projet.

Open-source, 100% local avec Ollama.
Cross-platform: Windows, macOS, Linux.
"""

__version__ = "0.1.0"
__author__ = "PromptForge Contributors"

from .core import PromptForge
from .database import Database, Project, PromptHistory
from .logging_config import get_logger, init_logging
from .providers import (
    OllamaConfig,
    OllamaError,
    OllamaModelNotFoundError,
    OllamaProvider,
    OllamaTimeoutError,
)
from .scanner import ProjectScanner, ScanResult, scan_directory
from .security import (
    CVEInfo,
    SecretFinding,
    SecurityContext,
    check_cve_osv,
    check_package_cve,
    detect_dev_context,
    enrich_prompt_with_security,
    format_secret_alerts,
    get_security_guidelines,
    scan_directory_for_secrets,
)
from .tokens import count_tokens_detailed, estimate_tokens, get_token_info

__all__ = [
    "PromptForge",
    "Database",
    "Project",
    "PromptHistory",
    "OllamaProvider",
    "OllamaConfig",
    "OllamaError",
    "OllamaModelNotFoundError",
    "OllamaTimeoutError",
    "estimate_tokens",
    "count_tokens_detailed",
    "get_token_info",
    "init_logging",
    "get_logger",
    "ProjectScanner",
    "ScanResult",
    "scan_directory",
    # Security
    "detect_dev_context",
    "check_cve_osv",
    "check_package_cve",
    "get_security_guidelines",
    "enrich_prompt_with_security",
    "scan_directory_for_secrets",
    "format_secret_alerts",
    "CVEInfo",
    "SecurityContext",
    "SecretFinding",
]
