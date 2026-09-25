"""
Tests pour le module CLI.
"""

import pytest
import sys
from io import StringIO
from unittest.mock import patch, MagicMock
from pathlib import Path

from promptforge.cli import main, get_forge


class TestGetForge:
    """Tests pour la fonction get_forge."""

    def test_get_forge_with_path(self, temp_dir):
        """Test avec chemin spécifié."""
        forge = get_forge(temp_dir)
        assert str(forge.base_path) == temp_dir
        forge.close()

    def test_get_forge_without_path(self):
        """Test sans chemin (utilise cwd)."""
        forge = get_forge(None)
        assert forge.base_path is not None
        forge.close()


    def test_get_forge_reads_data_path_from_environment(self, temp_dir, monkeypatch):
        """La CLI suit PROMPTFORGE_DATA_PATH, comme l'interface web."""
        monkeypatch.setenv("PROMPTFORGE_DATA_PATH", temp_dir)
        forge = get_forge(None)
        assert str(forge.base_path) == temp_dir
        forge.close()

    def test_explicit_path_beats_the_environment(self, temp_dir, tmp_path, monkeypatch):
        monkeypatch.setenv("PROMPTFORGE_DATA_PATH", str(tmp_path))
        forge = get_forge(temp_dir)
        assert str(forge.base_path) == temp_dir
        forge.close()

class TestCliCommands:
    """Tests pour les commandes CLI."""

    def test_help(self):
        """Test de l'aide."""
        with patch.object(sys, 'argv', ['promptforge', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_no_command(self, capsys):
        """Test sans commande."""
        with patch.object(sys, 'argv', ['promptforge']):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_init_command(self, temp_dir, sample_config_file, capsys):
        """Test de la commande init."""
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'init', 'my-project', '--config', sample_config_file
        ]):
            main()
        
        captured = capsys.readouterr()
        assert "✓" in captured.out
        assert "my-project" in captured.out

    def test_init_command_missing_config(self, temp_dir, capsys):
        """Test init avec config manquante."""
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'init', 'my-project', '--config', '/nonexistent.md'
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "✗" in captured.err  # Erreurs sur stderr

    def test_list_command_empty(self, temp_dir, capsys):
        """Test list sans projets."""
        with patch.object(sys, 'argv', ['promptforge', '--path', temp_dir, 'list']):
            main()
        
        captured = capsys.readouterr()
        assert "Aucun projet" in captured.out

    def test_list_command_with_projects(self, temp_dir, sample_config_file, capsys):
        """Test list avec projets."""
        # Créer des projets d'abord
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'init', 'project1', '--config', sample_config_file
        ]):
            main()
        
        with patch.object(sys, 'argv', ['promptforge', '--path', temp_dir, 'list']):
            main()
        
        captured = capsys.readouterr()
        assert "project1" in captured.out

    def test_use_command(self, temp_dir, sample_config_file, capsys):
        """Test de la commande use."""
        # Init projet
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'init', 'my-proj', '--config', sample_config_file
        ]):
            main()
        
        # Use projet
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'use', 'my-proj'
        ]):
            main()
        
        captured = capsys.readouterr()
        assert "activé" in captured.out

    def test_use_command_not_found(self, temp_dir, capsys):
        """Test use avec projet inexistant."""
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'use', 'nonexistent'
        ]):
            with pytest.raises(SystemExit):
                main()
        
        captured = capsys.readouterr()
        assert "✗" in captured.err  # Erreurs sur stderr

    def test_status_command(self, temp_dir, capsys):
        """Test de la commande status."""
        with patch.object(sys, 'argv', ['promptforge', '--path', temp_dir, 'status']):
            main()
        
        captured = capsys.readouterr()
        assert "Status PromptForge" in captured.out
        assert "Ollama" in captured.out

    def test_history_command_empty(self, temp_dir, capsys):
        """Test history sans historique."""
        with patch.object(sys, 'argv', ['promptforge', '--path', temp_dir, 'history']):
            main()
        
        captured = capsys.readouterr()
        assert "Aucun historique" in captured.out

    def test_delete_command_force(self, temp_dir, sample_config_file, capsys):
        """Test delete avec --force."""
        # Init projet
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'init', 'to-delete', '--config', sample_config_file
        ]):
            main()
        
        # Delete avec force
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'delete', 'to-delete', '--force'
        ]):
            main()
        
        captured = capsys.readouterr()
        assert "supprimé" in captured.out

    def test_reload_command(self, temp_dir, sample_config_file, capsys):
        """Test de la commande reload."""
        # Init projet
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'init', 'reload-test', '--config', sample_config_file
        ]):
            main()
        
        # Reload
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'reload', 'reload-test'
        ]):
            main()
        
        captured = capsys.readouterr()
        assert "rechargée" in captured.out

    def test_format_command_no_project(self, temp_dir, capsys):
        """Test format sans projet actif."""
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'format', 'test prompt'
        ]):
            with pytest.raises(SystemExit):
                main()
        
        captured = capsys.readouterr()
        assert "✗" in captured.err  # Erreurs sur stderr

    def test_format_command_empty_prompt(self, temp_dir, sample_config_file, capsys):
        """Test format avec prompt vide."""
        # Init projet
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'init', 'test', '--config', sample_config_file
        ]):
            main()
        
        # Format avec prompt vide (simulation entrée vide)
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'format'
        ]):
            with patch('builtins.input', side_effect=['']):
                with pytest.raises(SystemExit):
                    main()


class TestCliOutput:
    """Tests pour le format de sortie CLI."""

    def test_output_markers(self, temp_dir, sample_config_file, capsys):
        """Test des marqueurs visuels (✓, ✗, →)."""
        # Test succès
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'init', 'test', '--config', sample_config_file
        ]):
            main()
        
        captured = capsys.readouterr()
        assert "✓" in captured.out
        
        # Test échec
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'use', 'nonexistent'
        ]):
            with pytest.raises(SystemExit):
                main()
        
        captured = capsys.readouterr()
        assert "✗" in captured.err  # Erreurs sur stderr

    def test_list_shows_active_marker(self, temp_dir, sample_config_file, capsys):
        """Test que list affiche le marqueur du projet actif."""
        with patch.object(sys, 'argv', [
            'promptforge', '--path', temp_dir,
            'init', 'active-proj', '--config', sample_config_file
        ]):
            main()
        
        with patch.object(sys, 'argv', ['promptforge', '--path', temp_dir, 'list']):
            main()
        
        captured = capsys.readouterr()
        assert "→" in captured.out  # Marqueur projet actif
