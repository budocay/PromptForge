"""
Couture d'assemblage de l'interface web — sonde de construction (D-068).

Ce fichier ne teste aucune logique metier : il construit reellement
`create_interface()` et inspecte le graphe d'assemblage produit par Gradio.

Motivation (D-068) : les deux seuls tests existants sur cette couture etaient
un `import` et un `assert callable(...)`. Aucun test ne construisait
l'application. C'est pourquoi D-063 — dix-neuf composants interactifs cables a
rien, dont l'integralite de l'onglet « Assistant Guide » — a pu vivre des mois
sans etre vu, alors que la construction coute 0,12 s sans Ollama et sans
donnees. Le bloc 2 (DEC-012) en a resorbe dix-sept ; il en reste deux.

Trois verrous :
  1. la construction reussit hors ligne, dans un `base_path` temporaire ;
  2. aucun composant interactif n'est orphelin, hors exemptions **nommees** ;
  3. les nombres de blocs et de gestionnaires sont figes.
"""

import time
from pathlib import Path

import pytest

gr = pytest.importorskip("gradio", reason="Gradio est un extra optionnel ([web])")


# ═══════════════════════════════════════════════════════════════════════════
# BASELINE MESUREE — a mettre a jour sciemment, dans le meme commit que la
# modification d'interface qui la deplace, jamais « pour faire passer ».
# Mesure du 2026-09-07, gradio 6.26.0, sur `create_interface()`.
#
# Deplacement assume par le bloc 2 (DEC-012, cablage de l'assistant guide) :
#   blocs        188 -> 211  (-8 champs generiques, +30 champs du pool
#                             positionnel de `web/wizard.py`, +1 Markdown
#                             d'erreur `wizard_error`)
#   gestionnaires 27 -> 33   (+demarrer, +suivant, +precedent, +etat de
#                             chargement de la sauvegarde, +sauvegarder,
#                             +recommencer)
#   interactifs   59 -> 81   (-8 champs generiques, +30 champs du pool)
# ═══════════════════════════════════════════════════════════════════════════

EXPECTED_BLOCK_COUNT = 211
EXPECTED_HANDLER_COUNT = 34
EXPECTED_INTERACTIVE_COUNT = 81

# Plafond de temps de construction. La mesure de reference est 0,12 s ; le
# plafond est volontairement large (facteur ~15) car il ne surveille pas la
# performance mais la **nature** de la construction : un appel reseau, un scan
# disque ou une lecture de modele Ollama introduits au moment de l'assemblage
# feraient exploser ce budget au lieu de passer inapercus.
BUILD_TIME_BUDGET_SECONDS = 2.0


# ═══════════════════════════════════════════════════════════════════════════
# D-063 — COMPOSANTS INTERACTIFS CABLES A RIEN, EXEMPTION NOMMEE
# ═══════════════════════════════════════════════════════════════════════════
#
# Chaque entree est un composant qui existe a l'ecran mais n'est ni
# declencheur, ni entree, ni sortie d'un gestionnaire : l'utilisateur le voit,
# le manipule, et rien ne se produit.
#
# Cette liste EST la dette D-063, ecrite en clair. Elle doit **decroitre**.
# Le bloc 2 (DEC-012, cablage de l'assistant guide) en retire dix-sept ; le
# couple « Prompt a copier » / « Copier le prompt » de l'onglet « Generer
# config » ferme les deux derniers : la liste est desormais vide et doit le
# rester.
#
# Le test echoue dans les DEUX sens : un orphelin nouveau est une regression,
# une exemption devenue caduque est un progres a acter ici meme.

KNOWN_UNWIRED_D063: set[str] = set()

# Repartition declaree, pour que le compte reste lisible dans le rapport.
EXPECTED_EXEMPTIONS_BY_TAB: dict[str, int] = {}


# ═══════════════════════════════════════════════════════════════════════════
# INSTRUMENTATION
# ═══════════════════════════════════════════════════════════════════════════


def _describe(block) -> str:
    """Identifiant lisible et stable d'un composant.

    N'utilise **pas** `block._id` : ce compteur est global au processus Gradio,
    donc decale des qu'un autre test construit un composant avant celui-ci.
    On se rabat sur (onglet, type, libelle), qui survit a l'ordre des tests.
    """
    label = getattr(block, "label", None)
    if label is None:
        # Les boutons portent leur texte dans `value`, pas dans `label`.
        label = repr(getattr(block, "value", None))
    return f"{_enclosing_tab(block)} | {type(block).__name__} | {label}"


def _enclosing_tab(block) -> str:
    """Remonte les parents jusqu'a l'onglet contenant, pour lever les homonymes."""
    current = getattr(block, "parent", None)
    for _ in range(50):  # garde-fou : jamais de remontee infinie
        if current is None:
            break
        if isinstance(current, gr.Tab):
            return current.label
        current = getattr(current, "parent", None)
    return "<hors onglet>"


def _handlers(app):
    """Gestionnaires de l'application, quel que soit le conteneur Gradio."""
    fns = app.fns
    return list(fns.values()) if isinstance(fns, dict) else list(fns)


def _block_id(reference):
    """Un identifiant de bloc, qu'il arrive brut ou porte par un composant.

    Rend `None` pour une reference vide : un `.load()` porte par l'application
    elle-meme n'a pas de bloc declencheur, ce n'est pas un composant.
    """
    if reference is None:
        return None
    return reference if isinstance(reference, int) else reference._id


def _wired_block_ids(app) -> set:
    """Identifiants des blocs atteints par au moins un gestionnaire.

    Un bloc est cable s'il est declencheur (`targets`), entree (`inputs`) ou
    sortie (`outputs`) d'un gestionnaire — les trois seules facons pour un
    composant Gradio de participer a quoi que ce soit.
    """
    wired = set()
    for handler in _handlers(app):
        for target in handler.targets or []:
            wired.add(_block_id(target[0] if isinstance(target, tuple) else target))
        for component in list(handler.inputs or []) + list(handler.outputs or []):
            wired.add(_block_id(component))
    wired.discard(None)
    return wired


def _interactive_components(app) -> list:
    """Composants avec lesquels l'utilisateur interagit ou qui portent un etat.

    Exclut `Markdown` et `HTML`, purement decoratifs : leur absence de cablage
    est legitime. Tout le reste — champs, menus, boutons, curseurs, fichiers et
    `State` — doit servir a quelque chose.
    """
    return [
        block
        for block in app.blocks.values()
        if isinstance(block, gr.components.Component)
        and not isinstance(block, (gr.Markdown, gr.HTML))
    ]


class BuiltApp:
    """Resultat d'une construction instrumentee."""

    def __init__(self, app, seconds, base_path):
        self.app = app
        self.seconds = seconds
        self.base_path = base_path


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Construit l'application hors ligne, dans un `base_path` jetable.

    Deux isolations, toutes deux restaurees en sortie :
      - le singleton `get_forge()` pointe sur un repertoire temporaire, donc
        rien n'est ecrit dans `data/`, qui contient les donnees reelles du dev ;
      - `OllamaProvider` est neutralise, donc aucune socket n'est ouverte et le
        resultat ne depend pas de la presence d'un serveur ni d'un modele.
    """
    from promptforge import providers
    from promptforge.web import ollama_helpers

    base_path = tmp_path_factory.mktemp("promptforge_web_seam")

    saved = (
        providers.OllamaProvider.is_available,
        providers.OllamaProvider.list_models,
        ollama_helpers._base_path,
        ollama_helpers._forge,
    )
    providers.OllamaProvider.is_available = lambda self: False
    providers.OllamaProvider.list_models = lambda self: []
    try:
        ollama_helpers.set_base_path(str(base_path))
        from promptforge.web.interface import create_interface

        started = time.perf_counter()
        app = create_interface()
        elapsed = time.perf_counter() - started
        yield BuiltApp(app, elapsed, base_path)
    finally:
        (
            providers.OllamaProvider.is_available,
            providers.OllamaProvider.list_models,
            ollama_helpers._base_path,
            ollama_helpers._forge,
        ) = saved


# ═══════════════════════════════════════════════════════════════════════════
# 1. LA CONSTRUCTION EST POSSIBLE, HORS LIGNE ET SANS DONNEES
# ═══════════════════════════════════════════════════════════════════════════


class TestInterfaceBuilds:
    def test_create_interface_returns_blocks(self, built):
        assert isinstance(built.app, gr.Blocks)

    def test_nothing_is_written_outside_the_temporary_base_path(self, built):
        """La construction ne doit toucher ni `data/`, ni le repertoire courant."""
        from promptforge.web.ollama_helpers import get_forge

        forge = get_forge()
        for path in (forge.base_path, forge.db_path, forge.history_path, forge.projects_path):
            assert Path(path).resolve().is_relative_to(built.base_path.resolve()), (
                f"{path} sort du base_path temporaire : la construction ecrit hors "
                f"du bac a sable, donc potentiellement dans les donnees reelles du dev."
            )

    def test_build_needs_no_ollama_and_stays_cheap(self, built):
        """Budget de construction : garde-fou contre un appel externe a l'assemblage."""
        assert built.seconds < BUILD_TIME_BUDGET_SECONDS, (
            f"Construction en {built.seconds:.2f}s, budget "
            f"{BUILD_TIME_BUDGET_SECONDS}s (reference mesuree : 0,12s). "
            f"Un appel reseau ou disque a-t-il ete introduit au moment de "
            f"l'assemblage plutot que dans un gestionnaire ?"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 2. LE COEUR : AUCUN COMPOSANT INTERACTIF ORPHELIN HORS EXEMPTION NOMMEE
# ═══════════════════════════════════════════════════════════════════════════


class TestNoUnwiredComponent:
    def test_every_interactive_component_is_wired_or_named_in_d063(self, built):
        """Un composant interactif est declencheur, entree, sortie — ou une dette nommee."""
        wired = _wired_block_ids(built.app)
        orphans = {
            _describe(block)
            for block in _interactive_components(built.app)
            if block._id not in wired
        }

        regressions = sorted(orphans - KNOWN_UNWIRED_D063)
        assert not regressions, (
            "Composant(s) interactif(s) cable(s) a rien, hors exemption D-063 :\n  "
            + "\n  ".join(regressions)
            + "\n\nUn composant qui n'est ni declencheur, ni entree, ni sortie ne "
            "fait rien quand l'utilisateur le manipule. Cablez-le, retirez-le, "
            "ou inscrivez-le dans KNOWN_UNWIRED_D063 avec sa justification."
        )

    def test_exemption_list_holds_no_stale_entry(self, built):
        """Une exemption devenue caduque doit etre retiree : la dette D-063 se vide."""
        wired = _wired_block_ids(built.app)
        orphans = {
            _describe(block)
            for block in _interactive_components(built.app)
            if block._id not in wired
        }

        resolved = sorted(KNOWN_UNWIRED_D063 - orphans)
        assert not resolved, (
            "Exemption(s) D-063 sans objet — le composant est desormais cable, "
            "ou il a disparu :\n  "
            + "\n  ".join(resolved)
            + "\n\nRetirez ces entrees de KNOWN_UNWIRED_D063 dans le meme commit : "
            "la liste ne doit jamais etre plus longue que la dette reelle."
        )

    def test_every_button_actually_triggers_something(self, built):
        """Un bouton qui n'est que `outputs` passe pour cable, et ne fait rien.

        Trou constate par mutation au bloc 2 : supprimer
        `wizard_start_btn.click(...)` laissait le test d'orphelins vert, parce
        que le bouton restait sortie d'un autre gestionnaire. Un bouton se juge
        sur ce qu'il **declenche**, pas sur ce qu'on lui pousse.
        """
        triggers = set()
        for handler in _handlers(built.app):
            for target in handler.targets or []:
                triggers.add(_block_id(target[0] if isinstance(target, tuple) else target))

        inert = {
            _describe(block)
            for block in built.app.blocks.values()
            if isinstance(block, gr.Button) and block._id not in triggers
        }
        assert not sorted(inert - KNOWN_UNWIRED_D063), (
            "Bouton(s) qui ne declenchent aucun gestionnaire :\n  "
            + "\n  ".join(sorted(inert - KNOWN_UNWIRED_D063))
            + "\n\nL'utilisateur clique, rien ne se produit."
        )

    def test_exemptions_are_unambiguous(self, built):
        """Une exemption ne doit pas couvrir deux composants homonymes.

        Sans ce controle, exempter un libelle duplique masquerait le jour ou le
        second composant du meme nom, lui, se decablerait.
        """
        from collections import Counter

        counts = Counter(_describe(block) for block in _interactive_components(built.app))
        ambiguous = sorted(name for name in KNOWN_UNWIRED_D063 if counts[name] > 1)
        assert not ambiguous, (
            "Exemption(s) D-063 correspondant a plusieurs composants : "
            f"{ambiguous}. Renommez le libelle ou affinez l'identifiant, "
            "sinon l'exemption masque plus qu'elle ne declare."
        )

    def test_debt_inventory_is_declared_not_hidden(self, built):
        """Le compte de la dette est ecrit noir sur blanc, onglet par onglet.

        Le bloc 2 (DEC-012) a ramene la dette de dix-neuf exemptions a deux :
        les dix-sept composants de l'assistant guide sont desormais cables.
        Le bouton « Copier le prompt », relie a une copie cote navigateur,
        ferme les deux dernieres : la dette D-063 est soldee.
        """
        from collections import Counter

        by_tab = Counter(name.split(" | ")[0] for name in KNOWN_UNWIRED_D063)
        assert dict(by_tab) == EXPECTED_EXEMPTIONS_BY_TAB
        assert len(KNOWN_UNWIRED_D063) == 0
        assert len(_interactive_components(built.app)) == EXPECTED_INTERACTIVE_COUNT


# ═══════════════════════════════════════════════════════════════════════════
# 3. COUTURE wizard.py <-> interface.py : LE CONTRAT, PAS LA PRESENCE (D-074)
# ═══════════════════════════════════════════════════════════════════════════
#
# Le verrou d'orphelins ci-dessus compte un composant comme cable s'il est
# `inputs` **ou** `outputs`. Pour les trente champs de l'assistant, les deux
# roles sont distincts et chacun masque la perte de l'autre :
#
#   - sans les champs en `outputs`, aucune question ne s'affiche jamais ;
#   - sans les champs en `inputs`, le premier « Suivant » leve
#     `WizardCapacityError` ;
#   - un champ construit dans le mauvais type Gradio rend une question
#     inutilisable sans qu'aucun compte ne bouge.
#
# Ces trois mutations ont ete mesurees survivantes le 2026-09-07 sur la suite
# entiere : l'onglet etait mort, la suite verte. C'est la rechute de D-063,
# que les tests de presence ne peuvent pas voir par construction. Ce qui suit
# verifie donc le **contrat** : quels composants, dans quel ordre, de quel
# type — position par position.


#: Signature discriminante attendue pour chaque type de question, ecrite ici
#: independamment de `_SLOT_FIELD_BUILDERS`. Une table derivee du code teste
#: ne prouverait rien : elle suivrait la faute.
#: Second membre : nombre de lignes pour un `Textbox`, drapeau `multiselect`
#: pour un `Dropdown`, `None` quand la classe suffit a distinguer.
EXPECTED_SLOT_SIGNATURES = {
    "text": ("Textbox", 1),
    "textarea": ("Textbox", 4),
    "select": ("Dropdown", False),
    "multiselect": ("Dropdown", True),
    "number": ("Number", None),
    "slider": ("Slider", None),
}


def _field_signature(block):
    """(classe Gradio, trait discriminant) d'un composant de champ."""
    name = type(block).__name__
    if name == "Textbox":
        return (name, getattr(block, "lines", None))
    if name == "Dropdown":
        return (name, bool(getattr(block, "multiselect", False)))
    return (name, None)


def _wizard_handler(app, function):
    """Le gestionnaire branche sur une fonction de navigation donnee."""
    from promptforge.web import wizard

    expected = getattr(wizard, function)
    found = [h for h in _handlers(app) if getattr(h, "fn", None) is expected]
    assert len(found) == 1, (
        f"{len(found)} gestionnaire(s) branche(s) sur wizard.{function} au lieu "
        f"d'un seul. Le cablage de l'assistant a change sans que ce test le sache."
    )
    return found[0]


class TestWizardSeamContract:
    """Le contrat de `web/wizard.py` est-il **exactement** ce qui est branche ?"""

    def test_navigation_outputs_carry_the_whole_field_pool(self, built):
        """Sans les champs en sortie, aucune question ne s'affiche jamais."""
        from promptforge.web.wizard import WIZARD_FIELD_COUNT, WIZARD_NAV_HEADER_COUNT

        for function in ("start_wizard", "go_next", "go_prev"):
            outputs = list(_wizard_handler(built.app, function).outputs or [])
            assert len(outputs) == WIZARD_NAV_HEADER_COUNT + WIZARD_FIELD_COUNT, (
                f"wizard.{function} rend "
                f"{WIZARD_NAV_HEADER_COUNT + WIZARD_FIELD_COUNT} valeurs mais "
                f"{len(outputs)} composants sont branches en sortie. Les valeurs "
                f"excedentaires sont jetees : les champs concernes ne s'affichent "
                f"jamais et l'onglet est mort sans qu'aucun compte ne bouge."
            )

    def test_navigation_inputs_carry_the_whole_field_pool(self, built):
        """Sans les champs en entree, le premier « Suivant » leve WizardCapacityError."""
        from promptforge.web.wizard import WIZARD_FIELD_COUNT

        state_count = 3  # profession, step, answers
        for function in ("go_next", "go_prev"):
            inputs = list(_wizard_handler(built.app, function).inputs or [])
            assert len(inputs) == state_count + WIZARD_FIELD_COUNT, (
                f"wizard.{function} lit {WIZARD_FIELD_COUNT} champs apres ses "
                f"{state_count} etats, mais {len(inputs)} composants sont branches "
                f"en entree. `collect_answers` refuse une charge tronquee : "
                f"l'utilisateur recevrait une erreur des le premier « Suivant »."
            )

    def test_inputs_and_outputs_designate_the_very_same_fields(self, built):
        """Meme pool, meme ordre : sinon une reponse atterrit sur une autre question.

        Compare par `_id`, seule identite fiable d'un composant Gradio. Le
        pool est positionnel : un decalage d'un cran suffit a stocker la
        reponse d'une question dans une autre.
        """
        from promptforge.web.wizard import WIZARD_NAV_HEADER_COUNT

        for function in ("go_next", "go_prev"):
            handler = _wizard_handler(built.app, function)
            out_fields = [c._id for c in list(handler.outputs or [])[WIZARD_NAV_HEADER_COUNT:]]
            in_fields = [c._id for c in list(handler.inputs or [])[3:]]
            assert in_fields == out_fields, (
                f"wizard.{function} : les champs lus ne sont pas ceux ecrits.\n"
                f"  entrees : {in_fields}\n  sorties : {out_fields}"
            )

    def test_each_field_has_the_gradio_class_its_slot_position_demands(self, built):
        """Un champ NUMBER rendu en Slider reste « cable » et devient inutilisable."""
        from promptforge.web.wizard import (
            FIELDS_PER_SLOT,
            SLOT_TYPE_ORDER,
            WIZARD_NAV_HEADER_COUNT,
        )

        fields = list(_wizard_handler(built.app, "go_next").outputs or [])[WIZARD_NAV_HEADER_COUNT:]
        for index, block in enumerate(fields):
            question_type = SLOT_TYPE_ORDER[index % FIELDS_PER_SLOT]
            expected = EXPECTED_SLOT_SIGNATURES[question_type.value]
            assert _field_signature(block) == expected, (
                f"Bloc {index // FIELDS_PER_SLOT + 1}, position "
                f"« {question_type.value} » : composant {_field_signature(block)} "
                f"au lieu de {expected}. Une question de ce type serait rendue "
                f"dans un champ d'un autre type — visible, cable, inutilisable."
            )

    def test_the_signature_table_covers_every_declared_slot_type(self):
        """La table du test doit suivre `SLOT_TYPE_ORDER`, sinon elle devient borgne."""
        from promptforge.web.wizard import SLOT_TYPE_ORDER

        assert {q.value for q in SLOT_TYPE_ORDER} == set(EXPECTED_SLOT_SIGNATURES), (
            "Un type de question a ete ajoute ou retire de SLOT_TYPE_ORDER sans "
            "que EXPECTED_SLOT_SIGNATURES ne suive : la verification de type "
            "laisserait passer le nouveau venu."
        )

    def test_an_unknown_question_type_is_refused_not_silently_rendered(self):
        """Le repli silencieux est interdit : un type inconnu doit lever.

        Piege documente par `CLAUDE.md` pour `get_profile()`, qui retombe sur
        « universel » sans echouer et sert le mauvais prompt.
        """
        from promptforge.web.wizard import UnsupportedQuestionTypeError, build_slot_field

        with pytest.raises(UnsupportedQuestionTypeError):
            build_slot_field("un-type-qui-n-existe-pas", "Q1")


# ═══════════════════════════════════════════════════════════════════════════
# 4. VERROUS DE STRUCTURE : UNE SUPPRESSION ACCIDENTELLE SE VOIT
# ═══════════════════════════════════════════════════════════════════════════


class TestAssemblyIsLocked:
    def test_block_count_is_locked(self, built):
        assert len(built.app.blocks) == EXPECTED_BLOCK_COUNT, (
            f"L'application compte {len(built.app.blocks)} blocs au lieu de "
            f"{EXPECTED_BLOCK_COUNT}. Si le changement est voulu, mettez a jour "
            f"EXPECTED_BLOCK_COUNT dans le meme commit et dites pourquoi."
        )

    def test_handler_count_is_locked(self, built):
        handlers = _handlers(built.app)
        assert len(handlers) == EXPECTED_HANDLER_COUNT, (
            f"L'application compte {len(handlers)} gestionnaires au lieu de "
            f"{EXPECTED_HANDLER_COUNT}. Une suppression accidentelle rend "
            f"silencieusement des boutons inertes."
        )

    def test_every_handler_has_a_trigger(self, built):
        """Un gestionnaire sans declencheur est du code que rien n'appelle."""
        orphan_handlers = [handler for handler in _handlers(built.app) if not handler.targets]
        assert not orphan_handlers, (
            f"{len(orphan_handlers)} gestionnaire(s) sans declencheur : "
            f"la fonction existe, rien ne la declenche."
        )
