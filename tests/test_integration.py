"""
Tests d'intégration pour PromptForge.
Ces tests vérifient le flux complet de bout en bout.
"""

from pathlib import Path

from promptforge.core import PromptForge
from promptforge.security import SecurityContext


class TestIntegrationWorkflow:
    """Tests du workflow complet."""

    def test_full_workflow_with_mock(self, temp_dir, sample_config_file, mock_ollama_available):
        """Test du workflow complet avec Ollama simulé."""
        forge = PromptForge(temp_dir)
        forge.ollama = mock_ollama_available

        # 1. Init projet
        success, msg = forge.init_project("my-app", sample_config_file)
        assert success

        # 2. Activer le projet
        success, msg = forge.use_project("my-app")
        assert success

        # 3. Vérifier le statut
        status = forge.check_status()
        assert status["active_project"] == "my-app"
        assert status["ollama_available"]

        # 4. Reformater un prompt
        result = forge.format_prompt("crée une route REST pour gérer les utilisateurs")
        assert len(result) == 4
        success, file_path, formatted, security_ctx = result
        assert success
        assert formatted is not None
        # check_security vaut True par defaut : le 4e membre porte l'analyse
        assert isinstance(security_ctx, SecurityContext)

        # 5. Vérifier l'historique
        history = forge.get_history()
        assert len(history) == 1
        assert "utilisateurs" in history[0].raw_prompt

        # 6. Vérifier le fichier généré
        assert Path(file_path).exists()
        content = Path(file_path).read_text()
        assert "Prompt Original" in content
        assert "crée une route REST" in content

        forge.close()

    def test_multi_project_workflow(self, temp_dir, sample_config_content, mock_ollama_available):
        """Test avec plusieurs projets."""
        forge = PromptForge(temp_dir)
        forge.ollama = mock_ollama_available

        # Créer deux configs différentes
        config1 = Path(temp_dir) / "projects" / "frontend.md"
        config1.write_text(sample_config_content.replace("FastAPI", "React"))

        config2 = Path(temp_dir) / "projects" / "backend.md"
        config2.write_text(sample_config_content.replace("FastAPI", "Django"))

        # Init deux projets
        forge.init_project("frontend", str(config1))
        forge.init_project("backend", str(config2))

        # Switch entre projets
        forge.use_project("frontend")
        assert forge.get_current_project().name == "frontend"

        # Prompt pour frontend
        forge.format_prompt("create a React component")

        # Switch et prompt pour backend
        forge.use_project("backend")
        forge.format_prompt("create a Django view")

        # Vérifier l'historique par projet
        frontend_history = forge.get_history("frontend")
        backend_history = forge.get_history("backend")

        assert len(frontend_history) == 1
        assert len(backend_history) == 1
        assert "React" in frontend_history[0].raw_prompt
        assert "Django" in backend_history[0].raw_prompt

        forge.close()

    def test_history_persistence(self, temp_dir, sample_config_file, mock_ollama_available):
        """Test que l'historique persiste entre les sessions."""
        # Session 1
        forge1 = PromptForge(temp_dir)
        forge1.ollama = mock_ollama_available
        forge1.init_project("persist-test", sample_config_file)
        forge1.use_project("persist-test")
        forge1.format_prompt("first prompt")
        forge1.close()

        # Session 2 (nouvelle instance)
        forge2 = PromptForge(temp_dir)
        forge2.ollama = mock_ollama_available

        # Le projet doit toujours exister
        project = forge2.db.get_project("persist-test")
        assert project is not None

        # L'historique doit persister
        history = forge2.get_history("persist-test")
        assert len(history) == 1

        # Ajouter un autre prompt
        forge2.use_project("persist-test")
        forge2.format_prompt("second prompt")

        history = forge2.get_history("persist-test")
        assert len(history) == 2

        forge2.close()

    def test_config_reload_updates_content(self, temp_dir, mock_ollama_available):
        """Test que reload met à jour le contenu."""
        forge = PromptForge(temp_dir)
        forge.ollama = mock_ollama_available

        config_path = Path(temp_dir) / "projects" / "reload-test.md"
        config_path.write_text("# Original Config\n\nVersion 1")

        # Init avec config originale
        forge.init_project("reload-project", str(config_path))

        project = forge.db.get_project("reload-project")
        assert "Version 1" in project.config_content

        # Modifier le fichier
        config_path.write_text("# Updated Config\n\nVersion 2")

        # Reload
        forge.init_project("reload-project", str(config_path))

        project = forge.db.get_project("reload-project")
        assert "Version 2" in project.config_content

        forge.close()


class TestEdgeCases:
    """Tests des cas limites."""

    def test_empty_prompt(self, forge, sample_config_file, mock_ollama_available):
        """Test avec prompt vide."""
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = mock_ollama_available

        # Un prompt vide devrait quand même fonctionner
        success, message, formatted, security_ctx = forge.format_prompt("")
        # Le comportement dépend d'Ollama, mais ne devrait pas crasher
        assert success is True
        assert formatted is not None
        # Un prompt vide ne suffit pas a qualifier un contexte dev, mais l'analyse
        # a bien eu lieu : le 4e membre est un SecurityContext, pas None.
        assert isinstance(security_ctx, SecurityContext)
        assert Path(message).exists()

    def test_very_long_prompt(self, forge, sample_config_file, mock_ollama_available):
        """Test avec prompt très long."""
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = mock_ollama_available

        long_prompt = "test " * 1000
        success, file_path, formatted, security_ctx = forge.format_prompt(long_prompt)

        assert success is True
        assert formatted is not None
        assert isinstance(security_ctx, SecurityContext)
        # Le slug du fichier est limité
        assert len(Path(file_path).stem) < 100

    def test_special_characters_in_prompt(self, forge, sample_config_file, mock_ollama_available):
        """Test avec caractères spéciaux."""
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = mock_ollama_available

        special_prompt = "Create a function: f(x) = x² + 2x + 1 # @$%^&*()"
        success, file_path, formatted, security_ctx = forge.format_prompt(special_prompt)

        assert success is True
        assert formatted is not None
        assert isinstance(security_ctx, SecurityContext)
        assert Path(file_path).exists()

    def test_unicode_in_prompt(self, forge, sample_config_file, mock_ollama_available):
        """Test avec Unicode."""
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = mock_ollama_available

        unicode_prompt = (
            "Créer une fonction pour gérer les émojis 🚀 et les caractères japonais 日本語"
        )
        success, file_path, formatted, security_ctx = forge.format_prompt(unicode_prompt)

        assert success is True
        assert formatted is not None
        assert isinstance(security_ctx, SecurityContext)

        # Vérifier que le fichier contient l'Unicode
        content = Path(file_path).read_text(encoding="utf-8")
        assert "émojis" in content
