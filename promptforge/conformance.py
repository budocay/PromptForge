"""
Contrôles de conformité d'un prompt reformaté.

Ces contrôles ne notent pas la qualité d'un prompt : aucune source ne permet
de chiffrer cela, et le dépôt n'affiche aucun jugement qu'il ne mesure pas
(D-071). Ils vérifient, chacun en oui ou non et avec sa raison, qu'une sortie
du reformateur respecte ce que le produit promet :

- ``non_vide``            la sortie contient quelque chose ;
- ``format``              la syntaxe est celle du profil (XML, Markdown, ou
                          une seule des deux pour le profil universel) ;
- ``pas_d_annonce``       pas de « Voici le prompt... » en tête ;
- ``pas_de_raisonnement`` aucun bloc ``<think>`` n'a fuité ;
- ``demande_reformulee``  la sortie est un prompt structuré avec une section
                          d'objectif, pas l'exécution de la demande ;
- ``termes_conserves``    les mots porteurs de la demande sont repris ;
- ``meme_langue``         le prompt est écrit dans la langue de la demande ;
- ``aucun_chiffre_invente`` aucun pourcentage ni score absent de la demande
                          et du contexte.

Les seuils sont des heuristiques déclarées comme telles dans chaque contrôle,
pas des mesures de qualité. Ce module ne dépend que de la bibliothèque
standard : il sert au banc d'évaluation (``scripts/evaluate_prompt_quality.py``)
comme à n'importe quel appelant.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .profiles import SYNTAX_ANY, SYNTAX_MARKDOWN, SYNTAX_XML
from .providers import PREAMBLE_RE

SYNTAX_MIXED = "mixed"
SYNTAX_PLAIN = "plain"

# Noms de section qui désignent l'objectif du prompt, en balise ou en titre.
_OBJECTIVE_NAMES = (
    "task",
    "tache",
    "objectif",
    "objective",
    "goal",
    "but",
    "mission",
    "demande",
    "definition du probleme",
    "probleme",
)

# Mots vides retirés avant de chercher les termes porteurs de la demande.
_STOPWORDS = frozenset("""
    le la les un une des du de d l et ou a au aux en dans sur pour par avec sans
    ce cet cette ces mon ma mes ton ta tes son sa ses notre nos votre vos leur
    leurs je tu il elle on nous vous ils elles me moi te toi se lui y qui que quoi
    dont est sont etre avoir fait faire fais faites peux peut veux veut dois doit
    tres plus moins aussi comme tout tous toute toutes bien alors donc mais
    stp svp merci aide aider besoin juste
    trouve trouver ecris ecrire cree creer donne donner genere generer redige
    rediger prepare preparer propose proposer montre montrer explique expliquer
    the a an and or of to in on for with without this that these those my your
    his her our their i you he she we they me it is are be do make please help
    """.split())

_FR_MARKERS = frozenset(
    "le la les des une est pour avec dans sur que qui du au aux ce cette sont pas".split()
)
_EN_MARKERS = frozenset("the and for with that this are is to of in on you your be not".split())

_XML_SECTION_RE = re.compile(r"<([A-Za-z_][\w-]*)>(.*?)</\1>", re.DOTALL)
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_PERCENT_OR_SCORE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?%|\b\d+\s?/\s?100\b")


@dataclass(frozen=True)
class Check:
    """Un contrôle : son nom, son verdict, et pourquoi."""

    name: str
    passed: bool
    detail: str


@dataclass
class ConformanceReport:
    """Ensemble des contrôles d'une sortie."""

    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def get(self, name: str) -> Check:
        return next(c for c in self.checks if c.name == name)


def _normalize(text: str) -> str:
    """Minuscules, sans accents, ponctuation ramenée à des espaces."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def xml_sections(text: str) -> list[str]:
    """Noms des sections XML de premier niveau (balise ouvrante et fermante)."""
    return [m.group(1).lower() for m in _XML_SECTION_RE.finditer(text)]


def markdown_headings(text: str) -> list[str]:
    """Titres Markdown de la sortie."""
    return [m.group(1) for m in _MD_HEADING_RE.finditer(text)]


def detect_syntax(text: str) -> str:
    """``xml``, ``markdown``, ``mixed`` ou ``plain``.

    Une syntaxe est retenue à partir de deux sections : une balise isolée ou
    un titre unique ne font pas une structure.
    """
    has_xml = len(xml_sections(text)) >= 2
    has_md = len(markdown_headings(text)) >= 2
    if has_xml and has_md:
        return SYNTAX_MIXED
    if has_xml:
        return SYNTAX_XML
    if has_md:
        return SYNTAX_MARKDOWN
    return SYNTAX_PLAIN


def detect_language(text: str) -> str | None:
    """``fr``, ``en`` ou ``None`` si le texte ne permet pas de trancher."""
    words = _normalize(text).split()
    fr = sum(w in _FR_MARKERS for w in words)
    en = sum(w in _EN_MARKERS for w in words)
    if fr == en or max(fr, en) < 2:
        return None
    return "fr" if fr > en else "en"


def key_terms(raw_prompt: str) -> list[str]:
    """Mots porteurs de la demande : quatre lettres ou plus, hors mots vides."""
    seen = []
    for word in _normalize(raw_prompt).split():
        if len(word) >= 4 and word not in _STOPWORDS and word not in seen:
            seen.append(word)
    return seen


def _check_format(output: str, expected_syntax: str) -> Check:
    found = detect_syntax(output)
    if expected_syntax == SYNTAX_ANY:
        ok = found in (SYNTAX_XML, SYNTAX_MARKDOWN)
        want = "une seule convention, XML ou Markdown"
    else:
        ok = found == expected_syntax
        want = expected_syntax
    return Check("format", ok, f"attendu : {want} ; trouvé : {found}")


def _check_objective(output: str) -> Check:
    sections = xml_sections(output) + [_normalize(h) for h in markdown_headings(output)]
    names = [_normalize(s.replace("_", " ")) for s in sections]
    has_objective = any(n.startswith(o) or o in n.split() for n in names for o in _OBJECTIVE_NAMES)
    ok = len(sections) >= 2 and has_objective
    if ok:
        detail = "prompt structuré avec une section d'objectif"
    elif len(sections) < 2:
        detail = "moins de deux sections : la demande a pu être exécutée au lieu d'être réécrite"
    else:
        detail = f"aucune section d'objectif parmi : {', '.join(sections[:8])}"
    return Check("demande_reformulee", ok, detail)


def _check_terms(raw_prompt: str, output: str) -> Check:
    terms = key_terms(raw_prompt)
    if not terms:
        return Check("termes_conserves", True, "aucun terme porteur dans la demande")
    haystack = " " + _normalize(output) + " "
    # Préfixe de six lettres : « cles » retrouve « cles », « optimise »
    # retrouve « optimiser ». Heuristique, pas mesure de fidélité.
    found = [t for t in terms if " " + t[:6] in haystack]
    missing = [t for t in terms if t not in found]
    ratio = len(found) / len(terms)
    ok = ratio >= 0.6
    detail = f"{len(found)}/{len(terms)} termes repris (seuil 60 %)"
    if missing:
        detail += f" ; absents : {', '.join(missing[:6])}"
    return Check("termes_conserves", ok, detail)


def _check_language(raw_prompt: str, output: str) -> Check:
    lang_in, lang_out = detect_language(raw_prompt), detect_language(output)
    if lang_in is None:
        return Check("meme_langue", True, "langue de la demande indéterminée")
    ok = lang_out in (None, lang_in)
    return Check("meme_langue", ok, f"demande : {lang_in} ; prompt : {lang_out or 'indéterminée'}")


def _check_numbers(raw_prompt: str, output: str, project_context: str) -> Check:
    source = raw_prompt + "\n" + project_context
    allowed = {re.sub(r"\s", "", m) for m in _PERCENT_OR_SCORE_RE.findall(source)}
    invented = [
        m for m in _PERCENT_OR_SCORE_RE.findall(output) if re.sub(r"\s", "", m) not in allowed
    ]
    ok = not invented
    detail = "aucun" if ok else f"absents de la demande et du contexte : {', '.join(invented[:5])}"
    return Check("aucun_chiffre_invente", ok, detail)


# Libellés destinés à l'utilisateur, un par contrôle.
LABELS = {
    "non_vide": "sortie vide",
    "format": "format du profil non respecté",
    "pas_d_annonce": "phrase d'annonce en tête",
    "pas_de_raisonnement": "raisonnement <think> présent",
    "demande_reformulee": "demande peut-être exécutée au lieu d'être réécrite",
    "termes_conserves": "termes de la demande absents",
    "meme_langue": "langue différente de la demande",
    "aucun_chiffre_invente": "pourcentage ou score absent de la demande",
}


def check_reformatted_prompt(
    raw_prompt: str,
    output: str | None,
    expected_syntax: str,
    project_context: str = "",
) -> ConformanceReport:
    """Passe une sortie du reformateur à tous les contrôles.

    Args:
        raw_prompt: La demande brute de l'utilisateur.
        output: Le prompt reformaté (``None`` ou vide si le reformatage a
            échoué : tous les contrôles échouent alors, sauf ceux qui ne
            portent sur rien).
        expected_syntax: ``xml``, ``markdown`` ou ``any``
            (voir ``profiles.get_expected_syntax``).
        project_context: Le contexte projet fourni au reformateur ; il
            autorise les chiffres qu'il contient.
    """
    output = output or ""
    if not output.strip():
        return ConformanceReport([Check("non_vide", False, "sortie vide")])

    first_line = next((line for line in output.splitlines() if line.strip()), "")
    return ConformanceReport(
        [
            Check("non_vide", True, f"{len(output)} caractères"),
            _check_format(output, expected_syntax),
            Check(
                "pas_d_annonce",
                not PREAMBLE_RE.match(first_line),
                f"première ligne : {first_line[:60]!r}",
            ),
            Check(
                "pas_de_raisonnement",
                "<think" not in output.lower(),
                "bloc <think> présent" if "<think" in output.lower() else "aucun bloc <think>",
            ),
            _check_objective(output),
            _check_terms(raw_prompt, output),
            _check_language(raw_prompt, output),
            _check_numbers(raw_prompt, output, project_context),
        ]
    )
