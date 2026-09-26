"""
Tests pour le module core (PromptForge).
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from promptforge.core import PromptForge
from promptforge.providers import OllamaModelNotFoundError, OllamaTimeoutError
from promptforge.security import SecurityContext


class TestPromptForgeInit:
    """Tests pour l'initialisation de PromptForge."""

    def test_init_creates_directories(self, temp_dir):
        """Test que l'init crée les dossiers nécessaires."""
        forge = PromptForge(temp_dir)

        assert (Path(temp_dir) / "history").exists()
        assert (Path(temp_dir) / "projects").exists()
        assert (Path(temp_dir) / "promptforge.db").exists()

        forge.close()

    def test_init_default_path(self):
        """Test de l'init avec chemin par défaut."""
        # Devrait utiliser le répertoire courant
        forge = PromptForge()
        assert forge.base_path == Path.cwd()
        forge.close()


class TestProjectManagement:
    """Tests pour la gestion des projets."""

    def test_init_project_success(self, forge, sample_config_file):
        """Test de l'initialisation d'un projet."""
        success, message = forge.init_project("test-proj", sample_config_file)

        assert success
        assert "initialisé" in message or "succès" in message

        # Vérifier que le projet existe
        project = forge.db.get_project("test-proj")
        assert project is not None
        assert project.name == "test-proj"

    def test_init_project_file_not_found(self, forge):
        """Test avec fichier de config inexistant."""
        success, message = forge.init_project("test", "/nonexistent/file.md")

        assert not success
        assert "introuvable" in message

    def test_init_project_wrong_extension(self, forge, temp_dir):
        """Test avec mauvaise extension de fichier."""
        txt_file = Path(temp_dir) / "config.txt"
        txt_file.write_text("content")

        success, message = forge.init_project("test", str(txt_file))

        assert not success
        assert ".md" in message

    def test_init_project_update_existing(self, forge, sample_config_file, temp_dir):
        """Test de mise à jour d'un projet existant."""
        # Créer le projet
        forge.init_project("update-test", sample_config_file)

        # Modifier le fichier de config
        new_config = Path(temp_dir) / "updated.md"
        new_config.write_text("# Updated Config\nNew content")

        # Réinitialiser
        success, message = forge.init_project("update-test", str(new_config))

        assert success
        assert "mis à jour" in message

        project = forge.db.get_project("update-test")
        assert "Updated Config" in project.config_content

    def test_use_project_success(self, forge, sample_config_file):
        """Test de l'activation d'un projet."""
        forge.init_project("proj1", sample_config_file)

        success, message = forge.use_project("proj1")

        assert success
        assert forge.get_current_project().name == "proj1"

    def test_use_project_not_found(self, forge):
        """Test d'activation d'un projet inexistant."""
        success, message = forge.use_project("nonexistent")

        assert not success
        assert "introuvable" in message

    def test_list_projects(self, forge, sample_config_file):
        """Test de la liste des projets."""
        assert len(forge.list_projects()) == 0

        forge.init_project("alpha", sample_config_file)
        forge.init_project("beta", sample_config_file)

        projects = forge.list_projects()
        assert len(projects) == 2

    def test_delete_project_success(self, forge, sample_config_file):
        """Test de suppression d'un projet."""
        forge.init_project("to-delete", sample_config_file)

        success, message = forge.delete_project("to-delete")

        assert success
        assert forge.db.get_project("to-delete") is None

    def test_delete_project_not_found(self, forge):
        """Test de suppression d'un projet inexistant."""
        success, message = forge.delete_project("nonexistent")

        assert not success


class TestFormatPrompt:
    """Tests pour le reformatage de prompts."""

    def test_format_no_active_project(self, forge, mock_ollama_available):
        """Sans projet actif, le reformatage aboutit mais n'ecrit aucun historique.

        Le message « Aucun projet actif » qu'attendait la version precedente
        n'existe plus : le mode « sans projet » est un cas nominal, utilise par
        l'interface web (`project_name=""`) et par le CLI quand aucun projet
        n'est active. Le double est injecte explicitement pour que la
        disponibilite reelle d'Ollama sur la machine ne decide pas du verdict.
        """
        forge.ollama = mock_ollama_available

        result = forge.format_prompt("test prompt")

        assert len(result) == 4
        success, message, formatted, security_ctx = result

        assert success is True
        assert "sans projet" in message.lower()
        assert formatted is not None
        # Aucun historique n'est ecrit hors projet
        assert forge.get_history() == []
        # check_security vaut True par defaut : l'analyse a bien eu lieu
        assert isinstance(security_ctx, SecurityContext)

    def test_format_ollama_unavailable(self, forge, sample_config_file, mock_ollama_unavailable):
        """Ollama indisponible : quadruplet (False, message, None, None).

        Le quatrieme membre vaut None parce que la fonction sort avant l'analyse
        de securite, pas parce que celle-ci serait desactivee.
        """
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = mock_ollama_unavailable

        result = forge.format_prompt("test prompt")

        assert len(result) == 4
        success, message, formatted, security_ctx = result

        assert success is False
        assert "Ollama" in message
        assert formatted is None
        assert security_ctx is None

    def test_format_with_mock_ollama(self, forge, sample_config_file, mock_ollama_available):
        """Chemin nominal avec projet : quadruplet complet et historique ecrit."""
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = mock_ollama_available

        result = forge.format_prompt("create user route")

        assert len(result) == 4
        success, file_path, formatted, security_ctx = result

        assert success is True
        assert formatted is not None

        # L'assertion porte sur le contenu utile du prompt reformate, pas sur la
        # syntaxe des delimiteurs. La sortie simulee est du Markdown que
        # `providers.py` reecrit aujourd'hui en XML (« ## Contexte » devient
        # « <context> ») ; DEC-007 prevoit de supprimer cette reecriture. Assertion
        # volontairement neutre vis-a-vis des deux comportements : le choix du
        # format est tranche par R-009, pas ici.
        assert "Stack: Python 3.12, FastAPI, PostgreSQL" in formatted
        assert "/api/v1/users" in formatted

        # Le fichier d'historique existe et son chemin est bien le 2e membre
        assert Path(file_path).exists()

        # La config projet mentionne Python, FastAPI et PostgreSQL : contexte dev
        assert isinstance(security_ctx, SecurityContext)
        assert security_ctx.is_dev is True
        assert "python" in security_ctx.languages

    def test_format_without_security_check(self, forge, sample_config_file, mock_ollama_available):
        """check_security=False : le quatrieme membre vaut None, le reste est intact.

        Contre-partie de `test_format_with_mock_ollama`, qui couvre l'etat
        « SecurityContext present ». Les deux etats du quatrieme membre sont ainsi
        couverts sur le chemin de succes.
        """
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = mock_ollama_available

        success, file_path, formatted, security_ctx = forge.format_prompt(
            "create user route", check_security=False
        )

        assert success is True
        assert formatted is not None
        assert Path(file_path).exists()
        assert security_ctx is None

    def test_format_with_specific_project(self, forge, sample_config_file, mock_ollama_available):
        """Test avec projet specifique."""
        forge.init_project("proj1", sample_config_file)
        forge.init_project("proj2", sample_config_file)
        forge.use_project("proj1")
        forge.ollama = mock_ollama_available

        # Reformater pour proj2 sans changer le projet actif
        success, _, formatted, security_ctx = forge.format_prompt("test", project_name="proj2")

        assert success is True
        assert formatted is not None
        assert isinstance(security_ctx, SecurityContext)
        # Le projet actif reste proj1
        assert forge.get_current_project().name == "proj1"
        # L'historique est bien impute a proj2 et non au projet actif
        assert len(forge.get_history("proj2")) == 1
        assert forge.get_history("proj1") == []

    def test_format_saves_to_history(self, forge, sample_config_file, mock_ollama_available):
        """Test que le prompt est sauvegardé dans l'historique."""
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = mock_ollama_available

        forge.format_prompt("my test prompt")

        history = forge.get_history()
        assert len(history) == 1
        assert history[0].raw_prompt == "my test prompt"


class TestHistoryFile:
    """Tests pour la génération des fichiers d'historique."""

    def test_history_file_content(self, forge, sample_config_file, mock_ollama_available):
        """Test du contenu du fichier d'historique."""
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = mock_ollama_available

        success, file_path, formatted, security_ctx = forge.format_prompt("create api endpoint")

        assert success is True
        assert security_ctx is not None

        content = Path(file_path).read_text()

        assert "# Prompt History" in content
        assert "Projet" in content
        assert "test" in content
        assert "Prompt Original" in content
        assert "create api endpoint" in content
        assert "Prompt Reformaté" in content

    def test_slugify(self, forge):
        """Test de la création de slugs."""
        assert forge._slugify("Hello World!") == "hello_world"
        assert forge._slugify("Test@#$%^&*()") == "test"
        assert forge._slugify("A" * 50)[:30] == "a" * 30


class TestCheckStatus:
    """Tests pour le statut du système."""

    def test_check_status_structure(self, forge, sample_config_file):
        """Test de la structure du statut."""
        forge.init_project("test", sample_config_file)
        forge.use_project("test")

        status = forge.check_status()

        assert "ollama_available" in status
        assert "ollama_models" in status
        assert "current_model" in status
        assert "active_project" in status
        assert "total_projects" in status
        assert "db_path" in status
        assert "history_path" in status

    def test_check_status_values(self, forge, sample_config_file):
        """Test des valeurs du statut."""
        forge.init_project("status-test", sample_config_file)
        forge.use_project("status-test")

        status = forge.check_status()

        assert status["active_project"] == "status-test"
        assert status["total_projects"] == 1
        assert status["current_model"] == "qwen3:8b"


class TestConfigureOllama:
    """Tests pour la configuration d'Ollama."""

    def test_configure_model(self, forge):
        """Test du changement de modèle."""
        forge.configure_ollama(model="mistral")

        assert forge.ollama.config.model == "mistral"

    def test_configure_model_keeps_ollama_host(self, forge, monkeypatch):
        """`--model` seul ne doit pas ecraser OLLAMA_HOST par localhost."""
        monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box:11434")
        forge.configure_ollama(model="mistral")

        assert forge.ollama.config.base_url == "http://gpu-box:11434"

    def test_configure_without_model_uses_environment(self, forge, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "phi4-mini")
        forge.configure_ollama()

        assert forge.ollama.config.model == "phi4-mini"

    def test_configure_base_url(self, forge):
        """Test du changement d'URL."""
        forge.configure_ollama(base_url="http://custom:8080")

        assert forge.ollama.config.base_url == "http://custom:8080"


class TestModelPricingContract:
    """Tests du contrat de ModelPricing et de la table MODEL_PRICING (F-022).

    Placés ici faute de fichier de tests dédié à profiles.py dans le périmètre
    d'agent-backend ; à déplacer vers tests/test_profiles.py si ce fichier est
    créé un jour.
    """

    def test_pricing_table_covers_exactly_the_real_models(self):
        """Une entrée de tarif par modèle réel, aucune pour le synthétique.

        `TargetModel.UNIVERSAL` ne désigne aucun modèle : lui attribuer un
        tarif reviendrait à afficher le prix d'un produit qui n'existe pas
        (DEC-004 §1, résorption de D-032 par F-028).
        """
        from promptforge.profiles import MODEL_PRICING, TargetModel

        assert set(MODEL_PRICING) == set(TargetModel) - {TargetModel.UNIVERSAL}
        assert TargetModel.UNIVERSAL not in MODEL_PRICING

    def test_target_model_holds_no_retired_or_fictional_identifier(self):
        """Aucun identifiant arrêté ou sans existence connue ne subsiste.

        Les trois valeurs listées ci-dessous ont été mesurées le 2026-09-07 :
        `gemini-3-pro` arrêté le 2026-03-09, `gemini-3-flash` déprécié, et
        `gpt-5.1-mini` répondant 404 sur sa fiche modèle pour la deuxième fois
        indépendante. Proposer une cible inatteignable est aussi faux
        qu'afficher un tarif inventé.
        """
        from promptforge.profiles import TargetModel

        interdits = {"gemini-3-pro", "gemini-3-flash", "gpt-5.1-mini"}
        valeurs = {model.value for model in TargetModel}
        assert not (valeurs & interdits), sorted(valeurs & interdits)

    def test_unconfirmed_context_windows_are_none_not_a_stale_number(self):
        """Une fenêtre non reconfirmée vaut None, pas le chiffre d'avant.

        Les fiches modèles de `gemini-3.1-pro-preview`, `gemini-3.6-flash` et
        `gpt-5.6-terra` n'ont pas pu être ouvertes le 2026-09-07. Recopier la
        fenêtre de la génération précédente afficherait une mesure que
        personne n'a faite sur ces modèles.
        """
        from promptforge.profiles import MODEL_PRICING, TargetModel

        non_confirmes = {
            TargetModel.GEMINI_3_1_PRO,
            TargetModel.GEMINI_3_6_FLASH,
            TargetModel.GPT_5_6_TERRA,
        }
        for model in non_confirmes:
            assert MODEL_PRICING[model].context_window is None, model

    def test_every_pricing_entry_carries_an_official_source(self):
        """Plus aucune entrée sans source : celles qui n'en avaient pas sont parties.

        Avant F-028, quatre entrées portaient un `source_url` vide et
        restaient affichées à l'utilisateur (D-032).
        """
        from promptforge.profiles import MODEL_PRICING

        for model, pricing in MODEL_PRICING.items():
            assert pricing.source_url, model
            assert pricing.verified_on == "2026-09-07", model

    def test_universal_profile_carries_no_pricing(self):
        """Le profil universel n'expose aucun tarif, même par défaut."""
        from promptforge.profiles import PRESET_PROFILES

        assert PRESET_PROFILES["universel"].pricing is None

    def test_every_pricing_entry_is_a_model_pricing(self):
        """Chaque valeur est bien une ModelPricing exploitable."""
        from promptforge.profiles import MODEL_PRICING, ModelPricing

        for model, pricing in MODEL_PRICING.items():
            assert isinstance(pricing, ModelPricing), model
            assert pricing.input_price > 0, model
            assert pricing.output_price > 0, model
            # None = fenêtre non confirmée par une source ; jamais 0 ni négatif.
            assert pricing.context_window is None or pricing.context_window > 0, model

    def test_cached_input_is_never_zero(self):
        """Un cache absent vaut None, jamais 0.0 : zéro facturerait un cache gratuit."""
        from promptforge.profiles import MODEL_PRICING

        for model, pricing in MODEL_PRICING.items():
            assert pricing.cached_input is None or pricing.cached_input > 0, model

    def test_sourced_entries_carry_url_and_date(self):
        """Une entrée qui porte une source porte aussi sa date de vérification."""
        from promptforge.profiles import MODEL_PRICING

        for model, pricing in MODEL_PRICING.items():
            if pricing.source_url:
                assert pricing.source_url.startswith("https://"), model
                assert pricing.verified_on, model
                # ISO 8601, forme AAAA-MM-JJ
                assert len(pricing.verified_on) == 10, model
                assert pricing.verified_on[4] == "-" and pricing.verified_on[7] == "-", model

    def test_estimate_cost_without_cache_price_ignores_cached_pct(self):
        """Sans tarif de cache confirmé, la remise n'est pas appliquée."""
        from promptforge.profiles import ModelPricing

        pricing = ModelPricing(input_price=15.0, output_price=120.0, context_window=400_000)

        assert pricing.cached_input is None
        full = pricing.estimate_cost(1_000_000, 0, cached_pct=0)
        discounted = pricing.estimate_cost(1_000_000, 0, cached_pct=1.0)
        assert full == pytest.approx(15.0)
        assert discounted == pytest.approx(full)

    def test_estimate_cost_applies_confirmed_cache_price(self):
        """Avec un tarif de cache confirmé, la remise s'applique."""
        from promptforge.profiles import ModelPricing

        pricing = ModelPricing(
            input_price=1.0,
            output_price=5.0,
            context_window=200_000,
            cached_input=0.1,
        )

        assert pricing.estimate_cost(1_000_000, 0, cached_pct=1.0) == pytest.approx(0.1)
        assert pricing.estimate_cost(1_000_000, 0, cached_pct=0.5) == pytest.approx(0.55)
        assert pricing.estimate_cost(0, 1_000_000) == pytest.approx(5.0)

    def test_gpt_5_pro_has_no_input_cache(self):
        """GPT-5 Pro ne propose pas de cache d'entrée (source officielle 2026-09-03)."""
        from promptforge.profiles import MODEL_PRICING, TargetModel

        assert MODEL_PRICING[TargetModel.GPT_5_PRO].cached_input is None

    def test_corrected_values_match_the_official_sources(self):
        """Valeurs relevées sur les pages officielles, F-022 puis F-028.

        Les quatre corrections de F-022 tiennent toujours pour les modèles
        qu'elle visait et qui restent ciblés ; s'y ajoutent les valeurs des
        trois modèles introduits par F-028, relevées le 2026-09-07.
        """
        from promptforge.profiles import MODEL_PRICING, TargetModel

        haiku = MODEL_PRICING[TargetModel.CLAUDE_HAIKU_4_5]
        assert (haiku.input_price, haiku.output_price) == (1.0, 5.0)

        gpt5pro = MODEL_PRICING[TargetModel.GPT_5_PRO]
        assert (gpt5pro.input_price, gpt5pro.output_price) == (15.0, 120.0)
        assert gpt5pro.context_window == 400_000

        assert MODEL_PRICING[TargetModel.GPT_5_1].context_window == 400_000

        # F-028 : Sonnet 5 remplace Sonnet 4.5 et coûte moins cher, avec la
        # fenêtre 1M réservée à Claude 4.6+.
        sonnet = MODEL_PRICING[TargetModel.CLAUDE_SONNET_5]
        assert (sonnet.input_price, sonnet.output_price) == (2.0, 10.0)
        assert sonnet.context_window == 1_000_000

        opus = MODEL_PRICING[TargetModel.CLAUDE_OPUS_5]
        assert (opus.input_price, opus.output_price) == (5.0, 25.0)
        assert opus.context_window == 1_000_000

        terra = MODEL_PRICING[TargetModel.GPT_5_6_TERRA]
        assert (terra.input_price, terra.output_price) == (2.0, 12.0)

        # Palier « jusqu'à 200K tokens d'entrée » pour Gemini 3.1 Pro.
        gemini_pro = MODEL_PRICING[TargetModel.GEMINI_3_1_PRO]
        assert (gemini_pro.input_price, gemini_pro.output_price) == (2.0, 12.0)

        # Tarif d'introduction Gemini 3.6 Flash, valable jusqu'au 2026-12-31.
        gemini_flash = MODEL_PRICING[TargetModel.GEMINI_3_6_FLASH]
        assert (gemini_flash.input_price, gemini_flash.output_price) == (0.75, 3.75)

    def test_model_pricing_has_no_dead_member(self):
        """avg_price_per_1k est supprimée : aucun appelant, contrat nettoyé."""
        from promptforge.profiles import ModelPricing

        assert not hasattr(ModelPricing, "avg_price_per_1k")

    def test_profiles_module_holds_no_dead_helper(self):
        """Quatre fonctions sans aucun appelant sont supprimées (F-028).

        Elles n'étaient ni exportées par `promptforge/__init__.py`, ni citées
        par `CLAUDE.md`, ni appelées par `promptforge/` ou `tests/`. Les
        repointer vers les nouveaux modèles aurait entretenu une abstraction
        de vitrine ; `compare_models()`, elle, a deux appelants vivants et
        reste en place.
        """
        import promptforge.profiles as profiles

        for nom in (
            "get_recommendation",
            "get_pricing",
            "format_comparison_table",
            "get_model_optimization_tips",
        ):
            assert not hasattr(profiles, nom), nom

        assert hasattr(profiles, "compare_models")

    def test_target_model_values_are_the_exact_published_identifiers(self):
        """Les huit identifiants sont ceux publiés, à la lettre.

        `claude-haiku-4-5-20251001` détonne à côté de `claude-opus-5` et
        `claude-sonnet-5`, et reste pourtant tel quel : la page officielle du
        2026-09-07 ne publie que cette forme datée, Anthropic n'ayant cessé de
        dater ses identifiants qu'à partir de Claude 4.6. Raccourcir en
        `claude-haiku-4-5` par souci d'homogénéité fabriquerait un alias
        qu'aucune source ne documente. La lisibilité est le rôle de
        `display_name`, pas celui de l'identifiant.
        """
        from promptforge.profiles import TargetModel

        assert {model.value for model in TargetModel} == {
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-haiku-4-5-20251001",
            "gpt-5.1",
            "gpt-5.6-terra",
            "gpt-5-pro",
            "gemini-3.1-pro-preview",
            "gemini-3.6-flash",
            "universal",
        }

    def test_every_pricing_entry_carries_a_readable_display_name(self):
        """Chaque modèle porte le nom commercial publié par son éditeur.

        Sans lui, les surfaces destinées à l'utilisateur affichent
        `claude-haiku-4-5-20251001` ou `gpt-5-pro` : exact, sourcé, illisible.
        """
        from promptforge.profiles import MODEL_PRICING, TargetModel

        attendus = {
            TargetModel.CLAUDE_OPUS_5: "Claude Opus 5",
            TargetModel.CLAUDE_SONNET_5: "Claude Sonnet 5",
            TargetModel.CLAUDE_HAIKU_4_5: "Claude Haiku 4.5",
            TargetModel.GPT_5_1: "GPT-5.1",
            TargetModel.GPT_5_6_TERRA: "GPT-5.6 Terra",
            TargetModel.GPT_5_PRO: "GPT-5 Pro",
            TargetModel.GEMINI_3_1_PRO: "Gemini 3.1 Pro",
            TargetModel.GEMINI_3_6_FLASH: "Gemini 3.6 Flash",
        }
        assert {m: p.display_name for m, p in MODEL_PRICING.items()} == attendus

    def test_compare_models_exposes_both_identifier_and_label(self):
        """La comparaison porte l'identifiant ET le nom lisible, pas l'un ou l'autre."""
        from promptforge.profiles import MODEL_PRICING, compare_models

        rows = compare_models(1000, 500)
        assert len(rows) == len(MODEL_PRICING)
        identifiants = {p.display_name: m.value for m, p in MODEL_PRICING.items()}
        for row in rows:
            assert row["label"] in identifiants
            assert row["model"] == identifiants[row["label"]]

    def test_universal_prompt_imposes_no_syntax_and_cites_its_source(self):
        """DEC-008 : le profil universel exige la cohérence, pas une syntaxe.

        Il ne vise aucun modèle et ne peut donc citer aucune documentation
        d'éditeur à l'appui d'un « XML UNIQUEMENT ». Il demande des
        délimiteurs clairs — balises XML ou titres Markdown — et une seule
        convention sur tout le prompt, seule règle réellement commune aux trois
        éditeurs, que Google documente explicitement.
        """
        from promptforge.profiles import SYSTEM_PROMPT_UNIVERSAL

        assert "XML UNIQUEMENT" not in SYSTEM_PROMPT_UNIVERSAL
        assert "PAS DE MARKDOWN" not in SYSTEM_PROMPT_UNIVERSAL
        assert "ai.google.dev/gemini-api/docs/prompting-strategies" in SYSTEM_PROMPT_UNIVERSAL
        assert "2026-06-10" in SYSTEM_PROMPT_UNIVERSAL
        # Les deux conventions sont proposées, pas une seule imposée.
        assert "Markdown" in SYSTEM_PROMPT_UNIVERSAL
        assert "<context>" in SYSTEM_PROMPT_UNIVERSAL

    def test_gemini_prompts_no_longer_claim_an_absolute_google_never_wrote(self):
        """DEC-007 volet 2 : plus d'« XML UNIQUEMENT » sur les profils Gemini.

        La source Google, mise à jour le 2026-06-10, documente balises XML et
        titres Markdown comme deux délimiteurs efficaces au choix ; la seule
        exigence est la cohérence interne. Le produit continue de retenir XML
        pour que sa sortie reste prévisible, mais le dit comme une convention
        de produit et cite la source, au lieu de présenter un absolu que
        l'éditeur n'a jamais écrit.
        """
        from promptforge.profiles import (
            SYSTEM_PROMPT_GEMINI_3_1_PRO,
            SYSTEM_PROMPT_GEMINI_3_6_FLASH,
        )

        for prompt in (SYSTEM_PROMPT_GEMINI_3_1_PRO, SYSTEM_PROMPT_GEMINI_3_6_FLASH):
            assert "XML UNIQUEMENT" not in prompt
            assert "PAS DE MARKDOWN" not in prompt
            assert "ai.google.dev/gemini-api/docs/prompting-strategies" in prompt
            assert "2026-06-10" in prompt
            # La convention retenue reste XML, et elle est annoncée comme telle.
            assert "<balise>contenu</balise>" in prompt

    def test_no_system_prompt_imposes_xml_as_an_absolute_without_a_source(self):
        """Aucun profil n'écrit « XML UNIQUEMENT » sans source à l'appui.

        Anthropic recommande réellement les balises XML : les profils Claude
        gardent donc leur consigne. Personne ne documente cet absolu pour
        Gemini ni pour un profil qui ne cible aucun modèle.
        """
        from promptforge.profiles import SYSTEM_PROMPTS, TargetModel

        sans_source = set(TargetModel) - {
            TargetModel.CLAUDE_OPUS_5,
            TargetModel.CLAUDE_SONNET_5,
            TargetModel.CLAUDE_HAIKU_4_5,
        }
        for model in sans_source:
            assert "XML UNIQUEMENT" not in SYSTEM_PROMPTS[model], model

    def test_static_system_prompts_hold_no_context_literal(self):
        """Aucun prompt système n'annonce une fenêtre que MODEL_PRICING dément.

        Verrou demandé par D-053 : `SYSTEM_PROMPT_GPT_5_1` annonçait « Contexte
        272K tokens » pendant que la table du domaine portait 400 000, dans le
        même fichier. Un prompt système ne recopie plus de fenêtre du tout.
        """
        import re

        from promptforge.profiles import SYSTEM_PROMPTS

        literal = re.compile(r"[Cc]ontexte[^\n]*?\b\d+(?:[.,]\d+)?\s*[KM]\b")
        for model, prompt in SYSTEM_PROMPTS.items():
            trouve = literal.findall(prompt)
            assert not trouve, f"{model}: fenêtre de contexte en dur {trouve}"


class TestComparisonRanksOnTariffOnly:
    """D-071 — la comparaison ne classe que sur ce qu'elle mesure.

    `profiles._get_model_tier()` câblait « Premium / Performant / Économique »
    par listes de membres. Deux contradictions mesurées avant correction :
    Claude Sonnet 5 (2.00 / 10.00) sortait « Performant » pendant que GPT-5.6
    Terra (2.00 / 12.00) sortait « Économique », alors que Sonnet 5 est moins
    cher sur les deux axes ; et ce même Terra était séparé de Gemini 3.1 Pro,
    qui porte pourtant exactement le même tarif.

    Ce qui est sourçable ici, ce sont les tarifs : chaque entrée de
    `MODEL_PRICING` porte son `source_url` et son `verified_on`. La puissance
    ne l'est pas — aucun éditeur ne publie de mesure de suivi de format. Le
    classement est donc l'ordre des coûts, et rien d'autre (DEC-006 appliqué
    aux modèles distants).

    Ces verrous portent sur la propriété qui rend ces deux contradictions
    impossibles, jamais sur l'existence d'un libellé : un test qui vérifierait
    qu'un palier existe ne verrouillerait rien.
    """

    def test_the_tier_computed_from_a_membership_list_is_gone(self):
        """La fonction qui traduisait une identité en appréciation n'existe plus.

        Son seul appelant était `compare_models()`, et la seule chose que ses
        deux consommateurs en faisaient était de l'afficher. Rien à repointer :
        on supprime, comme pour `get_recommendation()` et D-055.
        """
        import promptforge.profiles as profiles

        assert not hasattr(profiles, "_get_model_tier")

    def test_a_compared_row_carries_only_what_the_tariff_publishes(self):
        """Le jeu de clés d'une ligne est fermé.

        Verrou de mutation : réintroduire une clé `tier`, ou toute autre
        appréciation posée à côté des tarifs, fait échouer ce test sans qu'il
        ait à connaître le libellé choisi.
        """
        from promptforge.profiles import MODEL_PRICING, compare_models

        attendu = {
            "model",
            "label",
            "cost",
            "cost_display",
            "input_price",
            "output_price",
            "context",
        }
        lignes = compare_models()
        assert len(lignes) == len(MODEL_PRICING)
        for ligne in lignes:
            assert set(ligne) == attendu, ligne["model"]

    def test_no_compared_value_states_a_power_the_repo_never_measured(self):
        """Le jugement ne revient pas non plus par une valeur.

        Complément du verrou précédent : celui-là ferme les clés, celui-ci
        ferme le vocabulaire. Restaurer l'ancien palier ferait échouer les deux.
        """
        from promptforge.profiles import compare_models

        for ligne in compare_models():
            rendu = " ".join(str(valeur) for valeur in ligne.values())
            for mot in ("Premium", "Performant", "puissant", "Puissant"):
                assert mot not in rendu, (ligne["model"], mot)

    def test_two_models_on_the_same_tariff_are_described_identically(self):
        """GPT-5.6 Terra et Gemini 3.1 Pro : même tarif, même description.

        Les deux sont à 2.00 / 12.00 avec une fenêtre non confirmée. Le palier
        retiré les séparait pourtant, « Économique » pour l'un, « Performant »
        pour l'autre, sur la seule foi de deux listes écrites à la main. Plus
        rien de ce que rend la comparaison ne peut les distinguer, hors leur
        identité et le nom commercial que publie leur éditeur.
        """
        from promptforge.profiles import MODEL_PRICING, TargetModel, compare_models

        terra = MODEL_PRICING[TargetModel.GPT_5_6_TERRA]
        gemini = MODEL_PRICING[TargetModel.GEMINI_3_1_PRO]
        assert (terra.input_price, terra.output_price) == (2.0, 12.0)
        assert (gemini.input_price, gemini.output_price) == (2.0, 12.0)
        assert terra.context_window == gemini.context_window

        lignes = {ligne["model"]: ligne for ligne in compare_models()}

        def description(identifiant):
            return {
                cle: valeur
                for cle, valeur in lignes[identifiant].items()
                if cle not in {"model", "label"}
            }

        assert description("gpt-5.6-terra") == description("gemini-3.1-pro-preview")

    def test_sonnet_5_ranks_ahead_of_gpt_5_6_terra_as_its_tariff_demands(self):
        """Le cas exact qui a révélé le défaut (D-071).

        Sonnet 5 est à 2.00 / 10.00, Terra à 2.00 / 12.00 : même tarif
        d'entrée, sortie moins chère. Sonnet 5 passe donc devant, quel que soit
        le mélange de tokens. L'ancien palier affichait l'inverse.
        """
        from promptforge.profiles import MODEL_PRICING, TargetModel, compare_models

        sonnet = MODEL_PRICING[TargetModel.CLAUDE_SONNET_5]
        terra = MODEL_PRICING[TargetModel.GPT_5_6_TERRA]
        assert (sonnet.input_price, sonnet.output_price) == (2.0, 10.0)
        assert (terra.input_price, terra.output_price) == (2.0, 12.0)

        for entree, sortie in ((1000, 500), (1, 1), (100_000, 10), (10, 100_000)):
            ordre = [ligne["model"] for ligne in compare_models(entree, sortie)]
            assert ordre.index("claude-sonnet-5") < ordre.index("gpt-5.6-terra"), (
                entree,
                sortie,
            )

    def test_no_model_cheaper_on_both_axes_is_ever_ranked_after_a_dearer_one(self):
        """La propriété générale dont la paire Sonnet 5 / Terra n'est qu'un cas.

        Elle tient par construction depuis que le classement est l'ordre des
        coûts. Aucune table écrite à la main ne peut la garantir, et l'ancienne
        la violait.
        """
        from promptforge.profiles import MODEL_PRICING, compare_models

        rang = {ligne["model"]: i for i, ligne in enumerate(compare_models())}
        for modele_a, tarif_a in MODEL_PRICING.items():
            for modele_b, tarif_b in MODEL_PRICING.items():
                jamais_plus_cher = (
                    tarif_a.input_price <= tarif_b.input_price
                    and tarif_a.output_price <= tarif_b.output_price
                )
                moins_cher_quelque_part = (
                    tarif_a.input_price < tarif_b.input_price
                    or tarif_a.output_price < tarif_b.output_price
                )
                if jamais_plus_cher and moins_cher_quelque_part:
                    assert rang[modele_a.value] < rang[modele_b.value], (
                        modele_a.value,
                        modele_b.value,
                    )

    def test_the_ranking_follows_the_tariffs_when_two_of_them_are_swapped(self, monkeypatch):
        """Verrou de mutation : le classement lit le tarif, pas l'identité.

        On échange les tarifs du modèle le moins cher et du plus cher. Un
        classement dérivé suit l'échange ; une table indexée par modèle ne le
        suivrait pas, et c'est précisément ce qui produisait D-071.
        """
        import promptforge.profiles as profiles
        from promptforge.profiles import TargetModel

        avant = [ligne["model"] for ligne in profiles.compare_models()]
        assert avant[0] == "gemini-3.6-flash"
        assert avant[-1] == "gpt-5-pro"

        echange = dict(profiles.MODEL_PRICING)
        flash, pro = TargetModel.GEMINI_3_6_FLASH, TargetModel.GPT_5_PRO
        echange[flash], echange[pro] = echange[pro], echange[flash]
        monkeypatch.setattr(profiles, "MODEL_PRICING", echange)

        apres = [ligne["model"] for ligne in profiles.compare_models()]
        assert apres[0] == "gpt-5-pro"
        assert apres[-1] == "gemini-3.6-flash"


class TestFormatPromptTimeout:
    """Le depassement de delai Ollama, vu depuis le quadruplet de `format_prompt()`.

    F-032. Le contrat de retour est inchange : `format_prompt()` rend toujours
    `(succes, message, prompt_formate, security_context)` et `generate()` rend
    toujours `Optional[str]`. Seul le canal `message`, deja affiche tel quel par
    le CLI (`cli.py:170`) et par le web (`web/interface.py:139`), gagne une
    troisieme valeur distincte.
    """

    class TimingOutProvider:
        """Provider qui depasse le delai, sans qu'Ollama soit installe."""

        def __init__(self, model="qwen3:14b", timeout=600):
            self.config = MagicMock(model=model, timeout=timeout)
            self._model = model
            self._timeout = timeout

        def is_available(self):
            return True

        def list_models(self):
            return [self._model]

        def generate(self, prompt, system_prompt="", num_ctx=16384):
            raise OllamaTimeoutError(self._model, self._timeout)

    def test_timeout_is_reported_as_a_failure_not_a_crash(self, forge):
        """Avant F-032, ce cas remontait un `TimeoutError` nu jusqu'a l'appelant."""
        forge.ollama = self.TimingOutProvider()

        result = forge.format_prompt("test prompt")

        assert len(result) == 4
        success, message, formatted, _ = result
        assert success is False
        assert formatted is None
        assert message

    def test_timeout_message_explains_the_model_was_too_slow(self, forge):
        """L'utilisateur doit comprendre que le modele a trainé, pas que le service est tombé."""
        forge.ollama = self.TimingOutProvider(model="qwen3:14b", timeout=600)

        _, message, _, _ = forge.format_prompt("test prompt")

        assert "qwen3:14b" in message
        assert "600" in message
        assert "joignable" in message.lower()

    def test_timeout_message_offers_both_levers(self, forge):
        forge.ollama = self.TimingOutProvider()

        _, message, _, _ = forge.format_prompt("test prompt")

        assert "OLLAMA_TIMEOUT" in message
        assert "OLLAMA_MODEL" in message

    def test_timeout_is_distinguishable_from_ollama_absent(self, forge, mock_ollama_unavailable):
        """Mutant vise : servir le meme message pour les deux conditions.

        Si les deux messages se confondent, l'utilisateur dont le modele est
        simplement lent ira relancer `ollama serve` pour rien.
        """
        forge.ollama = mock_ollama_unavailable
        _, absent_message, _, _ = forge.format_prompt("test prompt")

        forge.ollama = self.TimingOutProvider()
        _, timeout_message, _, _ = forge.format_prompt("test prompt")

        assert timeout_message != absent_message
        assert "n'est pas disponible" in absent_message
        assert "n'est pas disponible" not in timeout_message

    def test_timeout_is_distinguishable_from_a_network_failure(self, forge):
        """Mutant vise : confondre depassement de delai et erreur reseau.

        Un echec reseau fait rendre None a `generate()` et aboutit au message
        generique ; un depassement de delai doit dire autre chose.
        """
        network_failure = self.TimingOutProvider()
        network_failure.generate = lambda *a, **k: None
        forge.ollama = network_failure
        _, network_message, _, _ = forge.format_prompt("test prompt")

        forge.ollama = self.TimingOutProvider()
        _, timeout_message, _, _ = forge.format_prompt("test prompt")

        assert timeout_message != network_message
        assert "Erreur lors du reformatage" in network_message
        assert "delai" in timeout_message.lower()

    def test_timeout_saves_nothing(self, forge, sample_config_file):
        """Lecon D-054 : le message affirme « rien n'a ete sauvegarde ».

        Ce test verifie que l'affirmation est vraie, dans les deux lieux de
        stockage : la base SQLite et les fichiers Markdown d'historique.
        """
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = self.TimingOutProvider()

        success, message, _, _ = forge.format_prompt("test prompt")

        assert success is False
        assert "rien n'a ete sauvegarde" in message.lower()
        assert forge.get_history() == []
        assert list((Path(forge.base_path) / "history").glob("*.md")) == []

    def test_security_context_survives_the_timeout(self, forge, sample_config_file):
        """L'analyse de securite deja payee n'est pas jetee avec l'erreur."""
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = self.TimingOutProvider()

        _, _, _, security_ctx = forge.format_prompt(
            "ajouter une authentification", check_security=True
        )

        assert isinstance(security_ctx, SecurityContext)


class TestFormatPromptMissingModel:
    """Un modele non installe produit un message qui dit quoi faire."""

    class MissingModelProvider:
        def __init__(self, model="absent:1b"):
            self.config = MagicMock(model=model, timeout=600)
            self._model = model

        def is_available(self):
            return True

        def list_models(self):
            return []

        def generate(self, prompt, system_prompt="", num_ctx=16384):
            raise OllamaModelNotFoundError(self._model)

    def test_missing_model_is_a_failure_with_the_install_command(self, forge):
        forge.ollama = self.MissingModelProvider()

        success, message, formatted, _ = forge.format_prompt("test prompt")

        assert success is False
        assert formatted is None
        assert "absent:1b" in message
        assert "ollama pull absent:1b" in message

    def test_missing_model_saves_nothing(self, forge, sample_config_file):
        forge.init_project("test", sample_config_file)
        forge.use_project("test")
        forge.ollama = self.MissingModelProvider()

        forge.format_prompt("test prompt")

        assert forge.get_history() == []
