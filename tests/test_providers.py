"""
Tests pour le module providers (Ollama).
"""

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from promptforge.providers import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT,
    OLLAMA_TIMEOUT_ENV_VAR,
    REFORMAT_SYSTEM_PROMPT,
    OllamaConfig,
    OllamaError,
    OllamaModelNotFoundError,
    OllamaProvider,
    OllamaTimeoutError,
    build_timeout_message,
    format_prompt_with_ollama,
    get_default_ollama_timeout,
)


class TestOllamaConfig:
    """Tests pour OllamaConfig."""

    def test_default_values(self, monkeypatch):
        """Test des valeurs par défaut.

        `OLLAMA_TIMEOUT` est retiree de l'environnement : sans cela le verdict
        dependrait du shell qui lance la suite, pas du code.
        """
        monkeypatch.delenv(OLLAMA_TIMEOUT_ENV_VAR, raising=False)
        config = OllamaConfig()

        # L'URL peut varier selon l'environnement (WSL vs normal)
        assert "11434" in config.base_url
        assert config.model == DEFAULT_OLLAMA_MODEL == "qwen3:8b"
        assert config.timeout == DEFAULT_OLLAMA_TIMEOUT

    def test_custom_values(self):
        """Test des valeurs personnalisées."""
        config = OllamaConfig(base_url="http://custom:8080", model="mistral", timeout=60)

        assert config.base_url == "http://custom:8080"
        assert config.model == "mistral"
        assert config.timeout == 60


class TestOllamaProvider:
    """Tests pour OllamaProvider."""

    def test_init_default_config(self):
        """Test de l'initialisation avec config par défaut."""
        provider = OllamaProvider()

        assert provider.config.base_url == "http://localhost:11434"
        assert provider.config.model == DEFAULT_OLLAMA_MODEL

    def test_init_custom_config(self):
        """Test de l'initialisation avec config personnalisée."""
        config = OllamaConfig(model="mistral")
        provider = OllamaProvider(config)

        assert provider.config.model == "mistral"

    @patch("urllib.request.urlopen")
    def test_is_available_success(self, mock_urlopen):
        """Test de disponibilité quand Ollama répond."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        provider = OllamaProvider()
        assert provider.is_available()

    @patch("urllib.request.urlopen")
    def test_is_available_failure(self, mock_urlopen):
        """Test de disponibilité quand Ollama ne répond pas."""
        mock_urlopen.side_effect = URLError("Connection refused")

        provider = OllamaProvider()
        assert not provider.is_available()

    @patch("urllib.request.urlopen")
    def test_list_models_success(self, mock_urlopen):
        """Test de la liste des modèles."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"models": [{"name": "llama3.1:latest"}, {"name": "mistral:latest"}]}
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        provider = OllamaProvider()
        models = provider.list_models()

        assert len(models) == 2
        assert "llama3.1:latest" in models
        assert "mistral:latest" in models

    @patch("urllib.request.urlopen")
    def test_list_models_failure(self, mock_urlopen):
        """Test de la liste des modèles en cas d'erreur."""
        mock_urlopen.side_effect = URLError("Connection refused")

        provider = OllamaProvider()
        models = provider.list_models()

        assert models == []

    @patch("urllib.request.urlopen")
    def test_generate_success(self, mock_urlopen):
        """Test de génération de texte."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"response": "Generated text response"}
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        provider = OllamaProvider()
        result = provider.generate("Test prompt", "System prompt")

        assert result == "Generated text response"

        # Vérifier l'appel
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        assert request.full_url == "http://localhost:11434/api/generate"

        # Vérifier le payload
        payload = json.loads(request.data.decode())
        assert payload["model"] == DEFAULT_OLLAMA_MODEL
        assert payload["prompt"] == "Test prompt"
        assert payload["system"] == "System prompt"

    @patch("urllib.request.urlopen")
    def test_generate_failure(self, mock_urlopen):
        """Test de génération en cas d'erreur."""
        mock_urlopen.side_effect = URLError("Connection refused")

        provider = OllamaProvider()
        result = provider.generate("Test prompt")

        assert result is None


class TestFormatPromptWithOllama:
    """Tests pour la fonction format_prompt_with_ollama."""

    def test_format_with_available_provider(self, mock_ollama_available, sample_config_content):
        """Le contenu produit par le modele survit au reformatage, section par section.

        F-006 / D-005 : ce test porte sur le CONTENU du prompt reformate, jamais
        sur la syntaxe qui l'entoure. Aujourd'hui `format_prompt_with_ollama`
        reecrit en XML la sortie Markdown du modele (providers.py:498-499), donc
        le libelle `## Contexte` de la reponse simulee devient `<context>` ;
        DEC-007 §1 supprime cette reecriture (R-009) et le libelle Markdown
        reapparaitra. Les fragments verifies ci-dessous sont ceux qui survivent
        aux deux comportements, un par section de `mock_ollama_response`, ce qui
        prouve en prime qu'aucune section n'est perdue en chemin. L'assertion sur
        le format de sortie appartient a R-009, pas a ce test.
        """
        result = format_prompt_with_ollama(
            raw_prompt="create user route",
            project_context=sample_config_content,
            provider=mock_ollama_available,
        )

        assert result is not None
        # Section "Contexte" de la reponse simulee
        assert "Projet: Test Project" in result
        assert "Stack: Python 3.12, FastAPI, PostgreSQL" in result
        # Section "Demande"
        assert "Créer une route API pour la gestion des utilisateurs" in result
        # Section "Spécifications"
        assert "Endpoint REST: /api/v1/users" in result
        # Section "Contraintes"
        assert "Respecter la structure src/api/" in result

    def test_format_with_unavailable_provider(self, mock_ollama_unavailable, sample_config_content):
        """Test du formatage avec provider indisponible."""
        result = format_prompt_with_ollama(
            raw_prompt="create user route",
            project_context=sample_config_content,
            provider=mock_ollama_unavailable,
        )

        assert result is None

    def test_system_prompt_exists(self):
        """Vérifie que le system prompt est bien défini."""
        assert REFORMAT_SYSTEM_PROMPT is not None
        assert len(REFORMAT_SYSTEM_PROMPT) > 100
        # Vérifie que le prompt contient des mots-clés attendus
        prompt_lower = REFORMAT_SYSTEM_PROMPT.lower()
        assert "xml" in prompt_lower or "prompt" in prompt_lower or "réécris" in prompt_lower


class TestDeadCodeRemoved:
    """`ensure_xml_format()` est supprimée : aucun appelant (D-055, F-028).

    Septième fonction morte du dépôt, découverte après la rédaction de la
    roadmap qui n'en dénombrait que six. Elle n'était appelée ni par
    `promptforge/`, ni par `tests/`, et n'apparaissait ni dans `__all__` ni
    dans `CLAUDE.md`. Les deux fonctions dont elle n'était qu'un aiguillage,
    `is_markdown_format()` et `convert_markdown_to_xml()`, restent vivantes :
    `format_prompt_with_ollama()` les appelle directement.
    """

    def test_ensure_xml_format_is_gone(self):
        import promptforge.providers as providers

        assert not hasattr(providers, "ensure_xml_format")

    def test_the_two_live_helpers_it_wrapped_are_still_there(self):
        import promptforge.providers as providers

        assert hasattr(providers, "is_markdown_format")
        assert hasattr(providers, "convert_markdown_to_xml")


# =============================================================================
# DEPASSEMENT DE DELAI OLLAMA (F-032)
#
# Avant F-032, `TimeoutError` derivait d'`OSError` et d'aucune des trois
# exceptions rattrapees par `generate()` : il remontait brut jusqu'a
# l'interface. Reproduction avant correction, contre un serveur local qui ne
# repond jamais :
#     generate:    EXCEPTION NON RATTRAPEE builtins.TimeoutError -> timed out
#     list_models: EXCEPTION NON RATTRAPEE builtins.TimeoutError -> timed out
#     is_available: RETOURNE False
#
# Les tests ci-dessous portent sur le CONTRAT (quelle condition est rendue, et
# avec quel message actionnable), pas sur la simple presence d'un try/except :
# un `except TimeoutError: return None` les laisserait rouges.
# =============================================================================


@pytest.fixture
def dead_server():
    """Socket qui accepte la connexion TCP et ne repond jamais.

    Permet d'exercer le VRAI chemin de depassement de delai d'urllib (socket,
    `http.client`, `urlopen(timeout=...)`) sans qu'Ollama soit installe : ce
    test reste vert sur une machine sans Ollama, contrairement aux dix-sept
    tests de `test_ollama_integration.py`.

    Un `socket.listen()` jamais suivi d'`accept()` suffit : le noyau termine la
    poignee de main TCP, le client emet sa requete puis attend une reponse qui
    ne viendra pas. Aucun fil d'execution, donc une fermeture instantanee — un
    `HTTPServer` dont le gestionnaire dort aurait bloque le demontage aussi
    longtemps que le sommeil.
    """
    import socket

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        listener.close()


class TestOllamaTimeoutType:
    """Le type d'exception et sa compatibilite ascendante."""

    def test_timeout_error_is_an_ollama_error(self):
        assert issubclass(OllamaTimeoutError, OllamaError)

    def test_timeout_error_stays_a_timeout_error(self):
        """Compatibilite : avant F-032 un `TimeoutError` brut remontait.

        Un appelant qui s'en protegeait deja par `except TimeoutError` ou
        `except OSError` ne doit pas casser.
        """
        exc = OllamaTimeoutError("qwen3:14b", 600)
        assert isinstance(exc, TimeoutError)
        assert isinstance(exc, OSError)

    def test_timeout_error_carries_model_and_timeout(self):
        exc = OllamaTimeoutError("qwen3:14b", 600)
        assert exc.model == "qwen3:14b"
        assert exc.timeout == 600


class TestTimeoutMessage:
    """Le message rendu a l'utilisateur, sur le fond."""

    def test_message_names_the_model_and_the_elapsed_budget(self):
        message = build_timeout_message("qwen3:14b", 600)
        assert "qwen3:14b" in message
        assert "600" in message

    def test_message_says_the_service_is_up_not_down(self):
        """Exigence explicite : l'utilisateur ne doit pas croire qu'Ollama est tombe."""
        message = build_timeout_message("qwen3:14b", 600).lower()
        assert "joignable" in message

    def test_message_states_nothing_was_saved(self):
        """Lecon D-054 : ne jamais laisser croire a une sauvegarde inexistante."""
        message = build_timeout_message("qwen3:14b", 600).lower()
        assert "rien n'a ete sauvegarde" in message

    def test_message_gives_the_two_actionable_levers(self):
        """Allonger le delai, ou prendre un modele plus leger."""
        message = build_timeout_message("qwen3:14b", 600)
        assert OLLAMA_TIMEOUT_ENV_VAR in message
        assert "OLLAMA_MODEL" in message
        # Le levier « allonger » propose une valeur concrete, pas une consigne vague
        assert "1200" in message

    def test_message_is_not_confusable_with_a_network_failure(self):
        """Mutant vise : rendre le meme message pour un timeout et un echec reseau.

        Le message de depassement de delai doit parler de duree, et ne doit pas
        se resumer au vocabulaire d'indisponibilite employe ailleurs.
        """
        message = build_timeout_message("qwen3:14b", 600).lower()
        assert "delai" in message
        assert "injoignable" not in message
        assert "n'est pas disponible" not in message


class TestGenerateTimeout:
    """`generate()` face au depassement de delai."""

    @patch("urllib.request.urlopen")
    def test_read_timeout_raises_typed_error(self, mock_urlopen):
        """Depassement a la LECTURE : urllib remonte un `TimeoutError` nu."""
        mock_urlopen.side_effect = TimeoutError("timed out")

        provider = OllamaProvider(OllamaConfig(model="qwen3:14b", timeout=42))

        with pytest.raises(OllamaTimeoutError) as excinfo:
            provider.generate("Test prompt")

        assert excinfo.value.model == "qwen3:14b"
        assert excinfo.value.timeout == 42

    @patch("urllib.request.urlopen")
    def test_connect_timeout_wrapped_in_urlerror_raises_typed_error(self, mock_urlopen):
        """Depassement a la CONNEXION : urllib l'emballe dans URLError.

        Sans l'inspection de `URLError.reason`, ce cas retomberait sur le
        message generique « Ollama injoignable » et l'utilisateur croirait le
        service tombe alors qu'il est seulement lent.
        """
        mock_urlopen.side_effect = URLError(TimeoutError("timed out"))

        provider = OllamaProvider(OllamaConfig(model="qwen3:8b", timeout=7))

        with pytest.raises(OllamaTimeoutError) as excinfo:
            provider.generate("Test prompt")

        assert excinfo.value.timeout == 7

    @patch("urllib.request.urlopen")
    def test_network_failure_still_returns_none(self, mock_urlopen):
        """Contrat inchange : un echec reseau reste un None, pas une exception."""
        mock_urlopen.side_effect = URLError("Connection refused")

        provider = OllamaProvider()
        assert provider.generate("Test prompt") is None

    @patch("urllib.request.urlopen")
    def test_http_error_still_returns_none(self, mock_urlopen):
        """Contrat inchange : une reponse HTTP en erreur reste un None."""
        mock_urlopen.side_effect = HTTPError(
            url="http://localhost:11434/api/generate",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=None,
        )

        provider = OllamaProvider()
        assert provider.generate("Test prompt") is None

    @patch("urllib.request.urlopen")
    def test_missing_model_raises_a_named_error(self, mock_urlopen):
        """Un 404 d'Ollama nomme le modele absent et dit comment l'installer."""
        mock_urlopen.side_effect = HTTPError(
            url="http://localhost:11434/api/generate",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

        provider = OllamaProvider(OllamaConfig(model="absent:1b"))
        with pytest.raises(OllamaModelNotFoundError) as exc_info:
            provider.generate("Test prompt")

        assert exc_info.value.model == "absent:1b"
        assert "ollama pull absent:1b" in str(exc_info.value)
        assert isinstance(exc_info.value, OllamaError)

    @patch("urllib.request.urlopen")
    def test_unreadable_response_still_returns_none(self, mock_urlopen):
        """Contrat inchange : un JSON illisible reste un None."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"pas du json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        provider = OllamaProvider()
        assert provider.generate("Test prompt") is None

    def test_real_socket_timeout_is_caught(self, dead_server):
        """Chemin reel de bout en bout, sans Ollama et sans mock.

        C'est le test qui reproduit le defaut signale par le dev : avant F-032
        il rendait `TimeoutError: timed out` non rattrape.
        """
        provider = OllamaProvider(OllamaConfig(base_url=dead_server, model="qwen3:14b", timeout=1))

        with pytest.raises(OllamaTimeoutError) as excinfo:
            provider.generate("Test prompt")

        assert "qwen3:14b" in str(excinfo.value)
        assert excinfo.value.timeout == 1

    def test_no_stdout_pollution_on_failure(self, capsys):
        """Une bibliotheque n'ecrit pas sur la sortie standard de qui l'importe.

        `providers.py` faisait `print(f"Erreur Ollama: {e}")`, ce qui polluait
        la sortie du CLI et de tout script important le module.
        """
        with patch("urllib.request.urlopen", side_effect=URLError("Connection refused")):
            OllamaProvider().generate("Test prompt")

        captured = capsys.readouterr()
        assert captured.out == ""


class TestListModelsTimeout:
    """`list_models()` avait la meme faille que `generate()`."""

    @patch("urllib.request.urlopen")
    def test_timeout_returns_empty_list(self, mock_urlopen):
        """Contrat de `list_models()` : la liste vide, jamais une exception nue."""
        mock_urlopen.side_effect = TimeoutError("timed out")

        assert OllamaProvider().list_models() == []

    @patch("urllib.request.urlopen")
    def test_connect_timeout_wrapped_in_urlerror_returns_empty_list(self, mock_urlopen):
        mock_urlopen.side_effect = URLError(TimeoutError("timed out"))

        assert OllamaProvider().list_models() == []

    @patch("urllib.request.urlopen")
    def test_is_available_still_false_on_timeout(self, mock_urlopen):
        """Non-regression : `is_available()` rattrapait deja le depassement.

        Simule plutot que joue sur socket reel : `is_available()` impose un
        budget fixe de 5 s et `list_models()` de 10 s, non reglables, qui
        auraient alourdi la suite de quinze secondes pour aucune information
        supplementaire. Le chemin socket reel reste couvert par
        `test_real_socket_timeout_is_caught`.
        """
        mock_urlopen.side_effect = TimeoutError("timed out")

        assert OllamaProvider().is_available() is False


class TestTimeoutConfiguration:
    """Le delai se regle par variable d'environnement, comme OLLAMA_HOST/MODEL."""

    def test_default_when_variable_absent(self, monkeypatch):
        monkeypatch.delenv(OLLAMA_TIMEOUT_ENV_VAR, raising=False)
        assert get_default_ollama_timeout() == DEFAULT_OLLAMA_TIMEOUT

    def test_default_covers_the_longest_generation_measured(self):
        """Le chiffre est fonde sur une mesure, pas choisi au hasard.

        Mesure de premiere main du 2026-09-07, `OllamaProvider.generate()` sur
        un prompt de reformatage realiste : `qwen3:14b` rend 83,34 s, 195,23 s
        et 98,20 s sur trois passages. Le passage a 195,23 s vaut 1,63 fois
        l'ancien defaut de 120 s, sans charge artificielle : cette valeur etait
        franchie par une generation nominale, et le reformatage etait perdu
        alors que le modele repondait. Le depot avait par ailleurs releve
        457,48 s en charge (D-073), que le nouveau defaut couvre aussi.
        """
        assert DEFAULT_OLLAMA_TIMEOUT >= 458
        assert DEFAULT_OLLAMA_TIMEOUT > 120

    def test_environment_variable_is_honoured(self, monkeypatch):
        monkeypatch.setenv(OLLAMA_TIMEOUT_ENV_VAR, "45")
        assert get_default_ollama_timeout() == 45

    def test_config_built_from_the_environment(self, monkeypatch):
        """Mutant vise : lire la variable puis ne pas la cabler sur OllamaConfig."""
        monkeypatch.setenv(OLLAMA_TIMEOUT_ENV_VAR, "45")
        assert OllamaConfig().timeout == 45

    def test_environment_variable_reaches_the_socket(self, monkeypatch):
        """Mutant vise : la variable est lue, mais `urlopen` recoit autre chose."""
        monkeypatch.setenv(OLLAMA_TIMEOUT_ENV_VAR, "33")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({"response": "ok"}).encode()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            OllamaProvider().generate("Test prompt")

        assert mock_urlopen.call_args.kwargs["timeout"] == 33

    def test_explicit_value_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv(OLLAMA_TIMEOUT_ENV_VAR, "45")
        assert OllamaConfig(timeout=10).timeout == 10

    @pytest.mark.parametrize("bad_value", ["", "   ", "abc", "60s", "12.5", "0", "-30"])
    def test_invalid_values_fall_back_without_crashing(self, monkeypatch, bad_value):
        """Cas limites : une variable mal remplie ne doit pas casser le demarrage.

        Un delai nul ou negatif est refuse : `urlopen(timeout=0)` ferait
        echouer chaque appel instantanement, ce qui serait pire que le defaut
        corrige ici.
        """
        monkeypatch.setenv(OLLAMA_TIMEOUT_ENV_VAR, bad_value)
        assert get_default_ollama_timeout() == DEFAULT_OLLAMA_TIMEOUT


class TestOllamaModelFromEnvironment:
    """Le modele par defaut suit OLLAMA_MODEL, pour la CLI comme pour le web."""

    def test_environment_variable_is_honoured(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "phi4-mini")
        assert OllamaConfig().model == "phi4-mini"

    def test_blank_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "   ")
        assert OllamaConfig().model == DEFAULT_OLLAMA_MODEL

    def test_explicit_value_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "phi4-mini")
        assert OllamaConfig(model="qwen3:14b").model == "qwen3:14b"


# =============================================================================
# POST-TRAITEMENT : LA SYNTAXE DU PROFIL EST PRESERVEE
# =============================================================================


class _CannedProvider:
    """Provider qui rend une sortie fixée, sans Ollama."""

    def __init__(self, output):
        self.output = output
        self.config = OllamaConfig(model="fake")
        self.calls = []

    def is_available(self):
        return True

    def generate(self, prompt, system_prompt="", num_ctx=16384):
        self.calls.append((prompt, system_prompt))
        return self.output


MARKDOWN_OUTPUT = (
    "## Objectif\nTrier une liste en Python.\n\n"
    "## Exigences\n- Montrer sorted()\n- Montrer .sort()\n\n"
    "## Format de sortie\nCode commenté."
)


class TestPostProcessingKeepsTheProfileSyntax:
    """Un profil GPT demande du Markdown : le convertir en XML le trahissait."""

    @pytest.mark.parametrize("profile", ["gpt_5.1", "gpt_5.6_terra", "gpt_5_pro"])
    def test_markdown_profiles_keep_markdown(self, profile):
        out, converted = format_prompt_with_ollama(
            "trie une liste",
            "",
            provider=_CannedProvider(MARKDOWN_OUTPUT),
            profile_name=profile,
            return_conversion_info=True,
        )
        assert converted is False
        assert out.startswith("## Objectif")
        assert "<task>" not in out

    @pytest.mark.parametrize("profile", ["claude_sonnet_5", "gemini_3.6_flash", None])
    def test_xml_profiles_still_convert_stray_markdown(self, profile):
        out, converted = format_prompt_with_ollama(
            "trie une liste",
            "",
            provider=_CannedProvider(MARKDOWN_OUTPUT),
            profile_name=profile,
            return_conversion_info=True,
        )
        assert converted is True
        assert "<task>" in out

    def test_universal_profile_keeps_whichever_convention_was_chosen(self):
        out, converted = format_prompt_with_ollama(
            "trie une liste",
            "",
            provider=_CannedProvider(MARKDOWN_OUTPUT),
            profile_name="universel",
            return_conversion_info=True,
        )
        assert converted is False
        assert out.startswith("## Objectif")

    def test_every_profile_declares_the_syntax_its_prompt_asks_for(self):
        from promptforge.profiles import (
            PRESET_PROFILES,
            SYNTAX_ANY,
            SYNTAX_MARKDOWN,
            SYNTAX_XML,
            SYSTEM_PROMPTS,
            TargetModel,
            get_expected_syntax,
        )

        for name, profile in PRESET_PROFILES.items():
            prompt = SYSTEM_PROMPTS[profile.target_model]
            syntax = get_expected_syntax(name)
            if profile.target_model is TargetModel.UNIVERSAL:
                assert syntax == SYNTAX_ANY
            elif "prompts Markdown" in prompt:
                assert syntax == SYNTAX_MARKDOWN, name
            else:
                assert syntax == SYNTAX_XML, name


class TestCleanModelOutput:
    """Ce qui n'est pas le prompt ne doit pas atteindre l'utilisateur."""

    def test_reasoning_block_is_removed(self):
        from promptforge.providers import clean_model_output

        out = clean_model_output(
            "<think>\nJe dois structurer.\n</think>\n<task>\nX\n</task>", "xml"
        )
        assert out == "<task>\nX\n</task>"

    def test_truncated_reasoning_yields_nothing(self):
        from promptforge.providers import clean_model_output

        assert clean_model_output("<think>\nJe réfléchis encore", "xml") == ""

    def test_wrapping_code_fence_is_removed(self):
        from promptforge.providers import clean_model_output

        assert clean_model_output("```xml\n<task>\nX\n</task>\n```", "xml") == "<task>\nX\n</task>"

    def test_announcement_line_is_removed(self):
        from promptforge.providers import clean_model_output

        out = clean_model_output("Voici le prompt reformaté :\n\n## Objectif\nX", "markdown")
        assert out == "## Objectif\nX"

    def test_short_wrapping_text_around_xml_is_removed(self):
        from promptforge.providers import clean_model_output

        out = clean_model_output(
            "Bien entendu, le prompt suit.\n<task>\nX\n</task>\nN'hésite pas si besoin !", "xml"
        )
        assert out == "<task>\nX\n</task>"

    def test_content_is_never_touched(self):
        """Une ligne de contenu qui commence par « Voici » n'est pas une annonce."""
        from promptforge.providers import clean_model_output

        text = "## Objectif\nVoici ce qu'il faut produire : une liste.\n## Format\nTexte."
        assert clean_model_output(text, "markdown") == text

    def test_empty_output_after_cleanup_is_reported_as_failure(self):
        out = format_prompt_with_ollama(
            "x", "", provider=_CannedProvider("<think>rien</think>"), profile_name="gpt_5.1"
        )
        assert out is None
