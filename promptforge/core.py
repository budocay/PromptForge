"""
Core de PromptForge - Logique principale de reformatage des prompts.
"""

import re
from datetime import datetime
from pathlib import Path

from .database import Database, Project
from .logging_config import get_logger
from .providers import (
    OllamaConfig,
    OllamaModelNotFoundError,
    OllamaProvider,
    OllamaTimeoutError,
    format_prompt_with_ollama,
    get_default_ollama_model,
    get_default_ollama_url,
)
from .security import (
    SecurityContext,
    check_cve_osv,
    detect_dependencies_from_text,
    detect_dev_context,
    get_security_guidelines,
)

logger = get_logger(__name__)


class PromptForge:
    def __init__(self, base_path: str | None = None):
        """
        Initialise PromptForge.

        Args:
            base_path: Chemin de base pour la DB et l'historique.
                       Si None, utilise le répertoire courant.
        """
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.db_path = self.base_path / "promptforge.db"
        self.history_path = self.base_path / "history"
        self.projects_path = self.base_path / "projects"

        # Création des dossiers si nécessaire
        self.history_path.mkdir(exist_ok=True)
        self.projects_path.mkdir(exist_ok=True)

        # Initialisation
        self.db = Database(str(self.db_path))
        self.ollama = OllamaProvider()

    def configure_ollama(self, model: str | None = None, base_url: str | None = None) -> bool:
        """Configure le provider Ollama.

        Un argument omis reprend le defaut de l'environnement
        (``OLLAMA_MODEL``, ``OLLAMA_HOST``) au lieu d'une valeur figee :
        ``promptforge format --model x`` ne perd donc plus ``OLLAMA_HOST``.
        """
        self.ollama = OllamaProvider(
            OllamaConfig(
                base_url=base_url or get_default_ollama_url(),
                model=model or get_default_ollama_model(),
            )
        )
        return self.ollama.is_available()

    def init_project(self, name: str, config_path: str) -> tuple[bool, str]:
        """
        Initialise un nouveau projet à partir d'un fichier de configuration.

        Args:
            name: Nom du projet
            config_path: Chemin vers le fichier .md de configuration

        Returns:
            Tuple (succès, message)
        """
        config_file = Path(config_path)

        if not config_file.exists():
            return False, f"Fichier de configuration introuvable: {config_path}"

        if not config_file.suffix.lower() == ".md":
            return False, "Le fichier de configuration doit être un fichier .md"

        try:
            config_content = config_file.read_text(encoding="utf-8")
        except Exception as e:
            return False, f"Erreur de lecture du fichier: {e}"

        # Vérifier si le projet existe déjà
        existing = self.db.get_project(name)
        if existing:
            # Mise à jour du projet existant
            self.db.update_project(name, config_content)
            return True, f"Projet '{name}' mis à jour avec succès"

        # Création du nouveau projet
        self.db.add_project(name, str(config_file.absolute()), config_content)
        return True, f"Projet '{name}' initialisé avec succès"

    def use_project(self, name: str) -> tuple[bool, str]:
        """
        Active un projet pour l'utiliser.

        Args:
            name: Nom du projet à activer

        Returns:
            Tuple (succès, message)
        """
        if self.db.set_active_project(name):
            return True, f"Projet '{name}' activé"
        return False, f"Projet '{name}' introuvable"

    def get_current_project(self) -> Project | None:
        """Retourne le projet actuellement actif."""
        return self.db.get_active_project()

    def list_projects(self) -> list[Project]:
        """Liste tous les projets disponibles."""
        return self.db.list_projects()

    def delete_project(self, name: str) -> tuple[bool, str]:
        """Supprime un projet."""
        if self.db.delete_project(name):
            return True, f"Projet '{name}' supprimé"
        return False, f"Projet '{name}' introuvable"

    def format_prompt(
        self,
        raw_prompt: str,
        project_name: str | None = None,
        profile_name: str | None = None,
        check_security: bool = True,
        check_cves: bool = False,
    ) -> tuple[bool, str, str | None, SecurityContext | None]:
        """
        Reformate un prompt en utilisant le contexte projet.

        Args:
            raw_prompt: Le prompt brut à reformater
            project_name: Nom du projet. None = utiliser le projet actif
                (comportement CLI), "" = explicitement sans projet (interface web),
                "xxx" = ce projet précis, sans changer le projet actif.
            profile_name: Profil de reformatage (claude_technique, chatgpt_standard, etc.)
            check_security: Si True, analyse et injecte les guidelines de sécurité
            check_cves: Si True, vérifie les CVE via OSV.dev (plus lent)

        Returns:
            Un quadruplet (succès, message, prompt_reformaté, security_context) :

            - succès (bool) : True si le reformatage a abouti.
            - message (str) : en cas de succès avec projet, le chemin du fichier
              d'historique écrit ; en cas de succès sans projet, la mention que
              l'historique n'a pas été sauvegardé ; en cas d'échec, le message
              d'erreur.
            - prompt_reformaté (Optional[str]) : le prompt produit, ou None dès que
              succès vaut False.
            - security_context (Optional[SecurityContext]) : None quand
              check_security vaut False, et None quand Ollama est indisponible car
              la fonction sort avant l'analyse. Sinon un SecurityContext, y compris
              sur le chemin d'échec du reformatage puisque l'analyse a déjà eu lieu.

            Les deux appelants de production déballent ces quatre valeurs et
            consomment security_context : cli.py pour l'affichage du contexte dev et
            des CVE, web/interface.py pour les indicateurs de sécurité de l'UI.
        """
        # Récupération du projet (optionnel)
        # project_name = None -> utiliser le projet actif (CLI)
        # project_name = "" -> explicitement sans projet (Web "Sans projet")
        # project_name = "xxx" -> utiliser ce projet spécifique
        project = None
        if project_name is None:
            # Non spécifié = utiliser le projet actif (comportement CLI)
            project = self.db.get_active_project()
        elif project_name != "":
            # Projet spécifique demandé
            project = self.db.get_project(project_name)
        # Si project_name == "", on garde project = None (explicitement sans projet)

        # Vérification Ollama
        if not self.ollama.is_available():
            return False, "Ollama n'est pas disponible. Vérifiez qu'il est lancé.", None, None

        # Contexte projet (vide si pas de projet)
        project_context = project.config_content if project else ""

        # === SECURITY ENRICHMENT ===
        security_context = None
        if check_security:
            # Analyze prompt and project for dev context
            full_text = f"{raw_prompt}\n{project_context}"
            security_context = detect_dev_context(full_text)

            if security_context.is_dev:
                logger.info(
                    f"Dev context detected: languages={security_context.languages}, "
                    f"level={security_context.security_level}"
                )

                # Check for CVEs if requested and dependencies found
                if check_cves:
                    dependencies = detect_dependencies_from_text(project_context)
                    if dependencies:
                        logger.info(f"Checking {len(dependencies)} dependencies for CVEs...")
                        security_context.cves = check_cve_osv(dependencies)
                        if security_context.cves:
                            logger.warning(
                                f"Found {len(security_context.cves)} CVE(s) in dependencies!"
                            )

                # Enrich project context with security guidelines
                security_guidelines = get_security_guidelines(security_context)
                if security_guidelines:
                    project_context = f"{project_context}\n{security_guidelines}"
                    logger.debug("Security guidelines injected into context")

        # Reformatage via Ollama
        try:
            formatted = format_prompt_with_ollama(
                raw_prompt=raw_prompt,
                project_context=project_context,
                provider=self.ollama,
                profile_name=profile_name,
            )
        except OllamaTimeoutError as exc:
            # Condition explicite, distincte d'un Ollama absent (traite plus
            # haut) et d'une erreur reseau (traitee juste en dessous). On sort
            # AVANT `_save_history` et `db.add_history` : le message peut donc
            # affirmer sans mentir que rien n'a ete sauvegarde (lecon D-054).
            logger.warning(
                f"Timeout Ollama pendant le reformatage: "
                f"model={exc.model} timeout={exc.timeout}s"
            )
            return False, str(exc), None, security_context
        except OllamaModelNotFoundError as exc:
            logger.warning(f"Modele Ollama introuvable: {exc.model}")
            return False, str(exc), None, security_context

        if not formatted:
            return False, "Erreur lors du reformatage avec Ollama", None, security_context

        # Sauvegarde dans l'historique (seulement si projet actif)
        if project:
            file_path = self._save_history(project, raw_prompt, formatted)

            # Enregistrement en base
            self.db.add_history(
                project_id=project.id,
                raw_prompt=raw_prompt,
                formatted_prompt=formatted,
                file_path=str(file_path),
            )
            return True, str(file_path), formatted, security_context
        else:
            # Sans projet, on retourne juste le résultat (pas d'historique)
            return (
                True,
                "Reformaté sans projet (historique non sauvegardé)",
                formatted,
                security_context,
            )

    def _save_history(self, project: Project, raw_prompt: str, formatted_prompt: str) -> Path:
        """Sauvegarde le prompt dans un fichier d'historique."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")

        # Création d'un nom de fichier basé sur le prompt
        slug = self._slugify(raw_prompt[:50])
        filename = f"{timestamp}_{project.name}_{slug}.md"

        file_path = self.history_path / filename

        content = f"""# Prompt History - {datetime.now().strftime("%Y-%m-%d %H:%M")}

## Projet
**Nom:** {project.name}

---

## Prompt Original (brut)
```
{raw_prompt}
```

---

## Prompt Reformaté
{formatted_prompt}

---

## Contexte Projet Utilisé
<details>
<summary>Voir le contexte</summary>

{project.config_content}

</details>
"""

        file_path.write_text(content, encoding="utf-8")
        return file_path

    def _slugify(self, text: str) -> str:
        """Convertit un texte en slug pour nom de fichier."""
        # Supprime les caractères spéciaux
        text = re.sub(r"[^\w\s-]", "", text.lower())
        # Remplace les espaces par des underscores
        text = re.sub(r"[\s]+", "_", text)
        return text[:30].strip("_")

    def get_history(self, project_name: str | None = None, limit: int = 20) -> list:
        """Récupère l'historique des prompts."""
        return self.db.get_history(project_name, limit)

    def check_status(self) -> dict:
        """Retourne le statut du système."""
        active_project = self.get_current_project()
        ollama_ok = self.ollama.is_available()
        models = self.ollama.list_models() if ollama_ok else []

        return {
            "ollama_available": ollama_ok,
            "ollama_models": models,
            "current_model": self.ollama.config.model,
            "active_project": active_project.name if active_project else None,
            "total_projects": len(self.list_projects()),
            "db_path": str(self.db_path),
            "history_path": str(self.history_path),
        }

    def close(self):
        """Ferme proprement les ressources."""
        self.db.close()
