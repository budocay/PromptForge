"""
Prompt quality analysis for PromptForge web interface.
Evaluates prompts and compares before/after reformatting.

IMPORTANT: Les métriques sont basées sur:
1. Des mesures directes (tokens, caractères, structure)
2. Des prédictions sourcées (études publiées)
3. Des preuves officielles (documentation Anthropic, OpenAI, Google)

Aucun chiffre n'est inventé. Voir RESEARCH_SOURCES.md pour les sources.
"""

import re
import unicodedata
from functools import lru_cache

from ..profiles import MODEL_PRICING, TargetModel
from ..tokens import estimate_tokens


@lru_cache(maxsize=4096)
def normalize_for_matching(text: str) -> str:
    """Forme comparable d'un texte : minuscules, sans accent, sans trait d'union.

    Motif mesuré (D-057) : les mots-clés de `detect_domain()` ne portaient que
    `'mot-clé'` et `'mots-clés'`. Un utilisateur francophone qui écrit
    « mots clés » avec une espace, ou « mots cles » sans accent, n'obtenait
    **aucune correspondance, tous domaines confondus**, et retombait sur
    `general` — donc sur aucune recommandation.

    La correction normalise **avant** de comparer, des deux côtés, plutôt que
    d'empiler les variantes clé par clé : la même lacune menaçait
    `'longue traîne'`, `'cold email'`, `'référencement'` et toutes les clés
    multi-mots ou accentuées des autres domaines, et les traiter une à une
    aurait réintroduit le défaut ailleurs.

    Ce qui est normalisé, et rien d'autre : la casse, les diacritiques, les
    traits d'union et tirets bas ramenés à une espace, les espaces répétées
    réduites à une. Les autres séparateurs (`/`, `.`, `<`, `` ` ``) sont
    laissés intacts : ils portent du sens dans `'a/b test'`, `'robots.txt'`,
    `'<context>'`.

    Le cache est là parce que la fonction est appelée une fois par mot-clé et
    par appel : l'ensemble des clés est fini et fixe, il sature au premier
    appel.
    """
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    spaced = re.sub(r"[-_]+", " ", without_accents)
    return re.sub(r"\s+", " ", spaced).strip()


def analyze_prompt_quality(prompt: str) -> dict:
    """
    Analyse la qualité d'un prompt selon plusieurs critères.
    Retourne un dict avec scores (0-100) et détails.

    Critères évalués:
    - clarity: Instructions claires et directes
    - context: Présence de contexte suffisant
    - specificity: Niveau de détail et précision
    - structure: Organisation et formatage
    - output_format: Format de sortie spécifié
    - constraints: Contraintes/limites définies
    - examples: Présence d'exemples
    """
    prompt_lower = prompt.lower()
    prompt_len = len(prompt)

    scores = {}
    details = {}

    # ==========================================================================
    # 1. CLARTÉ (0-100) - Instructions directes, pas de vague
    # ==========================================================================
    clarity_score = 50  # Base
    clarity_notes = []

    # Verbes d'action directs
    action_verbs = [
        "écris",
        "crée",
        "génère",
        "analyse",
        "résume",
        "explique",
        "liste",
        "compare",
        "traduis",
        "corrige",
        "optimise",
        "refactor",
        "write",
        "create",
        "generate",
        "analyze",
        "summarize",
        "explain",
        "list",
        "compare",
        "translate",
        "fix",
        "optimize",
        "implement",
    ]
    if any(v in prompt_lower for v in action_verbs):
        clarity_score += 20
        clarity_notes.append("✅ Verbes d'action clairs")
    else:
        clarity_notes.append("❌ Manque de verbes d'action directs")

    # Mots vagues
    vague_words = [
        "peut-être",
        "possiblement",
        "éventuellement",
        "quelque chose",
        "maybe",
        "possibly",
        "something",
        "stuff",
        "things",
        "etc",
    ]
    vague_count = sum(1 for w in vague_words if w in prompt_lower)
    if vague_count == 0:
        clarity_score += 15
        clarity_notes.append("✅ Pas de termes vagues")
    else:
        clarity_score -= vague_count * 5
        clarity_notes.append(f"⚠️ {vague_count} terme(s) vague(s)")

    # Longueur minimale
    if prompt_len > 100:
        clarity_score += 15
        clarity_notes.append("✅ Longueur suffisante")
    elif prompt_len < 30:
        clarity_score -= 10
        clarity_notes.append("❌ Prompt trop court")

    scores["clarity"] = min(100, max(0, clarity_score))
    details["clarity"] = clarity_notes

    # ==========================================================================
    # 2. CONTEXTE (0-100) - Informations de fond fournies
    # ==========================================================================
    context_score = 30  # Base faible
    context_notes = []

    # Balises de contexte explicites
    context_markers = [
        "<context>",
        "contexte:",
        "context:",
        "background:",
        "situation:",
        "## contexte",
        "## context",
        "given:",
    ]
    if any(m in prompt_lower for m in context_markers):
        context_score += 40
        context_notes.append("✅ Section contexte explicite")

    # Mentions de projet/stack technique
    tech_context = [
        "projet",
        "project",
        "application",
        "système",
        "system",
        "stack",
        "architecture",
        "database",
        "api",
        "frontend",
        "backend",
    ]
    if any(t in prompt_lower for t in tech_context):
        context_score += 20
        context_notes.append("✅ Contexte technique mentionné")

    # Longueur comme proxy de contexte
    if prompt_len > 500:
        context_score += 15
        context_notes.append("✅ Contexte détaillé (longueur)")
    elif prompt_len < 100:
        context_notes.append("⚠️ Peu de contexte fourni")

    if context_score <= 30:
        context_notes.append("❌ Contexte insuffisant")

    scores["context"] = min(100, max(0, context_score))
    details["context"] = context_notes

    # ==========================================================================
    # 3. SPÉCIFICITÉ (0-100) - Niveau de détail
    # ==========================================================================
    specificity_score = 40  # Base
    specificity_notes = []

    # Nombres et métriques spécifiques
    numbers = re.findall(r"\d+", prompt)
    if len(numbers) >= 2:
        specificity_score += 20
        specificity_notes.append(f"✅ Métriques spécifiques ({len(numbers)} nombres)")

    # Termes techniques
    tech_terms = [
        "mongodb",
        "postgresql",
        "react",
        "vue",
        "python",
        "java",
        "fastapi",
        "django",
        "express",
        "typescript",
        "docker",
        "kubernetes",
        "json",
        "xml",
        "csv",
        "rest",
        "graphql",
        "oauth",
        "jwt",
    ]
    tech_count = sum(1 for t in tech_terms if t in prompt_lower)
    if tech_count >= 2:
        specificity_score += 25
        specificity_notes.append(f"✅ Termes techniques précis ({tech_count})")
    elif tech_count == 0:
        specificity_notes.append("⚠️ Peu de termes spécifiques")

    # Mots de détail
    detail_words = [
        "précisément",
        "exactement",
        "spécifiquement",
        "notamment",
        "precisely",
        "exactly",
        "specifically",
        "including",
        "such as",
    ]
    if any(d in prompt_lower for d in detail_words):
        specificity_score += 15
        specificity_notes.append("✅ Indicateurs de précision")

    scores["specificity"] = min(100, max(0, specificity_score))
    details["specificity"] = specificity_notes

    # ==========================================================================
    # 4. STRUCTURE (0-100) - Organisation et formatage
    # ==========================================================================
    structure_score = 20  # Base faible
    structure_notes = []

    # Balises XML/Markdown
    if "<" in prompt and ">" in prompt:
        structure_score += 30
        structure_notes.append("✅ Balises XML structurantes")

    # Headers Markdown
    if "##" in prompt or "###" in prompt:
        structure_score += 20
        structure_notes.append("✅ Headers Markdown")

    # Listes
    if re.search(r"^\s*[-*]\s", prompt, re.MULTILINE) or re.search(
        r"^\s*\d+\.", prompt, re.MULTILINE
    ):
        structure_score += 20
        structure_notes.append("✅ Listes structurées")

    # Sections séparées
    if "\n\n" in prompt:
        structure_score += 10
        structure_notes.append("✅ Paragraphes séparés")

    if structure_score <= 30:
        structure_notes.append("❌ Pas de structure claire")

    scores["structure"] = min(100, max(0, structure_score))
    details["structure"] = structure_notes

    # ==========================================================================
    # 5. FORMAT DE SORTIE (0-100) - Output attendu spécifié
    # ==========================================================================
    output_score = 20  # Base faible
    output_notes = []

    format_markers = [
        "format:",
        "output:",
        "retourne",
        "return",
        "génère un",
        "produis",
        "produce",
        "en json",
        "en markdown",
        "as json",
        "<output_format>",
        "<format>",
        "format de sortie",
        "output format",
    ]
    if any(f in prompt_lower for f in format_markers):
        output_score += 50
        output_notes.append("✅ Format de sortie spécifié")

    file_types = [".json", ".md", ".py", ".js", ".ts", ".csv", ".xml", ".html", ".yaml"]
    if any(ft in prompt_lower for ft in file_types):
        output_score += 20
        output_notes.append("✅ Type de fichier spécifié")

    if "structure" in prompt_lower or "template" in prompt_lower:
        output_score += 15
        output_notes.append("✅ Structure de réponse demandée")

    if output_score <= 30:
        output_notes.append("❌ Format de sortie non spécifié")

    scores["output_format"] = min(100, max(0, output_score))
    details["output_format"] = output_notes

    # ==========================================================================
    # 6. CONTRAINTES (0-100) - Limites et règles définies
    # ==========================================================================
    constraints_score = 30  # Base
    constraints_notes = []

    constraint_words = [
        "ne pas",
        "évite",
        "sans",
        "maximum",
        "minimum",
        "limite",
        "do not",
        "avoid",
        "without",
        "max",
        "min",
        "limit",
        "only",
        "seulement",
        "uniquement",
        "doit",
        "must",
        "should not",
        "<constraints>",
        "<requirements>",
        "règles:",
        "rules:",
    ]
    constraint_count = sum(1 for c in constraint_words if c in prompt_lower)
    if constraint_count >= 2:
        constraints_score += 40
        constraints_notes.append(f"✅ Contraintes explicites ({constraint_count})")
    elif constraint_count == 1:
        constraints_score += 20
        constraints_notes.append("✅ Quelques contraintes")
    else:
        constraints_notes.append("⚠️ Pas de contraintes définies")

    if re.search(r"\d+\s*(mots|words|lignes|lines|caractères|chars)", prompt_lower):
        constraints_score += 20
        constraints_notes.append("✅ Limite de longueur spécifiée")

    scores["constraints"] = min(100, max(0, constraints_score))
    details["constraints"] = constraints_notes

    # ==========================================================================
    # 7. EXEMPLES (0-100) - Présence d'exemples
    # ==========================================================================
    examples_score = 20  # Base faible
    examples_notes = []

    example_markers = [
        "exemple:",
        "example:",
        "par exemple",
        "for example",
        "e.g.",
        "comme:",
        "such as:",
        "like:",
        "voici un exemple",
        "here's an example",
        "<example>",
        "<examples>",
        "```",
    ]
    if any(e in prompt_lower for e in example_markers):
        examples_score += 50
        examples_notes.append("✅ Exemples fournis")

    if prompt.count("```") >= 2:
        examples_score += 30
        examples_notes.append("✅ Blocs de code (exemples)")

    if examples_score <= 30:
        examples_notes.append("⚠️ Pas d'exemples fournis")

    scores["examples"] = min(100, max(0, examples_score))
    details["examples"] = examples_notes

    # ==========================================================================
    # SCORE GLOBAL PONDÉRÉ
    # ==========================================================================
    weights = {
        "clarity": 0.20,
        "context": 0.20,
        "specificity": 0.15,
        "structure": 0.15,
        "output_format": 0.12,
        "constraints": 0.10,
        "examples": 0.08,
    }

    global_score = sum(scores[k] * weights[k] for k in weights)

    # Classification
    if global_score >= 80:
        grade, grade_label = "A", "🟢 Excellent"
    elif global_score >= 65:
        grade, grade_label = "B", "🟡 Bon"
    elif global_score >= 50:
        grade, grade_label = "C", "🟠 Moyen"
    elif global_score >= 35:
        grade, grade_label = "D", "🔴 Faible"
    else:
        grade, grade_label = "F", "⚫ Insuffisant"

    return {
        "scores": scores,
        "details": details,
        "global_score": round(global_score, 1),
        "grade": grade,
        "grade_label": grade_label,
        "token_count": estimate_tokens(prompt),
        "char_count": len(prompt),
        "word_count": len(prompt.split()),
    }


def compare_prompts(raw_prompt: str, formatted_prompt: str) -> str:
    """
    Compare le prompt brut et reformaté, génère un rapport d'amélioration
    basé sur l'analyse de la structure et du contenu.

    NOTE: Les métriques de qualité sont basées sur des heuristiques (présence
    de balises XML, contexte, contraintes, etc.), pas sur des études empiriques.
    """
    raw_analysis = analyze_prompt_quality(raw_prompt)
    formatted_analysis = analyze_prompt_quality(formatted_prompt)

    score_diff = formatted_analysis["global_score"] - raw_analysis["global_score"]
    diff_str = f"+{score_diff:.1f}" if score_diff >= 0 else f"{score_diff:.1f}"

    raw_score = raw_analysis["global_score"]
    after_score = formatted_analysis["global_score"]

    lines = []

    # ==========================================================================
    # SECTION 1: RÉSUMÉ - Honnête sur ce qui est mesuré
    # ==========================================================================
    lines.append("## 🎯 Analyse du reformatage\n")

    if score_diff >= 25:
        value_verdict = "🚀 **TRANSFORMATION MAJEURE**"
        verdict_note = "Le prompt a été considérablement enrichi et structuré."
    elif score_diff >= 15:
        value_verdict = "✅ **AMÉLIORATION SIGNIFICATIVE**"
        verdict_note = "Structure et contexte nettement améliorés."
    elif score_diff >= 8:
        value_verdict = "🟡 **AMÉLIORATION UTILE**"
        verdict_note = "Améliorations modérées mais concrètes."
    elif score_diff >= 3:
        value_verdict = "➡️ **OPTIMISATION LÉGÈRE**"
        verdict_note = "Ajustements mineurs apportés."
    else:
        value_verdict = "📋 **PROMPT DÉJÀ OPTIMISÉ**"
        verdict_note = "Le prompt original était déjà bien formulé."

    lines.append(f"### {value_verdict}\n")
    lines.append(f"*{verdict_note}*\n")

    # Tableau basé sur des MESURES RÉELLES du prompt
    len_ratio = formatted_analysis["char_count"] / max(raw_analysis["char_count"], 1)

    lines.append("| Métrique | Avant | Après | Changement |")
    lines.append("|----------|-------|-------|------------|")
    lines.append(
        f"| Score qualité (heuristique) | {raw_score:.0f}% | {after_score:.0f}% | **{diff_str}%** |"
    )
    lines.append(
        f"| Caractères | {raw_analysis['char_count']:,} | {formatted_analysis['char_count']:,} | **x{len_ratio:.1f}** |"
    )
    lines.append(
        f"| Tokens estimés | ~{raw_analysis['token_count']} | ~{formatted_analysis['token_count']} | **x{formatted_analysis['token_count']/max(raw_analysis['token_count'],1):.1f}** |"
    )

    # Structure XML détectée
    has_xml_before = "<" in raw_prompt and ">" in raw_prompt
    has_xml_after = "<" in formatted_prompt and ">" in formatted_prompt
    xml_status = "✅ Oui" if has_xml_after else "❌ Non"
    lines.append(
        f"| Structure XML | {'✅' if has_xml_before else '❌'} | {xml_status} | {'🆕 Ajoutée' if has_xml_after and not has_xml_before else '—'} |"
    )

    lines.append(
        '\n> ⚠️ *Le "score qualité" est une heuristique basée sur la présence de structure,'
    )
    lines.append("> contexte, contraintes, etc. Ce n'est pas une mesure de performance réelle.*")

    # ==========================================================================
    # SECTION 2: CE QUI A ÉTÉ AMÉLIORÉ (factuel)
    # ==========================================================================
    lines.append("\n### 🔍 Améliorations détectées\n")

    concrete_improvements = []

    if "<" in formatted_prompt and ">" in formatted_prompt and "<" not in raw_prompt:
        concrete_improvements.append(
            "📐 **Structure XML ajoutée** : Balises `<task>`, `<context>`, `<instructions>`"
        )

    if formatted_analysis["scores"]["context"] > raw_analysis["scores"]["context"] + 15:
        concrete_improvements.append(
            "📖 **Contexte enrichi** : Section contexte détectée/améliorée"
        )

    if formatted_analysis["scores"]["specificity"] > raw_analysis["scores"]["specificity"] + 15:
        concrete_improvements.append(
            "🔍 **Spécificité augmentée** : Plus de termes techniques détectés"
        )

    if formatted_analysis["scores"]["output_format"] > raw_analysis["scores"]["output_format"] + 15:
        concrete_improvements.append("📤 **Format de sortie** : Instructions de format ajoutées")

    if formatted_analysis["scores"]["constraints"] > raw_analysis["scores"]["constraints"] + 15:
        concrete_improvements.append("⚠️ **Contraintes** : Limites et règles explicites ajoutées")

    if formatted_analysis["scores"]["examples"] > raw_analysis["scores"]["examples"] + 15:
        concrete_improvements.append("💡 **Exemples** : Cas concrets ajoutés")

    if formatted_analysis["scores"]["clarity"] > raw_analysis["scores"]["clarity"] + 15:
        concrete_improvements.append("🎯 **Clarté** : Verbes d'action plus directs")

    if len_ratio > 2:
        concrete_improvements.append(f"📝 **Enrichissement** : Prompt {len_ratio:.1f}x plus long")

    if concrete_improvements:
        for imp in concrete_improvements:
            lines.append(f"- {imp}")
    else:
        lines.append("- Aucune amélioration majeure détectée (prompt original déjà structuré)")

    # ==========================================================================
    # SECTION 3: SCORE DE STRUCTURE (heuristique)
    # ==========================================================================
    lines.append("\n### 📊 Score de Structure (heuristique)\n")

    lines.append(
        "> ⚠️ *Ce score mesure la STRUCTURE du prompt (balises, contexte, contraintes), "
        "pas la qualité des réponses. L'impact réel dépend du modèle et de la tâche.*\n"
    )

    before_bar = "█" * int(raw_analysis["global_score"] / 10) + "░" * (
        10 - int(raw_analysis["global_score"] / 10)
    )
    after_bar = "█" * int(formatted_analysis["global_score"] / 10) + "░" * (
        10 - int(formatted_analysis["global_score"] / 10)
    )

    lines.append(
        f"**Avant:** {raw_analysis['grade_label']} `{before_bar}` {raw_analysis['global_score']}%"
    )
    lines.append(
        f"**Après:** {formatted_analysis['grade_label']} `{after_bar}` {formatted_analysis['global_score']}%"
    )
    lines.append(f"**Gain structurel:** {diff_str}%\n")

    # Tableau détaillé par critère
    lines.append("| Critère | Avant | Après | Δ |")
    lines.append("|---------|:-----:|:-----:|:-:|")

    criteria_labels = {
        "clarity": "🎯 Clarté",
        "context": "📖 Contexte",
        "specificity": "🔍 Spécificité",
        "structure": "📐 Structure",
        "output_format": "📤 Format sortie",
        "constraints": "⚠️ Contraintes",
        "examples": "💡 Exemples",
    }

    for key, label in criteria_labels.items():
        before = raw_analysis["scores"][key]
        after = formatted_analysis["scores"][key]
        diff = after - before

        if diff > 15:
            diff_icon = f"🟢 **+{diff}**"
        elif diff > 5:
            diff_icon = f"🟡 +{diff}"
        elif diff > 0:
            diff_icon = f"⬆️ +{diff}"
        elif diff == 0:
            diff_icon = "➡️ 0"
        else:
            diff_icon = f"🔴 {diff}"

        lines.append(f"| {label} | {before}% | {after}% | {diff_icon} |")

    # ==========================================================================
    # SECTION 4: MÉTRIQUES MESURÉES (100% vérifiables)
    # ==========================================================================
    lines.append("\n### 📏 Métriques Mesurées\n")
    lines.append("*Ces valeurs sont calculées directement, sans estimation.*\n")

    lines.append("| Métrique | Avant | Après | Ratio |")
    lines.append("|----------|------:|------:|------:|")
    lines.append(
        f"| Caractères | {raw_analysis['char_count']:,} | {formatted_analysis['char_count']:,} | x{len_ratio:.1f} |"
    )
    lines.append(
        f"| Mots | {raw_analysis['word_count']} | {formatted_analysis['word_count']} | x{formatted_analysis['word_count']/max(raw_analysis['word_count'],1):.1f} |"
    )
    lines.append(
        f"| Tokens (est.) | ~{raw_analysis['token_count']} | ~{formatted_analysis['token_count']} | x{formatted_analysis['token_count']/max(raw_analysis['token_count'],1):.1f} |"
    )

    # Coût tokens supplémentaires
    extra_tokens = formatted_analysis["token_count"] - raw_analysis["token_count"]
    if extra_tokens > 0:
        # Tarif lu dans le domaine, jamais recopié ici (F-022 bloc 2).
        sonnet_input_price = MODEL_PRICING[TargetModel.CLAUDE_SONNET_5].input_price
        extra_cost = extra_tokens * sonnet_input_price / 1_000_000
        lines.append(
            f"\n**Tokens supplémentaires:** +{extra_tokens} (~${extra_cost:.6f} par requête avec Sonnet)"
        )

    # ==========================================================================
    # SECTION 5: IMPACT ATTENDU (basé sur la recherche)
    # ==========================================================================
    lines.append("\n---\n### 🔬 Impact Attendu (basé sur la recherche)\n")

    research_impacts = []

    # XML ajouté
    has_xml_before = "<" in raw_prompt and ">" in raw_prompt
    has_xml_after = "<" in formatted_prompt and ">" in formatted_prompt
    if not has_xml_before and has_xml_after:
        research_impacts.append(
            {
                "feature": "📐 Structure XML ajoutée",
                "impact": "↔️ Variable",
                "range": "-5% à +40%",
                "source": "Voyce et al. 2024 (arXiv:2411.10541)",
                "note": "GPT-3.5 varie jusqu'à 40%, GPT-4 ~5%. Claude optimisé pour XML.",
            }
        )

    # Étapes numérotées
    has_steps_before = len(re.findall(r"^\s*\d+[\.\)]\s", raw_prompt, re.MULTILINE)) >= 2
    has_steps_after = len(re.findall(r"^\s*\d+[\.\)]\s", formatted_prompt, re.MULTILINE)) >= 2
    if not has_steps_before and has_steps_after:
        research_impacts.append(
            {
                "feature": "🔢 Étapes numérotées",
                "impact": "📈 Positif",
                "range": "+50% à +87%",
                "source": "Latitude 2025",
                "note": "Meilleure compliance aux instructions.",
            }
        )

    # Exemples (few-shot)
    example_markers = ["example:", "exemple:", "<example>", "input:", "output:"]
    has_examples_before = any(m in raw_prompt.lower() for m in example_markers)
    has_examples_after = any(m in formatted_prompt.lower() for m in example_markers)
    if not has_examples_before and has_examples_after:
        research_impacts.append(
            {
                "feature": "💡 Exemples (few-shot)",
                "impact": "📈 Positif",
                "range": "+7% à +12%",
                "source": "GPT-3 paper, Analytics Vidhya 2025",
                "note": "Plateau après 2-8 exemples.",
            }
        )

    # Chain-of-Thought
    cot_markers = ["step by step", "étape par étape", "think through"]
    has_cot_before = any(m in raw_prompt.lower() for m in cot_markers)
    has_cot_after = any(m in formatted_prompt.lower() for m in cot_markers)
    if not has_cot_before and has_cot_after:
        research_impacts.append(
            {
                "feature": "🧠 Chain-of-Thought",
                "impact": "↔️ Variable",
                "range": "-36% à +87%",
                "source": "Wei et al. 2022, Wharton 2025",
                "note": "⚠️ Excellent pour math/raisonnement, peut nuire sur d'autres tâches. +300% temps.",
            }
        )

    if research_impacts:
        lines.append("| Caractéristique | Impact | Plage | Source |")
        lines.append("|-----------------|--------|-------|--------|")
        for ri in research_impacts:
            lines.append(f"| {ri['feature']} | {ri['impact']} | {ri['range']} | {ri['source']} |")

        lines.append("\n**Notes des études:**")
        for ri in research_impacts:
            lines.append(f"- *{ri['feature']}*: {ri['note']}")
    else:
        lines.append("*Pas de changement majeur détecté par rapport aux études de référence.*")

    # ==========================================================================
    # SECTION 6: CE QU'ON NE PEUT PAS PRÉDIRE
    # ==========================================================================
    lines.append("\n---\n### ⚠️ Ce qu'on ne peut PAS prédire\n")
    lines.append("""
Sans tests A/B réels sur votre cas d'usage spécifique, il est **impossible** de prédire:

- ❌ Le % exact de "réponses utiles du premier essai"
- ❌ Le nombre d'itérations nécessaires
- ❌ Le temps économisé par tâche
- ❌ Le "risque de mauvaise interprétation"

*Ces métriques dépendent du modèle, de la tâche, et du contexte. Testez les deux versions!*
""")

    # ==========================================================================
    # SECTION 7: BONNES PRATIQUES
    # ==========================================================================
    lines.append("\n---\n### 📜 Bonnes Pratiques\n")
    lines.append("*Recommandations des principaux fournisseurs:*\n")

    lines.append("| Fournisseur | Recommandation |")
    lines.append("|-------------|----------------|")
    lines.append("| **Anthropic** | Utiliser des balises XML pour structurer les prompts |")
    lines.append("| **OpenAI** | Séparer clairement instructions et contexte |")
    lines.append("| **Google** | Fournir des exemples et du contexte détaillé |")

    lines.append("\n> 💡 **Consensus:** La structure claire améliore les résultats des LLM.")

    # ==========================================================================
    # SECTION 8: VERDICT HONNÊTE
    # ==========================================================================
    lines.append("\n---\n## 🎯 Verdict\n")

    if score_diff >= 20 and len(research_impacts) >= 2:
        lines.append("### ✅ Reformatage recommandé\n")
        lines.append(
            f"Le prompt reformaté ajoute {len(research_impacts)} caractéristique(s) "
            f"associée(s) à des améliorations dans la recherche publiée.\n"
        )
        lines.append(
            f"**Score structurel:** +{score_diff:.0f}% | **Expansion:** x{len_ratio:.1f}\n"
        )
        lines.append(
            "⚠️ *L'impact réel dépend de votre modèle et tâche. Les études montrent des résultats variables.*"
        )
    elif score_diff >= 10:
        lines.append("### 🟡 Reformatage potentiellement utile\n")
        lines.append(
            f"Amélioration structurelle de **+{score_diff:.0f}%**, mais l'impact réel dépend du contexte."
        )
        lines.append("\n*Testez les deux versions pour valider.*")
    elif len_ratio > 3.0:
        lines.append("### ⚠️ Attention: expansion importante\n")
        lines.append(
            f"Le prompt est **{len_ratio:.1f}x plus long** (+{(len_ratio-1)*100:.0f}% de tokens).\n"
        )
        lines.append(
            "Cette augmentation de coût n'est justifiée que si la qualité de sortie s'améliore significativement."
        )
        lines.append("\n*Testez pour vérifier si l'expansion apporte de la valeur.*")
    else:
        lines.append("### ➡️ Changements modérés\n")
        lines.append(
            "Le reformatage apporte des ajustements mineurs. L'impact dépendra de votre cas d'usage."
        )

    return "\n".join(lines)


def detect_task_type(prompt: str) -> str:
    """Détecte le type de tâche à partir du prompt."""
    prompt_lower = prompt.lower()

    code_keywords = [
        "code",
        "fonction",
        "function",
        "api",
        "endpoint",
        "bug",
        "debug",
        "refactor",
        "test",
        "class",
        "method",
        "variable",
        "import",
        "database",
        "sql",
        "query",
        "script",
        "algorithm",
        "implementation",
        "module",
        "library",
        "framework",
        "backend",
        "frontend",
        "crud",
        "route",
        "controller",
        "model",
        "schema",
        "migration",
        "deploy",
        "docker",
        "git",
        "commit",
        "branch",
        "merge",
        "pull request",
    ]

    analysis_keywords = [
        "analyse",
        "analyze",
        "research",
        "study",
        "compare",
        "evaluate",
        "review",
        "audit",
        "report",
        "summary",
        "synthesize",
        "document",
        "résumé",
        "synthèse",
        "données",
        "data",
        "statistics",
        "metrics",
        "benchmark",
        "performance",
        "optimize",
        "améliorer",
        "improve",
    ]

    creative_keywords = [
        "write",
        "create",
        "design",
        "imagine",
        "story",
        "article",
        "blog",
        "content",
        "creative",
        "idea",
        "concept",
        "brand",
        "écris",
        "rédige",
        "histoire",
        "récit",
        "poème",
        "slogan",
        "marketing",
        "publicité",
        "campagne",
        "narratif",
        "fiction",
    ]

    chat_keywords = [
        "explain",
        "help",
        "what is",
        "how to",
        "question",
        "answer",
        "clarify",
        "describe",
        "tell me",
        "explique",
        "aide",
        "comment",
        "pourquoi",
        "quest-ce",
        "définition",
        "definition",
        "meaning",
        "understand",
        "comprendre",
        "learn",
        "apprendre",
        "tutorial",
    ]

    code_score = sum(1 for k in code_keywords if k in prompt_lower)
    analysis_score = sum(1 for k in analysis_keywords if k in prompt_lower)
    creative_score = sum(1 for k in creative_keywords if k in prompt_lower)
    chat_score = sum(1 for k in chat_keywords if k in prompt_lower)

    if "<context>" in prompt_lower or "<task>" in prompt_lower:
        code_score += 2
    if "```" in prompt_lower:
        code_score += 3
    if "requirements" in prompt_lower or "specifications" in prompt_lower:
        code_score += 1

    scores = {
        "code": code_score,
        "analysis": analysis_score,
        "creative": creative_score,
        "chat": chat_score,
    }

    max_type = max(scores, key=scores.get)
    if scores[max_type] == 0:
        return "general"
    return max_type


def detect_domain(prompt: str) -> str:
    """Détecte le domaine du prompt pour une recommandation précise.

    Prompt et mots-clés passent par `normalize_for_matching()` avant
    comparaison : sans elle, « mots clés » et « mots cles » ne rencontraient
    aucune clé d'aucun domaine (D-057).
    """
    prompt_lower = normalize_for_matching(prompt)

    domains = {
        # === DOMAINES TECHNIQUES ===
        "code": [
            "code",
            "function",
            "api",
            "endpoint",
            "bug",
            "debug",
            "refactor",
            "test",
            "class",
            "method",
            "import",
            "database",
            "sql",
            "script",
            "algorithm",
            "backend",
            "frontend",
            "deploy",
            "docker",
            "git",
            "python",
            "javascript",
            "typescript",
            "react",
            "fastapi",
            "node",
            "variable",
            "compiler",
            "runtime",
            "library",
            "framework",
            "component",
        ],
        "data": [
            "data",
            "analytics",
            "dashboard",
            "report",
            "metrics",
            "kpi",
            "visualization",
            "statistics",
            "dataset",
            "csv",
            "excel",
            "tableau",
            "données",
            "rapport",
            "statistiques",
            "graphique",
            "bigquery",
            "snowflake",
            "sql query",
            "etl",
            "pipeline",
            "warehouse",
            "dbt",
            "looker",
            "powerbi",
        ],
        # === DOMAINES MÉTIERS (NOUVEAUX) ===
        "seo": [
            "seo",
            "keyword",
            "backlink",
            "serp",
            "ranking",
            "organic",
            "meta description",
            "title tag",
            "alt text",
            "sitemap",
            "robots.txt",
            "canonical",
            "indexation",
            "référencement",
            "mot-clé",
            "mots-clés",
            "position google",
            "search console",
            "ahrefs",
            "semrush",
            "moz",
            "domain authority",
            "page authority",
            "crawl",
            "longue traîne",
            "featured snippet",
            "core web vitals",
            "lighthouse",
        ],
        "marketing": [
            "marketing",
            "campaign",
            "ads",
            "advertising",
            "funnel",
            "conversion",
            "lead generation",
            "cac",
            "ltv",
            "roas",
            "ctr",
            "cpc",
            "cpm",
            "roi",
            "persona",
            "target audience",
            "ab test",
            "landing page",
            "copywriting",
            "email marketing",
            "newsletter",
            "automation",
            "hubspot",
            "mailchimp",
            "google ads",
            "facebook ads",
            "meta ads",
            "linkedin ads",
            "retargeting",
            "campagne",
            "publicité",
            "acquisition",
            "growth",
            "branding",
            "awareness",
        ],
        "hr": [
            "rh",
            "hr",
            "recrutement",
            "recruitment",
            "hiring",
            "candidate",
            "candidat",
            "job description",
            "fiche de poste",
            "onboarding",
            "offboarding",
            "talent",
            "entretien",
            "interview",
            "cv",
            "resume",
            "sourcing",
            "linkedin recruiter",
            "salaire",
            "salary",
            "compensation",
            "benefits",
            "avantages",
            "culture",
            "turnover",
            "retention",
            "performance review",
            "feedback",
            "formation",
            "training",
            "développement",
            "carrière",
            "mobilité",
            "ats",
            "lever",
            "greenhouse",
        ],
        "sales": [
            "sales",
            "vente",
            "commercial",
            "prospect",
            "prospection",
            "pipeline",
            "deal",
            "closing",
            "négociation",
            "negotiation",
            "objection",
            "pitch",
            "crm",
            "salesforce",
            "hubspot",
            "pipedrive",
            "cold email",
            "cold call",
            "discovery call",
            "demo",
            "proposal",
            "devis",
            "pricing",
            "discount",
            "quota",
            "forecast",
            "revenue",
            "arr",
            "mrr",
            "churn",
            "upsell",
            "cross-sell",
            "account executive",
            "sdr",
            "bdr",
            "account manager",
            "client",
            "customer",
        ],
        "product": [
            "product",
            "produit",
            "roadmap",
            "backlog",
            "user story",
            "epic",
            "sprint",
            "agile",
            "scrum",
            "kanban",
            "jira",
            "linear",
            "notion",
            "productboard",
            "prd",
            "spec",
            "specification",
            "feature",
            "mvp",
            "pmf",
            "product market fit",
            "user research",
            "discovery",
            "a/b test",
            "north star",
            "okr",
            "kpi",
            "prioritization",
            "rice",
            "ice",
            "moscow",
            "stakeholder",
            "release",
        ],
        "support": [
            "support client",
            "customer service",
            "helpdesk",
            "ticket support",
            "zendesk",
            "intercom",
            "freshdesk",
            "crisp",
            "csat",
            "nps support",
            "satisfaction client",
            "complaint",
            "plainte",
            "resolution ticket",
            "escalation",
            "sla support",
            "response time",
            "first contact resolution",
            "knowledge base",
            "faq",
            "help center",
            "chatbot support",
            "live chat",
            "service client",
            "customer success manager",
            "onboarding client",
            "churn prevention",
            "client mécontent",
            "répondre au ticket",
            "problème client",
            "réclamation",
            "assistance",
        ],
        # === DOMAINES SPÉCIALISÉS ===
        "legal": [
            "legal",
            "law",
            "contract",
            "clause",
            "attorney",
            "lawyer",
            "court",
            "juridique",
            "contrat",
            "avocat",
            "tribunal",
            "loi",
            "règlement",
            "compliance",
            "regulation",
            "litigation",
            "lawsuit",
            "patent",
            "rgpd",
            "gdpr",
            "cnil",
            "dpo",
            "nda",
            "cgv",
            "cgu",
            "propriété intellectuelle",
        ],
        "medical": [
            "medical",
            "health",
            "doctor",
            "patient",
            "diagnosis",
            "treatment",
            "symptom",
            "disease",
            "medication",
            "clinical",
            "hospital",
            "médical",
            "santé",
            "médecin",
            "diagnostic",
            "traitement",
            "maladie",
            "diabète",
            "hypertension",
            "fatigue",
            "douleur",
            "fièvre",
        ],
        "finance": [
            "financial",
            "investment",
            "stock",
            "trading",
            "portfolio",
            "revenue",
            "profit",
            "accounting",
            "audit",
            "tax",
            "budget",
            "forecast",
            "financier",
            "investissement",
            "bourse",
            "comptabilité",
            "impôt",
        ],
        "creative": [
            "write",
            "story",
            "article",
            "blog",
            "creative",
            "poem",
            "fiction",
            "narrative",
            "script",
            "screenplay",
            "novel",
            "content",
            "écris",
            "histoire",
            "récit",
            "créatif",
            "rédaction",
        ],
        "research": [
            "research",
            "study",
            "analyze",
            "paper",
            "thesis",
            "literature",
            "scientific",
            "academic",
            "peer-review",
            "hypothesis",
            "experiment",
            "recherche",
            "étude",
            "analyse",
            "scientifique",
            "académique",
        ],
        "math": [
            "math",
            "equation",
            "calcul",
            "formula",
            "proof",
            "theorem",
            "algebra",
            "geometry",
            "calculus",
            "probability",
            "statistics",
            "mathématique",
            "équation",
            "formule",
            "preuve",
            "théorème",
        ],
        "image": [
            "image",
            "picture",
            "photo",
            "illustration",
            "generate image",
            "draw",
            "visual",
            "artwork",
            "design",
            "logo",
            "banner",
            "poster",
            "graphic",
            "midjourney",
            "dall-e",
            "dalle",
            "stable diffusion",
            "flux",
            "génère une image",
            "dessine",
            "crée une image",
            "illustre",
        ],
        "document": [
            "document",
            "pdf",
            "file",
            "read",
            "extract",
            "summarize document",
            "analyze document",
            "ocr",
            "scan",
            "attachment",
            "upload",
            "fichier",
            "lire",
            "extraire",
            "résumer le document",
            "pièce jointe",
        ],
    }

    scores = {}
    for domain, keywords in domains.items():
        scores[domain] = sum(1 for k in keywords if normalize_for_matching(k) in prompt_lower)

    # Protection des domaines spécialisés (ne pas écraser par 'code' si match fort)
    protected_domains = [
        "legal",
        "medical",
        "finance",
        "math",
        "image",
        "document",
        "creative",
        "seo",
        "marketing",
        "hr",
        "sales",
        "product",
        "support",
    ]
    max_protected = max(protected_domains, key=lambda d: scores.get(d, 0))
    protected_score = scores.get(max_protected, 0)

    if protected_score < 1:
        prompt_for_code_check = prompt_lower
        for xml_tag in [
            "<context>",
            "</context>",
            "<task>",
            "</task>",
            "<requirements>",
            "</requirements>",
            "<output_format>",
            "</output_format>",
        ]:
            prompt_for_code_check = prompt_for_code_check.replace(xml_tag, "")

        real_code_patterns = [
            "```",
            "def ",
            "function ",
            "class ",
            "import ",
            "const ",
            "let ",
            "var ",
        ]
        has_real_code = any(pattern in prompt_for_code_check for pattern in real_code_patterns)

        if has_real_code:
            scores["code"] = scores.get("code", 0) + 3

    max_domain = max(scores, key=scores.get)
    if scores[max_domain] == 0:
        return "general"
    return max_domain
