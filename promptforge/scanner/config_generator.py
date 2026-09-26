"""Generation de la configuration Markdown a partir d'un `ScanResult`."""

from datetime import datetime

from ..security import (
    format_secret_alerts,
)
from .models import DetectedFramework, ScanResult


class ConfigGeneratorMixin:
    """Genere la config projet PromptForge (`generate_config`)."""

    def generate_config(
        self,
        result: ScanResult,
        project_name: str,
        description: str | None = None,
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
                services_str = (
                    ", ".join(result.docker.services[:5]) if result.docker.services else ""
                )
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
                lines.append(
                    f"- **Fichiers de config**: {', '.join(result.conventions.config_files)}"
                )
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
                    lines.append(
                        "- Utiliser `secrets` au lieu de `random` pour tokens/mots de passe"
                    )
                    lines.append("- Requêtes SQL paramétrées (pas de f-string dans les queries)")
                    lines.append("- Valider les inputs avec Pydantic ou dataclasses")
                    lines.append("- `bcrypt` ou `argon2` pour le hashing de mots de passe")
                    lines.append(
                        "- Éviter les fonctions d'évaluation dynamique avec données utilisateur"
                    )
                    lines.append("")

                if (
                    "javascript" in security_context.languages
                    or "typescript" in security_context.languages
                ):
                    lines.append("#### JavaScript/TypeScript")
                    lines.append("- Échapper les outputs HTML (prévention XSS)")
                    lines.append("- Requêtes paramétrées pour les bases de données")
                    lines.append(
                        "- Valider les inputs côté serveur (ne jamais faire confiance au client)"
                    )
                    lines.append("- Configurer CORS correctement")
                    lines.append("- Utiliser `helmet.js` pour les headers de sécurité")
                    lines.append("")

                if "rust" in security_context.languages:
                    lines.append("#### Rust")
                    lines.append(
                        "- Préférer les types sûrs (`Option`, `Result`) aux valeurs nulles"
                    )
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
                    lines.append(
                        "- Utiliser les requêtes paramétrées avec Entity Framework ou Dapper"
                    )
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
                    lines.append(
                        "- ActiveRecord avec requêtes paramétrées (where avec placeholders)"
                    )
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

                if any(
                    k in security_context.security_keywords_found
                    for k in ["auth", "login", "password", "jwt", "token", "credentials"]
                ):
                    lines.append("#### 🔐 Authentification")
                    lines.append("- Implémenter rate limiting sur les endpoints d'auth")
                    lines.append("- HTTPS uniquement pour toutes les communications")
                    lines.append(
                        "- JWT: expiration courte, refresh tokens, signature forte (RS256)"
                    )
                    lines.append("- Stocker les mots de passe avec bcrypt/argon2 (jamais MD5/SHA1)")
                    lines.append("- Protection CSRF sur tous les formulaires")
                    lines.append("")

                if any(
                    k in security_context.security_keywords_found
                    for k in ["sql", "database", "query"]
                ):
                    lines.append("#### 🗄️ Base de Données")
                    lines.append(
                        "- **TOUJOURS** utiliser des requêtes paramétrées (prepared statements)"
                    )
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

                if any(
                    k in security_context.security_keywords_found
                    for k in ["api", "endpoint", "route"]
                ):
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
        from ..security import CVE_CHECK_INCOMPLETE_PREFIX

        cve_check_warnings = [
            error for error in result.errors if error.startswith(CVE_CHECK_INCOMPLETE_PREFIX)
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
                        lines.append("")
                        lines.append(
                            f"**Remediation:** Mettre à jour vers `{alert.fixed_version}` ou version supérieure"
                        )
                    else:
                        lines.append("")
                        lines.append(
                            "**Remediation:** Vérifier si une version corrigée existe ou envisager une alternative"
                        )
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
                    fix_str = (
                        f" → Mettre à jour vers `{alert.fixed_version}`"
                        if alert.fixed_version
                        else ""
                    )
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
        lines.append("- Configuration generee automatiquement par PromptForge Scanner")
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
