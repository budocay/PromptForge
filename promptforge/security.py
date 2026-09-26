"""
PromptForge Security Module
============================

Provides security-focused features for development prompts:
- Dev context detection (languages, frameworks)
- CVE checking via OSV.dev API (free, no API key required)
- Security guidelines injection for secure code generation
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .logging_config import get_logger

logger = get_logger(__name__)

# =============================================================================
# CONSTANTS - Dev Detection
# =============================================================================

# Programming languages keywords
DEV_LANGUAGES = {
    "python": ["python", "py", "pip", "django", "flask", "fastapi", "pytorch", "pandas"],
    "javascript": [
        "javascript",
        "js",
        "node",
        "nodejs",
        "npm",
        "react",
        "vue",
        "angular",
        "express",
    ],
    "typescript": ["typescript", "ts", "tsx", "deno", "bun"],
    "rust": ["rust", "cargo", "tokio", "actix", "axum", "warp"],
    "go": ["golang", "go ", "gin", "fiber", "echo"],
    "java": ["java", "spring", "maven", "gradle", "kotlin"],
    "csharp": ["c#", "csharp", ".net", "dotnet", "asp.net", "blazor"],
    "php": ["php", "laravel", "symfony", "composer"],
    "ruby": ["ruby", "rails", "gem", "bundler"],
    "swift": ["swift", "ios", "swiftui", "cocoapods"],
}

# Security-sensitive keywords that trigger security mode
SECURITY_KEYWORDS = [
    # Auth & Identity
    "auth",
    "authentication",
    "authorization",
    "login",
    "password",
    "jwt",
    "token",
    "oauth",
    "session",
    "cookie",
    "credentials",
    "api key",
    "secret",
    # Data
    "database",
    "sql",
    "query",
    "insert",
    "update",
    "delete",
    "select",
    "mongodb",
    "postgresql",
    "mysql",
    "redis",
    "elasticsearch",
    # Network
    "api",
    "endpoint",
    "route",
    "http",
    "https",
    "request",
    "response",
    "webhook",
    "websocket",
    "cors",
    "proxy",
    # File & System
    "file",
    "upload",
    "download",
    "path",
    "command",
    "shell",
    "process",
    "subprocess",
    "system",
    # Crypto
    "encrypt",
    "decrypt",
    "hash",
    "bcrypt",
    "argon",
    "crypto",
    "ssl",
    "tls",
    # Input/Output
    "input",
    "form",
    "validate",
    "sanitize",
    "escape",
    "encode",
    "decode",
    "serialize",
    "deserialize",
    "yaml",
    "xml",
    "json",
]

# OWASP Top 10 2021 categories
OWASP_TOP_10 = {
    "A01": "Broken Access Control",
    "A02": "Cryptographic Failures",
    "A03": "Injection",
    "A04": "Insecure Design",
    "A05": "Security Misconfiguration",
    "A06": "Vulnerable and Outdated Components",
    "A07": "Identification and Authentication Failures",
    "A08": "Software and Data Integrity Failures",
    "A09": "Security Logging and Monitoring Failures",
    "A10": "Server-Side Request Forgery (SSRF)",
}


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class CVEInfo:
    """Information about a CVE vulnerability."""

    id: str
    summary: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    package: str
    affected_versions: str
    fixed_version: str | None = None
    references: list[str] = field(default_factory=list)


@dataclass
class SecurityContext:
    """Security context detected from prompt or project."""

    is_dev: bool = False
    languages: list[str] = field(default_factory=list)
    security_keywords_found: list[str] = field(default_factory=list)
    cves: list[CVEInfo] = field(default_factory=list)
    security_level: str = "standard"  # standard, elevated, critical


@dataclass
class SecretFinding:
    """A detected secret or sensitive data."""

    secret_type: str  # api_key, password, token, private_key, etc.
    file_path: str
    line_number: int
    key_name: str  # The variable/key name (e.g., "AWS_SECRET_KEY")
    masked_value: str  # Masked value for display (e.g., "AKIA****WXYZ")
    severity: str  # HIGH, CRITICAL
    recommendation: str


# =============================================================================
# SECRET DETECTION PATTERNS
# =============================================================================

# Patterns for detecting secrets - (name, regex, severity, recommendation)
SECRET_PATTERNS = [
    # AWS
    # Longueur bornee a droite : un AWS Access Key ID fait exactement 20 caracteres
    # (prefixe AKIA + 16). Sans le lookahead, {16} se comporte comme {16,} et une
    # chaine plus longue commencant par AKIA serait remontee a tort.
    (
        "AWS Access Key ID",
        r'(?:AWS|aws)?_?(?:ACCESS|access)?_?(?:KEY|key)?_?(?:ID|id)?\s*[=:]\s*["\']?(AKIA[0-9A-Z]{16})(?![0-9A-Za-z])["\']?',
        "CRITICAL",
        "Utilisez AWS IAM roles ou AWS Secrets Manager au lieu de credentials en dur",
    ),
    (
        "AWS Secret Access Key",
        r'(?:AWS|aws)?_?(?:SECRET|secret)?_?(?:ACCESS|access)?_?(?:KEY|key)\s*[=:]\s*["\']?([A-Za-z0-9/+=]{40})["\']?',
        "CRITICAL",
        "Ne jamais commiter les AWS secret keys. Utilisez des variables d'environnement securisees",
    ),
    # Google Cloud
    (
        "Google API Key",
        r'(?:GOOGLE|google)?_?(?:API|api)?_?(?:KEY|key)\s*[=:]\s*["\']?(AIza[0-9A-Za-z\-_]{35})["\']?',
        "HIGH",
        "Restreignez cette cle API dans Google Cloud Console et utilisez des secrets managers",
    ),
    (
        "Google OAuth Client Secret",
        r'(?:client_secret|CLIENT_SECRET)\s*[=:]\s*["\']?([a-zA-Z0-9_-]{24})["\']?',
        "HIGH",
        "Ne jamais exposer les OAuth client secrets. Utilisez des variables d'environnement",
    ),
    # OpenAI / Anthropic / LLM APIs
    (
        "OpenAI API Key",
        r'(?:OPENAI|openai)?_?(?:API|api)?_?(?:KEY|key)\s*[=:]\s*["\']?(sk-(?:proj-)?[a-zA-Z0-9]{20,})["\']?',
        "CRITICAL",
        "Cle OpenAI detectee! Risque de facturation non autorisee. Regenerez cette cle immediatement",
    ),
    (
        "Anthropic API Key",
        r'(?:ANTHROPIC|anthropic)?_?(?:API|api)?_?(?:KEY|key)\s*[=:]\s*["\']?(sk-ant-[a-zA-Z0-9\-]{20,})["\']?',
        "CRITICAL",
        "Cle Anthropic detectee! Regenerez cette cle et utilisez des variables d'environnement",
    ),
    # Stripe
    (
        "Stripe Secret Key",
        r'(?:STRIPE|stripe)?_?(?:SECRET|secret)?_?(?:KEY|key)\s*[=:]\s*["\']?(sk_live_[a-zA-Z0-9]{24,})["\']?',
        "CRITICAL",
        "Cle Stripe LIVE detectee! Risque de fraude financiere. Regenerez immediatement",
    ),
    (
        "Stripe Publishable Key",
        r'(?:STRIPE|stripe)?_?(?:PUBLISHABLE|publishable)?_?(?:KEY|key)\s*[=:]\s*["\']?(pk_live_[a-zA-Z0-9]{24,})["\']?',
        "HIGH",
        "Cle Stripe publishable en production. Verifiez que c'est intentionnel",
    ),
    # Database
    (
        "Database URL with Password",
        r'(?:DATABASE_URL|DB_URL|MONGO_URI|POSTGRES_URL|MYSQL_URL)\s*[=:]\s*["\']?([a-z]+://[^:]+:[^@]+@[^\s"\']+)["\']?',
        "CRITICAL",
        "URL de base de donnees avec credentials en clair. Utilisez des secrets managers",
    ),
    (
        "Database Password",
        r'(?:DB_PASS(?:WORD)?|DATABASE_PASS(?:WORD)?|POSTGRES_PASSWORD|MYSQL_PASSWORD|MONGO_PASSWORD)\s*[=:]\s*["\']?([^\s"\']{8,})["\']?',
        "CRITICAL",
        "Mot de passe de base de donnees en clair. Ne jamais commiter!",
    ),
    # Generic Secrets
    (
        "Generic API Key",
        r'(?:API_KEY|APIKEY|api_key|apikey)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?',
        "HIGH",
        "Cle API detectee. Utilisez des variables d'environnement ou un secrets manager",
    ),
    (
        "Generic Secret",
        r'(?:SECRET|secret)(?:_KEY|_TOKEN)?\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{16,})["\']?',
        "HIGH",
        "Secret en clair detecte. Utilisez des variables d'environnement securisees",
    ),
    (
        "Generic Password",
        r'(?:PASSWORD|PASSWD|PWD|pass(?:word)?)\s*[=:]\s*["\']?([^\s"\']{8,})["\']?',
        "HIGH",
        "Mot de passe en clair detecte. Ne jamais stocker de mots de passe dans le code",
    ),
    # Tokens
    (
        "JWT Token",
        r'(?:JWT|jwt|token|TOKEN)\s*[=:]\s*["\']?(eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*)["\']?',
        "HIGH",
        "JWT token en dur detecte. Les tokens doivent etre generes dynamiquement",
    ),
    (
        "Bearer Token",
        r'(?:BEARER|bearer|AUTH|auth)(?:_TOKEN|_token)?\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{32,})["\']?',
        "HIGH",
        "Token d'authentification en clair. Utilisez un gestionnaire de secrets",
    ),
    # Private Keys
    (
        "RSA Private Key",
        r"-----BEGIN (?:RSA )?PRIVATE KEY-----",
        "CRITICAL",
        "Cle privee RSA detectee! Ne JAMAIS commiter de cles privees. Utilisez un vault",
    ),
    (
        "SSH Private Key",
        r"-----BEGIN OPENSSH PRIVATE KEY-----",
        "CRITICAL",
        "Cle privee SSH detectee! Regenerez cette cle et ne la commitez jamais",
    ),
    (
        "PGP Private Key",
        r"-----BEGIN PGP PRIVATE KEY BLOCK-----",
        "CRITICAL",
        "Cle privee PGP detectee! Ne jamais exposer de cles privees",
    ),
    # GitHub / GitLab
    # Longueurs volontairement exactes et bornees a droite par un lookahead.
    # PAT classique : prefixe `ghp_` puis 36 caracteres (30 de donnees aleatoires
    # base62 + 6 de somme de controle CRC32), soit 40 caracteres au total.
    # PAT a portee fine : `github_pat_` + 22 + `_` + 59.
    # Deux sources concordantes, verifiees le 2026-09-04 (D-044 levee) :
    #   1. GitHub Engineering, « Behind GitHub's new authentication token
    #      formats »,
    #      https://github.blog/engineering/behind-githubs-new-authentication-token-formats/
    #      — 30 caracteres aleatoires base62 suivis de « a 32 bit checksum in
    #      the last 6 digits », soit exactement 36.
    #   2. Regles gitleaks, `cmd/generate/config/rules/github.go`, branche
    #      master : `ghp_[0-9a-zA-Z]{36}` et `github_pat_\w{82}`, ce dernier
    #      confirmant le bornage a 22 + 1 + 59 = 82 du PAT a portee fine.
    # Reserve, tiree de la source primaire elle-meme : GitHub y ecrit « we will
    # increase this entropy even more ». Un motif borne a droite est donc
    # fragile par construction, du fait de l'emetteur. Si GitHub allonge le
    # corps, ce motif cessera de detecter les nouveaux jetons sans rien signaler.
    # Sans le lookahead, {36} se comporte comme {36,} : une chaine de 40 caracteres
    # serait remontee comme un jeton GitHub valide, ce qui est un faux positif.
    (
        "GitHub Token",
        r'(?:GITHUB|github)(?:_TOKEN|_token|_PAT)?\s*[=:]\s*["\']?(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59})(?![a-zA-Z0-9])["\']?',
        "CRITICAL",
        "Token GitHub detecte! Revoquez ce token dans les settings GitHub",
    ),
    (
        "GitLab Token",
        r'(?:GITLAB|gitlab)(?:_TOKEN|_token)?\s*[=:]\s*["\']?(glpat-[a-zA-Z0-9\-]{20})["\']?',
        "CRITICAL",
        "Token GitLab detecte! Revoquez ce token dans les settings GitLab",
    ),
    # Slack / Discord
    (
        "Slack Token",
        r'(?:SLACK|slack)(?:_TOKEN|_token|_WEBHOOK)?\s*[=:]\s*["\']?(xox[baprs]-[a-zA-Z0-9\-]+)["\']?',
        "HIGH",
        "Token Slack detecte. Regenerez ce token dans les settings Slack",
    ),
    (
        "Discord Webhook",
        r'(?:DISCORD|discord)(?:_WEBHOOK|_webhook)?\s*[=:]\s*["\']?(https://discord(?:app)?\.com/api/webhooks/[0-9]+/[a-zA-Z0-9_\-]+)["\']?',
        "HIGH",
        "Webhook Discord detecte. Les webhooks peuvent etre abuses pour du spam",
    ),
    # SendGrid / Mailgun / Email
    (
        "SendGrid API Key",
        r'(?:SENDGRID|sendgrid)(?:_API)?(?:_KEY|_key)?\s*[=:]\s*["\']?(SG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43})["\']?',
        "HIGH",
        "Cle SendGrid detectee. Risque d'envoi de spam. Utilisez des IP whitelists",
    ),
    # Twilio
    (
        "Twilio Auth Token",
        r'(?:TWILIO|twilio)(?:_AUTH)?(?:_TOKEN|_token)?\s*[=:]\s*["\']?([a-f0-9]{32})["\']?',
        "HIGH",
        "Token Twilio detecte. Risque de facturation SMS non autorisee",
    ),
    # Heroku
    (
        "Heroku API Key",
        r'(?:HEROKU|heroku)(?:_API)?(?:_KEY|_key)?\s*[=:]\s*["\']?([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})["\']?',
        "HIGH",
        "Cle API Heroku detectee. Risque de modification d'infrastructure",
    ),
]

# Files to scan for secrets
SECRET_SCAN_FILES = [
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
    ".env.example",
    ".env.sample",
    ".env.template",
    "config.py",
    "config.js",
    "config.ts",
    "config.json",
    "config.yaml",
    "config.yml",
    "settings.py",
    "settings.json",
    "settings.yaml",
    "settings.yml",
    "credentials.json",
    "credentials.yaml",
    "credentials.yml",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "application.properties",
    "application.yml",
    "application.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "Dockerfile",
    "dockerfile",
]

# File extensions to scan
SECRET_SCAN_EXTENSIONS = [
    ".env",
    ".ini",
    ".cfg",
    ".conf",
    ".config",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".properties",
    ".xml",
    ".sh",
    ".bash",
    ".zsh",
    ".dockerfile",
    ".pem",
    ".key",
    ".p12",
    ".pfx",  # Private key files
]


# Marqueurs de valeur factice.
#
# Arbitrage F-004, assume et pin par des tests : sur un scanner de secrets, le
# cout d'un faux positif est juge superieur au cout d'un faux negatif sur une
# valeur qui contient litteralement le mot « example ». `.env.example` figure
# explicitement dans SECRET_SCAN_FILES, les README et les docs d'editeurs sont
# remplis d'identifiants d'exemple publies : ceux de la documentation AWS
# elle-meme, `AKIAIOSFO...EXAMPLE` et `wJalrXUtn...EXAMPLEKEY`, sont tronques
# ici a dessein, un commentaire n'ayant aucune raison d'en porter la forme
# complete. Les remonter contredirait l'exigence de veracite de CLAUDE.md et
# provoquerait de la fatigue d'alerte, qui fait ignorer les vraies alertes.
#
# Recherche de sous-chaine, insensible a la casse, sur la valeur capturee.
PLACEHOLDER_SUBSTRINGS = [
    "your_",
    "xxx",
    "changeme",
    "replace",
    "example",
    "placeholder",
    "todo",
]

# Marqueurs d'interpolation de gabarit : leur seule presence suffit.
PLACEHOLDER_TEMPLATE_MARKERS = ["${", "{{"]


def is_placeholder_value(value: str) -> bool:
    """Tell whether a captured secret value is an obvious placeholder.

    Args:
        value: The raw value captured by a secret pattern.

    Returns:
        True when the value should not be reported as a secret.
    """
    if not value:
        return True

    lowered = value.lower()
    if any(marker in lowered for marker in PLACEHOLDER_SUBSTRINGS):
        return True
    if any(marker in value for marker in PLACEHOLDER_TEMPLATE_MARKERS):
        return True

    # Convention `<A_REMPLACER>` : c'est l'encadrement qui fait le gabarit, pas la
    # simple presence d'un chevron. Rejeter toute valeur *contenant* `<` ou `>`
    # ferait manquer les mots de passe qui en contiennent, ce qui est frequent.
    if value.startswith("<") and value.endswith(">"):
        return True

    return False


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret value for safe display."""
    if not value or len(value) <= show_chars * 2:
        return "*" * len(value) if value else "****"
    return value[:show_chars] + "*" * (len(value) - show_chars * 2) + value[-show_chars:]


def scan_file_for_secrets(file_path: Path) -> list[SecretFinding]:
    """Scan a single file for secrets."""
    findings = []

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        for line_num, line in enumerate(lines, 1):
            # Skip comments (but not PEM headers which start with dashes)
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            # Skip SQL comments but not PEM headers (-----BEGIN)
            if stripped.startswith("--") and not stripped.startswith("-----BEGIN"):
                continue

            for secret_name, pattern, severity, recommendation in SECRET_PATTERNS:
                matches = re.finditer(pattern, line, re.IGNORECASE)
                for match in matches:
                    # Extract the secret value (last group or full match)
                    secret_value = match.group(1) if match.lastindex else match.group(0)

                    # Skip placeholder values
                    if is_placeholder_value(secret_value):
                        continue

                    # Skip very short values (likely not real secrets)
                    if len(secret_value) < 8 and "KEY" not in secret_name:
                        continue

                    # Extract key name from the line
                    key_match = re.search(r"^([A-Z_][A-Z0-9_]*)\s*[=:]", line, re.IGNORECASE)
                    key_name = key_match.group(1) if key_match else secret_name

                    findings.append(
                        SecretFinding(
                            secret_type=secret_name,
                            file_path=str(file_path),
                            line_number=line_num,
                            key_name=key_name,
                            masked_value=mask_secret(secret_value),
                            severity=severity,
                            recommendation=recommendation,
                        )
                    )
                    break  # One finding per line per pattern type

    except Exception as e:
        logger.debug(f"Error scanning {file_path}: {e}")

    return findings


def scan_directory_for_secrets(directory: Path, max_files: int = 1000) -> list[SecretFinding]:
    """
    Scan a directory for secrets in configuration files.

    Args:
        directory: Path to scan
        max_files: Maximum files to scan (for performance)

    Returns:
        List of SecretFinding objects
    """
    findings = []
    files_scanned = 0

    # First, scan known sensitive files
    for filename in SECRET_SCAN_FILES:
        file_path = directory / filename
        if file_path.exists() and file_path.is_file():
            findings.extend(scan_file_for_secrets(file_path))
            files_scanned += 1

    # Then scan by extension (limited depth for performance)
    for ext in SECRET_SCAN_EXTENSIONS:
        if files_scanned >= max_files:
            break

        for file_path in directory.rglob(f"*{ext}"):
            if files_scanned >= max_files:
                break

            # Skip node_modules, venv, .git, etc.
            path_str = str(file_path).lower()
            skip_patterns = [
                "node_modules",
                "venv",
                ".venv",
                "__pycache__",
                ".git",
                "dist",
                "build",
            ]
            if any(p in path_str for p in skip_patterns):
                continue

            # Skip already scanned files
            if file_path.name in SECRET_SCAN_FILES:
                continue

            findings.extend(scan_file_for_secrets(file_path))
            files_scanned += 1

    # Deduplicate findings (same secret in same file)
    seen = set()
    unique_findings = []
    for f in findings:
        key = (f.file_path, f.line_number, f.secret_type)
        if key not in seen:
            seen.add(key)
            unique_findings.append(f)

    logger.info(
        f"Secret scan: scanned {files_scanned} files, found {len(unique_findings)} potential secrets"
    )
    return unique_findings


def format_secret_alerts(findings: list[SecretFinding]) -> str:
    """Format secret findings as a security alert section."""
    if not findings:
        return ""

    lines = []
    lines.append("## ⚠️ ALERTE: Secrets Detectes")
    lines.append("")
    lines.append(
        "> **ATTENTION**: Des secrets et donnees sensibles ont ete detectes dans votre projet."
    )
    lines.append("> Meme si votre environnement est local, ces donnees peuvent fuiter via:")
    lines.append("> - Les logs et historiques de conversation avec l'IA")
    lines.append("> - Les commits Git accidentels")
    lines.append("> - Les sauvegardes et synchronisations cloud")
    lines.append("> - Les rapports d'erreur automatiques")
    lines.append("")

    # Group by severity
    critical = [f for f in findings if f.severity == "CRITICAL"]
    high = [f for f in findings if f.severity == "HIGH"]

    if critical:
        lines.append("### 🔴 CRITIQUE - Action Immediate Requise")
        lines.append("")
        for finding in critical:
            rel_path = Path(finding.file_path).name
            lines.append(f"**{finding.secret_type}** dans `{rel_path}:{finding.line_number}`")
            lines.append(f"- Variable: `{finding.key_name}`")
            lines.append(f"- Valeur: `{finding.masked_value}`")
            lines.append(f"- ⚡ {finding.recommendation}")
            lines.append("")

    if high:
        lines.append("### 🟠 ELEVE - Correction Recommandee")
        lines.append("")
        for finding in high[:10]:  # Limit display
            rel_path = Path(finding.file_path).name
            lines.append(
                f"- **{finding.key_name}** (`{finding.secret_type}`) dans `{rel_path}:{finding.line_number}`"
            )
        if len(high) > 10:
            lines.append(f"- ... et {len(high) - 10} autres")
        lines.append("")

    # Recommendations
    lines.append("### Recommandations Generales")
    lines.append("")
    lines.append("1. **Ne jamais commiter de secrets** - Ajoutez `.env` a `.gitignore`")
    lines.append("2. **Utilisez des variables d'environnement** - Chargez les secrets au runtime")
    lines.append("3. **Secrets Manager** - AWS Secrets Manager, HashiCorp Vault, Doppler")
    lines.append("4. **Rotation reguliere** - Changez vos cles API periodiquement")
    lines.append("5. **Principe du moindre privilege** - Limitez les permissions des cles")
    lines.append("")
    lines.append("```bash")
    lines.append("# Exemple: Charger les secrets depuis l'environnement")
    lines.append("export API_KEY=$(cat /run/secrets/api_key)")
    lines.append("# Ou utilisez un fichier .env NON commite")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
# DEV CONTEXT DETECTION
# =============================================================================


def detect_dev_context(text: str) -> SecurityContext:
    """
    Analyze text to detect if it's development-related and security-sensitive.
    """
    text_lower = text.lower()
    context = SecurityContext()

    # Detect programming languages
    for lang, keywords in DEV_LANGUAGES.items():
        for keyword in keywords:
            if keyword in text_lower:
                if lang not in context.languages:
                    context.languages.append(lang)
                break

    # Detect security-sensitive keywords
    for keyword in SECURITY_KEYWORDS:
        if keyword in text_lower:
            context.security_keywords_found.append(keyword)

    # Determine if this is dev context
    context.is_dev = len(context.languages) > 0 or len(context.security_keywords_found) >= 2

    # Determine security level
    if len(context.security_keywords_found) >= 5:
        context.security_level = "critical"
    elif len(context.security_keywords_found) >= 2:
        context.security_level = "elevated"
    else:
        context.security_level = "standard"

    return context


def detect_dependencies_from_text(text: str) -> list[tuple[str, str, str]]:
    """
    Extract package dependencies from text (requirements.txt, package.json, etc.)
    """
    dependencies = []

    # Python: package==version or package>=version
    python_pattern = r"([a-zA-Z0-9_-]+)\s*[=><]+\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)"
    for match in re.finditer(python_pattern, text):
        pkg, version = match.groups()
        if pkg.lower() not in ["python", "pip", "version"]:
            dependencies.append(("PyPI", pkg, version))

    # npm: "package": "^version" or "package": "version"
    npm_pattern = r'"([a-zA-Z0-9@/_-]+)"\s*:\s*"[\^~]?([0-9]+\.[0-9]+(?:\.[0-9]+)?)'
    for match in re.finditer(npm_pattern, text):
        pkg, version = match.groups()
        if not pkg.startswith("@types/"):
            dependencies.append(("npm", pkg, version))

    # Cargo.toml: package = "version"
    cargo_pattern = r'([a-zA-Z0-9_-]+)\s*=\s*"([0-9]+\.[0-9]+(?:\.[0-9]+)?)"'
    for match in re.finditer(cargo_pattern, text):
        pkg, version = match.groups()
        if pkg not in ["version", "edition", "name"]:
            dependencies.append(("crates.io", pkg, version))

    return dependencies


# =============================================================================
# OSV.DEV API - CVE CHECKING
# =============================================================================

OSV_API_URL = "https://api.osv.dev/v1/querybatch"
OSV_TIMEOUT = 10


def fetch_vuln_details(vuln_id: str) -> dict | None:
    """Fetch full vulnerability details from OSV.dev."""
    try:
        url = f"https://api.osv.dev/v1/vulns/{vuln_id}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def parse_cvss_vector(cvss_string: str) -> str:
    """Parse CVSS vector string to determine severity level."""
    # CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H -> CRITICAL
    # Look for impact metrics: C (Confidentiality), I (Integrity), A (Availability)
    if not cvss_string:
        return "UNKNOWN"

    cvss_upper = cvss_string.upper()

    # Count high impacts
    high_impacts = cvss_upper.count("/C:H") + cvss_upper.count("/I:H") + cvss_upper.count("/A:H")
    low_impacts = cvss_upper.count("/C:L") + cvss_upper.count("/I:L") + cvss_upper.count("/A:L")

    # Check attack complexity and privileges
    easy_attack = "/AC:L" in cvss_upper and "/PR:N" in cvss_upper

    if high_impacts >= 2 and easy_attack:
        return "CRITICAL"
    elif high_impacts >= 2 or (high_impacts >= 1 and easy_attack):
        return "HIGH"
    elif high_impacts >= 1 or low_impacts >= 2:
        return "MEDIUM"
    else:
        return "LOW"


# -----------------------------------------------------------------------------
# Ecosystemes acceptes par OSV.dev
# -----------------------------------------------------------------------------
# Mesure directe du 2026-09-04 depuis ce depot, une requete `querybatch` par
# ecosysteme, avec le paquet fictif `foo` en version `1.0.0` :
#
#   PyPI, npm, Go, crates.io, Maven, NuGet, Packagist, RubyGems,
#   ConanCenter, vcpkg, SwiftURL ................................. HTTP 200
#   SwiftPM, CMake, Conan ........................................ HTTP 400
#     {"code":3,"message":"error in query at index 0: rpc error:
#      code = InvalidArgument desc = invalid ecosystem"}
#
# Le scanner (`promptforge/scanner/`) etiquette ses paquets avec les libelles de l'outillage reel
# (`SwiftPM` est le gestionnaire, `Conan` est le client, `CMake` est le systeme
# de construction) et ces libelles sont affiches a l'utilisateur. La traduction
# vers les libelles OSV se fait donc ici, a la frontiere reseau, et nulle part
# ailleurs : l'affichage reste stable, la requete devient valide.
OSV_ECOSYSTEM_ALIASES = {
    "SwiftPM": "SwiftURL",
    "Conan": "ConanCenter",
}

OSV_SUPPORTED_ECOSYSTEMS = frozenset(
    {
        "PyPI",
        "npm",
        "Go",
        "crates.io",
        "Maven",
        "NuGet",
        "Packagist",
        "RubyGems",
        "ConanCenter",
        "vcpkg",
        "SwiftURL",
    }
)

# `CMake` n'a pas d'equivalent OSV et n'en aura pas : ce n'est pas un index de
# paquets mais un systeme de construction. Les dependances lues dans un
# `CMakeLists.txt` ne sont donc jamais envoyees. Elles sont comptees comme
# ignorees, jamais comme saines.
OSV_UNSUPPORTED_ECOSYSTEMS = frozenset({"CMake"})

# Taille de lot. OSV accepte des lots bien plus gros, mais un lot court reduit
# le cout de la bissection quand une entree est rejetee, et borne la perte quand
# une requete expire.
OSV_BATCH_SIZE = 50

# Une version envoyee a OSV doit etre une version concrete. Mesure du
# 2026-09-04 sur `PyPI/gradio` : version `4.0.0` -> 80 vulnerabilites ; version
# vide, champ `version` absent, `detected` ou `>=3.10` -> 86 a 100, c'est-a-dire
# le catalogue entier du paquet, toutes versions confondues. Envoyer une version
# non concrete ne produit donc pas une reponse vide mais une avalanche de faux
# positifs, ce que `CLAUDE.md` interdit explicitement.
_CONCRETE_VERSION_RE = re.compile(r"^v?\d+(\.\d+)*")

# Prefixe du message rendu a l'utilisateur quand la verification est incomplete.
# Constante partagee : `scanner.generate_config` s'en sert pour reconnaitre le
# message dans `ScanResult.errors` et afficher un avertissement explicite plutot
# qu'une absence d'alerte.
CVE_CHECK_INCOMPLETE_PREFIX = "Verification CVE incomplete :"


@dataclass
class CVECheckOutcome:
    """Resultat d'une verification CVE, ou l'echec se distingue de l'absence.

    `check_cve_osv` rendait une liste vide aussi bien pour un projet sain que
    pour une API injoignable ou un lot rejete. Les deux situations sont
    indiscernables par l'appelant, donc par l'utilisateur. Cette structure les
    separe : `cves` vide avec `complete` vrai est un constat, `cves` vide avec
    `complete` faux est une panne.
    """

    cves: list[CVEInfo] = field(default_factory=list)
    checked: list[tuple[str, str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str, str]] = field(default_factory=list)
    failed: list[tuple[str, str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Vrai seulement si tout ce qui devait etre verifie l'a ete."""
        return not self.failed and not self.errors

    def summary(self) -> str:
        """Message destine a l'utilisateur, vide quand il n'y a rien a signaler.

        Les paquets ignores sont signales meme quand le reste a reussi : un
        ecosysteme hors index OSV n'est pas un ecosysteme sans vulnerabilite.
        """
        parts = []
        if self.failed:
            ecosystems = sorted({eco for eco, _, _ in self.failed})
            parts.append(
                f"verification CVE echouee pour {len(self.failed)} paquet(s) "
                f"({', '.join(ecosystems)})"
            )
        if self.skipped:
            ecosystems = sorted({eco for eco, _, _ in self.skipped})
            parts.append(
                f"{len(self.skipped)} paquet(s) non verifiables par OSV.dev "
                f"({', '.join(ecosystems)})"
            )
        if not parts:
            return ""
        detail = f" — {self.errors[0]}" if self.errors else ""
        return f"{CVE_CHECK_INCOMPLETE_PREFIX} " + " ; ".join(parts) + detail


def normalize_osv_ecosystem(ecosystem: str) -> str | None:
    """Traduit un libelle interne vers celui attendu par OSV, ou None.

    Returns:
        Le libelle OSV, ou None quand l'ecosysteme n'est pas indexe par OSV. Un
        None n'est pas une absence de vulnerabilite : c'est une absence de
        verification, et l'appelant doit le remonter comme tel.
    """
    canonical = OSV_ECOSYSTEM_ALIASES.get(ecosystem, ecosystem)
    if canonical in OSV_SUPPORTED_ECOSYSTEMS:
        return canonical
    return None


def normalize_osv_package_name(ecosystem: str, name: str) -> str:
    """Met un nom de paquet dans la forme qu'indexe OSV pour cet ecosysteme.

    Seul `SwiftURL` demande un traitement : OSV y indexe les paquets Swift par
    l'URL de leur depot, sans schema ni suffixe `.git`. Mesure du 2026-09-04 sur
    swift-nio 2.0.0 : `https://github.com/apple/swift-nio.git` -> 0 resultat,
    `github.com/apple/swift-nio` -> 5 resultats.
    """
    if ecosystem != "SwiftURL":
        return name

    cleaned = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", name.strip())
    cleaned = cleaned.rstrip("/")
    if cleaned.lower().endswith(".git"):
        cleaned = cleaned[: -len(".git")]
    return cleaned


def _osv_querybatch(chunk: list[tuple[str, str, str]]) -> list[dict]:
    """Envoie un lot a OSV et rend la liste des resultats. Ne rattrape rien."""
    queries = [
        {
            "package": {"name": normalize_osv_package_name(eco, pkg), "ecosystem": eco},
            "version": version,
        }
        for eco, pkg, version in chunk
    ]
    data = json.dumps({"queries": queries}).encode("utf-8")
    req = urllib.request.Request(
        OSV_API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=OSV_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("results", [])


def _collect_vulns(
    chunk: list[tuple[str, str, str]],
    results: list[dict],
    outcome: "CVECheckOutcome",
    seen_osv_ids: set,
    seen_cve_ids: set,
) -> None:
    """Transforme les resultats OSV d'un lot en CVEInfo, sans doublon.

    Deux ensembles distincts, et non un seul : l'identifiant OSV et
    l'identifiant rendu vivent dans le meme espace de noms et coincident quand
    la vulnerabilite n'a pas d'alias CVE. Les confondre ferait disparaitre
    toutes les vulnerabilites sans alias.
    """
    for (_, package, _version), result_item in zip(chunk, results):
        for vuln in result_item.get("vulns", [])[:3]:
            vuln_id = vuln.get("id", "")
            if not vuln_id or vuln_id in seen_osv_ids:
                continue
            seen_osv_ids.add(vuln_id)

            full_vuln = fetch_vuln_details(vuln_id)
            if not full_vuln:
                # Une vulnerabilite trouvee puis perdue faute de details est un
                # faux negatif : elle doit se voir, pas disparaitre.
                outcome.errors.append(f"details indisponibles pour {vuln_id} ({package})")
                continue
            cve = parse_osv_vulnerability(full_vuln, package)
            if not cve:
                continue
            # Deuxieme filtre, sur l'identifiant rendu et non sur celui d'OSV :
            # une meme CVE est indexee plusieurs fois chez OSV (GHSA-..., puis
            # PYSEC-...), et `parse_osv_vulnerability` ramene ces entrees a leur
            # alias CVE commun. Sans ce filtre, la meme CVE est comptee deux
            # fois et le nombre affiche a l'utilisateur est faux. Mesure du
            # 2026-09-04 sur `PyPI/pytest 8.3.4` : CVE-2025-71176 rendue deux
            # fois avec le seul filtre sur l'identifiant OSV.
            if cve.id in seen_cve_ids:
                continue
            seen_cve_ids.add(cve.id)
            outcome.cves.append(cve)


def _osv_query_resilient(
    chunk: list[tuple[str, str, str]],
    outcome: "CVECheckOutcome",
    seen_osv_ids: set,
    seen_cve_ids: set,
) -> None:
    """Interroge OSV pour `chunk` en isolant les entrees que l'API rejette.

    OSV valide le lot entier avant de le traiter : une seule entree invalide
    fait repondre HTTP 400 et le lot complet est perdu. Mesure du 2026-09-04 :
    `[PyPI/gradio 4.0.0]` seul -> HTTP 200, 80 vulnerabilites ;
    `[PyPI/gradio 4.0.0, SwiftPM/swift-nio 2.0.0]` -> HTTP 400, zero resultat.
    Sur un 400, on bissecte donc le lot jusqu'a isoler la ou les entrees
    fautives, qui sont les seules comptees en echec.

    Toute autre erreur (reseau, expiration, HTTP 5xx) ne vise aucune entree en
    particulier : bissecter n'apporterait rien et multiplierait les appels. Le
    lot entier est marque en echec.
    """
    if not chunk:
        return

    try:
        results = _osv_querybatch(chunk)
    except urllib.error.HTTPError as error:
        if error.code == 400 and len(chunk) > 1:
            middle = len(chunk) // 2
            _osv_query_resilient(chunk[:middle], outcome, seen_osv_ids, seen_cve_ids)
            _osv_query_resilient(chunk[middle:], outcome, seen_osv_ids, seen_cve_ids)
            return
        detail = _read_http_error_body(error)
        outcome.failed.extend(chunk)
        outcome.errors.append(
            f"OSV.dev a repondu HTTP {error.code} sur {len(chunk)} paquet(s){detail}"
        )
        logger.warning("OSV.dev HTTP %s sur %s paquet(s)%s", error.code, len(chunk), detail)
        return
    except urllib.error.URLError as error:
        outcome.failed.extend(chunk)
        outcome.errors.append(f"OSV.dev injoignable : {error.reason}")
        logger.warning("OSV.dev injoignable : %s", error.reason)
        return
    except (ValueError, OSError) as error:
        # ValueError couvre json.JSONDecodeError ; OSError couvre les coupures
        # de socket en cours de lecture, qui ne remontent pas en URLError.
        outcome.failed.extend(chunk)
        outcome.errors.append(f"reponse OSV.dev illisible : {error}")
        logger.warning("Reponse OSV.dev illisible : %s", error)
        return

    if len(results) != len(chunk):
        outcome.failed.extend(chunk)
        outcome.errors.append(
            f"OSV.dev a rendu {len(results)} resultat(s) pour {len(chunk)} requete(s)"
        )
        logger.warning(
            "OSV.dev a rendu %s resultat(s) pour %s requete(s)", len(results), len(chunk)
        )
        return

    outcome.checked.extend(chunk)
    _collect_vulns(chunk, results, outcome, seen_osv_ids, seen_cve_ids)


def _read_http_error_body(error: urllib.error.HTTPError) -> str:
    """Lit le corps d'une erreur HTTP pour le journaliser, sans jamais lever."""
    try:
        body = error.read().decode("utf-8", "replace").strip()
    except OSError as read_error:
        return f" (corps illisible : {read_error})"
    return f" : {body[:200]}" if body else ""


def check_cve_osv_detailed(dependencies: list[tuple[str, str, str]]) -> CVECheckOutcome:
    """Verifie des dependances aupres d'OSV.dev en distinguant echec et absence.

    Args:
        dependencies: triplets `(ecosysteme, nom, version)`, avec les libelles
            d'ecosysteme du scanner, pas ceux d'OSV.

    Returns:
        Un CVECheckOutcome. `outcome.complete` dit si la reponse est fiable ;
        `outcome.skipped` liste ce qu'OSV ne peut pas verifier ;
        `outcome.failed` liste ce qui aurait du l'etre et ne l'a pas ete.
    """
    outcome = CVECheckOutcome()
    if not dependencies:
        return outcome

    translated: list[tuple[str, str, str]] = []
    for ecosystem, package, version in dependencies:
        osv_ecosystem = normalize_osv_ecosystem(ecosystem)
        if osv_ecosystem is None:
            outcome.skipped.append((ecosystem, package, version))
            continue
        if not version or not _CONCRETE_VERSION_RE.match(version.strip()):
            outcome.skipped.append((ecosystem, package, version))
            continue
        translated.append((osv_ecosystem, package, version.strip()))

    seen_osv_ids: set = set()
    seen_cve_ids: set = set()
    for start in range(0, len(translated), OSV_BATCH_SIZE):
        _osv_query_resilient(
            translated[start : start + OSV_BATCH_SIZE],
            outcome,
            seen_osv_ids,
            seen_cve_ids,
        )

    logger.info(
        "OSV.dev: %s paquet(s) verifie(s), %s ignore(s), %s en echec, "
        "%s vulnerabilite(s) trouvee(s)",
        len(outcome.checked),
        len(outcome.skipped),
        len(outcome.failed),
        len(outcome.cves),
    )
    return outcome


def check_cve_osv(dependencies: list[tuple[str, str, str]]) -> list[CVEInfo]:
    """Check for known vulnerabilities using OSV.dev API.

    Enveloppe de compatibilite : elle ne rend que les vulnerabilites et perd
    donc la distinction entre « aucune vulnerabilite » et « verification
    echouee ». Tout appelant qui montre ce resultat a un utilisateur doit passer
    par `check_cve_osv_detailed` et remonter `outcome.summary()`.
    """
    return check_cve_osv_detailed(dependencies).cves


def parse_osv_vulnerability(vuln: dict, package: str) -> CVEInfo | None:
    """Parse OSV vulnerability response into CVEInfo."""
    try:
        vuln_id = vuln.get("id", "")
        aliases = vuln.get("aliases", [])
        cve_id = next((a for a in aliases if a.startswith("CVE-")), vuln_id)

        severity = "UNKNOWN"
        if "severity" in vuln and vuln["severity"]:
            for sev in vuln["severity"]:
                if sev.get("type") == "CVSS_V3":
                    score_raw = sev.get("score", "")
                    # Score can be a CVSS vector string like "CVSS:3.1/AV:N/AC:H/..."
                    if isinstance(score_raw, str) and "CVSS" in score_raw.upper():
                        severity = parse_cvss_vector(score_raw)
                    else:
                        # Try as numeric score
                        try:
                            score = float(str(score_raw).split("/")[0])
                            if score >= 9.0:
                                severity = "CRITICAL"
                            elif score >= 7.0:
                                severity = "HIGH"
                            elif score >= 4.0:
                                severity = "MEDIUM"
                            else:
                                severity = "LOW"
                        except (ValueError, TypeError):
                            severity = parse_cvss_vector(str(score_raw))
                    break

        affected_str = "unknown"
        fixed_version = None
        if "affected" in vuln:
            for affected in vuln["affected"]:
                if affected.get("package", {}).get("name", "").lower() == package.lower():
                    ranges = affected.get("ranges", [])
                    for r in ranges:
                        events = r.get("events", [])
                        for event in events:
                            if "fixed" in event:
                                fixed_version = event["fixed"]
                                break
                    versions = affected.get("versions", [])
                    if versions:
                        affected_str = (
                            f"{versions[0]} - {versions[-1]}" if len(versions) > 1 else versions[0]
                        )

        references = [ref.get("url", "") for ref in vuln.get("references", [])[:3]]

        return CVEInfo(
            id=cve_id,
            summary=vuln.get("summary", vuln.get("details", "No description")[:200]),
            severity=severity,
            package=package,
            affected_versions=affected_str,
            fixed_version=fixed_version,
            references=references,
        )
    except Exception as e:
        logger.warning(f"Error parsing vulnerability: {e}")
        return None


def check_package_cve(package: str, version: str, ecosystem: str = "PyPI") -> list[CVEInfo]:
    """Check a single package for CVEs."""
    return check_cve_osv([(ecosystem, package, version)])


# =============================================================================
# SECURITY GUIDELINES
# =============================================================================


def get_security_guidelines(context: SecurityContext) -> str:
    """Generate security guidelines based on detected context."""
    if not context.is_dev:
        return ""

    lines = []
    lines.append("\n## CONTRAINTES DE SECURITE OBLIGATOIRES\n")

    if "python" in context.languages:
        lines.append("""### Python Security
- Utiliser `secrets` au lieu de `random` pour les tokens/mots de passe
- Parametrer les requetes SQL (pas de f-string dans les queries)
- Valider les inputs avec Pydantic ou dataclasses
- Eviter les fonctions d'execution dynamique avec des donnees utilisateur
- Utiliser `bcrypt` ou `argon2` pour les mots de passe""")

    if "javascript" in context.languages or "typescript" in context.languages:
        lines.append("""### JavaScript/TypeScript Security
- Echapper les outputs HTML (XSS prevention)
- Utiliser des requetes parametrees pour les bases de donnees
- Valider les inputs cote serveur (ne jamais faire confiance au client)
- Configurer CORS correctement
- Utiliser `helmet.js` pour les headers de securite""")

    if "rust" in context.languages:
        lines.append("""### Rust Security
- Preferer les types surs (`Option`, `Result`) aux valeurs nulles
- Utiliser `sqlx` avec requetes parametrees pour SQL
- Valider les inputs avec `validator` crate
- Utiliser `argon2` pour le hashing de mots de passe
- Eviter `unsafe` sauf si absolument necessaire""")

    if "go" in context.languages:
        lines.append("""### Go Security
- Utiliser `prepared statements` pour SQL
- Echapper les templates HTML avec `html/template`
- Valider les inputs avec `go-playground/validator`
- Utiliser `golang.org/x/crypto` pour la cryptographie
- Ne jamais logger les secrets/mots de passe""")

    if "java" in context.languages:
        lines.append("""### Java Security
- Utiliser `PreparedStatement` pour toutes les requetes SQL
- Bean Validation (JSR 380) pour valider les inputs
- Spring Security pour l'authentification/autorisation
- Eviter ObjectInputStream avec des donnees non fiables (deserialisation)
- Utiliser OWASP ESAPI pour l'encodage des outputs""")

    if "csharp" in context.languages:
        lines.append("""### C# / .NET Security
- Entity Framework ou Dapper avec requetes parametrees
- ASP.NET Core Identity pour l'authentification
- Anti-forgery tokens (ValidateAntiForgeryToken) pour les formulaires
- `HtmlEncoder` pour encoder les outputs HTML
- Data Protection API pour le chiffrement des donnees sensibles""")

    if "php" in context.languages:
        lines.append("""### PHP Security
- PDO avec requetes preparees (bindParam/bindValue)
- `password_hash()` / `password_verify()` pour les mots de passe
- `htmlspecialchars()` avec ENT_QUOTES pour l'echappement HTML
- Valider les uploads: verifier le MIME reel avec finfo_file()
- Utiliser CSRF tokens avec verification cote serveur""")

    if "ruby" in context.languages:
        lines.append("""### Ruby Security
- ActiveRecord avec requetes parametrees (where avec placeholders)
- `has_secure_password` pour le hashing de mots de passe
- Strong Parameters dans Rails pour filtrer les inputs
- Protection CSRF activee par defaut dans Rails
- Eviter `eval()`, `send()` avec des inputs utilisateur""")

    if "swift" in context.languages:
        lines.append("""### Swift / iOS Security
- Keychain pour stocker les credentials (pas UserDefaults)
- App Transport Security (ATS) active
- Certificate pinning pour les connexions sensibles
- Valider les inputs avant traitement
- Eviter les donnees sensibles dans les logs""")

    if "c" in context.languages or "cpp" in context.languages:
        lines.append("""### C/C++ Security
- Eviter les fonctions non-securisees: gets, strcpy, sprintf -> utiliser fgets, strncpy, snprintf
- Toujours verifier les bornes des buffers (buffer overflow)
- Initialiser toutes les variables avant utilisation
- Utiliser RAII en C++ pour la gestion memoire
- Activer les protections: -fstack-protector, -D_FORTIFY_SOURCE=2, -fPIE
- AddressSanitizer et MemorySanitizer pour detecter les erreurs memoire""")

    if any(
        k in context.security_keywords_found for k in ["auth", "login", "password", "jwt", "token"]
    ):
        lines.append("""### Authentification
- Implementer rate limiting sur les endpoints d'auth
- Utiliser HTTPS uniquement
- Tokens JWT: expiration courte, refresh tokens, signature forte (RS256)
- Stocker les mots de passe avec bcrypt/argon2 (jamais MD5/SHA1)
- Implementer la protection CSRF""")

    if any(k in context.security_keywords_found for k in ["sql", "database", "query"]):
        lines.append("""### Base de donnees
- TOUJOURS utiliser des requetes parametrees (prepared statements)
- Principe du moindre privilege pour les acces DB
- Chiffrer les donnees sensibles au repos
- Valider et sanitizer les inputs avant insertion""")

    if any(k in context.security_keywords_found for k in ["file", "upload", "path"]):
        lines.append("""### Fichiers & Uploads
- Valider le type MIME et l'extension des fichiers uploades
- Limiter la taille des uploads
- Stocker hors du webroot avec noms generes
- Scanner les fichiers pour malware si possible
- Eviter les path traversal (../../)""")

    if any(k in context.security_keywords_found for k in ["api", "endpoint", "route"]):
        lines.append("""### API Security
- Authentification sur tous les endpoints sensibles
- Rate limiting et throttling
- Validation des inputs (schema validation)
- Headers de securite (CORS, CSP, X-Frame-Options)
- Logging des acces et erreurs""")

    # Framework-specific security guidelines
    if any(k in context.security_keywords_found for k in ["react", "vue", "angular", "frontend"]):
        lines.append("""### Frontend Framework Security (React/Vue/Angular)
- Echapper les donnees avec les mecanismes natifs du framework
- Ne jamais utiliser dangerouslySetInnerHTML (React) ou v-html (Vue) avec des inputs
- Valider les URLs avant navigation/redirection
- Sanitizer les inputs rich text avec DOMPurify
- Content Security Policy (CSP) pour bloquer les scripts inline
- Eviter eval() et les constructeurs dynamiques avec des donnees utilisateur""")

    if any(k in context.security_keywords_found for k in ["django", "flask", "fastapi"]):
        lines.append("""### Python Web Framework Security
- Django: CSRF_COOKIE_SECURE=True, SESSION_COOKIE_SECURE=True
- Django: Utiliser @login_required et @permission_required
- Flask: Utiliser Flask-WTF pour la protection CSRF
- FastAPI: Utiliser Depends() pour l'injection de dependances securisee
- Pydantic pour la validation stricte des schemas
- Ne jamais desactiver DEBUG en production""")

    if any(k in context.security_keywords_found for k in ["express", "nestjs", "node", "koa"]):
        lines.append("""### Node.js Framework Security
- Express: helmet.js pour les headers de securite
- Express: express-rate-limit pour le throttling
- NestJS: Guards et Pipes pour validation/autorisation
- Utiliser express-validator ou class-validator
- Configurer CORS strictement (pas de origin: '*' en production)
- PM2 ou similar pour le process management securise""")

    if any(k in context.security_keywords_found for k in ["spring", "springboot"]):
        lines.append("""### Spring Boot Security
- Spring Security avec configuration explicite
- @PreAuthorize et @Secured pour le controle d'acces
- BCryptPasswordEncoder pour le hashing
- CSRF protection activee pour les formulaires
- Configurer les headers de securite via HttpSecurity
- Valider avec @Valid et @Validated""")

    if any(k in context.security_keywords_found for k in ["aspnet", "blazor", "dotnet"]):
        lines.append("""### ASP.NET Core Security
- Identity pour l'authentification/autorisation
- [Authorize] attribute sur les controllers/actions
- Data Annotations pour la validation
- Anti-forgery tokens automatiques
- HTTPS redirection et HSTS
- Secret Manager pour les credentials en dev""")

    if context.cves:
        lines.append("\n### VULNERABILITES DETECTEES (CVE)")
        for cve in context.cves[:5]:
            sev_tag = {
                "CRITICAL": "[CRIT]",
                "HIGH": "[HIGH]",
                "MEDIUM": "[MED]",
                "LOW": "[LOW]",
            }.get(cve.severity, "[?]")
            lines.append(f"\n**{sev_tag} {cve.id}** - {cve.package}")
            lines.append(f"- Severite: {cve.severity}")
            lines.append(f"- {cve.summary[:150]}...")
            if cve.fixed_version:
                lines.append(f"- Corrige dans: {cve.fixed_version}")

    lines.append("""
### Rappel OWASP Top 10
Verifie que ton code n'est pas vulnerable a:
1. Broken Access Control
2. Cryptographic Failures
3. Injection (SQL, Command, XSS)
4. Insecure Design
5. Security Misconfiguration
6. Vulnerable Components
7. Authentication Failures
8. Integrity Failures
9. Logging Failures
10. SSRF""")

    return "\n".join(lines)


def get_security_system_prompt_addition() -> str:
    """Returns additional system prompt text for security-focused reformatting."""
    return """
IMPORTANT - SECURITE DU CODE:
Tu generes du code qui sera utilise en production. La securite est CRITIQUE.
- Applique TOUJOURS les bonnes pratiques de securite
- Utilise des requetes parametrees pour toute interaction base de donnees
- Valide et sanitize TOUS les inputs utilisateur
- N'expose JAMAIS de secrets dans le code ou les logs
- Prefere les bibliotheques de securite eprouvees
- Si tu detectes un risque de securite, ALERTE explicitement dans ta reponse
"""


# =============================================================================
# INTEGRATION HELPERS
# =============================================================================


def enrich_prompt_with_security(
    raw_prompt: str, project_context: str = "", check_cves: bool = True
) -> tuple[str, SecurityContext]:
    """Analyze prompt and project, add security context if dev-related."""
    full_text = f"{raw_prompt}\n{project_context}"
    context = detect_dev_context(full_text)

    if not context.is_dev:
        return project_context, context

    if check_cves:
        dependencies = detect_dependencies_from_text(project_context)
        if dependencies:
            context.cves = check_cve_osv(dependencies)

    security_guidelines = get_security_guidelines(context)

    if project_context:
        enriched = f"{project_context}\n{security_guidelines}"
    else:
        enriched = security_guidelines

    return enriched, context


def format_cve_alert(cves: list[CVEInfo]) -> str:
    """Format CVE alerts for display in UI."""
    if not cves:
        return ""

    lines = ["## Vulnerabilites detectees\n"]

    critical = [c for c in cves if c.severity == "CRITICAL"]
    high = [c for c in cves if c.severity == "HIGH"]
    medium = [c for c in cves if c.severity == "MEDIUM"]
    low = [c for c in cves if c.severity == "LOW"]

    if critical:
        lines.append(f"### [CRITICAL] ({len(critical)})")
        for cve in critical:
            lines.append(f"- **{cve.id}**: {cve.package} - {cve.summary[:100]}")
            if cve.fixed_version:
                lines.append(f"  - Mettre a jour vers: `{cve.fixed_version}`")

    if high:
        lines.append(f"\n### [HIGH] ({len(high)})")
        for cve in high:
            lines.append(f"- **{cve.id}**: {cve.package} - {cve.summary[:100]}")

    if medium:
        lines.append(f"\n### [MEDIUM] ({len(medium)})")
        for cve in medium[:3]:
            lines.append(f"- **{cve.id}**: {cve.package}")
        if len(medium) > 3:
            lines.append(f"  - ... et {len(medium) - 3} autres")

    if low:
        lines.append(f"\n### [LOW] ({len(low)})")
        lines.append(f"- {len(low)} vulnerabilite(s) de faible severite")

    return "\n".join(lines)
