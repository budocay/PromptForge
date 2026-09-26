"""
Web package for PromptForge Gradio interface.

This package is modularized for maintainability:
- assets: CSS et logos
- ollama_helpers: Ollama status and model management
- project_helpers: Project CRUD operations for UI
- scanner_helpers: Project scanning for auto-config
- analysis: Prompt quality analysis and comparison
- recommendations: Model recommendations and benchmarks
- profiles_ui: Profile selection UI helpers
- template_helpers: Template loading utilities
- onboarding: Questionnaires metiers (donnee) et generation de contexte
- wizard: Parcours de l'assistant guide (plan, navigation, sauvegarde)
- interface: Main Gradio interface
"""

from .interface import create_interface, launch_web
from .ollama_helpers import get_forge, set_base_path

__all__ = ["create_interface", "launch_web", "set_base_path", "get_forge"]
