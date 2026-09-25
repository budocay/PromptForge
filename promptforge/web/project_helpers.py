"""
Project helper functions for PromptForge web interface.
Handles project CRUD operations for the UI.
"""

from pathlib import Path

import gradio as gr

from ..tokens import estimate_tokens
from .ollama_helpers import get_forge

# Constante partagée
SANS_PROJET = "🔧 Sans projet (prompt seul)"


def get_projects_list() -> list[str]:
    """Liste les projets disponibles avec l'option 'Sans projet'."""
    forge = get_forge()
    projects = forge.list_projects()
    return [SANS_PROJET] + [p.name for p in projects]


def get_current_project() -> str:
    """Retourne le projet actif."""
    forge = get_forge()
    project = forge.get_current_project()
    return project.name if project else ""


def get_project_config(project_name: str) -> str:
    """Récupère la config d'un projet avec stats."""
    if not project_name:
        return ""

    if project_name == SANS_PROJET:
        return "*Aucun projet sélectionné*"

    forge = get_forge()
    project = forge.db.get_project(project_name)
    if not project:
        return "*Projet introuvable*"

    content = project.config_content or ""
    char_count = len(content)
    line_count = content.count("\n") + 1
    word_count = len(content.split())

    # Estimation tokens précise
    token_count = estimate_tokens(content)

    stats = f"""<div style="background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px; margin-bottom: 20px;">

### 📊 Statistiques du contexte projet

| Métrique | Valeur |
|----------|--------|
| 📝 Caractères | **{char_count:,}** |
| 📖 Mots | **{word_count:,}** |
| 📄 Lignes | **{line_count}** |
| 🎯 Tokens | **{token_count:,}** |

</div>

---

### 📄 Configuration du projet

{content}
"""
    return stats


def refresh_projects_dropdown():
    """Rafraîchit la liste des projets."""
    projects = get_projects_list()
    current = get_current_project()
    return gr.update(choices=projects, value=current if current in projects else None)


def select_project(project_name: str) -> tuple[str, str]:
    """Sélectionne un projet et retourne sa config."""
    if not project_name:
        return "*Sélectionnez un projet ou 'Sans projet'*", ""

    if project_name == SANS_PROJET:
        return (
            """### 🔧 Mode Sans Projet

**Utilisation:** Reformatage et recommandation basés uniquement sur votre prompt.

**Avantages:**
- ✅ Détection de domaine précise (pas de pollution par le contexte)
- ✅ Idéal pour tester des prompts génériques
- ✅ Recommandations pures basées sur le contenu du prompt

**Note:** L'historique n'est pas sauvegardé en mode sans projet.""",
            "ℹ️ Mode consultation (sans projet)",
        )

    forge = get_forge()
    success, msg = forge.use_project(project_name)
    config = get_project_config(project_name)

    status = f"✅ Projet '{project_name}' activé" if success else f"❌ {msg}"
    return config, status


def normalize_name(name: str) -> str:
    """Normalise un nom de projet."""
    return name.strip().replace(" ", "-").lower()


def create_project_from_editor(name: str, config_content: str):
    """Crée un projet depuis l'éditeur manuel."""
    if not name or not config_content:
        return "❌ Nom et configuration requis", config_content, gr.update()

    normalized_name = normalize_name(name)
    forge = get_forge()

    config_path = forge.projects_path / f"{normalized_name}.md"
    config_path.write_text(config_content, encoding="utf-8")

    success, msg = forge.init_project(normalized_name, str(config_path))

    projects = get_projects_list()
    if success:
        forge.use_project(normalized_name)
        return f"✅ {msg}", config_content, gr.update(choices=projects, value=normalized_name)
    return f"❌ {msg}", config_content, gr.update(choices=projects)


def upload_file(file, project_name: str):
    """Upload un fichier .md et crée le projet."""
    if file is None:
        return "❌ Aucun fichier sélectionné", gr.update(), gr.update()

    if not project_name:
        return "❌ Entrez d'abord un nom de projet", gr.update(), gr.update()

    try:
        content = Path(file).read_text(encoding="utf-8")
        normalized_name = normalize_name(project_name)
        forge = get_forge()

        config_path = forge.projects_path / f"{normalized_name}.md"
        config_path.write_text(content, encoding="utf-8")

        success, msg = forge.init_project(normalized_name, str(config_path))

        projects = get_projects_list()
        if success:
            forge.use_project(normalized_name)
            return (
                f"✅ {msg}",
                gr.update(choices=projects, value=normalized_name),
                gr.update(choices=projects, value=normalized_name),
            )
        return f"❌ {msg}", gr.update(choices=projects), gr.update(choices=projects)
    except Exception as e:
        return f"❌ Erreur: {e}", gr.update(), gr.update()


def delete_project(project_name: str):
    """Supprime un projet."""
    if not project_name:
        return "❌ Sélectionnez un projet", gr.update()

    forge = get_forge()
    success, msg = forge.delete_project(project_name)

    projects = get_projects_list()
    status = f"✅ {msg}" if success else f"❌ {msg}"
    return status, gr.update(choices=projects, value=None)


def load_project_to_editor(project_name: str) -> tuple[str, str]:
    """Charge un projet dans l'éditeur (contenu brut)."""
    if not project_name or project_name == SANS_PROJET:
        return "", ""

    forge = get_forge()
    project = forge.db.get_project(project_name)
    if not project:
        return project_name, ""

    return project_name, project.config_content or ""


def get_history_display(project_filter: str, limit: int = 10) -> str:
    """Affiche l'historique formaté."""
    forge = get_forge()

    project_name = project_filter if project_filter and project_filter != "Tous" else None
    history = forge.get_history(project_name, int(limit))

    if not history:
        return "📭 Aucun historique"

    output = []
    for h in history:
        date_str = h.created_at[:16].replace("T", " ")
        preview = h.raw_prompt[:80].replace("\n", " ")
        if len(h.raw_prompt) > 80:
            preview += "..."
        output.append(f"**[{date_str}]** {preview}\n\n📁 `{Path(h.file_path).name}`\n\n---")

    return "\n".join(output)
