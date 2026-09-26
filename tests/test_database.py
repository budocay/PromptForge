"""
Tests pour le module database.
"""

import pytest


class TestDatabase:
    """Tests pour la classe Database."""

    def test_init_creates_tables(self, temp_db):
        """Vérifie que l'initialisation crée les tables."""
        # Vérifier que les tables existent
        cursor = temp_db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert "projects" in tables
        assert "prompt_history" in tables
        assert "settings" in tables

    def test_add_project(self, temp_db):
        """Test de l'ajout d'un projet."""
        project = temp_db.add_project(
            name="test-project", config_path="/path/to/config.md", config_content="# Test Config"
        )

        assert project.id is not None
        assert project.name == "test-project"
        assert project.config_path == "/path/to/config.md"
        assert project.config_content == "# Test Config"
        assert not project.is_active

    def test_get_project(self, temp_db):
        """Test de la récupération d'un projet."""
        temp_db.add_project("my-project", "/config.md", "content")

        project = temp_db.get_project("my-project")
        assert project is not None
        assert project.name == "my-project"

        # Projet inexistant
        assert temp_db.get_project("nonexistent") is None

    def test_update_project(self, temp_db):
        """Test de la mise à jour d'un projet."""
        temp_db.add_project("update-test", "/config.md", "old content")

        result = temp_db.update_project("update-test", "new content")
        assert result

        project = temp_db.get_project("update-test")
        assert project.config_content == "new content"

    def test_set_active_project(self, temp_db):
        """Test de l'activation d'un projet."""
        temp_db.add_project("project1", "/p1.md", "c1")
        temp_db.add_project("project2", "/p2.md", "c2")

        # Activer project1
        result = temp_db.set_active_project("project1")
        assert result

        active = temp_db.get_active_project()
        assert active.name == "project1"

        # Activer project2 (devrait désactiver project1)
        temp_db.set_active_project("project2")
        active = temp_db.get_active_project()
        assert active.name == "project2"

        # Vérifier que project1 n'est plus actif
        p1 = temp_db.get_project("project1")
        assert not p1.is_active

    def test_list_projects(self, temp_db):
        """Test de la liste des projets."""
        assert len(temp_db.list_projects()) == 0

        temp_db.add_project("alpha", "/a.md", "a")
        temp_db.add_project("beta", "/b.md", "b")
        temp_db.add_project("gamma", "/g.md", "g")

        projects = temp_db.list_projects()
        assert len(projects) == 3
        # Vérifier l'ordre alphabétique
        assert projects[0].name == "alpha"
        assert projects[1].name == "beta"
        assert projects[2].name == "gamma"

    def test_delete_project(self, temp_db):
        """Test de la suppression d'un projet."""
        temp_db.add_project("to-delete", "/d.md", "d")
        project = temp_db.get_project("to-delete")

        # Ajouter de l'historique
        temp_db.add_history(project.id, "raw", "formatted", "/history.md")

        # Supprimer
        result = temp_db.delete_project("to-delete")
        assert result

        # Vérifier la suppression
        assert temp_db.get_project("to-delete") is None

        # Projet inexistant
        assert not temp_db.delete_project("nonexistent")

    def test_add_history(self, temp_db):
        """Test de l'ajout dans l'historique."""
        project = temp_db.add_project("hist-test", "/h.md", "h")

        history = temp_db.add_history(
            project_id=project.id,
            raw_prompt="create user route",
            formatted_prompt="## Formatted prompt...",
            file_path="/history/2024-01-01.md",
        )

        assert history.id is not None
        assert history.project_id == project.id
        assert history.raw_prompt == "create user route"
        assert history.formatted_prompt == "## Formatted prompt..."

    def test_get_history(self, temp_db):
        """Test de la récupération de l'historique."""
        p1 = temp_db.add_project("proj1", "/p1.md", "p1")
        p2 = temp_db.add_project("proj2", "/p2.md", "p2")

        temp_db.add_history(p1.id, "raw1", "fmt1", "/h1.md")
        temp_db.add_history(p1.id, "raw2", "fmt2", "/h2.md")
        temp_db.add_history(p2.id, "raw3", "fmt3", "/h3.md")

        # Tout l'historique
        all_history = temp_db.get_history(limit=10)
        assert len(all_history) == 3

        # Filtré par projet
        p1_history = temp_db.get_history("proj1", limit=10)
        assert len(p1_history) == 2

        p2_history = temp_db.get_history("proj2", limit=10)
        assert len(p2_history) == 1

    def test_get_history_limit(self, temp_db):
        """Test de la limite sur l'historique."""
        project = temp_db.add_project("limit-test", "/l.md", "l")

        for i in range(10):
            temp_db.add_history(project.id, f"raw{i}", f"fmt{i}", f"/h{i}.md")

        history = temp_db.get_history(limit=5)
        assert len(history) == 5

    def test_unique_project_name(self, temp_db):
        """Test de l'unicité du nom de projet."""
        temp_db.add_project("unique", "/u.md", "u")

        with pytest.raises(Exception):  # IntegrityError
            temp_db.add_project("unique", "/u2.md", "u2")
