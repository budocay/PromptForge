"""
Scanner helper functions for PromptForge web interface.
Handles project scanning and configuration generation from the UI.
"""

import shutil
import tempfile
import zipfile
from pathlib import Path

import gradio as gr

from ..scanner import ProjectScanner, ScanResult
from ..security import OWASP_TOP_10
from .ollama_helpers import get_forge
from .project_helpers import get_projects_list, normalize_name

# =============================================================================
# FOLDER BROWSER (native dialog)
# =============================================================================


def browse_for_folder() -> str:
    """
    Ouvre un dialogue système natif pour sélectionner un dossier.
    Utilise tkinter.filedialog (stdlib Python).
    """
    try:
        from tkinter import Tk, filedialog

        # Créer une fenêtre Tk cachée
        root = Tk()
        root.withdraw()  # Cache la fenêtre principale
        root.attributes("-topmost", True)  # Met le dialogue au premier plan

        # Ouvrir le dialogue de sélection de dossier
        folder_path = filedialog.askdirectory(
            title="Sélectionne le dossier de ton projet", initialdir=get_default_scan_path()
        )

        root.destroy()
        return folder_path if folder_path else ""

    except Exception as e:
        return f"Erreur: {e}"


# =============================================================================
# PROJECT DETECTION HELPERS
# =============================================================================

# Fichiers qui indiquent qu'un dossier est un projet
PROJECT_INDICATORS = [
    # Python
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "Pipfile",
    # Node.js
    "package.json",
    # Rust
    "Cargo.toml",
    # Go
    "go.mod",
    # Java/Kotlin
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    # .NET
    "*.csproj",
    "*.sln",
    # Ruby
    "Gemfile",
    # PHP
    "composer.json",
    # Generic
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".git",
    "README.md",
    "README.rst",
]


def is_valid_project(path: Path) -> tuple[bool, str, list[str]]:
    """
    Check if a folder looks like a valid project.

    Returns:
        tuple: (is_project, reason, found_indicators)
    """
    if not path.exists():
        return False, "Le dossier n'existe pas", []

    if not path.is_dir():
        return False, "Ce n'est pas un dossier", []

    found = []

    # Check for project indicators
    for indicator in PROJECT_INDICATORS:
        if "*" in indicator:
            # Glob pattern
            pattern = indicator
            if list(path.glob(pattern)):
                found.append(indicator)
        else:
            if (path / indicator).exists():
                found.append(indicator)

    if found:
        return True, f"Projet détecté ({len(found)} indicateurs)", found

    # Check if it has subdirectories with code
    has_code_files = False
    code_extensions = [".py", ".js", ".ts", ".go", ".rs", ".java", ".cs", ".rb", ".php"]

    try:
        for item in path.iterdir():
            if item.is_file() and item.suffix in code_extensions:
                has_code_files = True
                break
            if item.is_dir() and not item.name.startswith("."):
                # Check one level deep
                for subitem in item.iterdir():
                    if subitem.is_file() and subitem.suffix in code_extensions:
                        has_code_files = True
                        break
                if has_code_files:
                    break
    except PermissionError:
        pass

    if has_code_files:
        return True, "Fichiers de code détectés (pas de fichier de config)", ["code files"]

    # Not a project
    return False, "Aucun indicateur de projet trouvé", []


def get_folder_info(path_str: str) -> str:
    """
    Get detailed info about a folder for display.
    """
    if not path_str:
        return ""

    path = Path(path_str).expanduser()

    if not path.exists():
        return "❌ **Ce chemin n'existe pas**"

    if not path.is_dir():
        return "❌ **Ce n'est pas un dossier**"

    is_project, reason, indicators = is_valid_project(path)

    lines = []
    lines.append(f"📂 **{path.name}**")
    lines.append(f"📍 `{path}`")
    lines.append("")

    if is_project:
        lines.append(f"✅ **{reason}**")
        if indicators and indicators[0] != "code files":
            lines.append(f"📋 Fichiers: {', '.join(indicators[:5])}")
        lines.append("")
        lines.append("👉 **Prêt à scanner !** Donne un nom et clique sur Scanner.")
    else:
        lines.append(f"⚠️ **{reason}**")
        lines.append("")
        lines.append("Ce dossier ne semble pas être un projet de développement.")
        lines.append("")
        lines.append("**Un projet valide contient généralement:**")
        lines.append("- `package.json` (Node.js)")
        lines.append("- `pyproject.toml` ou `requirements.txt` (Python)")
        lines.append("- `Cargo.toml` (Rust)")
        lines.append("- `go.mod` (Go)")
        lines.append("- `.git`, `Makefile`, `Dockerfile`...")
        lines.append("")
        lines.append("💡 Sélectionne un sous-dossier dans l'explorateur.")

    return "\n".join(lines)


# =============================================================================
# LLM-POWERED SCAN (Ollama)
# =============================================================================


def collect_project_data(path: Path, max_depth: int = 5) -> dict:
    """
    Collecte les données brutes d'un projet pour analyse LLM.

    Returns:
        dict avec: file_tree, readme, configs, key_files, stats
    """
    data = {
        "root_name": path.name,
        "file_tree": [],
        "readme": "",
        "configs": {},
        "key_files": {},
        "stats": {"total_files": 0, "total_dirs": 0, "extensions": {}},
    }

    # Fichiers de config importants à lire
    config_files = [
        "README.md",
        "README.rst",
        "README.txt",
        "README",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "package.json",
        "tsconfig.json",
        "Cargo.toml",
        "go.mod",
        "go.sum",
        "pom.xml",
        "build.gradle",
        "Gemfile",
        "composer.json",
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env.example",
        ".env.sample",
        "CLAUDE.md",
        "CONTEXT.md",
        "PROJECT.md",
    ]

    # Extensions de fichiers clés à échantillonner
    key_extensions = {".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".php", ".cs"}

    def should_skip(name: str) -> bool:
        """Dossiers à ignorer pour l'arbre mais pas pour les stats."""
        skip_dirs = {
            "node_modules",
            ".git",
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
            "vendor",
            ".idea",
            ".vscode",
            ".cache",
            "coverage",
            ".pytest_cache",
            ".mypy_cache",
            "eggs",
            "*.egg-info",
            "htmlcov",
            ".tox",
        }
        return name in skip_dirs or name.startswith(".")

    def scan_dir(dir_path: Path, depth: int, prefix: str = "") -> list[str]:
        """Scan récursif pour construire l'arbre."""
        if depth > max_depth:
            return [f"{prefix}... (profondeur max atteinte)"]

        tree_lines = []
        try:
            items = sorted(dir_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))

            # Filtrer les items
            dirs = [i for i in items if i.is_dir() and not should_skip(i.name)]
            files = [i for i in items if i.is_file()]

            # Limiter pour éviter l'explosion
            if len(files) > 15:
                shown_files = files[:10]
                hidden_count = len(files) - 10
            else:
                shown_files = files
                hidden_count = 0

            if len(dirs) > 20:
                shown_dirs = dirs[:15]
                hidden_dirs = len(dirs) - 15
            else:
                shown_dirs = dirs
                hidden_dirs = 0

            # Traiter les dossiers
            for d in shown_dirs:
                data["stats"]["total_dirs"] += 1
                tree_lines.append(f"{prefix}📁 {d.name}/")
                tree_lines.extend(scan_dir(d, depth + 1, prefix + "  "))

            if hidden_dirs > 0:
                tree_lines.append(f"{prefix}... et {hidden_dirs} autres dossiers")

            # Traiter les fichiers
            for f in shown_files:
                data["stats"]["total_files"] += 1
                ext = f.suffix.lower()
                data["stats"]["extensions"][ext] = data["stats"]["extensions"].get(ext, 0) + 1
                tree_lines.append(f"{prefix}📄 {f.name}")

                # Lire les fichiers de config
                if f.name in config_files:
                    try:
                        content = f.read_text(encoding="utf-8", errors="ignore")[:5000]
                        if f.name.lower().startswith("readme"):
                            data["readme"] = content
                        else:
                            data["configs"][f.name] = content
                    except OSError:
                        pass

                # Échantillonner les fichiers clés (premier du type)
                elif ext in key_extensions and ext not in data["key_files"]:
                    try:
                        content = f.read_text(encoding="utf-8", errors="ignore")
                        # Prendre les 100 premières lignes
                        lines = content.split("\n")[:100]
                        data["key_files"][f.name] = "\n".join(lines)
                    except OSError:
                        pass

            if hidden_count > 0:
                tree_lines.append(f"{prefix}... et {hidden_count} autres fichiers")

        except PermissionError:
            tree_lines.append(f"{prefix}⚠️ Accès refusé")

        return tree_lines

    # Construire l'arbre
    data["file_tree"] = scan_dir(path, 0)

    return data


def build_llm_prompt(project_name: str, data: dict, description: str = "") -> str:
    """
    Construit le prompt pour Ollama pour générer la config projet.
    STRICT: Le LLM doit UNIQUEMENT utiliser les données fournies, jamais inventer.
    """
    file_tree_str = "\n".join(data["file_tree"][:300])  # Plus de contexte

    # Construire la section configs avec plus de contenu
    configs_str = ""
    for name, content in list(data["configs"].items())[:8]:
        configs_str += f"\n### {name}\n```\n{content[:3000]}\n```\n"

    # Inclure les fichiers clés (code source échantillonné)
    key_files_str = ""
    for name, content in list(data.get("key_files", {}).items())[:3]:
        key_files_str += f"\n### {name} (extrait)\n```\n{content[:1500]}\n```\n"

    # Stats extensions
    top_extensions = sorted(data["stats"]["extensions"].items(), key=lambda x: x[1], reverse=True)[
        :15
    ]
    extensions_str = ", ".join([f"{ext}: {count}" for ext, count in top_extensions])

    # Description utilisateur si fournie
    desc_section = (
        f"\n## DESCRIPTION FOURNIE PAR L'UTILISATEUR\n{description}\n" if description else ""
    )

    prompt = f"""# MISSION CRITIQUE

Tu dois analyser le projet "{project_name}" et générer sa documentation de contexte.

## ⚠️ RÈGLES ABSOLUES - À RESPECTER IMPÉRATIVEMENT

1. **UTILISE UNIQUEMENT les données ci-dessous** - NE JAMAIS inventer de technologies, fichiers ou fonctionnalités
2. **Si une information n'est pas dans les données, NE PAS la mentionner**
3. **Le nom du projet est "{data["root_name"]}"** - utilise ce nom exact
4. **Base-toi sur les VRAIS fichiers listés** - pas sur des suppositions

---

# DONNÉES RÉELLES DU PROJET "{data["root_name"]}"
{desc_section}
## ARBORESCENCE RÉELLE
```
{file_tree_str}
```

## STATISTIQUES RÉELLES
- Total fichiers scannés: {data["stats"]["total_files"]}
- Total dossiers: {data["stats"]["total_dirs"]}
- Extensions trouvées: {extensions_str}

## CONTENU DU README (si trouvé)
{data["readme"][:4000] if data["readme"] else "❌ Aucun README trouvé dans ce projet"}

## FICHIERS DE CONFIGURATION RÉELS
{configs_str if configs_str else "❌ Aucun fichier de configuration standard trouvé"}

## EXTRAITS DE CODE SOURCE
{key_files_str if key_files_str else "❌ Aucun fichier de code échantillonné"}

---

# INSTRUCTIONS DE GÉNÉRATION

Analyse les données RÉELLES ci-dessus et génère une configuration de contexte en Markdown.

**Détecte le TYPE de projet** à partir des fichiers réels:
- Fichiers .py, requirements.txt, pyproject.toml → Projet Python
- Fichiers .js/.ts, package.json → Projet Node.js/JavaScript
- Fichiers .md, docs/ → Documentation
- Fichiers .csv, .ipynb, data/ → Projet Data/Analytics
- Fichiers marketing, seo, analytics → Projet Marketing/SEO
- Autre → Décris ce que tu vois réellement

**GÉNÈRE CE MARKDOWN** (adapte les sections au type de projet détecté):

# {data["root_name"]}

## Vue d'ensemble
[Décris ce que fait CE projet basé sur le README et les fichiers vus]

## Stack / Outils
[Liste UNIQUEMENT les technologies que tu vois dans les fichiers de config]
[Ex: Si tu vois "gradio" dans pyproject.toml, mentionne Gradio]

## Structure clé
[Décris les dossiers/fichiers RÉELS que tu as vus dans l'arborescence]
[Explique leur rôle basé sur leur nom et contenu]

## Concepts importants
[Extrais les patterns et concepts du code/config réels]

## Comment travailler avec ce projet
[Base-toi sur les scripts dans pyproject.toml, package.json, Makefile, etc.]

## Points d'attention
[Ce qu'un LLM doit savoir pour aider sur CE projet spécifique]

---

**RAPPEL FINAL**: Génère UNIQUEMENT du Markdown basé sur les données réelles fournies.
Ne mentionne JAMAIS Flask, Django, React, PostgreSQL ou autre technologie que tu ne vois PAS explicitement dans les fichiers ci-dessus.
"""

    return prompt


def _generate_security_section(path: Path, check_cves: bool = True) -> tuple[str, list]:
    """
    Génère la section de sécurité pour un projet scanné.

    Args:
        path: Chemin du projet
        check_cves: Si True, vérifie les CVE via OSV.dev

    Returns:
        tuple: (security_markdown, security_alerts)
    """
    try:
        # Scan rapide pour détecter les packages
        scanner = ProjectScanner(max_depth=3, max_files=5000)
        result = scanner.scan(path)

        # Check CVEs si demandé
        if check_cves and result.packages:
            result.security_alerts = scanner.check_security(result)

        # Build security context
        security_context = scanner._build_security_context(result)

        if not security_context.is_dev:
            return "", []

        lines = []
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
        lines.append(
            f"> Niveau de sécurité: {level_indicators.get(security_context.security_level, 'STANDARD')}"
        )
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
                lines.append("")

            if (
                "javascript" in security_context.languages
                or "typescript" in security_context.languages
            ):
                lines.append("#### JavaScript/TypeScript")
                lines.append("- Échapper les outputs HTML (prévention XSS)")
                lines.append("- Valider les inputs côté serveur")
                lines.append("- Configurer CORS correctement")
                lines.append("- Utiliser `helmet.js` pour les headers de sécurité")
                lines.append("")

            if "go" in security_context.languages:
                lines.append("#### Go")
                lines.append("- Utiliser `prepared statements` pour SQL")
                lines.append("- Échapper les templates HTML avec `html/template`")
                lines.append("")

            if "rust" in security_context.languages:
                lines.append("#### Rust")
                lines.append("- Utiliser `sqlx` avec requêtes paramétrées")
                lines.append("- Éviter `unsafe` sauf si nécessaire")
                lines.append("")

        # Context-specific recommendations
        if security_context.security_keywords_found:
            lines.append("### Recommandations Spécifiques")
            lines.append("")

            if any(k in security_context.security_keywords_found for k in ["auth", "credentials"]):
                lines.append("#### 🔐 Authentification")
                lines.append("- Rate limiting sur les endpoints d'auth")
                lines.append("- HTTPS uniquement")
                lines.append("- JWT avec expiration courte")
                lines.append("")

            if any(
                k in security_context.security_keywords_found for k in ["database", "sql", "query"]
            ):
                lines.append("#### 🗄️ Base de Données")
                lines.append("- **TOUJOURS** requêtes paramétrées")
                lines.append("- Principe du moindre privilège")
                lines.append("")

            if any(k in security_context.security_keywords_found for k in ["api"]):
                lines.append("#### 🌐 API Security")
                lines.append("- Authentification sur tous les endpoints sensibles")
                lines.append("- Rate limiting et validation des inputs")
                lines.append("")

        # OWASP Top 10
        lines.append("### Rappel OWASP Top 10")
        lines.append("")
        lines.append("| # | Vulnérabilité |")
        lines.append("|---|---------------|")
        for code, name in list(OWASP_TOP_10.items())[:5]:
            lines.append(f"| {code} | {name} |")
        lines.append("")

        # CVE Alerts
        if result.security_alerts:
            lines.append("---")
            lines.append("")
            lines.append("## Alertes de Sécurité (CVE)")
            lines.append("")

            critical = [a for a in result.security_alerts if a.severity == "CRITICAL"]
            high = [a for a in result.security_alerts if a.severity == "HIGH"]

            if critical:
                lines.append("### 🔴 CRITIQUES")
                for a in critical:
                    fix = f" → `{a.fixed_version}`" if a.fixed_version else ""
                    lines.append(f"- **{a.cve_id}**: `{a.package}`{fix}")
                lines.append("")

            if high:
                lines.append("### 🟠 ÉLEVÉES")
                for a in high[:5]:
                    lines.append(f"- {a.cve_id}: `{a.package}`")
                lines.append("")

        return "\n".join(lines), result.security_alerts

    except Exception as e:
        return f"\n---\n\n## Sécurité\n\n⚠️ Erreur lors de l'analyse de sécurité: {e}\n", []


def generate_config_with_llm(
    path_str: str, project_name: str, description: str = "", depth: int = 5, check_cves: bool = True
) -> tuple[str, str, str]:
    """
    Génère la config projet en utilisant Ollama pour l'analyse.

    Returns:
        tuple: (status, summary, config)
    """
    path = Path(path_str).expanduser()

    if not path.exists():
        return f"❌ Le chemin '{path}' n'existe pas", "", ""

    if not path.is_dir():
        return f"❌ '{path}' n'est pas un répertoire", "", ""

    # 1. Collecter les données
    try:
        data = collect_project_data(path, max_depth=depth)
    except Exception as e:
        return f"❌ Erreur lors de la collecte: {e}", "", ""

    # 2. Construire le prompt
    prompt = build_llm_prompt(project_name, data, description)

    # 3. Appeler Ollama
    try:
        forge = get_forge()

        # Vérifier qu'Ollama est disponible
        if not forge.ollama.is_available():
            return "❌ Ollama non disponible - Lance 'ollama serve'", "", ""

        # Générer avec Ollama (utilise le provider existant)
        config = forge.ollama.generate(
            prompt=prompt,
            system_prompt="""Tu es un analyste de code expert. Tu génères des documentations de contexte projet.

RÈGLES CRITIQUES:
1. Tu utilises UNIQUEMENT les données fournies dans le prompt
2. Tu ne doit JAMAIS inventer de technologies, frameworks ou fonctionnalités
3. Si tu ne vois pas une technologie dans les fichiers, tu ne la mentionnes PAS
4. Tu réponds UNIQUEMENT en Markdown, sans texte avant ou après
5. Tu bases ton analyse sur les fichiers RÉELS listés dans les dossiers et sous dossier qui t'ont été fournis""",
        )

        if not config:
            return "❌ Ollama n'a pas généré de réponse", "", ""

        # Nettoyer la réponse (enlever les balises code si présentes)
        config = config.strip()
        if config.startswith("```markdown"):
            config = config[11:]
        if config.startswith("```"):
            config = config[3:]
        if config.endswith("```"):
            config = config[:-3]
        config = config.strip()

        # 4. Ajouter la section sécurité (générée automatiquement)
        security_section, security_alerts = _generate_security_section(path, check_cves=check_cves)
        if security_section:
            config = config + "\n\n" + security_section

        # 5. Construire le résumé
        summary = f"""## 📊 Analyse du projet

**Fichiers scannés**: {data["stats"]["total_files"]}
**Dossiers**: {data["stats"]["total_dirs"]}

### Extensions détectées
"""
        for ext, count in sorted(
            data["stats"]["extensions"].items(), key=lambda x: x[1], reverse=True
        )[:8]:
            summary += f"- `{ext}`: {count} fichiers\n"

        if data["readme"]:
            summary += "\n✅ README détecté et analysé"
        if data["configs"]:
            summary += f"\n✅ {len(data['configs'])} fichiers de config analysés"

        # Ajouter infos sécurité au résumé
        if security_alerts:
            crit = sum(1 for a in security_alerts if a.severity == "CRITICAL")
            high = sum(1 for a in security_alerts if a.severity == "HIGH")
            summary += (
                f"\n⚠️ **{len(security_alerts)} CVE détectées** ({crit} critiques, {high} élevées)"
            )
        else:
            summary += "\n✅ Section sécurité ajoutée"

        status = "✅ Configuration générée par IA + Sécurité"
        return status, summary, config

    except Exception as e:
        return f"❌ Erreur Ollama: {e}", "", ""


# =============================================================================
# SCAN FUNCTIONS (legacy + new)
# =============================================================================


def scan_directory_for_ui(
    path_str: str,
    project_name: str,
    description: str | None = None,
    depth: int = 5,
    check_cves: bool = False,
) -> tuple[str, str, str]:
    """
    Scan a directory and return results for UI display.

    Args:
        path_str: Path to the directory to scan
        project_name: Name for the project
        description: Optional description override
        depth: Scan depth (default: 5 for comprehensive scan)
        check_cves: If True, check detected packages for CVEs via OSV.dev

    Returns:
        tuple: (status_message, scan_summary, generated_config)
    """
    if not path_str.strip():
        return "❌ Entrez un chemin de répertoire", "", ""

    if not project_name.strip():
        return "❌ Entrez un nom de projet", "", ""

    path = Path(path_str).expanduser()

    if not path.exists():
        return f"❌ Le chemin '{path}' n'existe pas", "", ""

    if not path.is_dir():
        return f"❌ '{path}' n'est pas un répertoire", "", ""

    try:
        # max_files élevé pour les gros projets, max_depth selon le slider
        scanner = ProjectScanner(max_depth=depth, max_files=50000)
        result = scanner.scan(path)

        # Check for CVEs if requested
        if check_cves and result.packages:
            result.security_alerts = scanner.check_security(result)

        # Generate summary
        summary = format_scan_summary(result)

        # Generate config
        config = scanner.generate_config(
            result, project_name.strip(), description.strip() if description else None
        )

        status = f"✅ Scan terminé: {result.files_scanned} fichiers en {result.scan_duration_ms}ms"
        if result.packages:
            status += f" | {len(result.packages)} dépendances"
        if result.security_alerts:
            crit = sum(1 for a in result.security_alerts if a.severity == "CRITICAL")
            high = sum(1 for a in result.security_alerts if a.severity == "HIGH")
            status += f" | ⚠️ {len(result.security_alerts)} CVEs ({crit}C/{high}H)"

        return status, summary, config

    except Exception as e:
        return f"❌ Erreur lors du scan: {e}", "", ""


def format_scan_summary(result: ScanResult) -> str:
    """Format scan results as Markdown summary."""
    lines = ["## 📊 Résumé du Scan\n"]

    # Languages
    if result.languages:
        lines.append("### Langages détectés")
        lines.append("")
        for lang in result.languages[:5]:
            version_str = f" ({lang.version})" if lang.version else ""
            lines.append(
                f"- **{lang.name}**{version_str}: {lang.file_count} fichiers ({lang.percentage}%)"
            )
        lines.append("")

    # Frameworks
    if result.frameworks:
        lines.append("### Frameworks et Librairies")
        lines.append("")
        by_category: dict[str, list] = {}
        for fw in result.frameworks:
            by_category.setdefault(fw.category, []).append(fw)

        category_labels = {
            "backend": "🔧 Backend",
            "frontend": "🎨 Frontend",
            "orm": "🗄️ ORM/DB",
            "ui": "🖥️ UI Framework",
            "validation": "✅ Validation",
            "http": "🌐 HTTP Client",
            "task-queue": "⚡ Task Queue",
            "state": "📦 State",
            "mobile": "📱 Mobile",
            "other": "📌 Autres",
        }

        for cat, fws in by_category.items():
            label = category_labels.get(cat, f"📌 {cat.title()}")
            fw_names = ", ".join(f"**{f.name}**" for f in fws)
            lines.append(f"- {label}: {fw_names}")
        lines.append("")

    # Databases
    if result.databases:
        lines.append("### Base de données")
        lines.append("")
        for db in result.databases:
            orm_str = f" (ORM: {db.orm})" if db.orm else ""
            lines.append(f"- **{db.name}**{orm_str} - détecté dans {db.detected_from}")
        lines.append("")

    # Tests
    if result.tests:
        lines.append("### Tests")
        lines.append("")
        for test in result.tests:
            dirs_str = f" ({', '.join(test.test_dirs)})" if test.test_dirs else ""
            lines.append(f"- **{test.framework}**{dirs_str}")
        lines.append("")

    # Conventions
    if result.conventions:
        conv = result.conventions
        if conv.formatter or conv.linter:
            lines.append("### Conventions")
            lines.append("")
            if conv.formatter:
                lines.append(f"- Formatter: **{conv.formatter}**")
            if conv.linter:
                lines.append(f"- Linter: **{conv.linter}**")
            if conv.typechecker:
                lines.append(f"- Type checker: **{conv.typechecker}**")
            if conv.line_length:
                lines.append(f"- Longueur ligne: {conv.line_length}")
            lines.append("")

    # Docker
    if result.docker and (result.docker.has_dockerfile or result.docker.has_compose):
        lines.append("### 🐳 Docker")
        lines.append("")
        if result.docker.has_dockerfile:
            lines.append("- ✅ Dockerfile présent")
        if result.docker.has_compose:
            services_str = ", ".join(result.docker.services[:5]) if result.docker.services else ""
            lines.append(f"- ✅ Docker Compose: {result.docker.compose_file}")
            if services_str:
                lines.append(f"- Services: {services_str}")
        lines.append("")

    # CI/CD
    if result.cicd and result.cicd.provider:
        lines.append("### 🔄 CI/CD")
        lines.append("")
        lines.append(f"- Provider: **{result.cicd.provider}**")
        if result.cicd.workflows:
            lines.append(f"- Workflows: {', '.join(result.cicd.workflows[:5])}")
        lines.append("")

    # Structure info
    if result.structure:
        lines.append("### 📁 Structure")
        lines.append("")
        lines.append(f"- Répertoires: {result.structure.total_dirs}")
        lines.append(f"- Fichiers: {result.structure.total_files}")
        if result.structure.directories:
            top_dirs = ", ".join(result.structure.directories[:8])
            lines.append(f"- Dossiers racine: {top_dirs}")
        lines.append("")

    # Packages
    if result.packages:
        lines.append("### 📦 Dépendances détectées")
        lines.append("")

        # Count installed vs declared for confidence indicator
        installed_count = sum(1 for p in result.packages if p.version_source == "installed")
        total_count = len(result.packages)

        if installed_count == total_count:
            lines.append("✅ *Toutes les versions sont vérifiées (installées)*")
        elif installed_count > 0:
            lines.append(f"ℹ️ *{installed_count}/{total_count} versions vérifiées (installées)*")
        else:
            lines.append("⚠️ *Versions déclarées uniquement (non vérifiées)*")
        lines.append("")

        by_ecosystem: dict[str, list] = {}
        for pkg in result.packages[:30]:
            by_ecosystem.setdefault(pkg.ecosystem, []).append(pkg)

        for ecosystem, pkgs in by_ecosystem.items():
            # Show version source indicator
            def format_pkg(p):
                icon = "✓" if p.version_source == "installed" else "?"
                return f"`{p.name}@{p.version}` {icon}"

            pkg_list = ", ".join(format_pkg(p) for p in pkgs[:6])
            if len(pkgs) > 6:
                pkg_list += f" ... +{len(pkgs) - 6}"
            lines.append(f"- **{ecosystem}**: {pkg_list}")
        lines.append("")

    # Security Alerts
    lines.append("### 🔒 Sécurité (CVE)")
    lines.append("")
    if not result.security_alerts and result.packages:
        lines.append("✅ **Aucune vulnérabilité connue** dans les dépendances détectées")
        lines.append("")
    elif result.security_alerts:
        critical = [a for a in result.security_alerts if a.severity == "CRITICAL"]
        high = [a for a in result.security_alerts if a.severity == "HIGH"]
        medium = [a for a in result.security_alerts if a.severity == "MEDIUM"]

        if critical:
            lines.append(f"🔴 **CRITIQUES ({len(critical)})**:")
            for a in critical[:3]:
                fix = f" → `{a.fixed_version}`" if a.fixed_version else ""
                lines.append(f"  - **{a.cve_id}**: `{a.package}`{fix}")
            lines.append("")

        if high:
            lines.append(f"🟠 **ÉLEVÉES ({len(high)})**:")
            for a in high[:3]:
                lines.append(f"  - {a.cve_id}: `{a.package}`")
            if len(high) > 3:
                lines.append(f"  - ... et {len(high) - 3} autres")
            lines.append("")

        if medium:
            lines.append(f"🟡 **MOYENNES**: {len(medium)} vulnérabilité(s)")
            lines.append("")

    # Errors
    if result.errors:
        lines.append("### ⚠️ Avertissements")
        lines.append("")
        for error in result.errors[:3]:
            lines.append(f"- {error}")
        lines.append("")

    return "\n".join(lines)


def save_scanned_config(
    project_name: str, config_content: str, auto_activate: bool = True
) -> tuple[str, gr.update, gr.update]:
    """
    Save the generated config and register as project.

    Args:
        project_name: Name for the project
        config_content: Generated Markdown configuration
        auto_activate: Whether to auto-activate the project

    Returns:
        tuple: (status_message, projects_dropdown_update, scan_projects_dropdown_update)
    """
    if not project_name.strip():
        return "❌ Nom de projet requis", gr.update(), gr.update()

    if not config_content.strip():
        return "❌ Configuration vide - scannez d'abord", gr.update(), gr.update()

    forge = get_forge()
    normalized_name = normalize_name(project_name.strip())

    # Save config file
    config_path = forge.projects_path / f"{normalized_name}.md"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_content, encoding="utf-8")

    # Register project
    success, msg = forge.init_project(normalized_name, str(config_path))

    if success and auto_activate:
        forge.use_project(normalized_name)

    # Get updated project list
    projects = get_projects_list()

    if success:
        status = f"✅ Projet '{normalized_name}' créé et activé"
    else:
        status = f"❌ Erreur: {msg}"

    return (
        status,
        gr.update(choices=projects, value=normalized_name if success else None),
        gr.update(choices=projects),
    )


def get_default_scan_path() -> str:
    """Get a sensible default path for scanning."""
    # Check if /hostfs exists (Docker with mounted volume)
    hostfs = Path("/hostfs")
    if hostfs.exists() and hostfs.is_dir():
        return "/hostfs"
    return str(Path.cwd())


def scan_uploaded_zip(
    zip_file, project_name: str, description: str | None = None, depth: int = 3
) -> tuple[str, str, str]:
    """
    Scan an uploaded ZIP file containing a project.

    Args:
        zip_file: Uploaded file object from Gradio
        project_name: Name for the project
        description: Optional description override
        depth: Scan depth

    Returns:
        tuple: (status_message, scan_summary, generated_config)
    """
    if zip_file is None:
        return "❌ Uploadez un fichier ZIP de votre projet", "", ""

    if not project_name.strip():
        return "❌ Entrez un nom de projet", "", ""

    # Get the file path from Gradio upload
    zip_path = Path(zip_file.name if hasattr(zip_file, "name") else zip_file)

    if not zip_path.exists():
        return "❌ Fichier non trouvé", "", ""

    if not zipfile.is_zipfile(zip_path):
        return "❌ Le fichier n'est pas un ZIP valide", "", ""

    temp_dir = None
    try:
        # Create temp directory for extraction
        temp_dir = tempfile.mkdtemp(prefix="promptforge_scan_")
        extract_path = Path(temp_dir) / "project"

        # Extract ZIP
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_path)

        # Check if ZIP contains a single root folder
        contents = list(extract_path.iterdir())
        if len(contents) == 1 and contents[0].is_dir():
            # Use the single folder as project root
            project_path = contents[0]
        else:
            # Use extract_path directly
            project_path = extract_path

        # Scan the extracted project
        scanner = ProjectScanner(max_depth=depth)
        result = scanner.scan(project_path)

        # Generate summary
        summary = format_scan_summary(result)

        # Generate config
        config = scanner.generate_config(
            result, project_name.strip(), description.strip() if description else None
        )

        status = f"✅ Scan terminé: {result.files_scanned} fichiers en {result.scan_duration_ms}ms"

        return status, summary, config

    except zipfile.BadZipFile:
        return "❌ Fichier ZIP corrompu ou invalide", "", ""
    except Exception as e:
        return f"❌ Erreur lors du scan: {e}", "", ""
    finally:
        # Cleanup temp directory
        if temp_dir and Path(temp_dir).exists():
            try:
                shutil.rmtree(temp_dir)
            except OSError:
                pass
