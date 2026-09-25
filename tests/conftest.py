"""
Fixtures partagées pour les tests PromptForge.
"""

import pytest
import tempfile
import os
from pathlib import Path

from promptforge.database import Database
from promptforge.core import PromptForge
from promptforge.providers import OllamaProvider, OllamaConfig


@pytest.fixture
def temp_dir():
    """Crée un répertoire temporaire pour les tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def temp_db(temp_dir):
    """Crée une base de données temporaire."""
    db_path = os.path.join(temp_dir, "test.db")
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture(autouse=True)
def _isolate_promptforge_env(monkeypatch):
    """Isole la suite du shell qui la lance.

    `OLLAMA_MODEL` et `PROMPTFORGE_DATA_PATH` sont lus par la CLI, le coeur et
    l'interface web : sans ce nettoyage, un `export OLLAMA_MODEL=...` chez le
    contributeur changerait le verdict de tests qui n'en parlent pas.
    """
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("PROMPTFORGE_DATA_PATH", raising=False)


@pytest.fixture
def forge(temp_dir):
    """Crée une instance PromptForge avec répertoire temporaire."""
    pf = PromptForge(temp_dir)
    yield pf
    pf.close()


@pytest.fixture
def sample_config_content():
    """Contenu de configuration projet exemple."""
    return """# Test Project

## Stack
- Python 3.12
- FastAPI
- PostgreSQL

## Structure
```
src/
├── api/
├── models/
└── services/
```

## Conventions
- Type hints obligatoires
- Docstrings Google style
- Tests avec pytest
"""


@pytest.fixture
def sample_config_file(temp_dir, sample_config_content):
    """Crée un fichier de configuration temporaire."""
    config_path = Path(temp_dir) / "test-project.md"
    config_path.write_text(sample_config_content, encoding="utf-8")
    return str(config_path)


@pytest.fixture
def mock_ollama_response():
    """Réponse simulée d'Ollama."""
    return """## Contexte
- Projet: Test Project
- Stack: Python 3.12, FastAPI, PostgreSQL

## Demande
Créer une route API pour la gestion des utilisateurs avec les opérations CRUD.

## Spécifications
- Endpoint REST: /api/v1/users
- Méthodes: GET, POST, PUT, DELETE
- Validation avec Pydantic
- Type hints obligatoires
- Docstrings Google style

## Contraintes
- Respecter la structure src/api/
- Tests unitaires avec pytest
"""


class MockOllamaProvider:
    """Provider Ollama simulé pour les tests."""
    
    def __init__(self, available: bool = True, response: str = "Mocked response"):
        self._available = available
        self._response = response
        self.config = OllamaConfig()
    
    def is_available(self) -> bool:
        return self._available
    
    def list_models(self) -> list[str]:
        if self._available:
            return ["llama3.1:latest", "mistral:latest"]
        return []
    
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self._available:
            return None
        return self._response


@pytest.fixture
def mock_ollama_available(mock_ollama_response):
    """Provider Ollama simulé disponible."""
    return MockOllamaProvider(available=True, response=mock_ollama_response)


@pytest.fixture
def mock_ollama_unavailable():
    """Provider Ollama simulé non disponible."""
    return MockOllamaProvider(available=False)
