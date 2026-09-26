"""
Tests des contrôles de conformité d'un prompt reformaté (promptforge.conformance).
"""

import pytest

from promptforge.conformance import (
    check_reformatted_prompt,
    detect_language,
    detect_syntax,
    key_terms,
)

RAW = "trouve moi des mots clés pour mon site"
CONTEXT = "Site: exemple.fr\nNiche: jardinage"

GOOD_XML = """<task>
Identifier des mots-clés SEO pour le site de jardinage exemple.fr.
</task>

<context>
Site exemple.fr, niche jardinage.
</context>

<output_format>
Liste de mots-clés avec l'intention de recherche de chacun.
</output_format>"""

GOOD_MARKDOWN = """## Objectif
Identifier des mots-clés SEO pour le site de jardinage exemple.fr.

## Contexte
Site exemple.fr, niche jardinage.

## Format de sortie
Liste de mots-clés avec l'intention de recherche de chacun."""


class TestDetectSyntax:
    def test_xml(self):
        assert detect_syntax(GOOD_XML) == "xml"

    def test_markdown(self):
        assert detect_syntax(GOOD_MARKDOWN) == "markdown"

    def test_mixed(self):
        assert detect_syntax(GOOD_XML + "\n\n" + GOOD_MARKDOWN) == "mixed"

    def test_plain_text(self):
        assert detect_syntax("Les feuilles tombent doucement.") == "plain"

    def test_a_single_section_is_not_a_structure(self):
        assert detect_syntax("<task>X</task>") == "plain"


class TestDetectLanguage:
    def test_french(self):
        assert detect_language("Identifier les mots-clés pour le site de la marque") == "fr"

    def test_english(self):
        assert detect_language("Identify the keywords for the website and the brand") == "en"

    def test_too_short_to_tell(self):
        assert detect_language("SEO") is None


class TestKeyTerms:
    def test_stopwords_and_request_verbs_are_dropped(self):
        assert key_terms(RAW) == ["mots", "cles", "site"]

    def test_accents_are_normalized(self):
        assert "reseau" in key_terms("optimise mon réseau")


class TestCompliantOutputs:
    @pytest.mark.parametrize(
        "output,syntax",
        [(GOOD_XML, "xml"), (GOOD_MARKDOWN, "markdown"), (GOOD_XML, "any"), (GOOD_MARKDOWN, "any")],
    )
    def test_everything_passes(self, output, syntax):
        report = check_reformatted_prompt(RAW, output, syntax, CONTEXT)
        assert report.passed, report.failures


class TestEachCheckCatchesItsDefect:
    def test_empty_output(self):
        report = check_reformatted_prompt(RAW, "", "xml")
        assert not report.passed
        assert report.get("non_vide").passed is False

    def test_wrong_syntax_for_the_profile(self):
        report = check_reformatted_prompt(RAW, GOOD_XML, "markdown", CONTEXT)
        assert report.get("format").passed is False
        assert "attendu : markdown" in report.get("format").detail

    def test_universal_profile_rejects_mixed_conventions(self):
        report = check_reformatted_prompt(RAW, GOOD_XML + "\n\n" + GOOD_MARKDOWN, "any", CONTEXT)
        assert report.get("format").passed is False

    def test_announcement_line(self):
        report = check_reformatted_prompt(RAW, "Voici le prompt :\n" + GOOD_XML, "xml", CONTEXT)
        assert report.get("pas_d_annonce").passed is False

    def test_leaked_reasoning(self):
        report = check_reformatted_prompt(RAW, "<think>hmm</think>\n" + GOOD_XML, "xml", CONTEXT)
        assert report.get("pas_de_raisonnement").passed is False

    def test_executed_request(self):
        """« écris un poème » a rendu le poème au lieu d'un prompt qui le demande."""
        poem = "Les feuilles tombent doucement,\nL'automne danse dans le vent."
        report = check_reformatted_prompt("écris un poème sur l'automne", poem, "any")
        assert report.get("demande_reformulee").passed is False

    def test_structure_without_objective_section(self):
        output = "<context>\nX\n</context>\n<output_format>\nY\n</output_format>"
        report = check_reformatted_prompt(RAW, output, "xml")
        assert report.get("demande_reformulee").passed is False

    def test_dropped_request_terms(self):
        output = "<task>\nRédiger un article.\n</task>\n<context>\nBlog.\n</context>"
        report = check_reformatted_prompt(RAW, output, "xml")
        assert report.get("termes_conserves").passed is False
        assert "absents" in report.get("termes_conserves").detail

    def test_wrong_language(self):
        output = (
            "## Objective\nIdentify the keywords for the site and the niche.\n\n"
            "## Output format\nA list of the keywords with the intent of each."
        )
        report = check_reformatted_prompt(
            "trouve des mots clés pour le site de la boutique", output, "markdown"
        )
        assert report.get("meme_langue").passed is False

    def test_invented_percentage(self):
        output = GOOD_MARKDOWN + "\n\n## Gains\nHausse du trafic de 48 %."
        report = check_reformatted_prompt(RAW, output, "markdown", CONTEXT)
        assert report.get("aucun_chiffre_invente").passed is False

    def test_percentage_from_the_request_is_allowed(self):
        raw = "baisse le taux de rebond de 20 % sur mon site"
        output = "## Objectif\nBaisser le taux de rebond du site de 20 %.\n\n## Format de sortie\nPlan d'action."
        report = check_reformatted_prompt(raw, output, "markdown")
        assert report.get("aucun_chiffre_invente").passed is True
