"""
Ollama helper functions for PromptForge web interface.
Handles Ollama status checking and model management.
"""

import os

from ..core import PromptForge

# Instance globale
_forge: PromptForge | None = None
_base_path: str | None = None


def set_base_path(path: str):
    """Définit le chemin de base pour PromptForge."""
    global _base_path, _forge
    _base_path = path
    _forge = None  # Reset pour recréer avec le bon path


def get_forge() -> PromptForge:
    """Récupère ou crée l'instance PromptForge."""
    global _forge
    if _forge is None:
        # Priorité: 1) _base_path défini, 2) variable d'env, 3) défaut
        base = _base_path or os.environ.get("PROMPTFORGE_DATA_PATH")
        if base:
            _forge = PromptForge(base)
        else:
            _forge = PromptForge()

        # Configurer Ollama avec les variables d'environnement
        _forge.configure_ollama()
        ollama_model = _forge.ollama.config.model
        ollama_host = _forge.ollama.config.base_url

        # Import du logger
        from ..logging_config import get_logger

        logger = get_logger(__name__)
        logger.info(f"Ollama configured: {ollama_host} | Model: {ollama_model}")
    return _forge


def check_ollama_status() -> str:
    """Vérifie le statut d'Ollama."""
    forge = get_forge()
    if forge.ollama.is_available():
        models = forge.ollama.list_models()
        model_list = ", ".join(models[:5]) if models else "aucun"
        return (
            f"✅ Ollama connecté | Modèle: {forge.ollama.config.model} | Disponibles: {model_list}"
        )
    return "❌ Ollama non disponible - Lancez 'ollama serve'"


def get_ollama_models() -> list[str]:
    """Liste les modèles Ollama disponibles."""
    forge = get_forge()
    try:
        if forge.ollama.is_available():
            return forge.ollama.list_models()
    except Exception:
        pass
    return []


def get_current_ollama_model() -> str:
    """Retourne le modèle Ollama actuellement configuré."""
    forge = get_forge()
    return forge.ollama.config.model


def change_ollama_model(model_name: str) -> str:
    """Change le modèle Ollama utilisé."""
    if not model_name:
        return "❌ Aucun modèle sélectionné"

    forge = get_forge()
    try:
        # Mettre à jour la configuration
        forge.ollama.config.model = model_name

        from ..logging_config import get_logger

        logger = get_logger(__name__)
        logger.info(f"Model changed to: {model_name}")

        return f"✅ Modèle changé: **{model_name}**"
    except Exception as e:
        return f"❌ Erreur: {str(e)}"
