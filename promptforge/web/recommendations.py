"""
Recommandations de modeles pour l'interface web de PromptForge.

**Aucune note de qualite n'est produite ni affichee par ce module.** Ni pour les
modeles locaux, ni pour les modeles cibles. Motif (D-021, DEC-004 §1) : les
`reformat_score` d'`OLLAMA_MODELS_INFO` — quatorze notes de 68 a 99 — et les
dix-huit couples note/justification par modele de `DOMAIN_EXPERTISE` n'avaient
aucune source, aucune mesure et aucune methodologie dans le depot.
`agent-veille` a confirme deux fois, a quatre jours d'ecart, qu'aucune source
officielle ne publie de score de suivi de format, pour aucun modele : ces notes
ne pouvaient donc pas etre sourcees, elles sont supprimees sans attendre leur
remplacant. Le banc de mesure (DEC-004 §2) reintroduira des chiffres mesures.

Ce que ce module classe, et sur quoi (DEC-006) :

- Les **modeles locaux** sont ordonnes sur leur empreinte memoire d'inference,
  lue dans `promptforge.models_catalog`, seule source du depot pour ce fait.
  Rien n'est recalcule ici : `by_memory_footprint()` et `group_by_memory_tier()`
  font le classement, l'interface le met en forme.
- Les **modeles cibles** sont ordonnes sur leur cout estime, compose depuis
  `MODEL_PRICING`, qui porte l'URL de sa source et sa date de verification.

Ni l'un ni l'autre n'est un classement de qualite, et l'interface le dit
explicitement a chaque rendu plutot que de laisser croire que le premier de la
liste est « le meilleur ».
"""

from ..models_catalog import (
    CATALOG,
    LICENSE_OSI_APPROVED,
    LICENSE_OSI_UNDETERMINED,
    LocalModel,
    get_memory_tier,
    group_by_memory_tier,
)
from ..profiles import MODEL_PRICING, compare_models
from ..tokens import estimate_tokens
from .analysis import detect_domain
from .profiles_ui import format_context_window

# =============================================================================
# Ce que les classements ne disent pas, ecrit noir sur blanc.
#
# Ces phrases ne sont pas decoratives : sans elles, un ordre reste un jugement
# implicite. Un ordre provisoire annonce comme tel n'est pas une affirmation non
# fondee ; un ordre silencieux en serait une (F-021).
# =============================================================================

#: Rappel affiche partout ou des modeles locaux sont ordonnes.
LOCAL_ORDER_DISCLAIMER = (
    "Classement par empreinte memoire, pas par qualite. La qualite de "
    "reformatage de ces modeles n'est **pas mesuree a ce jour** dans ce depot : "
    "le premier de la liste est le plus lourd, pas le meilleur."
)

#: Rappel affiche partout ou des modeles cibles sont ordonnes.
CLOUD_ORDER_DISCLAIMER = (
    "Classement par cout estime, seule grandeur sourcee ici. La pertinence de "
    "chaque modele pour ce domaine n'est **pas mesuree** : le depot ne contient "
    "ni banc d'evaluation, ni note publiee par un editeur."
)

#: Affiche quand un tag Ollama n'est pas au catalogue. Aucune valeur n'est
#: devinee a la place : servir silencieusement l'entree d'un modele voisin est
#: precisement ce que faisait l'ancien appariement partiel.
UNKNOWN_MODEL_NOTICE = (
    "Ce tag n'est pas au catalogue source : ni empreinte memoire, ni licence, "
    "ni fenetre de contexte connues. Rien n'est estime a sa place."
)

DOMAIN_LABELS = {
    "code": "💻 Code/Dev",
    "legal": "⚖️ Juridique",
    "medical": "🏥 Médical/Santé",
    "finance": "💹 Finance",
    "creative": "✨ Créatif",
    "research": "🔬 Recherche",
    "data": "📊 Data/Analytics",
    "math": "🔢 Mathématiques",
    "image": "🎨 Génération d'Images",
    "document": "📄 Analyse de Documents",
    "general": "🔧 Général",
    "analysis": "📊 Analyse",
    "chat": "💬 Chat",
    # Domaines métiers
    "seo": "🔍 SEO/Référencement",
    "marketing": "📢 Marketing Digital",
    "hr": "👥 RH/Recrutement",
    "sales": "💼 Commercial/Ventes",
    "product": "🎯 Product Management",
    "support": "🎧 Support Client",
}


# =============================================================================
# Mise en forme des faits du catalogue
#
# Ces helpers ne decident rien : ils rendent lisible ce que `models_catalog`
# porte deja. Aucun seuil, aucun palier et aucun ordre n'est recree ici.
# =============================================================================


def _gb(value: float) -> str:
    """Nombre de Go sans zero decimal inutile : 6.0 -> « 6 », 10.5 -> « 10,5 »."""
    return f"{value:g}".replace(".", ",")


def format_memory_footprint(model: LocalModel) -> str:
    """Empreinte memoire lisible, avec la nature du chiffre.

    La fourchette est celle du catalogue, transcrite telle quelle. « estimée »
    et « publiée » ne sont pas un detail de style : `memory_footprint_basis`
    distingue un chiffre publie par la fiche officielle d'une estimation
    d'ingenierie de la veille, et l'utilisateur a droit a la difference.
    """
    if model.memory_footprint_low_bytes == model.memory_footprint_bytes:
        span = f"{_gb(model.memory_footprint_gb)} Go"
    else:
        span = f"{_gb(model.memory_footprint_low_gb)}–{_gb(model.memory_footprint_gb)} Go"
    nature = "estimée" if model.memory_footprint_is_estimated else "publiée"
    return f"{span} ({nature})"


def format_license(model: LocalModel) -> str:
    """Licence annoncee, avec sa qualification OSI.

    Les trois etats du catalogue sont rendus distinctement : un « non
    determine » n'est pas presente comme un feu vert.
    """
    if model.license_osi_status == LICENSE_OSI_APPROVED:
        return f"{model.license_name} (OSI)"
    if model.license_osi_status == LICENSE_OSI_UNDETERMINED:
        return f"{model.license_name} (OSI non déterminé)"
    return f"{model.license_name} (hors définition OSI)"


def get_ollama_model_info(ollama_model: str) -> dict | None:
    """Faits connus sur un tag Ollama, ou l'aveu qu'il est inconnu.

    Aucun appariement partiel : l'ancien code faisait
    `model_lower.split(':')[0] == key.split(':')[0]`, ce qui servait les
    donnees de `qwen3:32b` a qui demandait `qwen3:1.7b`. Un tag absent du
    catalogue rend `known=False` et rien d'autre — pas d'empreinte devinee, pas
    de note, pas de `KeyError` non plus, l'appelant etant une interface.

    Returns:
        dict | None: ``None`` si aucun modele n'est passe. Sinon un dict portant
        toujours `name` et `known`, et les faits du catalogue si `known`.
    """
    if not ollama_model:
        return None

    model = CATALOG.get(ollama_model.strip())
    if model is None:
        return {"name": ollama_model, "known": False}

    return {
        "name": model.tag,
        "known": True,
        "memory": format_memory_footprint(model),
        "tier_label": model.memory_tier_label,
        "license": format_license(model),
        "source_url": model.source_url,
        "verified_on": model.verified_on,
    }


def _local_catalog_lines() -> list[str]:
    """Le catalogue local, du plus lourd au plus leger, par palier memoire.

    Le decoupage et l'ordre viennent de `group_by_memory_tier()` : les
    reconstituer ici recreerait la seconde verite que le catalogue supprime
    (D-022). Les paliers vides ne sont pas rendus, ils n'apprennent rien.
    """
    lines = [
        "\n---",
        "### 🧩 Modèles locaux du catalogue, du plus lourd au plus léger\n",
        f"> {LOCAL_ORDER_DISCLAIMER}\n",
    ]
    grouped = group_by_memory_tier()
    for tier_id, models in grouped.items():
        if not models:
            continue
        lines.append(f"**{get_memory_tier(tier_id).label}**\n")
        lines.append("| Modèle | Empreinte mémoire | Licence |")
        lines.append("|--------|-------------------|---------|")
        for model in models:
            lines.append(
                f"| `{model.tag}` | {format_memory_footprint(model)} "
                f"| {format_license(model)} |"
            )
        lines.append("")
    return lines


def generate_recommendation(
    formatted_prompt: str, task_type: str, ollama_model: str = None, domain_override: str = None
) -> str:
    """Compose le panneau de recommandation affiche apres un reformatage.

    Args:
        formatted_prompt: Le prompt reformate.
        task_type: Type de tache detecte.
        ollama_model: Tag du modele Ollama ayant servi au reformatage.
        domain_override: Force un domaine au lieu de le detecter.

    Returns:
        str: texte Markdown. Aucune note de qualite n'y figure ; les deux
        classements rendus portent leur critere et sa limite.
    """
    input_tokens = estimate_tokens(formatted_prompt)
    output_multiplier = {
        "code": 2.5,
        "legal": 1.5,
        "medical": 1.2,
        "finance": 1.5,
        "creative": 2.0,
        "research": 1.5,
        "data": 1.5,
        "math": 1.0,
        "analysis": 1.5,
        "chat": 0.8,
        "general": 1.5,
        "image": 0.5,
        "document": 2.0,
    }
    output_tokens = int(input_tokens * output_multiplier.get(task_type, 1.5))

    domain = domain_override if domain_override else detect_domain(formatted_prompt)
    domain_display = DOMAIN_LABELS.get(domain, "🔧 Général")

    ollama_info = get_ollama_model_info(ollama_model)

    lines = [
        "### 🎯 Analyse pour ce prompt",
        f"**Domaine détecté:** {domain_display} | "
        f"**Tokens:** ~{input_tokens:,} input → ~{output_tokens:,} output\n",
    ]

    # --- Modèle local ayant servi au reformatage -----------------------------
    if ollama_info:
        lines.append("---")
        lines.append("### 🔧 Modèle de reformatage (local)\n")

        if ollama_info["known"]:
            lines.append("| Modèle | Empreinte mémoire | Palier | Licence | Coût |")
            lines.append("|--------|-------------------|--------|---------|------|")
            lines.append(
                f"| **{ollama_info['name']}** | {ollama_info['memory']} "
                f"| {ollama_info['tier_label']} | {ollama_info['license']} | **$0** |"
            )
            lines.append(
                f"\n📚 Source : {ollama_info['source_url']} "
                f"(vérifié le {ollama_info['verified_on']})"
            )
        else:
            lines.append(f"**{ollama_info['name']}** — ⚠️ {UNKNOWN_MODEL_NOTICE}")

        lines.append(f"\n⚠️ {LOCAL_ORDER_DISCLAIMER}")

    lines.extend(_local_catalog_lines())

    # --- Modèles cibles, ordonnés sur le coût --------------------------------
    #
    # Itère sur MODEL_PRICING, jamais sur TargetModel : un adapter d'interface
    # n'énumère pas exhaustivement une énumération du domaine (F-022 bloc 2,
    # critère 10 de F-021).
    all_models = []
    for model, pricing in MODEL_PRICING.items():
        all_models.append(
            {
                "model": model,
                # Nom commercial publié par l'éditeur, pas l'identifiant d'API :
                # cette table est lue par un humain (F-028).
                "name": pricing.display_name or model.value,
                "cost": pricing.estimate_cost(input_tokens, output_tokens),
                "context": format_context_window(pricing) or "non confirmé",
                "source_url": pricing.source_url,
            }
        )

    all_models.sort(key=lambda m: (m["cost"], m["name"]))

    lines.append("\n---")
    lines.append(f"### 💵 Coût estimé pour exécuter ce prompt ({domain_display})\n")
    lines.append(f"> {CLOUD_ORDER_DISCLAIMER}\n")
    lines.append("| # | Modèle | Coût estimé | Contexte |")
    lines.append("|---|--------|-------------|----------|")
    for i, m in enumerate(all_models, 1):
        lines.append(f"| {i} | **{m['name']}** | ${m['cost']:.4f} | {m['context']} |")

    cheapest = all_models[0]
    lines.append(
        f"\n💰 **Le moins cher pour ce prompt :** {cheapest['name']} " f"(${cheapest['cost']:.4f})"
    )

    # --- Sources des tarifs affichés -----------------------------------------
    #
    # Les URL viennent de MODEL_PRICING, donc de la table réellement affichée.
    # L'ancienne liste `BENCHMARK_SOURCES` renvoyait vers des annonces de
    # générations révolues (Claude Opus 4.5, GPT-5) et ne sourçait plus rien de
    # ce qui restait à l'écran : elle est supprimée (DEC-004 §1).
    sources = sorted({m["source_url"] for m in all_models if m["source_url"]})
    if sources:
        lines.append("\n---")
        lines.append("### 📚 Sources des tarifs\n")
        lines.extend(f"- {url}" for url in sources)

    # --- Ce que rien ne dit --------------------------------------------------
    lines.append("\n---")
    lines.append("### 💡 Ce que ces deux classements ne disent pas\n")
    lines.append(
        "Aucun modèle n'est **recommandé** sur la qualité de sortie : ni ce "
        "dépôt, ni aucune documentation d'éditeur consultée ne publie de mesure "
        "de suivi de format par modèle. Les notes maison qui figuraient ici "
        "n'avaient pas de source et ont été retirées."
    )

    return "\n".join(lines)


def get_comparison_table() -> str:
    """Table de comparaison des modèles cibles, ordonnée par coût croissant.

    La colonne « Tier » (`🔥 Premium`, `⚡ Performant`, `💰 Économique`) n'est
    plus rendue. Elle venait de `profiles._get_model_tier()`, qui câblait les
    paliers par liste de membres, sans mesure ni source : deux modèles au tarif
    identique au dollar près en sortaient dans deux paliers différents. La
    fonction a depuis été **supprimée** (D-071), et non remplacée par un palier
    dérivé du tarif : la valeur serait sourçable, les bornes ne le seraient pas.
    """
    comparisons = compare_models(1000, 500)

    lines = [
        "| Modèle | Input/M | Output/M | Contexte | Coût 1K+500 |",
        "|--------|---------|----------|----------|-------------|",
    ]

    # `label` et non `model` : le tableau s'adresse a l'utilisateur, pas a un
    # appel d'API. L'identifiant exact reste disponible dans `c['model']`.
    for c in comparisons:
        lines.append(
            f"| {c['label']} | {c['input_price']} | {c['output_price']} | "
            f"{c['context']} | {c['cost_display']} |"
        )

    return "\n".join(lines)


def calculate_costs(input_tokens: int, output_tokens: int) -> str:
    """Coût de chaque modèle cible pour un volume de tokens donné.

    Le modèle le plus cher était étiqueté « 🔥 Le plus puissant » (D-070). Le
    tri porte sur le coût ; la puissance n'est ni mesurée ni sourcée nulle part
    dans le dépôt. L'étiquette dit donc ce qui est réellement mesuré : un prix.
    """
    if not input_tokens or not output_tokens:
        return "⚠️ Entre le nombre de tokens"

    comparisons = compare_models(int(input_tokens), int(output_tokens))

    lines = [
        f"### 💵 Coût estimé pour {int(input_tokens):,} input + "
        f"{int(output_tokens):,} output tokens\n",
        "| Modèle | Coût |",
        "|--------|------|",
    ]

    for c in comparisons:
        lines.append(f"| {c['label']} | **{c['cost_display']}** |")

    cheapest = comparisons[0]
    most_expensive = comparisons[-1]

    lines.append(f"\n**💰 Le moins cher:** {cheapest['label']} ({cheapest['cost_display']})")
    lines.append(
        f"\n**💸 Le plus cher:** {most_expensive['label']} " f"({most_expensive['cost_display']})"
    )
    lines.append(f"\n> {CLOUD_ORDER_DISCLAIMER}")

    return "\n".join(lines)
