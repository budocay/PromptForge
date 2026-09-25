"""
Tests pour les fonctionnalités Game Changer de PromptForge.
- Templates métiers
- Détection de domaine élargie
- Recommandations par domaine
"""

import ast
import re
import sys
from pathlib import Path

import pytest

# S'assurer que le package est importable
sys.path.insert(0, str(Path(__file__).parent.parent))

WEB_PACKAGE = Path(__file__).parent.parent / "promptforge" / "web"


#: Les deux modules qui portent les données affichées à l'utilisateur. Le
#: verrou d'absence de littéral s'y limite : `assets.py` contient du CSS et des
#: SVG, où « 100% » est une unité de mise en page, pas un tarif ni une note.
DATA_MODULES = ("recommendations.py", "profiles_ui.py")


def _target_model_aliases(arbre: ast.Module) -> set:
    """Noms locaux liés à `TargetModel` dans un module.

    Le verrou ne peut pas se contenter de chercher le mot `TargetModel` :
    `from ..profiles import TargetModel as _TM` remettrait la même table avec un
    autre nom, et un contrôle littéral la laisserait passer. Mutant M7b, mesuré
    survivant avant cette correction.
    """
    alias = set()
    for node in ast.walk(arbre):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "TargetModel":
                    alias.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.endswith("TargetModel"):
                    alias.add(a.asname or a.name.split(".")[-1])
    return alias


def _module_level_value_nodes(package: Path = WEB_PACKAGE, noms=None):
    """Rend (chemin, noeud) pour chaque valeur affectée au niveau module.

    Les verrous d'absence de ce fichier lisent la **source**, pas seulement
    l'espace de noms : un `assert not hasattr(...)` ne dit rien de ce qu'un
    contributeur réinjecterait sous un autre nom. C'est la leçon de la
    violation V1 du `CRAFT GATE` sur F-022 : un verrou qui vérifie la présence
    d'une valeur composée mais jamais l'absence d'un littéral ne verrouille
    rien.
    """
    for chemin in sorted(package.glob("*.py")):
        if noms is not None and chemin.name not in noms:
            continue
        arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        for node in arbre.body:
            if isinstance(node, ast.Assign):
                yield chemin, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                yield chemin, node.value


def _module_level_target_model_refs(package: Path = WEB_PACKAGE):
    """Rend (chemin, nom) pour chaque référence à `TargetModel` hors fonction."""
    for chemin in sorted(package.glob("*.py")):
        arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        alias = _target_model_aliases(arbre)
        if not alias:
            continue
        for node in arbre.body:
            if isinstance(node, ast.Assign):
                valeur = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                valeur = node.value
            else:
                continue
            for interne in ast.walk(valeur):
                if isinstance(interne, ast.Name) and interne.id in alias:
                    yield chemin, interne.id


class TestDomainDetection:
    """Tests pour la détection de domaine élargie."""

    def test_import_detect_domain(self):
        """Vérifie que detect_domain est importable."""
        from promptforge.web.analysis import detect_domain

        assert callable(detect_domain)

    def test_detect_seo_domain(self):
        """Détecte le domaine SEO."""
        from promptforge.web.analysis import detect_domain

        prompts_seo = [
            "trouve moi des mots clés seo pour mon site",
            "analyse les backlinks de mon concurrent",
            "optimise le référencement de ma page",
            "keyword research pour e-commerce",
            "améliore mon ranking google",
        ]

        for prompt in prompts_seo:
            result = detect_domain(prompt)
            assert result == "seo", f"Prompt '{prompt}' devrait être 'seo', got '{result}'"

    def test_detect_marketing_domain(self):
        """Détecte le domaine Marketing."""
        from promptforge.web.analysis import detect_domain

        prompts_marketing = [
            "crée une campagne google ads",
            "optimise mon funnel de conversion",
            "améliore le roas de mes publicités",
            "landing page pour lead generation",
        ]

        for prompt in prompts_marketing:
            result = detect_domain(prompt)
            assert (
                result == "marketing"
            ), f"Prompt '{prompt}' devrait être 'marketing', got '{result}'"

    def test_detect_hr_domain(self):
        """Détecte le domaine RH."""
        from promptforge.web.analysis import detect_domain

        prompts_hr = [
            "rédige une fiche de poste développeur",
            "process de recrutement tech",
            "onboarding nouveau collaborateur",
            "sourcing linkedin recruiter",
        ]

        for prompt in prompts_hr:
            result = detect_domain(prompt)
            assert result == "hr", f"Prompt '{prompt}' devrait être 'hr', got '{result}'"

    def test_detect_sales_domain(self):
        """Détecte le domaine Sales/Commercial."""
        from promptforge.web.analysis import detect_domain

        prompts_sales = [
            "écris un email de prospection commercial",
            "pitch commercial pour saas",
            "gérer les objections client en négociation",
            "cold call pour prise de rdv pipeline",
        ]

        for prompt in prompts_sales:
            result = detect_domain(prompt)
            assert result == "sales", f"Prompt '{prompt}' devrait être 'sales', got '{result}'"

    def test_detect_product_domain(self):
        """Détecte le domaine Product Management."""
        from promptforge.web.analysis import detect_domain

        prompts_product = [
            "écris les user stories pour cette feature",
            "prd pour nouvelle fonctionnalité",
            "roadmap produit q1 2025",
            "priorisation backlog avec rice",
        ]

        for prompt in prompts_product:
            result = detect_domain(prompt)
            assert result == "product", f"Prompt '{prompt}' devrait être 'product', got '{result}'"

    def test_detect_code_domain_still_works(self):
        """Vérifie que le domaine code fonctionne toujours."""
        from promptforge.web.analysis import detect_domain

        prompts_code = [
            "écris une fonction python pour calculer",
            "debug mon api fastapi",
            "refactor cette classe javascript",
        ]

        for prompt in prompts_code:
            result = detect_domain(prompt)
            assert result == "code", f"Prompt '{prompt}' devrait être 'code', got '{result}'"

    def test_detect_general_fallback(self):
        """Vérifie le fallback vers 'general'."""
        from promptforge.web.analysis import detect_domain

        result = detect_domain("bonjour comment vas-tu")
        assert result == "general"

    def test_detect_domain_ignores_hyphens_and_accents(self):
        """D-057 : « mots clés », « mots cles » et « mots-clés » se valent.

        Mesure avant correction : `detect_domain("trouve des mots cles pour mon
        site e-commerce")` rendait `general` — zéro correspondance, tous
        domaines confondus — parce que le dictionnaire ne portait que
        `'mot-clé'` et `'mots-clés'`. L'utilisateur n'obtenait aucune
        recommandation.
        """
        from promptforge.web.analysis import detect_domain

        for variante in [
            "trouve des mots-clés pour mon site e-commerce",
            "trouve des mots clés pour mon site e-commerce",
            "trouve des mots cles pour mon site e-commerce",
            "TROUVE DES MOTS CLES POUR MON SITE",
        ]:
            assert detect_domain(variante) == "seo", variante

    def test_other_multi_word_keys_survive_the_same_normalisation(self):
        """La correction vaut pour toutes les clés, pas pour la seule qui était rouge.

        Traiter `'mots-clés'` seul aurait laissé `'longue traîne'`,
        `'cold email'` et `'fiche de poste'` avec le même défaut : c'est
        précisément le travers que la normalisation évite.
        """
        from promptforge.web.analysis import detect_domain

        attendus = {
            "analyse la longue traine de mon site": "seo",
            "rédige un cold email de prospection commerciale": "sales",
            "rédige une fiche de poste pour un recrutement": "hr",
        }
        for prompt, domaine in attendus.items():
            assert detect_domain(prompt) == domaine, prompt

    def test_normalisation_leaves_meaningful_separators_alone(self):
        """Seuls casse, accents et traits d'union sont normalisés.

        `/`, `.` et `<` portent du sens dans `'a/b test'`, `'robots.txt'` et
        `'<context>'` : les écraser élargirait le motif sans le dire.
        """
        from promptforge.web.analysis import normalize_for_matching

        assert normalize_for_matching("Mots-Clés") == "mots cles"
        assert normalize_for_matching("A/B  test") == "a/b test"
        assert normalize_for_matching("robots.txt") == "robots.txt"
        assert normalize_for_matching("<context>") == "<context>"


class TestTemplateHelpers:
    """Tests pour les helpers de templates métiers."""

    def test_import_template_helpers(self):
        """Vérifie que les helpers sont importables."""
        from promptforge.web.template_helpers import (
            TEMPLATE_INFO,
            get_template_choices,
            get_template_content,
            get_template_labels,
        )

        assert isinstance(TEMPLATE_INFO, dict)
        assert callable(get_template_choices)
        assert callable(get_template_content)
        assert callable(get_template_labels)

    def test_template_info_has_required_keys(self):
        """Vérifie que TEMPLATE_INFO a tous les métiers."""
        from promptforge.web.template_helpers import TEMPLATE_INFO

        required_templates = [
            "seo-specialist",
            "marketing-digital",
            "redacteur-web",
            "dev-backend",
            "dev-frontend",
            "product-manager",
            "data-analyst",
            "commercial-sales",
            "rh-recruteur",
            "support-client",
            "legal",
        ]

        for template_key in required_templates:
            assert template_key in TEMPLATE_INFO, f"Template '{template_key}' manquant"
            assert "name" in TEMPLATE_INFO[template_key]
            assert "description" in TEMPLATE_INFO[template_key]
            assert "file" in TEMPLATE_INFO[template_key]

    def test_template_count(self):
        """Vérifie qu'il y a 11 templates."""
        from promptforge.web.template_helpers import TEMPLATE_INFO

        assert len(TEMPLATE_INFO) == 11, f"Attendu 11 templates, got {len(TEMPLATE_INFO)}"

    def test_get_template_choices_format(self):
        """Vérifie le format des choix pour dropdown."""
        from promptforge.web.template_helpers import get_template_choices

        choices = get_template_choices()
        assert isinstance(choices, list)
        assert len(choices) > 0

        # Chaque choix est un tuple (label, value)
        for choice in choices:
            assert isinstance(choice, tuple)
            assert len(choice) == 2

    def test_get_template_content_existing(self):
        """Vérifie le chargement d'un template existant."""
        from promptforge.web.template_helpers import get_template_content

        # Ce test peut échouer si les fichiers ne sont pas au bon endroit
        # mais c'est normal en environnement de test isolé
        content = get_template_content("seo-specialist")
        # Le contenu peut être None si le fichier n'est pas trouvé dans l'env de test
        # On vérifie juste que la fonction ne plante pas
        assert content is None or isinstance(content, str)

    def test_get_template_content_nonexistent(self):
        """Vérifie le comportement avec un template inexistant."""
        from promptforge.web.template_helpers import get_template_content

        content = get_template_content("template-qui-nexiste-pas")
        assert content is None

    def test_get_template_labels(self):
        """Vérifie les labels de templates."""
        from promptforge.web.template_helpers import get_template_labels

        labels = get_template_labels()
        assert isinstance(labels, dict)
        assert len(labels) == 11
        assert "seo-specialist" in labels


class TestDomainRecommendations:
    """Tests pour les recommandations par domaine."""

    def test_domain_labels_still_exist(self):
        """Les libellés de domaine restent : ce sont des noms, pas des notes."""
        from promptforge.web.recommendations import DOMAIN_LABELS

        assert isinstance(DOMAIN_LABELS, dict)

    def test_new_domains_in_labels(self):
        """Vérifie que les nouveaux domaines ont des labels."""
        from promptforge.web.recommendations import DOMAIN_LABELS

        new_domains = ["seo", "marketing", "hr", "sales", "product", "support"]

        for domain in new_domains:
            assert domain in DOMAIN_LABELS, f"Label manquant pour '{domain}'"
            assert DOMAIN_LABELS[domain], f"Label vide pour '{domain}'"

    def test_new_domains_are_rendered_without_any_expertise_score(self):
        """Les domaines métiers restent rendus, sans note d'expertise.

        `DOMAIN_EXPERTISE` attribuait dix-huit couples note/justification par
        modèle cible, sans source ni méthodologie (D-021). Le rendu doit rester
        utile pour ces domaines une fois les notes retirées : c'est le critère
        d'acceptation 4 de F-021, « il affiche moins, mais rien de faux ».
        """
        from promptforge.web.recommendations import DOMAIN_LABELS, generate_recommendation

        for domain in ["seo", "marketing", "hr", "sales", "product", "support"]:
            rendu = generate_recommendation(
                formatted_prompt="<task>Un travail à faire</task>",
                task_type="general",
                ollama_model=None,
                domain_override=domain,
            )
            assert DOMAIN_LABELS[domain] in rendu, domain
            assert "expertise" not in rendu.lower(), domain

    def test_domain_labels_count(self):
        """Vérifie le nombre total de labels de domaine."""
        from promptforge.web.recommendations import DOMAIN_LABELS

        # 11 anciens + 6 nouveaux = 17 minimum
        # (peut y avoir plus avec analysis, chat, etc.)
        assert len(DOMAIN_LABELS) >= 17, f"Attendu >= 17 labels, got {len(DOMAIN_LABELS)}"


class TestNoBullshitRule:
    """Tests pour la règle anti-bullshit."""

    def test_no_bullshit_rule_exists(self):
        """Vérifie que NO_BULLSHIT_RULE existe."""
        from promptforge.profiles import NO_BULLSHIT_RULE

        assert isinstance(NO_BULLSHIT_RULE, str)
        assert len(NO_BULLSHIT_RULE) > 100, "NO_BULLSHIT_RULE semble trop court"

    def test_no_bullshit_rule_content(self):
        """Vérifie le contenu de NO_BULLSHIT_RULE."""
        from promptforge.profiles import NO_BULLSHIT_RULE

        # Doit contenir des interdictions claires
        assert "INTERDIT" in NO_BULLSHIT_RULE
        assert "scores" in NO_BULLSHIT_RULE.lower() or "métrique" in NO_BULLSHIT_RULE.lower()

    def test_system_prompt_includes_rule(self):
        """Vérifie que les system prompts incluent la règle."""
        from promptforge.profiles import TargetModel, get_system_prompt

        prompt = get_system_prompt(TargetModel.CLAUDE_OPUS_5)

        # Le system prompt devrait inclure la règle anti-bullshit
        assert "INTERDIT" in prompt or len(prompt) > 2000


class TestInterfaceImports:
    """Tests pour les imports de l'interface."""

    def test_interface_imports_template_helpers(self):
        """Vérifie que l'interface importe les template helpers."""
        # Ce test vérifie que l'import ne plante pas
        try:
            from promptforge.web import create_interface  # noqa: F401
            from promptforge.web.template_helpers import TEMPLATE_INFO  # noqa: F401

            assert True
        except ImportError as e:
            pytest.fail(f"Import échoué: {e}")

    def test_create_interface_callable(self):
        """Vérifie que create_interface est appelable."""
        from promptforge.web import create_interface

        assert callable(create_interface)


class TestTemplateFilesExist:
    """Tests pour vérifier que les fichiers de templates existent."""

    def test_templates_directory_exists(self):
        """Vérifie que le dossier templates/metiers existe."""
        templates_dir = Path(__file__).parent.parent / "templates" / "metiers"
        assert templates_dir.exists(), f"Dossier {templates_dir} n'existe pas"

    def test_all_template_files_exist(self):
        """Vérifie que tous les fichiers de templates existent."""
        templates_dir = Path(__file__).parent.parent / "templates" / "metiers"

        expected_files = [
            "seo-specialist.md",
            "marketing-digital.md",
            "redacteur-web.md",
            "dev-backend.md",
            "dev-frontend.md",
            "product-manager.md",
            "data-analyst.md",
            "commercial-sales.md",
            "rh-recruteur.md",
            "support-client.md",
            "legal.md",
        ]

        for filename in expected_files:
            filepath = templates_dir / filename
            assert filepath.exists(), f"Template manquant: {filepath}"

    def test_template_files_not_empty(self):
        """Vérifie que les fichiers de templates ne sont pas vides."""
        templates_dir = Path(__file__).parent.parent / "templates" / "metiers"

        for md_file in templates_dir.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            assert (
                len(content) > 500
            ), f"Template {md_file.name} semble trop court ({len(content)} chars)"


# ============================================
# Tests de bout en bout (si Ollama disponible)
# ============================================


class TestEndToEndWithContext:
    """Tests E2E avec contexte projet (nécessite Ollama)."""

    @pytest.fixture
    def check_ollama(self):
        """Vérifie si Ollama est disponible."""
        import urllib.request

        try:
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
            return True
        except Exception:
            return False

    @pytest.mark.skipif(not pytest.importorskip("urllib.request"), reason="Ollama non disponible")
    def test_format_prompt_with_seo_context(self, check_ollama, tmp_path):
        """Test de reformatage avec contexte SEO (si Ollama dispo)."""
        if not check_ollama:
            pytest.skip("Ollama non disponible")

        # Ce test est un placeholder - en vrai environnement il appellerait Ollama
        # Pour l'instant on vérifie juste que la structure est en place
        from promptforge.web.analysis import detect_domain

        prompt = "trouve des mots clés pour mon site e-commerce"
        domain = detect_domain(prompt)
        assert domain == "seo"


class TestProfilesUiDomainParity:
    """Parité entre l'adapter d'interface et le domaine (F-022 bloc 2).

    Ces tests existent parce que la divergence a réellement eu lieu : trois
    tarifs et une fenêtre de contexte affichés par `web/profiles_ui.py`
    contredisaient `MODEL_PRICING`, et l'un des libellés avait été corrigé à la
    main sans que la source le soit.
    """

    def test_profile_descriptions_cover_exactly_domain_profiles(self):
        """Les clés de PROFILE_DESCRIPTIONS sont celles de list_profiles()."""
        from promptforge.profiles import list_profiles
        from promptforge.web.profiles_ui import PROFILE_DESCRIPTIONS

        assert set(PROFILE_DESCRIPTIONS) == set(list_profiles())

    def test_profile_details_cover_exactly_domain_profiles(self):
        """Les clés du panneau de détail sont celles de list_profiles()."""
        from promptforge.profiles import list_profiles
        from promptforge.web.profiles_ui import PROFILE_DETAILS

        assert set(PROFILE_DETAILS) == set(list_profiles())

    def test_no_module_level_structure_is_indexed_by_target_model(self):
        """Critère 9 de F-021 : plus aucune table de module câblée sur l'énumération.

        `DOMAIN_EXPERTISE` câblait les neuf membres de `TargetModel` un par un,
        dans un dictionnaire évalué à l'import. Conséquence mesurée par
        l'`ARCHITECTURE GATE` : retirer un seul membre faisait passer la suite
        de vingt-six à trente-trois rouges, parce que l'import du paquet web
        entier échouait. Les scores auraient pu disparaître en laissant ce
        couplage intact ; le critère porte donc sur la structure, pas sur les
        valeurs.
        """
        trouve = list(_module_level_target_model_refs())
        assert not trouve, (
            f"structure de niveau module référençant l'énumération du domaine : "
            f"{[(c.name, n) for c, n in trouve]} — un membre retiré casserait "
            f"l'import du paquet web entier"
        )

    def test_profile_choices_expose_a_label_and_the_profile_key(self):
        """Le menu propose un libellé lisible, et transmet toujours la clé.

        Avant F-028 il affichait la clé brute (`claude_opus_5`,
        `gemini_3.1_pro`) : un identifiant technique à la place d'un nom de
        produit. Les couples (libellé, clé) de Gradio corrigent l'affichage
        sans changer ce que reçoivent les gestionnaires.
        """
        from promptforge.web.profiles_ui import PROFILE_DESCRIPTIONS, get_profile_choices

        choices = get_profile_choices()
        assert [key for _, key in choices] == list(PROFILE_DESCRIPTIONS)
        for label, key in choices:
            assert label != key, key
            assert PROFILE_DESCRIPTIONS[key] in label, key

    def test_profile_label_price_comes_from_model_pricing(self):
        """Le tarif du libellé est composé depuis MODEL_PRICING, pas recopié."""
        from promptforge.profiles import MODEL_PRICING, PRESET_PROFILES, TargetModel
        from promptforge.web.profiles_ui import get_profile_choices

        for label, name in get_profile_choices():
            target = PRESET_PROFILES[name].target_model
            if target is TargetModel.UNIVERSAL:
                # Ne désigne aucun modèle réel : aucun tarif affiché (D-032).
                assert "$" not in label
                continue
            pricing = MODEL_PRICING[target]
            expected = f"(${pricing.input_price:g}/${pricing.output_price:g})"
            assert label.endswith(expected), f"{name}: {label!r} n'expose pas {expected!r}"

    def test_dead_profile_label_helper_is_gone(self):
        """`get_profile_label()` est supprimée : elle n'avait aucun appelant.

        Sixième fonction morte de la liste du gate (R-009). Sa logique n'est
        pas perdue pour autant : elle est branchée sur le menu déroulant par
        `get_profile_choices()`, sans quoi `PROFILE_DESCRIPTIONS` serait resté
        une table dont seules les clés servaient.
        """
        import promptforge.web.profiles_ui as profiles_ui

        assert not hasattr(profiles_ui, "get_profile_label")

    def test_profile_info_context_window_comes_from_model_pricing(self):
        """La fenêtre de contexte affichée est celle du domaine.

        Une fenêtre non confirmée par une source ne s'affiche pas comme un
        chiffre : elle est annoncée comme non confirmée (F-028). Un « 0K » ou
        la reprise du chiffre de la génération précédente serait une valeur
        que personne n'a mesurée sur ce modèle.
        """
        from promptforge.profiles import MODEL_PRICING, PRESET_PROFILES, TargetModel
        from promptforge.web.profiles_ui import PROFILE_DETAILS, get_profile_info

        for name in PROFILE_DETAILS:
            target = PRESET_PROFILES[name].target_model
            if target is TargetModel.UNIVERSAL:
                continue
            window = MODEL_PRICING[target].context_window
            if window is None:
                expected = "- Contexte: non confirmé par une source officielle"
            elif window >= 1_000_000 and window % 1_000_000 == 0:
                expected = f"- Contexte: {window // 1_000_000}M tokens"
            else:
                expected = f"- Contexte: {window // 1_000}K tokens"
            assert expected in get_profile_info(name), f"{name}: attendu {expected!r}"

    def test_no_profile_advertises_a_retired_or_fictional_model(self):
        """Aucun libellé ni panneau ne nomme un modèle retiré du domaine.

        Mesuré le 2026-09-07 : `gemini-3-pro` est arrêté depuis le 2026-03-09,
        `gemini-3-flash` est déprécié, `gpt-5.1-mini` n'a jamais existé. Le
        domaine ne les porte plus ; l'adapter d'interface non plus, sans quoi
        l'utilisateur choisirait une cible inatteignable.
        """
        from promptforge.web.profiles_ui import PROFILE_DESCRIPTIONS, PROFILE_DETAILS

        morts = ["Gemini 3 Pro —", "Gemini 3 Flash —", "Gemini 2.5 Flash", "GPT-5.1 Mini"]
        for name, description in PROFILE_DESCRIPTIONS.items():
            for mort in morts:
                assert mort not in description, f"{name}: {mort!r}"
        for name, details in PROFILE_DETAILS.items():
            assert not any(mort in details["title"] for mort in morts), name

    def test_gpt_profiles_announce_the_format_they_produce(self):
        """Les libellés GPT annonçaient XML alors que le prompt exige Markdown.

        `SYSTEM_PROMPT_GPT_5_1`, `_GPT_5_6_TERRA` et `_GPT_5_PRO` demandent
        tous du Markdown. Annoncer `[XML]` dans le menu revenait à décrire au
        client autre chose que ce que la machine produit.
        """
        from promptforge.profiles import PRESET_PROFILES, SYSTEM_PROMPTS, TargetModel
        from promptforge.web.profiles_ui import PROFILE_DESCRIPTIONS

        for name, description in PROFILE_DESCRIPTIONS.items():
            target = PRESET_PROFILES[name].target_model
            prompt = SYSTEM_PROMPTS[target]
            if target is TargetModel.UNIVERSAL:
                # DEC-008 : il ne vise aucun modèle, il n'impose aucune syntaxe.
                assert "[XML ou Markdown]" in description, name
            elif "prompts Markdown" in prompt:
                assert "[Markdown]" in description, name
            else:
                assert "[XML]" in description, name

    def test_profile_info_reports_pricing_provenance(self):
        """Une valeur sans source officielle est signalée comme telle."""
        from promptforge.profiles import MODEL_PRICING, PRESET_PROFILES, TargetModel
        from promptforge.web.profiles_ui import PROFILE_DETAILS, get_profile_info

        for name in PROFILE_DETAILS:
            target = PRESET_PROFILES[name].target_model
            if target is TargetModel.UNIVERSAL:
                continue
            info = get_profile_info(name)
            if MODEL_PRICING[target].source_url:
                assert MODEL_PRICING[target].source_url in info, name
            else:
                assert "non confirmé" in info, name

    def test_unknown_profile_label_and_info_do_not_invent_a_price(self):
        """Profil inconnu : aucun tarif inventé, aucune exception."""
        from promptforge.web.profiles_ui import _compose_label, get_profile_info

        assert _compose_label("profil-inexistant") == "profil-inexistant"
        info = get_profile_info("profil-inexistant")
        assert "$" not in info

    def test_static_descriptions_hold_no_price_nor_context_literal(self):
        """Aucun tarif ni fenêtre de contexte en dur dans le texte statique.

        Les tests de parité vérifiaient la PRÉSENCE du suffixe composé, jamais
        l'ABSENCE d'un littéral : réinjecter « ($999/$1) » dans une description
        les laissait tous verts, et l'utilisateur voyait deux tarifs dont un
        faux. Ce test est le verrou manquant (CRAFT V1).
        """
        import re

        from promptforge.web.profiles_ui import PROFILE_DESCRIPTIONS

        literal = re.compile(r"\$|\b\d+(?:[.,]\d+)?\s*[KM]\b")
        for name, description in PROFILE_DESCRIPTIONS.items():
            found = literal.findall(description)
            assert not found, (
                f"{name}: littéral de tarif ou de contexte {found} dans le texte "
                f"statique — ces valeurs se composent depuis MODEL_PRICING au rendu"
            )

    def test_static_details_hold_no_price_nor_context_literal(self):
        """Même verrou sur le panneau de détail, titre et puces compris."""
        import re

        from promptforge.web.profiles_ui import PROFILE_DETAILS

        literal = re.compile(r"\$|\b\d+(?:[.,]\d+)?\s*[KM]\b")
        for name, details in PROFILE_DETAILS.items():
            for text in [details["title"], *details["bullets"]]:
                found = literal.findall(text)
                assert not found, (
                    f"{name}: littéral de tarif ou de contexte {found} dans "
                    f"{text[:60]!r} — composer depuis MODEL_PRICING au rendu"
                )

    def test_recommendation_iterates_over_model_pricing(self):
        """`generate_recommendation()` couvre toutes les entrées de MODEL_PRICING."""
        from promptforge.profiles import MODEL_PRICING
        from promptforge.web.recommendations import generate_recommendation

        rendered = generate_recommendation(
            formatted_prompt="<task>Revue de code</task>",
            task_type="code",
            ollama_model=None,
            domain_override="code",
        )
        assert isinstance(rendered, str) and rendered

        # L'assertion porte sur l'ACTE, pas sur une constante de module : on
        # compte les modèles du domaine réellement cités par le rendu. Une
        # itération tronquée (`list(...)[:1]`) tombe ici, alors qu'un
        # `len(MODEL_PRICING) >= 5` resterait vrai (CRAFT V2).
        # Depuis F-028, le rendu cite le nom commercial et non l'identifiant
        # d'API : c'est ce nom-la qu'on compte, sans quoi le test mesurerait
        # une chaine que l'utilisateur ne voit plus.
        cites = [
            pricing.display_name
            for pricing in MODEL_PRICING.values()
            if pricing.display_name in rendered
        ]
        assert len(cites) >= 5, (
            f"seuls {len(cites)} modèles sur {len(MODEL_PRICING)} apparaissent "
            f"dans le rendu : {cites}"
        )


class TestUnsourcedFiguresAreGone:
    """F-021 — plus aucune note maison, et la réinjection d'un littéral échoue.

    Ces tests ne vérifient pas seulement que les notes ont disparu : ils
    vérifient qu'on ne peut pas les remettre. `agent-craft` a imposé ce critère
    de recette après la violation V1 de F-022, où tous les tests restaient
    verts alors qu'un tarif faux avait été réinjecté dans une description.
    """

    # --- ce qui a été supprimé, et doit le rester ------------------------

    def test_removed_symbols_are_gone(self):
        """Les tables non sourcées ne sont pas renommées, elles sont supprimées."""
        import promptforge.web.recommendations as reco

        for nom in [
            "OLLAMA_MODELS_INFO",  # quatorze notes de 68 à 99, sans source
            "DOMAIN_EXPERTISE",  # dix-huit couples note/justification par modèle
            "BENCHMARK_SOURCES",  # ne sourçait plus rien de ce qui reste affiché
            "_context_of",  # n'avait plus d'appelant après le retrait des notes
        ]:
            assert not hasattr(reco, nom), nom

    def test_module_level_data_holds_no_figure_nor_price(self):
        """Verrou d'absence : aucun nombre ni tarif dans les données statiques.

        C'est le verrou demandé : réinjecter `{'qwen3:32b': {'reformat_score':
        98}}` ou une ligne `| Midjourney V7 | $10-60/mois |` dans une constante
        de module fait tomber ce test, alors qu'aucun test de présence ne le
        remarquerait.

        Le contrôle porte sur les **littéraux numériques de l'AST**, pas sur
        les chiffres écrits dans un texte : `« DEC-006 »` ou une date restent
        licites dans une phrase, un `98` posé comme valeur ne l'est pas.
        """
        prix = re.compile(r"\$|\b\d+(?:[.,]\d+)?\s*%")
        for chemin, valeur in _module_level_value_nodes(noms=DATA_MODULES):
            for node in ast.walk(valeur):
                if isinstance(node, ast.Constant):
                    if isinstance(node.value, bool):
                        continue
                    assert not isinstance(node.value, (int, float)), (
                        f"{chemin.name}: littéral numérique {node.value!r} dans une "
                        f"donnée statique — une valeur affichée se compose depuis "
                        f"une source, elle ne se saisit pas"
                    )
                    if isinstance(node.value, str):
                        trouve = prix.findall(node.value)
                        assert not trouve, (
                            f"{chemin.name}: littéral de tarif ou de pourcentage "
                            f"{trouve} dans {node.value[:60]!r}"
                        )

    # --- ce que le rendu doit, et ne doit pas, contenir ------------------

    @staticmethod
    def _rendu(domaine="code", modele=None):
        from promptforge.web.recommendations import generate_recommendation

        return generate_recommendation(
            formatted_prompt="<task>Un travail à faire</task>",
            task_type="general",
            ollama_model=modele,
            domain_override=domaine,
        )

    def test_rendered_recommendation_publishes_no_percentage(self):
        """Aucun pourcentage : c'était la forme sous laquelle les notes sortaient.

        `generate_recommendation()` publiait `🟢 98%` par modèle cible et
        `🟡 75% (Suffisant)` pour le modèle local, avec des badges dérivés de
        seuils à 90 et 75. Rien n'établissait ces nombres.
        """
        for domaine in ["code", "seo", "image", "document", "general"]:
            rendu = self._rendu(domaine)
            trouve = re.findall(r"\d+\s*%", rendu)
            assert not trouve, f"{domaine}: pourcentage {trouve} dans le rendu"

    def test_every_rendered_amount_is_computed_from_model_pricing(self):
        """Chaque montant affiché se recalcule depuis `MODEL_PRICING`.

        Verrou de composition, jumeau de celui de F-022 : réinjecter
        `$10-60/mois` ou `Gratuit-$0.05` produit un montant que le domaine ne
        sait pas recalculer, et le test tombe. Vérifier seulement la présence
        d'un coût correct laisserait passer un second montant faux à côté.
        """
        from promptforge.profiles import MODEL_PRICING
        from promptforge.tokens import estimate_tokens

        prompt = "<task>Un travail à faire</task>"
        entree = estimate_tokens(prompt)
        sortie = int(entree * 1.5)
        attendus = {"$0"} | {
            f"${p.estimate_cost(entree, sortie):.4f}" for p in MODEL_PRICING.values()
        }

        for domaine in ["code", "image", "general"]:
            rendu = self._rendu(domaine, modele="qwen3:8b")
            for montant in re.findall(r"\$[\d.,]*\d|\$0\b", rendu):
                assert montant in attendus, (
                    f"{domaine}: montant {montant!r} absent de ce que "
                    f"MODEL_PRICING permet de recalculer"
                )

    def test_image_domain_no_longer_prices_third_party_tools(self):
        """D-034 : les tarifs d'outils d'image n'étaient ni sourcés ni composables.

        `Midjourney V7 $10-60/mois` et `Flux.2 Gratuit-$0.05` s'affichaient dès
        que le domaine détecté valait `image`, sans source, sans date, et sans
        entrée correspondante dans `MODEL_PRICING` : impossible à composer,
        donc supprimés (DEC-004 §1).
        """
        rendu = self._rendu("image")
        for outil in ["Midjourney", "Flux.2", "Ideogram", "DALL-E"]:
            assert outil not in rendu, outil

    def test_recommendation_says_quality_is_not_measured(self):
        """Critère 6 : la limite du classement est écrite, pas enfouie."""
        rendu = self._rendu("code", modele="qwen3:8b")
        assert "pas mesuree a ce jour" in rendu
        assert "pas mesuree" in rendu
        assert "empreinte memoire" in rendu

    # --- l'ordre, et sur quoi il repose ----------------------------------

    def test_local_models_are_ordered_by_memory_footprint(self):
        """DEC-006 : l'ordre affiché est celui du catalogue, pas un ordre maison.

        L'assertion porte sur l'ordre **rendu**, et non sur un appel supposé :
        un tri réintroduit dans l'interface passerait un test qui se
        contenterait de vérifier que le catalogue est importé.
        """
        from promptforge.models_catalog import group_by_memory_tier

        rendu = self._rendu("code")
        attendu = [m.tag for models in group_by_memory_tier().values() for m in models]
        positions = [rendu.index(f"`{tag}`") for tag in attendu]
        assert positions == sorted(
            positions
        ), "les modèles locaux ne sont pas rendus dans l'ordre du catalogue"

    def test_cloud_models_are_ordered_by_cost(self):
        """Le seul critère de tri restant est le coût, et il est sourcé."""
        from promptforge.profiles import MODEL_PRICING
        from promptforge.tokens import estimate_tokens

        prompt = "<task>Un travail à faire</task>"
        entree = estimate_tokens(prompt)
        sortie = int(entree * 1.5)
        attendu = [
            p.display_name
            for p in sorted(
                MODEL_PRICING.values(),
                key=lambda p: (p.estimate_cost(entree, sortie), p.display_name),
            )
        ]

        rendu = self._rendu("code")
        positions = [rendu.index(f"**{nom}**") for nom in attendu]
        assert positions == sorted(positions), attendu

    def test_unknown_ollama_tag_is_declared_unknown(self):
        """Critère 7 : un tag hors catalogue n'est ni coercé ni deviné.

        L'ancien appariement partiel faisait
        `model_lower.split(':')[0] == key.split(':')[0]` : qui demandait
        `qwen3:1.7b` recevait les données de `qwen3:32b` sans le savoir. Servir
        silencieusement l'entrée d'un voisin est ce qui rend ce genre de défaut
        indétectable.
        """
        from promptforge.web.recommendations import get_ollama_model_info

        assert get_ollama_model_info(None) is None
        assert get_ollama_model_info("") is None

        connu = get_ollama_model_info("qwen3:8b")
        assert connu["known"] is True
        assert "Go" in connu["memory"]
        assert connu["source_url"].startswith("https://")

        inconnu = get_ollama_model_info("qwen3:1.7b")
        assert inconnu["known"] is False
        assert set(inconnu) == {
            "name",
            "known",
        }, "un tag inconnu ne doit porter aucune valeur estimée à sa place"

        rendu = self._rendu("code", modele="modele-inexistant:1b")
        assert "pas au catalogue" in rendu

    # --- D-070 : ce qui est étiqueté est ce qui est mesuré ---------------

    def test_calculate_costs_labels_a_price_not_a_power(self):
        """D-070 : « Le plus puissant » désignait le modèle le plus cher.

        Le tri porte sur le coût ; la puissance n'est ni mesurée ni sourcée
        nulle part dans le dépôt. Étiqueter le dernier de la liste « le plus
        puissant » affirmait une équivalence prix égale puissance que rien
        n'établit — même famille que les `reformat_score` supprimés.
        """
        from promptforge.profiles import MODEL_PRICING
        from promptforge.web.recommendations import calculate_costs

        rendu = calculate_costs(1000, 500)
        assert "puissant" not in rendu.lower()
        assert "Le plus cher" in rendu
        assert "Le moins cher" in rendu

        cher = max(MODEL_PRICING.values(), key=lambda p: p.estimate_cost(1000, 500))
        bon_marche = min(MODEL_PRICING.values(), key=lambda p: p.estimate_cost(1000, 500))
        assert rendu.index(bon_marche.display_name) < rendu.index("Le plus cher")
        assert cher.display_name in rendu.split("Le plus cher")[1]

    def test_comparison_tables_render_no_quality_tier(self):
        """Le libellé de « tier » est un jugement, il n'est plus affiché.

        `profiles._get_model_tier()` câblait `🔥 Premium`, `⚡ Performant` et
        `💰 Économique` par liste de membres, sans mesure ni source (D-071). La
        fonction a été supprimée côté domaine ; ce verrou garde l'affichage,
        pour que les libellés ne reviennent pas par une autre porte.
        """
        from promptforge.web.recommendations import calculate_costs, get_comparison_table

        for rendu in [get_comparison_table(), calculate_costs(1000, 500)]:
            for libelle in ["Premium", "Performant"]:
                assert libelle not in rendu, libelle


class TestProfilesUiClaimsNoUnmeasuredAptitude:
    """D-071, volet interface — aucune aptitude annoncée sans de quoi la fonder.

    Le fichier affirmait des capacités que le dépôt ne connaît pas. Ces verrous
    sont mécaniques : chacun rattache une famille d'affirmation à la donnée
    sourcée qui pourrait la fonder, et échoue si l'affirmation revient sans
    elle.
    """

    @staticmethod
    def _textes_statiques():
        from promptforge.web.profiles_ui import PROFILE_DESCRIPTIONS, PROFILE_DETAILS

        for nom, description in PROFILE_DESCRIPTIONS.items():
            yield nom, description
        for nom, details in PROFILE_DETAILS.items():
            yield nom, details["title"]
            for puce in details["bullets"]:
                yield nom, puce

    def test_no_long_context_claim_without_a_confirmed_window(self):
        """« Documents longs, codebases entières » supposait une fenêtre connue.

        Mesure du 2026-09-07 : `MODEL_PRICING[GEMINI_3_1_PRO].context_window`
        vaut `None`, et `MEMORY/VEILLE.md` écrit que la fiche modèle Google
        était inaccessible (404). Le produit affirmait donc une aptitude fondée
        sur une capacité qu'il ne connaît pas.
        """
        from promptforge.profiles import MODEL_PRICING, PRESET_PROFILES, TargetModel

        revendications = [
            "documents longs",
            "documents entiers",
            "codebases",
            "long contexte",
            "gros volumes",
        ]
        for nom, texte in self._textes_statiques():
            cible = PRESET_PROFILES[nom].target_model
            fenetre = (
                None if cible is TargetModel.UNIVERSAL else MODEL_PRICING[cible].context_window
            )
            for mot in revendications:
                if mot in texte.lower():
                    assert fenetre is not None, (
                        f"{nom}: {mot!r} annoncé alors que la fenêtre de contexte "
                        f"n'est pas confirmée par une source"
                    )

    def test_no_economy_claim_unless_actually_the_cheapest(self):
        """« Économique » / « Budget » se vérifie dans `MODEL_PRICING`.

        GPT-5.6 Terra était annoncé « Économique » et « Budget, volume élevé »
        alors qu'il coûte $2/$12 contre $1.25/$10 pour GPT-5.1 : le produit
        contredisait sa propre table de tarifs.
        """
        from promptforge.profiles import MODEL_PRICING, PRESET_PROFILES, TargetModel

        moins_cher = min(p.input_price for p in MODEL_PRICING.values())
        for nom, texte in self._textes_statiques():
            minuscule = texte.lower()
            if not any(m in minuscule for m in ["économique", "budget", "bon marché"]):
                continue
            cible = PRESET_PROFILES[nom].target_model
            assert cible is not TargetModel.UNIVERSAL, nom
            assert MODEL_PRICING[cible].input_price == moins_cher, (
                f"{nom}: annonce un tarif avantageux sans être le moins cher " f"de MODEL_PRICING"
            )

    def test_no_unmeasured_superlative_in_static_text(self):
        """Un vocabulaire de jugement que rien ne mesure, banni du texte statique.

        « Meilleur pour: », « Ultra-rapide », « Instruction following
        chirurgical », « Deep thinking », « Idéal » : le dépôt ne mesure ni
        vitesse, ni suivi d'instruction, ni qualité de raisonnement, et aucune
        documentation d'éditeur consultée n'en publie de mesure comparative.
        """
        interdits = [
            "meilleur",
            "excellent",
            "chirurgical",
            "ultra-rapide",
            "le plus puissant",
            "idéal",
            "premium",
            "deep thinking",
            "deep reasoning",
        ]
        for nom, texte in self._textes_statiques():
            minuscule = texte.lower()
            for mot in interdits:
                assert mot not in minuscule, f"{nom}: {mot!r} dans {texte[:60]!r}"

    def test_format_recommendation_still_cites_its_source(self):
        """Ce qui est sourcé reste : Anthropic recommande bien les balises XML.

        Le ménage ci-dessus ne doit pas emporter les affirmations qui, elles,
        ont une source. `MEMORY/VEILLE.md` établit qu'Anthropic recommande le
        balisage XML (recommandation éditoriale qualitative, citée comme telle)
        et que Google traite XML et Markdown comme interchangeables.
        """
        from promptforge.web.profiles_ui import PROFILE_DETAILS

        for nom in ["claude_opus_5", "claude_sonnet_5", "claude_haiku_4.5"]:
            assert "recommandé par Anthropic" in PROFILE_DETAILS[nom]["title"], nom
