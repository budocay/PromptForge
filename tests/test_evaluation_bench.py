"""
Tests hors ligne du banc d'évaluation (scripts/evaluate_prompt_quality.py).

Le banc passe par le vrai pipeline ; ici Ollama est remplacé par des faux
providers dont on connaît le comportement.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from promptforge.providers import OllamaConfig

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "evaluate_prompt_quality.py"


@pytest.fixture(scope="module")
def bench():
    spec = importlib.util.spec_from_file_location("_bench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Les dataclasses du script résolvent leurs annotations via sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _request_from(user_prompt: str) -> str:
    return re.search(r'DEMANDE À REFORMATER[^\n]*\n"""\n(.*?)\n"""', user_prompt, re.S).group(1)


class ObedientProvider:
    """Reformule dans la syntaxe que demande le prompt système."""

    config = OllamaConfig(model="fake")

    def is_available(self):
        return True

    def generate(self, prompt, system_prompt="", num_ctx=16384):
        request = _request_from(prompt)
        english = request.startswith("write")
        objective, fmt = (
            ("Objective", "Output format") if english else ("Objectif", "Format de sortie")
        )
        body = (
            f"Produce what the user asks: {request}. The answer is for the user and the team."
            if english
            else f"Produire ce que demande l'utilisateur : {request}. Le résultat est pour le public visé."
        )
        tail = (
            "A complete draft for the reader."
            if english
            else "Un livrable complet pour le lecteur."
        )
        if "prompts Markdown" in system_prompt:
            return f"## {objective}\n{body}\n\n## {fmt}\n{tail}"
        return f"<task>\n{body}\n</task>\n\n<output_format>\n{tail}\n</output_format>"


class ExecutingProvider(ObedientProvider):
    """Répond à la demande au lieu de la réécrire."""

    def generate(self, prompt, system_prompt="", num_ctx=16384):
        return "Les feuilles tombent doucement, l'automne danse dans le vent."


class TestBenchDataset:
    def test_case_ids_are_unique(self, bench):
        ids = [c["id"] for c in bench.CASES]
        assert len(ids) == len(set(ids))

    def test_cases_cover_several_domains_and_the_traps(self, bench):
        domains = {c["domain"] for c in bench.CASES}
        assert len(domains) >= 8
        assert {"piege-execution", "piege-consigne", "anglais"} <= {c["id"] for c in bench.CASES}

    def test_default_profiles_exist(self, bench):
        from promptforge.profiles import list_profiles

        assert set(bench.DEFAULT_PROFILES) <= set(list_profiles())


class TestBenchRun:
    def test_an_obedient_reformatter_is_fully_compliant_on_every_profile(self, bench):
        results = bench.run_evaluation(ObedientProvider(), bench.CASES, bench.DEFAULT_PROFILES)
        assert len(results) == len(bench.CASES) * len(bench.DEFAULT_PROFILES)
        failing = [
            (r.profile, r.case_id, [c for c in r.checks if not c["passed"]])
            for r in results
            if not r.passed
        ]
        assert not failing

    def test_an_executing_reformatter_is_caught(self, bench):
        results = bench.run_evaluation(ExecutingProvider(), bench.CASES[:2], ["claude_sonnet_5"])
        for r in results:
            names = {c["name"] for c in r.checks if not c["passed"]}
            assert {"format", "demande_reformulee"} <= names

    def test_summary_counts_without_any_composite_score(self, bench):
        results = bench.run_evaluation(
            ExecutingProvider(), bench.CASES[:3], ["gpt_5.1", "universel"]
        )
        summary = bench.summarize(results)
        assert summary["sorties"] == 6
        assert summary["sorties_entierement_conformes"] == 0
        assert summary["par_controle"]["demande_reformulee"] == {"conformes": 0, "total": 6}
        assert "score" not in str(summary).lower()

    def test_main_refuses_to_run_without_ollama(self, bench, capsys, monkeypatch):
        monkeypatch.setattr(bench.OllamaProvider, "is_available", lambda self: False)
        assert bench.main(["--cases", "seo"]) == 2
        assert "injoignable" in capsys.readouterr().err
