"""
Test de valeur reelle de PromptForge.
Evalue objectivement si l'enrichissement ameliore vraiment les prompts.

Execution: python scripts/evaluate_prompt_quality.py

Ce fichier est un script de validation Ollama, pas une suite de tests pytest :
il ne contient aucune fonction collectable. Il vivait sous `tests/` et y
reassignait `sys.stdout` a l'import, ce qui faisait planter la session pytest
entiere (D-001).
"""

import json
import sys
import time
import urllib.request
from dataclasses import dataclass

# ============================================
# CONFIGURATION
# ============================================

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:8b"  # Modèle par défaut de PromptForge

# System prompt simplifié de PromptForge (extrait de profiles.py)
SYSTEM_PROMPT = """Tu transformes des demandes utilisateur en prompts XML structurés.

RÈGLES:
1. Ta réponse = UNIQUEMENT le prompt XML reformaté
2. Utilise les balises: <task_definition>, <context>, <requirements>, <constraints>, <output_format>
3. PAS de métriques inventées, PAS d'analyse, PAS de scores fictifs
4. Ajoute du contexte et des contraintes pertinentes

EXEMPLE:
Input: "fais moi un site web"
Output:
<task_definition>
Créer un site web fonctionnel
</task_definition>
<requirements>
- Structure HTML valide
- Design responsive
- Navigation claire
</requirements>
<output_format>
Code HTML/CSS complet et commenté
</output_format>
"""

# ============================================
# 10 PROMPTS DE TEST RÉALISTES
# ============================================

TEST_PROMPTS = [
    # SEO
    {
        "id": 1,
        "category": "SEO",
        "raw": "trouve moi des mots clés pour mon site de jardinage",
        "expected_additions": ["niche", "volume", "difficulté", "intent"],
    },
    # Dev Backend
    {
        "id": 2,
        "category": "Dev",
        "raw": "crée une API REST pour gérer des utilisateurs",
        "expected_additions": ["endpoints", "authentification", "validation", "erreurs"],
    },
    # Marketing
    {
        "id": 3,
        "category": "Marketing",
        "raw": "écris moi un email de prospection",
        "expected_additions": ["cible", "ton", "CTA", "objet"],
    },
    # Data
    {
        "id": 4,
        "category": "Data",
        "raw": "analyse mes données de vente",
        "expected_additions": ["métriques", "période", "dimensions", "visualisation"],
    },
    # Product
    {
        "id": 5,
        "category": "Product",
        "raw": "écris une user story pour le login",
        "expected_additions": ["persona", "critères acceptation", "edge cases"],
    },
    # Support
    {
        "id": 6,
        "category": "Support",
        "raw": "réponds à ce client mécontent",
        "expected_additions": ["ton", "solution", "empathie", "suivi"],
    },
    # RH
    {
        "id": 7,
        "category": "RH",
        "raw": "rédige une offre d'emploi pour un dev senior",
        "expected_additions": ["stack", "missions", "avantages", "culture"],
    },
    # Commercial
    {
        "id": 8,
        "category": "Sales",
        "raw": "prépare moi un pitch pour un prospect",
        "expected_additions": ["pain points", "valeur", "différenciation", "objections"],
    },
    # Général - vague
    {
        "id": 9,
        "category": "Général",
        "raw": "aide moi avec mon projet",
        "expected_additions": ["clarification", "contexte", "objectif"],
    },
    # Technique complexe
    {
        "id": 10,
        "category": "Dev",
        "raw": "optimise ma requête SQL qui est lente",
        "expected_additions": ["indexes", "explain", "volume données", "contraintes"],
    },
]


# ============================================
# METRICS
# ============================================


@dataclass
class TestResult:
    prompt_id: int
    category: str
    raw_prompt: str
    enriched_prompt: str
    raw_length: int
    enriched_length: int
    enrichment_ratio: float
    has_xml_structure: bool
    xml_tags_found: list
    expected_additions: list
    additions_found: list
    additions_score: float  # % des additions attendues trouvées
    processing_time: float
    error: str | None = None


def call_ollama(prompt: str, system: str) -> tuple[str, float]:
    """Appelle Ollama et retourne la réponse + temps."""
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.3, "top_p": 0.9},
    }

    start = time.time()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - start
            return result.get("response", ""), elapsed
    except Exception as e:
        return f"ERROR: {e}", time.time() - start


def analyze_enrichment(raw: str, enriched: str, expected: list) -> TestResult:
    """Analyse la qualité de l'enrichissement."""

    # Détection des balises XML
    import re

    xml_tags = re.findall(r"<(\w+)>", enriched)
    xml_tags = list(set(xml_tags))  # Unique

    has_xml = len(xml_tags) >= 2  # Au moins 2 balises différentes

    # Vérification des additions attendues
    enriched_lower = enriched.lower()
    found = []
    for addition in expected:
        if addition.lower() in enriched_lower:
            found.append(addition)

    additions_score = len(found) / len(expected) if expected else 0

    return TestResult(
        prompt_id=0,  # Sera rempli plus tard
        category="",
        raw_prompt=raw,
        enriched_prompt=enriched,
        raw_length=len(raw),
        enriched_length=len(enriched),
        enrichment_ratio=len(enriched) / len(raw) if len(raw) > 0 else 0,
        has_xml_structure=has_xml,
        xml_tags_found=xml_tags,
        expected_additions=expected,
        additions_found=found,
        additions_score=additions_score,
        processing_time=0,
    )


def run_tests() -> list[TestResult]:
    """Exécute tous les tests."""
    results = []

    print("=" * 60)
    print("🧪 TEST DE VALEUR RÉELLE - PROMPTFORGE")
    print("=" * 60)
    print(f"Modèle: {MODEL}")
    print(f"Nombre de tests: {len(TEST_PROMPTS)}")
    print("=" * 60)
    print()

    for test in TEST_PROMPTS:
        print(f"[{test['id']}/10] {test['category']}: {test['raw'][:40]}...")

        # Appel Ollama
        enriched, elapsed = call_ollama(test["raw"], SYSTEM_PROMPT)

        if enriched.startswith("ERROR"):
            print(f"  ❌ Erreur: {enriched}")
            results.append(
                TestResult(
                    prompt_id=test["id"],
                    category=test["category"],
                    raw_prompt=test["raw"],
                    enriched_prompt="",
                    raw_length=len(test["raw"]),
                    enriched_length=0,
                    enrichment_ratio=0,
                    has_xml_structure=False,
                    xml_tags_found=[],
                    expected_additions=test["expected_additions"],
                    additions_found=[],
                    additions_score=0,
                    processing_time=elapsed,
                    error=enriched,
                )
            )
            continue

        # Analyse
        result = analyze_enrichment(test["raw"], enriched, test["expected_additions"])
        result.prompt_id = test["id"]
        result.category = test["category"]
        result.processing_time = elapsed

        # Affichage rapide
        print(
            f"  📊 {result.raw_length} → {result.enriched_length} chars (×{result.enrichment_ratio:.1f})"
        )
        print(
            f"  🏷️  XML: {'✅' if result.has_xml_structure else '❌'} | Tags: {result.xml_tags_found[:5]}"
        )
        print(
            f"  🎯 Additions: {len(result.additions_found)}/{len(result.expected_additions)} ({result.additions_score*100:.0f}%)"
        )
        print(f"  ⏱️  {elapsed:.1f}s")
        print()

        results.append(result)

    return results


def print_summary(results: list[TestResult]):
    """Affiche le résumé des tests."""

    valid_results = [r for r in results if not r.error]

    if not valid_results:
        print("❌ Aucun test valide")
        return

    print()
    print("=" * 60)
    print("📊 RÉSUMÉ DES TESTS")
    print("=" * 60)

    # Métriques agrégées
    avg_ratio = sum(r.enrichment_ratio for r in valid_results) / len(valid_results)
    xml_success = sum(1 for r in valid_results if r.has_xml_structure) / len(valid_results)
    avg_additions = sum(r.additions_score for r in valid_results) / len(valid_results)
    avg_time = sum(r.processing_time for r in valid_results) / len(valid_results)

    print(f"""
┌─────────────────────────────────────────────────────────┐
│  MÉTRIQUES GLOBALES                                     │
├─────────────────────────────────────────────────────────┤
│  Tests réussis:     {len(valid_results)}/{len(results)}                                │
│  Ratio moyen:       ×{avg_ratio:.1f} (caractères)                      │
│  Structure XML:     {xml_success*100:.0f}% des prompts                        │
│  Additions pertinentes: {avg_additions*100:.0f}%                            │
│  Temps moyen:       {avg_time:.1f}s                                  │
└─────────────────────────────────────────────────────────┘
""")

    # Verdict
    print("=" * 60)
    print("🎯 VERDICT")
    print("=" * 60)

    score = (xml_success * 0.3) + (avg_additions * 0.5) + (min(avg_ratio / 20, 1) * 0.2)

    if score >= 0.7:
        print(f"✅ VALEUR CONFIRMÉE (score: {score*100:.0f}%)")
        print("   L'enrichissement ajoute une structure et du contexte pertinent.")
    elif score >= 0.5:
        print(f"⚠️  VALEUR PARTIELLE (score: {score*100:.0f}%)")
        print("   L'enrichissement fonctionne mais manque de pertinence contextuelle.")
    else:
        print(f"❌ VALEUR NON PROUVÉE (score: {score*100:.0f}%)")
        print("   L'enrichissement n'apporte pas de valeur mesurable.")

    print()

    # Détail par catégorie
    print("=" * 60)
    print("📋 DÉTAIL PAR CATÉGORIE")
    print("=" * 60)

    categories = {}
    for r in valid_results:
        if r.category not in categories:
            categories[r.category] = []
        categories[r.category].append(r)

    for cat, cat_results in categories.items():
        cat_additions = sum(r.additions_score for r in cat_results) / len(cat_results)
        cat_xml = sum(1 for r in cat_results if r.has_xml_structure) / len(cat_results)
        print(f"  {cat}: XML {cat_xml*100:.0f}% | Pertinence {cat_additions*100:.0f}%")

    print()

    # Exemples concrets
    print("=" * 60)
    print("📝 EXEMPLE CONCRET (Test #1)")
    print("=" * 60)

    if valid_results:
        r = valid_results[0]
        print(f"\n🔴 AVANT ({r.raw_length} chars):")
        print(f'   "{r.raw_prompt}"')
        print(f"\n🟢 APRÈS ({r.enriched_length} chars):")
        print("-" * 40)
        # Afficher les 1000 premiers caractères
        print(r.enriched_prompt[:1500])
        if len(r.enriched_prompt) > 1500:
            print(f"... [{len(r.enriched_prompt) - 1500} chars de plus]")
        print("-" * 40)


if __name__ == "__main__":
    # Sortie UTF-8 sur Windows. `reconfigure()` modifie le flux en place au
    # lieu de le remplacer : contrairement a l'ancienne reassignation de
    # `sys.stdout` faite a l'import, il ne casse aucun flux detenu par un
    # appelant. Et il ne s'execute qu'ici, jamais a l'import (D-001).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    results = run_tests()
    print_summary(results)
