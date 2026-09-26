"""
Profile selection UI helpers for PromptForge web interface.

Aucun tarif ni aucune fenetre de contexte n'est ecrit en dur dans ce module.
Ces valeurs sont composees au rendu depuis `promptforge.profiles.MODEL_PRICING`,
seule source du domaine, qui porte desormais l'URL de la source et la date de
verification de chaque entree (F-022, DEC-004, DEC-005, DEC-009).

Motif : avant F-022, trois tarifs et une fenetre de contexte divergeaient entre
le domaine et l'affichage, et un libelle avait ete corrige a la main sans que la
source le soit. Une valeur affichee ne se recopie plus, elle se compose.

Le format annonce dans chaque libelle est celui que produit reellement le
prompt systeme du profil, verifie profil par profil le 2026-09-07 : XML pour
Claude et Gemini, Markdown pour les trois profils GPT, XML ou Markdown au choix
pour le profil universel. Les libelles annoncaient `[XML]` pour GPT alors que
`SYSTEM_PROMPT_GPT_*` demande du Markdown, et `[XML]` pour le profil universel
alors que DEC-008 lui interdit d'imposer une syntaxe (F-028).

Les modeles cibles sont ceux de la gamme reellement disponible au 2026-09-07 :
`gemini-3-pro` (arrete), `gemini-3-flash` (deprecie) et `gpt-5.1-mini` (jamais
existe) ont ete retires du domaine par F-028, leurs libelles avec.

**Aucune aptitude non mesuree n'est plus annoncee (D-071, DEC-004 §1).** Les
libelles et les puces affirmaient des capacites que le depot ne connait pas :
« Meilleur pour: Documents longs, codebases entieres » pour Gemini 3.1 Pro,
dont la fenetre de contexte est explicitement **non confirmee** dans
`MEMORY/VEILLE.md` (fiche Google en 404 le 2026-09-07) ; « Economique » et
« Budget, volume eleve » pour GPT-5.6 Terra, dont `MODEL_PRICING` dit qu'il
coute **plus cher** que GPT-5.1 ; « Instruction following chirurgical »,
« Ultra-rapide », « Deep thinking », qu'aucune source du depot ne mesure. Ce
qui subsiste est de trois natures seulement : le format produit par le prompt
systeme du profil, les relations de succession et les dates de retrait
publiees par l'editeur et consignees dans la veille, et les balises que le
profil emet. Tout le reste — tarif, fenetre de contexte, provenance — est
compose au rendu depuis `MODEL_PRICING`.
"""

from ..profiles import MODEL_PRICING, PRESET_PROFILES, TargetModel

# Description courte de chaque profil, SANS tarif ni fenetre de contexte :
# ces deux valeurs sont ajoutees au rendu par `_compose_label()`.
# Les cles doivent rester alignees sur celles de `PRESET_PROFILES`
# (verrou : tests/test_game_changer.py::TestProfilesUiDomainParity).
# Chaque description dit ce que la veille etablit : la generation du modele,
# sa relation de succession, son etat de retrait ou l'etat de sa fenetre de
# contexte. Aucune n'annonce d'aptitude ni de qualite : le depot n'en mesure
# aucune (D-071).
PROFILE_DESCRIPTIONS = {
    # Claude (Anthropic) - XML, recommandé par Anthropic
    "claude_opus_5": "🟣 Claude Opus 5 — Génération courante de la gamme Opus [XML]",
    "claude_sonnet_5": "🟣 Claude Sonnet 5 — Génération courante de la gamme Sonnet [XML]",
    "claude_haiku_4.5": "🟣 Claude Haiku 4.5 — Aucun successeur publié à ce jour [XML]",
    # GPT (OpenAI) - Markdown, c'est ce que produisent SYSTEM_PROMPT_GPT_*
    "gpt_5.1": "🟢 GPT-5.1 — Aucun retrait annoncé [Markdown]",
    "gpt_5.6_terra": "🟢 GPT-5.6 Terra — Successeur désigné de GPT-5 Mini [Markdown]",
    "gpt_5_pro": "🟢 GPT-5 Pro — Retrait annoncé au 11 déc. 2026 [Markdown]",
    # Gemini (Google) - XML par convention de produit ; Google documente XML
    # et Markdown comme equivalents, la seule exigence etant la coherence
    # (DEC-007 volet 2)
    "gemini_3.1_pro": "🔵 Gemini 3.1 Pro — Preview, fenêtre de contexte non confirmée [XML]",
    "gemini_3.6_flash": "🔵 Gemini 3.6 Flash — Tarif d'introduction jusqu'à fin 2026 [XML]",
    # Universel - ne cible aucun modele, n'impose donc aucune syntaxe (DEC-008)
    "universel": "⚪ Universel — Aucun modèle ciblé, compatible tous [XML ou Markdown]",
}


# Contenu statique du panneau de detail : ni tarif, ni fenetre de contexte.
# Ces lignes sont ajoutees au rendu depuis MODEL_PRICING.
# Aucune puce ne reprend une mesure attachee a un modele different de celui
# qu'elle decrit : les chiffres de Claude Opus 4.5 ne sont pas ceux d'Opus 5,
# ceux de Gemini 3 Pro ne sont pas ceux de Gemini 3.1 Pro (F-028).
PROFILE_DETAILS = {
    "claude_opus_5": {
        "title": "**🟣 Claude Opus 5** — Format: XML (recommandé par Anthropic)",
        "bullets": [
            "Remplace Claude Opus 4.5, dont le plancher de retrait était le plus proche",
            "Aucun retrait annoncé avant le 24 juil. 2027, le plus long délai de la gamme Opus",
            "Balises: <task>, <context>, <thinking>, <instructions>, <constraints>, <output_format>",
        ],
    },
    "claude_sonnet_5": {
        "title": "**🟣 Claude Sonnet 5** — Format: XML (recommandé par Anthropic)",
        "bullets": [
            "Remplace Claude Sonnet 4.5, et coûte moins cher que lui",
            "Tarif d'introduction confirmé définitif : la hausse prévue est annulée",
            "Balises: <task>, <context>, <instructions>, <constraints>, <output_format>",
        ],
    },
    "claude_haiku_4.5": {
        "title": "**🟣 Claude Haiku 4.5** — Format: XML (recommandé par Anthropic)",
        "bullets": [
            "Aucun successeur publié à ce jour : modèle à surveiller",
            "Aucun retrait annoncé avant le 15 oct. 2026",
            "Balises: <task>, <context>, <instructions>, <output_format>",
        ],
    },
    "gpt_5.1": {
        "title": "**🟢 GPT-5.1** — Format: Markdown (point de départ recommandé par OpenAI)",
        "bullets": [
            "Aucun retrait annoncé pour l'identifiant de base",
            "Les variantes `chat-latest` et `codex` sont arrêtées depuis le 23 juil. 2026",
            "Sections: Contexte, Objectif, Exigences, Contraintes, Format de sortie",
        ],
    },
    "gpt_5.6_terra": {
        "title": "**🟢 GPT-5.6 Terra** — Format: Markdown",
        "bullets": [
            "Remplaçant officiellement désigné par OpenAI pour `gpt-5-mini`",
            "Fenêtre de contexte non confirmée : fiche modèle non ouverte le 2026-09-07",
            "Sections courtes: Objectif, Exigences, Format de sortie",
        ],
    },
    "gpt_5_pro": {
        "title": "**🟢 GPT-5 Pro** — Format: Markdown détaillé",
        "bullets": [
            "Retrait annoncé au 11 déc. 2026 : modèle à surveiller",
            "Remplaçant officiel désigné par OpenAI : GPT-5.6 Sol en mode raisonnement étendu",
            "Sections: Définition du problème, Contexte, Analyse requise, Contraintes",
        ],
    },
    "gemini_3.1_pro": {
        "title": "**🔵 Gemini 3.1 Pro** — Format: XML retenu par le produit (Preview)",
        "bullets": [
            "Remplaçant officiel de Gemini 3 Pro, arrêté le 9 mars 2026",
            "Statut « Preview » annoncé par Google",
            "Fenêtre de contexte non reconfirmée : fiche Google inaccessible le 2026-09-07",
            "Balises: <task>, <context>, <instructions>, <constraints>, <output_format>",
        ],
    },
    "gemini_3.6_flash": {
        "title": "**🔵 Gemini 3.6 Flash** — Format: XML retenu par le produit",
        "bullets": [
            "Remplaçant officiel de Gemini 3 Flash, déprécié",
            "Tarif d'introduction jusqu'au 31 décembre 2026, plus élevé ensuite",
            "Balises courtes: <task>, <context>, <instructions>, <output_format>",
        ],
    },
    "universel": {
        "title": "**⚪ Universel** — Format: balises XML ou titres Markdown, au choix",
        "bullets": [
            "Ne désigne aucun modèle réel : aucun tarif ne peut lui être attribué",
            "N'impose aucune syntaxe : il ne vise aucun éditeur, il ne peut en citer aucun",
            "Exige une seule convention tenue d'un bout à l'autre du prompt",
            "Compatible avec tous les LLM modernes (Claude, GPT, Gemini, Mistral, Llama)",
            "À utiliser quand le modèle cible n'est pas encore choisi",
        ],
    },
}


def get_pricing_for_profile(profile_name: str):
    """Retourne le `ModelPricing` du profil, ou None si le profil est inconnu.

    Passe par `PRESET_PROFILES` et non par `get_profile()`, dont le repli muet
    sur « universel » servirait le tarif d'un autre modèle sans le dire
    (D-029, corrigé par F-029).
    """
    profile = PRESET_PROFILES.get(profile_name)
    if profile is None:
        return None
    return profile.pricing or MODEL_PRICING.get(profile.target_model)


def _shows_pricing(profile_name: str) -> bool:
    """Le profil universel ne désigne aucun modèle réel : pas de tarif affiché.

    Depuis F-028, il n'a plus d'entrée du tout dans `MODEL_PRICING` : sa moyenne
    synthétique a été supprimée du domaine (D-032, DEC-004 §1). Ce garde reste
    en place comme second verrou, pour que le jour où quelqu'un recrée une
    entrée « universelle » elle ne s'affiche pas pour autant.
    """
    profile = PRESET_PROFILES.get(profile_name)
    return profile is not None and profile.target_model is not TargetModel.UNIVERSAL


def _money(value: float) -> str:
    """Formate un montant sans zéro décimal inutile : 5.0 -> '5', 1.25 -> '1.25'."""
    return f"{value:g}"


def format_price_short(pricing) -> str:
    """Tarif compact « $5/$25 » composé depuis le domaine. Vide si inconnu."""
    if pricing is None:
        return ""
    return f"${_money(pricing.input_price)}/${_money(pricing.output_price)}"


def format_context_window(pricing) -> str:
    """Fenêtre de contexte lisible (« 200K », « 1M ») composée depuis le domaine.

    Rend une chaîne vide quand la fenêtre n'est pas confirmée par une source :
    trois modèles cibles sont dans ce cas depuis F-028. Un « 0K » ou la reprise
    du chiffre de la génération précédente serait une valeur inventée.
    """
    if pricing is None or pricing.context_window is None:
        return ""
    window = pricing.context_window
    if window >= 1_000_000 and window % 1_000_000 == 0:
        return f"{window // 1_000_000}M"
    return f"{window // 1_000}K"


def format_pricing_source(pricing) -> str:
    """Mention de provenance du tarif, telle que portée par le domaine.

    Une source vide n'est pas masquée : elle est signalée comme non vérifiée
    (D-032, résorption prévue par F-028).
    """
    if pricing is None:
        return ""
    if not pricing.source_url:
        return "⚠️ Tarif non confirmé par une source officielle"
    if pricing.verified_on:
        return f"Source: {pricing.source_url} (vérifié le {pricing.verified_on})"
    return f"Source: {pricing.source_url}"


def _compose_label(profile_name: str) -> str:
    """Libellé affiché d'un profil : description statique + tarif composé.

    Remplace `get_profile_label()`, qui portait la même logique sans avoir le
    moindre appelant (R-009). Elle n'est pas repointée, elle est branchée :
    `get_profile_choices()` la consomme désormais, ce qui rend enfin visibles
    les descriptions de `PROFILE_DESCRIPTIONS`. Sans cela, supprimer la
    fonction aurait laissé le dictionnaire entier en donnée morte, dont seules
    les clés servaient encore.
    """
    description = PROFILE_DESCRIPTIONS.get(profile_name)
    if description is None:
        return profile_name
    if not _shows_pricing(profile_name):
        return description
    price = format_price_short(get_pricing_for_profile(profile_name))
    return f"{description} ({price})" if price else description


def get_profile_choices() -> list[tuple[str, str]]:
    """Choix du menu déroulant, sous la forme (libellé affiché, clé de profil).

    Le menu affichait la clé brute (`claude_opus_5`, `gemini_3.1_pro`) : un
    identifiant technique là où l'utilisateur attend un nom de produit. Gradio
    accepte des couples et ne transmet que le second membre aux gestionnaires,
    donc `get_profile_info()` et le reformatage continuent de recevoir la clé.
    """
    return [(_compose_label(name), name) for name in PROFILE_DESCRIPTIONS]


def get_profile_info(profile_name: str) -> str:
    """Return detailed info about a profile.

    Le tarif, la fenêtre de contexte et la provenance sont lus dans
    MODEL_PRICING au moment du rendu : aucune copie n'est conservée ici.
    """
    details = PROFILE_DETAILS.get(profile_name)
    if details is None:
        return f"**{profile_name}**\nProfil de reformatage XML standard."

    lines = [details["title"]]
    lines.extend(f"- {bullet}" for bullet in details["bullets"])

    pricing = get_pricing_for_profile(profile_name)
    if pricing is not None and _shows_pricing(profile_name):
        window = format_context_window(pricing)
        if window:
            lines.append(f"- Contexte: {window} tokens")
        else:
            lines.append("- Contexte: non confirmé par une source officielle")
        lines.append(
            f"- Prix: ${_money(pricing.input_price)}/M input, "
            f"${_money(pricing.output_price)}/M output"
        )
        lines.append(f"- {format_pricing_source(pricing)}")

    return "\n".join(lines)
