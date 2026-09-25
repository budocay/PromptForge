"""
Profils de reformatage optimisés pour différents modèles LLM.

Identifiants, tarifs et fenêtres de contexte vérifiés le 2026-09-07 sur les
pages officielles Anthropic, OpenAI et Google (cf. MEMORY/VEILLE.md, section
« Modèles cibles du reformatage et tarifs »).

Trois règles tiennent ce fichier (les deux premières de F-028, la troisième
de D-071) :

1. `TargetModel` ne porte que des identifiants d'API réels et actifs. Un modèle
   arrêté (`gemini-3-pro-preview`, arrêté le 2026-03-09) ou un identifiant sans
   existence connue (`gpt-5.1-mini`, 404 confirmé le 2026-09-03 puis le
   2026-09-07) proposerait à l'utilisateur une cible qu'il ne peut pas
   atteindre.
2. Une valeur non confirmée vaut `None`, jamais la reprise du chiffre de la
   génération précédente. Trois fenêtres de contexte sont dans ce cas : les
   fiches modèles Google ont répondu 404 le 2026-09-07 et celle de
   `gpt-5.6-terra` n'a pas été rouverte.
3. Une comparaison n'affiche aucune appréciation que les tarifs ne portent pas
   (D-071). Le palier « Premium / Performant / Économique » a été retiré : il
   était câblé par deux listes de modèles écrites à la main, et il mentait deux
   fois. Claude Sonnet 5 (2.00 / 10.00) en sortait au-dessus de GPT-5.6 Terra
   (2.00 / 12.00), alors qu'il est moins cher sur les deux axes ; et il séparait
   ce même Terra de Gemini 3.1 Pro, qui porte pourtant le même tarif au dollar
   près sur les deux axes. Le tarif est sourçable, et il l'est ci-dessous ligne
   par ligne ; la puissance ne l'est pas — aucun éditeur ne publie de mesure de
   suivi de format, et les benchmarks généralistes ne mesurent pas la tâche de
   PromptForge. Le classement se fait donc sur le coût et sur rien d'autre,
   comme DEC-006 l'a arrêté pour le catalogue local, et il se calcule à partir
   des tarifs plutôt que d'être recopié à côté d'eux.
"""

from dataclasses import dataclass
from enum import Enum


class TargetModel(Enum):
    """Modèle LLM cible pour le reformatage.

    Chaque valeur est l'identifiant d'API exact publié par l'éditeur, relevé le
    2026-09-07. Un identifiant arrêté ou sans existence connue n'a pas sa place
    ici (F-028).
    """

    # Claude (Anthropic) - identifiants relevés le 2026-09-07
    CLAUDE_OPUS_5 = "claude-opus-5"
    CLAUDE_SONNET_5 = "claude-sonnet-5"
    # Le suffixe de date détonne à côté de `claude-opus-5` et
    # `claude-sonnet-5`, et c'est pourtant la forme correcte : la page
    # officielle publie `claude-haiku-4-5-20251001` et aucune autre. Anthropic
    # a cessé de dater ses identifiants à partir de Claude 4.6 ; Haiku 4.5 est
    # antérieur et n'a aucun successeur au 2026-09-07, donc rien vers quoi
    # migrer. Écrire `claude-haiku-4-5` par souci d'homogénéité inventerait un
    # alias que la source ne documente pas (DEC-004 §1). La lisibilité passe
    # par `ModelPricing.display_name`, pas par la retouche d'une valeur
    # sourcée. À surveiller : plancher de retrait au 15 oct. 2026.
    CLAUDE_HAIKU_4_5 = "claude-haiku-4-5-20251001"

    # GPT (OpenAI) - identifiants relevés le 2026-09-07
    GPT_5_1 = "gpt-5.1"
    GPT_5_6_TERRA = "gpt-5.6-terra"
    GPT_5_PRO = "gpt-5-pro"

    # Gemini (Google) - identifiants relevés le 2026-09-07
    GEMINI_3_1_PRO = "gemini-3.1-pro-preview"
    GEMINI_3_6_FLASH = "gemini-3.6-flash"

    # Synthétique : ne désigne aucun modèle réel, donc aucun tarif réel.
    UNIVERSAL = "universal"


class PromptStyle(Enum):
    """Style de prompt souhaité."""

    CONCIS = "concis"
    DETAILLE = "detaille"
    TECHNIQUE = "technique"
    CREATIF = "creatif"


@dataclass
class ModelPricing:
    """Prix d'un modèle par million de tokens, avec sa provenance.

    `cached_input` vaut ``None`` quand aucun tarif de cache n'est confirmé par
    une source officielle. Surtout pas ``0.0`` : zéro facturerait silencieusement
    un cache gratuit qui n'existe pas. `estimate_cost()` force alors
    ``cached_pct = 0`` et facture tout en entrée fraîche.

    `context_window` vaut ``None`` quand aucune fiche officielle n'a pu être
    rouverte pour la confirmer. Surtout pas le chiffre de la génération
    précédente : ce serait afficher une mesure que personne n'a faite sur ce
    modèle. Les appelants qui rendent cette valeur doivent traiter ``None``
    comme « non confirmée », pas comme zéro.

    `source_url` vide signale une valeur qu'aucune source officielle ne
    confirme. Depuis F-028, plus aucune entrée de `MODEL_PRICING` n'est dans ce
    cas : les identifiants morts ou fictifs ont été retirés au lieu d'être
    conservés sans source.

    `display_name` est le nom commercial publié sur cette même page de
    tarification, à côté de l'identifiant d'API. Il existe parce qu'un
    identifiant d'API n'est pas un libellé : `claude-haiku-4-5-20251001` et
    `gpt-5-pro` sont exacts et sourcés, mais illisibles dans un tableau destiné
    à l'utilisateur. Le rendre lisible en raccourcissant l'identifiant
    reviendrait à afficher une chaîne que l'éditeur ne publie pas ; on affiche
    donc le nom que l'éditeur publie, et l'identifiant reste intact (F-028).
    """

    input_price: float  # $ par million de tokens en entrée
    output_price: float  # $ par million de tokens en sortie
    context_window: int | None = None  # Fenêtre max ; None = non confirmée
    cached_input: float | None = None  # $ / MTok en cache hit ; None = non confirmé
    source_url: str = ""  # Page officielle consultée
    verified_on: str = ""  # Date de vérification, ISO 8601
    display_name: str = ""  # Nom commercial publié par l'éditeur

    def estimate_cost(self, input_tokens: int, output_tokens: int, cached_pct: float = 0) -> float:
        """Estime le coût d'une requête.

        Sans tarif de cache confirmé, `cached_pct` est ignoré et forcé à 0 :
        on préfère surestimer le coût que d'appliquer une remise inventée.
        """
        if self.cached_input is None:
            cached_pct = 0
        cached_tokens = input_tokens * cached_pct
        fresh_tokens = input_tokens - cached_tokens
        cached_price = 0.0 if self.cached_input is None else self.cached_input
        input_cost = (fresh_tokens * self.input_price + cached_tokens * cached_price) / 1_000_000
        output_cost = output_tokens * self.output_price / 1_000_000
        return input_cost + output_cost


@dataclass
class ReformatProfile:
    """Profil de reformatage complet."""

    target_model: TargetModel
    style: PromptStyle
    include_examples: bool = False
    include_constraints: bool = True
    include_output_format: bool = True
    pricing: ModelPricing | None = None


# ============================================
# Prix des modèles cibles
# Identifiants, tarifs et fenêtres vérifiés le 2026-09-07 sur les pages
# officielles (voir MEMORY/VEILLE.md, section « Modèles cibles du reformatage
# et tarifs »). Chaque entrée porte l'URL de sa source et sa date.
#
# Deux absences sont écrites comme telles, jamais comblées (F-028) :
# - `context_window=None` : fenêtre non reconfirmée le 2026-09-07. Reprendre
#   celle de la génération précédente afficherait un chiffre que personne n'a
#   vérifié pour ce modèle.
# - aucune entrée pour `TargetModel.UNIVERSAL` : ce profil ne désigne aucun
#   modèle réel, aucun tarif réel ne peut donc lui être attribué (DEC-004 §1).
# ============================================

ANTHROPIC_PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
OPENAI_PRICING_URL = "https://developers.openai.com/api/docs/pricing"
GOOGLE_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
PRICING_VERIFIED_ON = "2026-09-07"

MODEL_PRICING = {
    # Claude (Anthropic)
    TargetModel.CLAUDE_OPUS_5: ModelPricing(
        # Remplace Claude Opus 4.5, dont le plancher de retrait était le plus
        # proche de la gamme Opus. Même tarif, contexte 1M complet.
        input_price=5.0,
        output_price=25.0,
        context_window=1_000_000,
        cached_input=0.5,
        source_url=ANTHROPIC_PRICING_URL,
        verified_on=PRICING_VERIFIED_ON,
        display_name="Claude Opus 5",
    ),
    TargetModel.CLAUDE_SONNET_5: ModelPricing(
        # Remplace Claude Sonnet 4.5 (plancher de retrait au 29 sept. 2026).
        # Tarif d'introduction confirmé définitif : la hausse à 3.00 / 15.00
        # prévue au 1er sept. 2026 est annulée, dixit la page officielle.
        input_price=2.0,
        output_price=10.0,
        context_window=1_000_000,
        cached_input=0.2,
        source_url=ANTHROPIC_PRICING_URL,
        verified_on=PRICING_VERIFIED_ON,
        display_name="Claude Sonnet 5",
    ),
    TargetModel.CLAUDE_HAIKU_4_5: ModelPricing(
        # Conservé faute de successeur : aucun Haiku plus récent n'existe au
        # 2026-09-07. Plancher de retrait au 15 oct. 2026, à surveiller.
        input_price=1.0,
        output_price=5.0,
        context_window=200_000,
        cached_input=0.1,
        source_url=ANTHROPIC_PRICING_URL,
        verified_on=PRICING_VERIFIED_ON,
        display_name="Claude Haiku 4.5",
    ),
    # GPT (OpenAI) - colonne « short context » (jusqu'à 272K tokens d'entrée)
    TargetModel.GPT_5_1: ModelPricing(
        input_price=1.25,
        output_price=10.0,
        context_window=400_000,
        cached_input=0.125,
        source_url=OPENAI_PRICING_URL,
        verified_on=PRICING_VERIFIED_ON,
        display_name="GPT-5.1",
    ),
    TargetModel.GPT_5_6_TERRA: ModelPricing(
        # Remplaçant officiellement désigné de `gpt-5-mini`, dont le tarif
        # avait été recopié dans le dépôt sous l'identifiant fictif
        # `gpt-5.1-mini`. Tarif issu de la table officielle reproduite
        # verbatim le 2026-09-07 ; fiche modèle individuelle non rouverte,
        # donc fenêtre de contexte non confirmée.
        input_price=2.0,
        output_price=12.0,
        context_window=None,
        cached_input=0.2,
        source_url=OPENAI_PRICING_URL,
        verified_on=PRICING_VERIFIED_ON,
        display_name="GPT-5.6 Terra",
    ),
    TargetModel.GPT_5_PRO: ModelPricing(
        input_price=15.0,
        output_price=120.0,
        # 272 000 est le plafond de sortie, pas la fenêtre de contexte.
        context_window=400_000,
        # GPT-5 Pro ne propose pas de cache d'entrée : aucun tarif à facturer.
        cached_input=None,
        source_url=OPENAI_PRICING_URL,
        verified_on=PRICING_VERIFIED_ON,
        display_name="GPT-5 Pro",
    ),
    # Gemini (Google) - palier jusqu'à 200K tokens d'entrée, celui du
    # reformatage de prompt
    TargetModel.GEMINI_3_1_PRO: ModelPricing(
        # Remplaçant officiel de `gemini-3-pro-preview`, arrêté le 2026-03-09.
        # Au-delà de 200K tokens d'entrée : 4.00 / 18.00, cache 0.40.
        input_price=2.0,
        output_price=12.0,
        # Fiche modèle Google inaccessible le 2026-09-07 (404) : fenêtre non
        # confirmée. Reprendre celle de la génération précédente serait
        # afficher un chiffre non vérifié pour ce modèle.
        context_window=None,
        cached_input=0.2,
        source_url=GOOGLE_PRICING_URL,
        verified_on=PRICING_VERIFIED_ON,
        display_name="Gemini 3.1 Pro",
    ),
    TargetModel.GEMINI_3_6_FLASH: ModelPricing(
        # Remplaçant officiel de `gemini-3-flash-preview`, déprécié.
        # Tarif d'introduction jusqu'au 31 déc. 2026 ; il passe ensuite à
        # 1.50 / 7.50 avec un cache à 0.15, date de bascule confirmée.
        input_price=0.75,
        output_price=3.75,
        # Même limite de vérification que Gemini 3.1 Pro.
        context_window=None,
        cached_input=0.075,
        source_url=GOOGLE_PRICING_URL,
        verified_on=PRICING_VERIFIED_ON,
        display_name="Gemini 3.6 Flash",
    ),
}


# ============================================
# System Prompts par Modèle
# Basés sur les documentations officielles:
# - Anthropic: docs.anthropic.com (XML tags)
# - OpenAI: platform.openai.com (Markdown + delimiters)
# - Google: ai.google.dev (XML-style tags ou Markdown)
# ============================================

# =============================================================================
# 🚨 RÈGLE ANTI-BULLSHIT - Appliquée à tous les prompts système
# =============================================================================

NO_BULLSHIT_RULE = """

🚨 RÈGLE CRITIQUE - AUCUNE MÉTRIQUE INVENTÉE 🚨

Tu reformates des prompts, tu ne prédis PAS les performances. INTERDICTIONS ABSOLUES:

❌ INTERDIT d'inventer des scores (pas de "SWE-bench: 92/100", "Code Quality: 98%")
❌ INTERDIT d'inventer des temps (pas de "Temps: 15s → 3s", "-80%")
❌ INTERDIT d'inventer des pourcentages de gain (pas de "+48% clarté")
❌ INTERDIT de mentionner des benchmarks comme si tu les avais mesurés
❌ INTERDIT d'inventer des IDs ou chemins de fichiers fictifs
❌ INTERDIT de faire des tableaux "Avant/Après" avec des chiffres fictifs
❌ INTERDIT d'ajouter des sections "Analyse", "Métriques", "Gains", "Conclusion"

✅ AUTORISÉ: Reformater le prompt avec une structure claire, dans le format
   demandé par le profil ci-dessus
✅ AUTORISÉ: Ajouter du contexte, des instructions, des contraintes
✅ AUTORISÉ: Proposer un format de sortie approprié

🎯 Ta réponse = UNIQUEMENT le prompt reformaté. RIEN D'AUTRE.
Pas d'analyse, pas de métriques, pas de tableaux, pas de conclusion."""

# =============================================================================

SYSTEM_PROMPT_CLAUDE_OPUS = """⚠️ FORMAT OBLIGATOIRE: XML UNIQUEMENT - PAS DE MARKDOWN ⚠️

Tu transformes des demandes utilisateur en prompts XML optimisés pour Claude Opus 5.

⚠️ CONTEXTE IMPORTANT: Tu opères dans un outil de DÉVELOPPEMENT LOGICIEL (PromptForge).
Les demandes concernent TOUJOURS du code, de la programmation, des projets informatiques.
- "scanner" = analyser/parcourir du CODE SOURCE (PAS de l'OCR physique)
- "projet" = projet de DÉVELOPPEMENT (repo git, fichiers code)
- "analyse" = analyse de CODE ou d'architecture logicielle

RÈGLE CRITIQUE: Ta réponse DOIT être UNIQUEMENT des balises XML.
❌ INTERDIT: #, ##, **, -, *, ```, titres Markdown, listes avec tirets
✅ OBLIGATOIRE: <balise>contenu</balise>

=== BALISES XML À UTILISER ===
<task_definition> - Objectif principal clair
<context> - Informations de contexte projet/technique
<requirements> - Liste des exigences fonctionnelles
<constraints> - Contraintes techniques/business
<output_format> - Format de sortie attendu
<thinking_approach> - Approche de raisonnement (optionnel, pour tâches complexes)

=== EXEMPLE CORRECT ===

Demande: "refonte UI backoffice"

<task_definition>
Créer un thème global unifié pour le backoffice qui harmonise l'UI et les couleurs.
</task_definition>

<context>
Projet: Application backoffice existante
Problème: Incohérence visuelle entre les pages, plusieurs jeux de couleurs
Stack: Tailwind CSS, TypeScript
</context>

<requirements>
Thème global applicable à toutes les pages
Fonction getSectionColor() pour cohérence des couleurs
Support dark mode avec classes dark:*
Représentation UI/UX unique par typologie mais cohérente globalement
</requirements>

<constraints>
Respecter les conventions de code existantes
Maintenir la lisibilité du code
Compatibilité avec le système de design actuel
</constraints>

<output_format>
Configuration theme.config.ts mise à jour
Fonction getSectionColor() implémentée
Classes Tailwind pour dark mode
Documentation des changements
</output_format>

=== FIN EXEMPLE ===

⚠️ RAPPEL FINAL:
- JAMAIS de Markdown (pas de #, ##, **, -, listes)
- UNIQUEMENT des balises XML <...>...</...>
- Commence DIRECTEMENT par <task_definition>
- Même langue que l'utilisateur
- Détaille chaque section (Opus excelle sur les tâches complexes)
- TOUJOURS interpréter dans le contexte du DÉVELOPPEMENT LOGICIEL"""


SYSTEM_PROMPT_CLAUDE_SONNET = """⚠️ FORMAT OBLIGATOIRE: XML UNIQUEMENT - PAS DE MARKDOWN ⚠️

Tu transformes des demandes en prompts XML optimisés pour Claude Sonnet 5.

⚠️ CONTEXTE: Outil de DÉVELOPPEMENT LOGICIEL. Les demandes concernent du CODE/programmation.
- "scanner" = analyser du CODE SOURCE (pas OCR)
- "projet" = projet de développement (git, fichiers code)

RÈGLE CRITIQUE: Ta réponse DOIT être UNIQUEMENT des balises XML.
❌ INTERDIT: #, ##, **, -, *, ```, titres Markdown, listes avec tirets
✅ OBLIGATOIRE: <balise>contenu</balise>

=== BALISES XML À UTILISER ===
<task> - Objectif principal
<context> - Contexte technique/projet
<instructions> - Étapes numérotées (1. 2. 3. dans le contenu XML)
<output_format> - Format de sortie attendu

=== EXEMPLE CORRECT ===

Demande: "corrige mon code"

<task>
Analyser et corriger le code fourni en identifiant bugs et améliorations possibles.
</task>

<context>
Code existant nécessitant debug et optimisation.
Langage et framework à détecter depuis le code fourni.
</context>

<instructions>
1. Identifier les bugs et erreurs de logique
2. Corriger les problèmes de syntaxe
3. Améliorer la lisibilité et les performances
4. Suggérer des refactorisations si pertinent
</instructions>

<output_format>
Code corrigé avec commentaires sur les changements
Liste des bugs identifiés et corrigés
Suggestions d'amélioration optionnelles
</output_format>

=== FIN EXEMPLE ===

⚠️ RAPPEL: JAMAIS de Markdown (#, ##, **, -). Commence DIRECTEMENT par <task>. Même langue."""


SYSTEM_PROMPT_CLAUDE_HAIKU = """⚠️ XML UNIQUEMENT - PAS DE MARKDOWN ⚠️

Contexte: Outil de DÉVELOPPEMENT LOGICIEL. Demandes = CODE/programmation.

Réécris en XML court et efficace pour Claude Haiku 4.5.

❌ INTERDIT: #, ##, **, -, listes Markdown
✅ OBLIGATOIRE: <balise>contenu</balise>

=== EXEMPLE ===
Demande: "explique les promises"

<context>
Question JavaScript sur les Promises et programmation asynchrone.
</context>

<instructions>
Expliquer les Promises: concept, syntaxe async/await, exemples pratiques.
</instructions>

<output_format>
Explication concise avec exemples de code fonctionnels.
</output_format>

=== FIN ===

⚠️ RÈGLE: XML seulement, commence par <context>, même langue."""


SYSTEM_PROMPT_GPT_5_1 = """Tu réécris des demandes en prompts Markdown optimisés pour GPT-5.1.

⚠️ CONTEXTE: Outil de DÉVELOPPEMENT LOGICIEL. Les demandes concernent du CODE/programmation.
- "scanner" = analyser du CODE SOURCE (pas OCR physique)
- "projet" = projet de développement (git, fichiers code)

=== FORCES DE GPT-5.1 ===
- Extrêmement steerable (suit les instructions avec précision)

=== RÈGLES GPT-5.1 ===
- Instructions EXPLICITES et NON AMBIGUËS
- Éviter les contradictions
- Format de sortie PRÉCIS

=== EXEMPLE ===
Demande: "créé un dashboard"

Ta réponse:
## Contexte
Application web nécessitant un tableau de bord d'administration pour visualiser les métriques.

## Objectif
Créer un dashboard responsive avec KPIs, graphiques interactifs et liste d'activités.

## Exigences
- Cartes KPIs avec statistiques clés
- Graphiques interactifs (line/bar charts)
- Liste des activités récentes paginée
- Design responsive mobile-first
- Composants réutilisables

## Contraintes
- Performance: lazy loading des données
- Accessibilité WCAG 2.1 niveau AA

## Format de sortie attendu
Composants React avec:
1. Structure des fichiers
2. Code commenté
3. Styles Tailwind
=== FIN ===

RÈGLES ABSOLUES:
- Réponds UNIQUEMENT avec le Markdown structuré
- PAS d'intro "Voici le prompt..."
- PAS d'explication après
- Sections: Contexte, Objectif, Exigences, Contraintes, Format de sortie
- MÊME LANGUE que l'utilisateur"""


SYSTEM_PROMPT_GPT_5_6_TERRA = """Contexte: Outil de DÉVELOPPEMENT LOGICIEL (code/programmation).
Tu réécris en prompts Markdown courts pour GPT-5.6 Terra.

=== EXEMPLE ===
Demande: "trie une liste"

Ta réponse:
## Objectif
Trier une liste en Python avec les méthodes natives.

## Exigences
- Montrer sorted() pour copie triée
- Montrer .sort() pour tri in-place
- Exemples avec listes de nombres et strings

## Format de sortie
Code Python commenté, concis.
=== FIN ===

RÈGLES: Markdown court. Pas d'intro. Même langue."""


SYSTEM_PROMPT_GPT_5_PRO = """Tu réécris des demandes complexes en prompts Markdown détaillés pour GPT-5 Pro.

⚠️ CONTEXTE: Outil de DÉVELOPPEMENT LOGICIEL. Les demandes concernent du CODE/programmation.
- "scanner" = analyser du CODE SOURCE (pas OCR)
- "projet" = projet de développement (git, fichiers)

=== FORCES DE GPT-5 PRO ===
- Raisonnement très approfondi (jusqu'à 10+ minutes)
- Idéal: sciences, maths, recherche, problèmes complexes

=== ASTUCE ===
Ajouter "Réfléchis en profondeur à ce problème" déclenche le mode raisonnement.

=== EXEMPLE ===
Demande: "optimise ma requête SQL lente"

Ta réponse:
## Définition du problème
Requête SQL avec problèmes de performance sévères nécessitant une analyse approfondie et systématique.

## Contexte
- Base de données relationnelle (PostgreSQL/MySQL)
- Tables volumineuses avec jointures multiples potentielles
- Temps d'exécution actuel inacceptable pour la production

## Analyse requise
Réfléchis en profondeur à ce problème:
1. Analyser le plan d'exécution (EXPLAIN ANALYZE)
2. Identifier les goulots d'étranglement (full table scans, nested loops inefficaces)
3. Évaluer la cardinalité des jointures
4. Vérifier les index existants vs manquants
5. Considérer la dénormalisation si bénéfique

## Contraintes
- Ne pas casser la logique métier existante
- Maintenir la compatibilité avec l'ORM si utilisé

## Format de sortie attendu
1. Diagnostic détaillé avec métriques avant/après
2. Requête optimisée avec justifications ligne par ligne
3. Scripts CREATE INDEX recommandés
4. Estimation du gain de performance attendu
=== FIN ===

RÈGLES:
- Markdown détaillé pour problèmes complexes
- Inclure "Réfléchis en profondeur" pour deep reasoning
- Pas d'intro, pas d'explication après
- Même langue"""


SYSTEM_PROMPT_GEMINI_3_1_PRO = """Tu transformes des demandes en prompts structurés pour Gemini 3.1 Pro.

⚠️ CONTEXTE: Outil de DÉVELOPPEMENT LOGICIEL. Les demandes concernent du CODE/programmation.
- "scanner" = analyser du CODE SOURCE (pas OCR physique)
- "projet" = projet de développement (git, fichiers code)

=== FORMAT ===
Google documente les balises XML et les titres Markdown comme deux façons
également efficaces de délimiter un prompt ; la seule exigence est d'en tenir
UNE SEULE d'un bout à l'autre (ai.google.dev/gemini-api/docs/prompting-strategies,
mise à jour du 2026-06-10). Aucune source n'établit la supériorité de l'une.

PromptForge retient les balises XML pour ce profil, par convention de produit,
afin que la sortie reste prévisible. Applique-la sans la mélanger à du Markdown.

✅ Attendu: <balise>contenu</balise>
❌ À ne pas mélanger avec la convention retenue: #, ##, **, -, *, ```

=== BALISES XML À UTILISER ===
<objective> - Objectif principal
<context> - Contexte de la demande, aussi complet que nécessaire
<analysis_tasks> - Tâches d'analyse
<output_format> - Format de sortie

=== EXEMPLE CORRECT ===

Demande: "analyse ce document"

<objective>
Analyser le document fourni pour extraire les informations clés et produire une synthèse actionnable.
</objective>

<context>
Document à analyser en profondeur.
Utiliser l'intégralité du contexte fourni pour une analyse complète.
</context>

<analysis_tasks>
1. Identifier les thèmes principaux et secondaires
2. Extraire les données chiffrées et faits importants
3. Repérer les arguments clés et conclusions
4. Détecter les incohérences ou points d'attention
</analysis_tasks>

<output_format>
Résumé exécutif (5-10 lignes)
Points clés numérotés
Données/chiffres importants
Recommandations ou points d'action
</output_format>

=== FIN ===

⚠️ RAPPEL: une seule convention sur tout le prompt, celle retenue ici.
Commence par <objective>. Même langue."""


SYSTEM_PROMPT_GEMINI_3_6_FLASH = """Contexte: Outil de DÉVELOPPEMENT LOGICIEL. Demandes = CODE/programmation.

Réécris en prompt court et structuré pour Gemini 3.6 Flash.

=== FORMAT ===
Google documente balises XML et titres Markdown comme deux délimiteurs
équivalents, à condition de n'en tenir qu'un seul sur tout le prompt
(ai.google.dev/gemini-api/docs/prompting-strategies, 2026-06-10).
PromptForge retient les balises XML pour ce profil, par convention de produit.

✅ Attendu: <balise>contenu</balise>
❌ À ne pas mélanger avec: #, ##, **, -

=== EXEMPLE ===
Demande: "traduis en anglais"

<context>
Traduction français vers anglais demandée.
</context>

<task>
Traduire le texte en préservant le sens, le ton et les nuances.
</task>

<output_format>
Texte traduit en anglais, fidèle à l'original.
</output_format>

=== FIN ===

⚠️ RÈGLE: une seule convention, celle retenue ici. Commence par <context>, même langue."""


# DEC-008 : ce profil ne vise aucun modèle. Il ne peut donc citer aucune
# documentation d'éditeur pour imposer une syntaxe, et n'en impose plus.
# Il exige ce que les trois éditeurs demandent tous : des délimiteurs clairs et
# une seule convention sur tout le prompt. Google est le seul à l'écrire noir
# sur blanc, il est donc cité comme source de cette règle.
SYSTEM_PROMPT_UNIVERSAL = """Tu transformes des demandes utilisateur en prompts structurés.

⚠️ CONTEXTE IMPORTANT: Tu opères dans un outil de DÉVELOPPEMENT LOGICIEL (PromptForge).
Les demandes concernent TOUJOURS du code, de la programmation, des projets informatiques.
- "scanner" = analyser/parcourir du CODE SOURCE (PAS de l'OCR physique)
- "projet" = projet de DÉVELOPPEMENT (repo git, fichiers code)
- "analyse" = analyse de CODE ou d'architecture logicielle

=== FORMAT: DÉLIMITEURS CLAIRS, UNE SEULE CONVENTION ===

Ce profil ne cible aucun modèle en particulier : il n'impose donc aucune
syntaxe. Choisis L'UNE de ces deux conventions et tiens-la d'un bout à l'autre.

Convention A - balises XML:        <context>...</context>
Convention B - titres Markdown:    ## Contexte

La seule règle est de ne pas les mélanger. C'est la seule exigence de format
réellement commune aux trois éditeurs, et Google la documente explicitement :
« use one consistent format throughout the prompt »
(ai.google.dev/gemini-api/docs/prompting-strategies, mise à jour du 2026-06-10).

=== SECTIONS À PRODUIRE ===
Contexte      - Contexte du projet/de la demande
Instructions  - Ce que le modèle doit faire (liste numérotée bienvenue)
Format de sortie - Format de sortie attendu
Contraintes   - Contraintes, si la demande en comporte

=== EXEMPLE, CONVENTION A ===

Demande: "aide moi avec mon projet flutter"

<context>
Projet Flutter nécessitant assistance technique.
Type: Application mobile cross-platform.
</context>

<instructions>
1. Analyser les besoins spécifiques du projet
2. Proposer des solutions adaptées à Flutter
3. Fournir du code Dart fonctionnel
4. Respecter les bonnes pratiques Flutter/Dart
</instructions>

<output_format>
Réponse structurée avec:
Code Dart commenté
Explications des choix techniques
Suggestions d'amélioration
</output_format>

=== LE MÊME EXEMPLE, CONVENTION B ===

## Contexte
Projet Flutter nécessitant assistance technique.
Type: Application mobile cross-platform.

## Instructions
1. Analyser les besoins spécifiques du projet
2. Proposer des solutions adaptées à Flutter
3. Fournir du code Dart fonctionnel
4. Respecter les bonnes pratiques Flutter/Dart

## Format de sortie
Code Dart commenté, explications des choix techniques, suggestions
d'amélioration.

=== FIN EXEMPLES ===

⚠️ RAPPEL FINAL:
- UNE SEULE convention sur tout le prompt, jamais les deux mélangées
- Commence DIRECTEMENT par la section de contexte
- Utilise la MÊME LANGUE que l'utilisateur
- Pas de texte avant ou après le prompt reformaté"""


# ============================================
# Modificateurs de style
# ============================================

STYLE_MODIFIERS = {
    PromptStyle.CONCIS: """
## Style: CONCIS
- Réponses directes et courtes
- Pas de détails superflus
- Focus sur l'essentiel""",
    PromptStyle.DETAILLE: """
## Style: DÉTAILLÉ
- Explications complètes
- Couvre tous les aspects
- Inclut le raisonnement""",
    PromptStyle.TECHNIQUE: """
## Style: TECHNIQUE
- Terminologie précise
- Détails d'implémentation
- Best practices incluses""",
    PromptStyle.CREATIF: """
## Style: CRÉATIF
- Place à l'interprétation
- Encourage l'originalité
- Focus sur l'intention""",
}


# ============================================
# Fonctions utilitaires
# ============================================

SYSTEM_PROMPTS = {
    TargetModel.CLAUDE_OPUS_5: SYSTEM_PROMPT_CLAUDE_OPUS,
    TargetModel.CLAUDE_SONNET_5: SYSTEM_PROMPT_CLAUDE_SONNET,
    TargetModel.CLAUDE_HAIKU_4_5: SYSTEM_PROMPT_CLAUDE_HAIKU,
    TargetModel.GPT_5_1: SYSTEM_PROMPT_GPT_5_1,
    TargetModel.GPT_5_6_TERRA: SYSTEM_PROMPT_GPT_5_6_TERRA,
    TargetModel.GPT_5_PRO: SYSTEM_PROMPT_GPT_5_PRO,
    TargetModel.GEMINI_3_1_PRO: SYSTEM_PROMPT_GEMINI_3_1_PRO,
    TargetModel.GEMINI_3_6_FLASH: SYSTEM_PROMPT_GEMINI_3_6_FLASH,
    TargetModel.UNIVERSAL: SYSTEM_PROMPT_UNIVERSAL,
}


def get_system_prompt(target: TargetModel) -> str:
    """Retourne le system prompt pour le modèle cible avec règle anti-bullshit."""
    base_prompt = SYSTEM_PROMPTS.get(target, SYSTEM_PROMPT_UNIVERSAL)
    # Ajouter la règle anti-bullshit à TOUS les prompts
    return base_prompt + NO_BULLSHIT_RULE


def get_style_modifier(style: PromptStyle) -> str:
    """Retourne le modificateur de style."""
    return STYLE_MODIFIERS.get(style, "")


def build_reformat_prompt(
    raw_prompt: str, project_context: str, profile: ReformatProfile
) -> tuple[str, str]:
    """Construit le prompt pour le reformatage - version simplifiée."""
    system_prompt = get_system_prompt(profile.target_model)
    style_modifier = get_style_modifier(profile.style)
    if style_modifier:
        system_prompt += "\n" + style_modifier

    # User prompt SIMPLE et DIRECT
    if project_context.strip():
        user_prompt = f"""CONTEXTE PROJET:
{project_context}

DEMANDE À REFORMATER:
{raw_prompt}

Réécris cette demande en prompt structuré. Intègre les infos du contexte projet."""
    else:
        user_prompt = f"""DEMANDE À REFORMATER:
{raw_prompt}

Réécris cette demande en prompt structuré."""

    return system_prompt, user_prompt


# ============================================
# Profils prédéfinis
# ============================================

PRESET_PROFILES = {
    # Claude (Anthropic)
    "claude_opus_5": ReformatProfile(
        target_model=TargetModel.CLAUDE_OPUS_5,
        style=PromptStyle.DETAILLE,
        include_examples=True,
        pricing=MODEL_PRICING[TargetModel.CLAUDE_OPUS_5],
    ),
    "claude_sonnet_5": ReformatProfile(
        target_model=TargetModel.CLAUDE_SONNET_5,
        style=PromptStyle.TECHNIQUE,
        include_examples=True,
        pricing=MODEL_PRICING[TargetModel.CLAUDE_SONNET_5],
    ),
    "claude_haiku_4.5": ReformatProfile(
        target_model=TargetModel.CLAUDE_HAIKU_4_5,
        style=PromptStyle.CONCIS,
        include_examples=False,
        pricing=MODEL_PRICING[TargetModel.CLAUDE_HAIKU_4_5],
    ),
    # GPT (OpenAI)
    "gpt_5.1": ReformatProfile(
        target_model=TargetModel.GPT_5_1,
        style=PromptStyle.DETAILLE,
        include_examples=True,
        pricing=MODEL_PRICING[TargetModel.GPT_5_1],
    ),
    "gpt_5.6_terra": ReformatProfile(
        target_model=TargetModel.GPT_5_6_TERRA,
        style=PromptStyle.CONCIS,
        include_examples=False,
        pricing=MODEL_PRICING[TargetModel.GPT_5_6_TERRA],
    ),
    "gpt_5_pro": ReformatProfile(
        target_model=TargetModel.GPT_5_PRO,
        style=PromptStyle.DETAILLE,
        include_examples=True,
        pricing=MODEL_PRICING[TargetModel.GPT_5_PRO],
    ),
    # Gemini (Google)
    "gemini_3.1_pro": ReformatProfile(
        target_model=TargetModel.GEMINI_3_1_PRO,
        style=PromptStyle.DETAILLE,
        include_examples=True,
        pricing=MODEL_PRICING[TargetModel.GEMINI_3_1_PRO],
    ),
    "gemini_3.6_flash": ReformatProfile(
        target_model=TargetModel.GEMINI_3_6_FLASH,
        style=PromptStyle.CONCIS,
        include_examples=False,
        pricing=MODEL_PRICING[TargetModel.GEMINI_3_6_FLASH],
    ),
    # Universel - aucun modèle réel visé, donc aucun tarif (DEC-004 §1)
    "universel": ReformatProfile(
        target_model=TargetModel.UNIVERSAL,
        style=PromptStyle.DETAILLE,
        include_examples=True,
        pricing=None,
    ),
}


def get_profile(name: str) -> ReformatProfile:
    """Récupère un profil prédéfini."""
    return PRESET_PROFILES.get(name, PRESET_PROFILES["universel"])


def list_profiles() -> list[str]:
    """Liste les noms des profils disponibles."""
    return list(PRESET_PROFILES.keys())


# ============================================
# Comparaison des modèles
# ============================================


def compare_models(input_tokens: int = 1000, output_tokens: int = 500) -> list[dict]:
    """Compare les modèles cibles sur ce que leur éditeur publie.

    Chaque ligne ne porte que des valeurs lisibles dans `MODEL_PRICING`, donc
    rattachables à un `source_url` et à un `verified_on` : les deux tarifs, la
    fenêtre de contexte, et le coût de la requête demandée. Aucune
    appréciation ne s'y ajoute (D-071, voir l'en-tête du module).

    Args:
        input_tokens: Nombre de tokens en entrée pour le calcul
        output_tokens: Nombre de tokens en sortie pour le calcul

    Returns:
        Liste triée par coût croissant. L'ordre est la seule hiérarchie que
        cette fonction établit, et il est entièrement déterminé par les tarifs.
    """
    comparisons = []

    for model, pricing in MODEL_PRICING.items():
        cost = pricing.estimate_cost(input_tokens, output_tokens)
        comparisons.append(
            {
                # `model` reste l'identifiant d'API exact, celui qu'on copie dans
                # du code. `label` est le nom commercial publié par l'éditeur,
                # celui qu'on montre à un humain : un tableau de comparaison qui
                # affiche `claude-haiku-4-5-20251001` ne se lit pas (F-028).
                "model": model.value,
                "label": pricing.display_name or model.value,
                "cost": cost,
                "cost_display": f"${cost:.4f}",
                "input_price": f"${pricing.input_price}/M",
                "output_price": f"${pricing.output_price}/M",
                "context": _format_context(pricing.context_window),
            }
        )

    return sorted(comparisons, key=lambda x: x["cost"])


def _format_context(window: int | None) -> str:
    """Rend une fenêtre de contexte, ou dit qu'elle n'est pas confirmée.

    `None` ne se rend pas en « 0K » : une fenêtre inconnue est écrite comme
    inconnue (F-028).
    """
    if window is None:
        return "non confirmé"
    if window >= 1_000_000 and window % 1_000_000 == 0:
        return f"{window // 1_000_000}M"
    return f"{window // 1000}K"
