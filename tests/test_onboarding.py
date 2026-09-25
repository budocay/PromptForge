"""
Tests pour le système d'onboarding guidé.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestOnboardingFlows:
    """Tests pour les flows d'onboarding."""

    def test_import_onboarding(self):
        """Vérifie que le module onboarding est importable."""
        from promptforge.web.onboarding import (
            generate_context_from_answers,
            get_available_professions,
            get_onboarding_flow,
        )

        assert callable(get_available_professions)
        assert callable(get_onboarding_flow)
        assert callable(generate_context_from_answers)

    def test_onboarding_flows_exist(self):
        """Vérifie que les flows d'onboarding existent."""
        from promptforge.web.onboarding import ONBOARDING_FLOWS

        expected_professions = [
            "seo-specialist",
            "marketing-digital",
            "dev-backend",
            "product-manager",
            "commercial-sales",
            "rh-recruteur",
            "data-analyst",
            "support-client",
        ]

        for profession in expected_professions:
            assert profession in ONBOARDING_FLOWS, f"Flow manquant: {profession}"

    def test_flow_structure(self):
        """Vérifie la structure d'un flow."""
        from promptforge.web.onboarding import ONBOARDING_FLOWS

        for key, flow in ONBOARDING_FLOWS.items():
            assert "name" in flow, f"{key}: 'name' manquant"
            assert "welcome" in flow, f"{key}: 'welcome' manquant"
            assert "steps" in flow, f"{key}: 'steps' manquant"
            assert len(flow["steps"]) >= 3, f"{key}: moins de 3 étapes"

    def test_step_structure(self):
        """Vérifie la structure des étapes."""
        from promptforge.web.onboarding import ONBOARDING_FLOWS

        for key, flow in ONBOARDING_FLOWS.items():
            for i, step in enumerate(flow["steps"]):
                assert hasattr(step, "title"), f"{key} step {i}: 'title' manquant"
                assert hasattr(step, "description"), f"{key} step {i}: 'description' manquant"
                assert hasattr(step, "questions"), f"{key} step {i}: 'questions' manquant"
                assert len(step.questions) >= 1, f"{key} step {i}: pas de questions"

    def test_question_structure(self):
        """Vérifie la structure des questions."""
        from promptforge.web.onboarding import ONBOARDING_FLOWS, QuestionType

        for key, flow in ONBOARDING_FLOWS.items():
            for step in flow["steps"]:
                for q in step.questions:
                    assert hasattr(q, "id"), f"Question sans id dans {key}"
                    assert hasattr(q, "label"), f"Question sans label dans {key}"
                    assert hasattr(q, "question_type"), f"Question sans type dans {key}"
                    assert isinstance(q.question_type, QuestionType)


class TestContextGeneration:
    """Tests pour la génération de contexte."""

    def test_generate_empty_answers(self):
        """Génère un contexte avec des réponses vides."""
        from promptforge.web.onboarding import generate_context_from_answers

        result = generate_context_from_answers("seo-specialist", {})

        assert result is not None
        assert len(result) > 100
        assert "# Configuration Projet" in result

    def test_generate_with_answers(self):
        """Génère un contexte avec des réponses."""
        from promptforge.web.onboarding import generate_context_from_answers

        answers = {
            "level": "Senior (3-5 ans)",
            "site_url": "mon-site.fr",
            "site_type": "Blog",
            "site_niche": "Jardinage",
            "domain_rating": 25,
        }

        result = generate_context_from_answers("seo-specialist", answers)

        assert "mon-site.fr" in result
        assert "Jardinage" in result
        assert "Blog" in result

    def test_generate_includes_llm_instructions(self):
        """Vérifie que les instructions LLM sont incluses."""
        from promptforge.web.onboarding import generate_context_from_answers

        result = generate_context_from_answers("dev-backend", {"level": "Senior"})

        assert "Instructions pour le LLM" in result
        assert "Utilise mon contexte" in result

    def test_generate_for_all_professions(self):
        """Génère un contexte pour chaque métier."""
        from promptforge.web.onboarding import ONBOARDING_FLOWS, generate_context_from_answers

        for profession_key in ONBOARDING_FLOWS.keys():
            result = generate_context_from_answers(profession_key, {})
            assert result is not None, f"Génération échouée pour {profession_key}"
            assert len(result) > 200, f"Contexte trop court pour {profession_key}"


class TestGetFunctions:
    """Tests pour les fonctions d'accès."""

    def test_get_available_professions(self):
        """Vérifie la liste des professions disponibles."""
        from promptforge.web.onboarding import get_available_professions

        professions = get_available_professions()

        assert isinstance(professions, list)
        assert len(professions) >= 8

        for name, key in professions:
            assert isinstance(name, str)
            assert isinstance(key, str)
            assert len(name) > 0
            assert len(key) > 0

    def test_get_onboarding_flow(self):
        """Vérifie la récupération d'un flow."""
        from promptforge.web.onboarding import get_onboarding_flow

        flow = get_onboarding_flow("seo-specialist")
        assert flow is not None
        assert "name" in flow
        assert "steps" in flow

    def test_get_nonexistent_flow(self):
        """Vérifie le comportement avec un flow inexistant."""
        from promptforge.web.onboarding import get_onboarding_flow

        flow = get_onboarding_flow("metier-qui-nexiste-pas")
        assert flow is None


class TestQuestionTypes:
    """Tests pour les types de questions."""

    def test_all_question_types_used(self):
        """Vérifie que tous les types de questions sont utilisés."""
        from promptforge.web.onboarding import ONBOARDING_FLOWS, QuestionType

        used_types = set()

        for flow in ONBOARDING_FLOWS.values():
            for step in flow["steps"]:
                for q in step.questions:
                    used_types.add(q.question_type)

        # Au moins TEXT, SELECT, MULTISELECT doivent être utilisés
        assert QuestionType.TEXT in used_types
        assert QuestionType.SELECT in used_types
        assert QuestionType.MULTISELECT in used_types

    def test_select_questions_have_options(self):
        """Vérifie que les SELECT ont des options."""
        from promptforge.web.onboarding import ONBOARDING_FLOWS, QuestionType

        for key, flow in ONBOARDING_FLOWS.items():
            for step in flow["steps"]:
                for q in step.questions:
                    if q.question_type in [QuestionType.SELECT, QuestionType.MULTISELECT]:
                        assert len(q.options) >= 2, f"{key}: {q.id} a moins de 2 options"


# ═══════════════════════════════════════════════════════════════════════════
# CABLAGE DE L'ASSISTANT GUIDE — DEC-012, D-063, D-064
# ═══════════════════════════════════════════════════════════════════════════
#
# Jusqu'au bloc 2, `interface.py` portait l'aveu en clair :
# « # Logique complete du wizard serait ici ». L'utilisateur choisissait son
# metier, « Demarrer l'assistant » apparaissait, il cliquait, et rien ne se
# produisait. Les tests ci-dessus verifiaient la **donnee** du questionnaire ;
# aucun ne verifiait qu'on puisse y repondre.
#
# Ces tests-ci pilotent le parcours en appelant les gestionnaires de
# `web/wizard.py` directement, avec des etats d'entree construits — un import
# reussi ou une page qui repond ne prouvent rien sur un parcours.

gr = pytest.importorskip("gradio", reason="Gradio est un extra optionnel ([web])")


class WizardDriver:
    """Utilisateur simule : lit les mises a jour rendues, remplit, navigue.

    Le pilote ne consulte **jamais** `ONBOARDING_FLOWS` pour savoir quoi
    remplir : il ne voit que ce que l'interface lui rend visible, exactement
    comme un humain. C'est ce qui rend le verdict « aucune question perdue »
    significatif — une question qu'aucun champ n'expose ne sera pas remplie,
    et ressortira en « Non renseigné » dans le contexte genere.
    """

    def __init__(self):
        from promptforge.web import wizard

        self.w = wizard
        self.raw = [None] * wizard.WIZARD_FIELD_COUNT
        self.view = None
        self.sentinels = {}

    # -- lecture de la vue ------------------------------------------------
    def header(self, name):
        return self.view[self.w.WIZARD_NAV_OUTPUT_NAMES.index(name)]

    @property
    def fields(self):
        return list(self.view[self.w.WIZARD_NAV_HEADER_COUNT :])

    @property
    def visible_fields(self):
        return [(i, u) for i, u in enumerate(self.fields) if u.get("visible")]

    def _absorb(self):
        """Le navigateur adopte les valeurs poussees par le serveur."""
        for index, update in enumerate(self.fields):
            if "value" in update:
                self.raw[index] = update["value"]

    # -- actions ----------------------------------------------------------
    def start(self, profession_label):
        self.view = self.w.start_wizard(profession_label)
        self._absorb()
        return self

    def fill_visible_step(self, tag):
        """Saisit une valeur tracable dans chaque champ visible."""
        for index, update in self.visible_fields:
            qtype = self.w.SLOT_TYPE_ORDER[index % self.w.FIELDS_PER_SLOT]
            self.raw[index] = self._value_for(qtype, update, tag, index)

    def _value_for(self, qtype, update, tag, index):
        from promptforge.web.onboarding import QuestionType

        token = f"SENTINELLE-{tag}-{index}"
        if qtype is QuestionType.MULTISELECT:
            choices = list(update.get("choices") or [])
            picked = choices[:1]
            self.sentinels[token] = picked[0] if picked else ""
            return picked
        if qtype is QuestionType.SELECT:
            choices = list(update.get("choices") or [])
            picked = choices[0] if choices else token
            self.sentinels[token] = picked
            return picked
        if qtype in (QuestionType.NUMBER, QuestionType.SLIDER):
            value = int(update.get("minimum") or 0) + 3
            self.sentinels[token] = str(value)
            return value
        self.sentinels[token] = token
        return token

    def next(self):
        self.view = self.w.go_next(
            self.header("profession"), self.header("step"), self.header("answers"), *self.raw
        )
        self._absorb()
        return self

    def prev(self):
        self.view = self.w.go_prev(
            self.header("profession"), self.header("step"), self.header("answers"), *self.raw
        )
        self._absorb()
        return self

    def on_questions_screen(self):
        return self.header("questions_group").get("visible") is True

    def on_result_screen(self):
        return self.header("result_group").get("visible") is True

    def result_text(self):
        return self.header("result").get("value", "")


def _walk_whole_flow(profession_label, max_steps=50):
    """Deroule un parcours complet en remplissant tout ce qui est visible."""
    driver = WizardDriver().start(profession_label)
    guard = 0
    while driver.on_questions_screen():
        guard += 1
        assert guard < max_steps, "Parcours qui ne se termine pas"
        driver.fill_visible_step(f"s{guard}")
        driver.next()
    return driver


class TestWizardCapacity:
    """Le piege central : une implementation naive ampute le questionnaire."""

    def test_slot_pool_matches_the_longest_step_measured(self):
        from promptforge.web.onboarding import ONBOARDING_FLOWS
        from promptforge.web.wizard import WIZARD_SLOT_COUNT

        longest = max(
            len(step.questions) for flow in ONBOARDING_FLOWS.values() for step in flow["steps"]
        )
        assert longest == 5, f"Mesure de reference deplacee : {longest} au lieu de 5"
        assert WIZARD_SLOT_COUNT >= longest, (
            f"Pool de {WIZARD_SLOT_COUNT} blocs pour une etape de {longest} questions : "
            f"les questions excedentaires seraient perdues sans un mot."
        )

    def test_plan_never_truncates_a_step(self):
        from promptforge.web.onboarding import ONBOARDING_FLOWS
        from promptforge.web.wizard import plan_step

        for key, flow in ONBOARDING_FLOWS.items():
            for index, step in enumerate(flow["steps"]):
                planned = [q for q in plan_step(key, index) if q is not None]
                assert [q.id for q in planned] == [q.id for q in step.questions], (
                    f"{key} etape {index} : le plan ne restitue pas les questions "
                    f"dans leur ordre d'ecriture."
                )

    def test_every_step_exposes_exactly_its_questions(self):
        """Autant de champs visibles que de questions, ni plus ni moins."""
        from promptforge.web.onboarding import ONBOARDING_FLOWS
        from promptforge.web.wizard import field_updates

        for key, flow in ONBOARDING_FLOWS.items():
            for index, step in enumerate(flow["steps"]):
                updates = field_updates(key, index, {})
                visible = [u for u in updates if u.get("visible")]
                assert len(visible) == len(step.questions), (
                    f"{key} etape {index} : {len(visible)} champs visibles pour "
                    f"{len(step.questions)} questions."
                )

    def test_capacity_error_when_a_step_exceeds_the_pool(self, monkeypatch):
        """Le depassement doit hurler, jamais tronquer."""
        from promptforge.web import wizard

        monkeypatch.setattr(wizard, "WIZARD_SLOT_COUNT", 1)
        with pytest.raises(wizard.WizardCapacityError):
            wizard.plan_step("seo-specialist", 0)

    def test_collect_refuses_a_truncated_payload(self, monkeypatch):
        """Moins de valeurs que de champs = reponse perdue : on refuse."""
        from promptforge.web import wizard

        with pytest.raises(wizard.WizardCapacityError):
            wizard.collect_answers("seo-specialist", 0, {}, [None] * 2)


class TestWizardReachesEveryQuestion:
    """Critere d'acceptation principal : les 123 questions sont atteignables."""

    def test_full_walk_answers_every_question_of_every_profession(self):
        from promptforge.web.onboarding import ONBOARDING_FLOWS

        grand_total = 0
        for key, flow in ONBOARDING_FLOWS.items():
            expected = {q.id for step in flow["steps"] for q in step.questions}
            driver = _walk_whole_flow(flow["name"])

            assert driver.on_result_screen(), f"{key} : le parcours ne s'est pas termine"
            answered = set(driver.header("answers"))
            assert expected - answered == set(), (
                f"{key} : question(s) jamais exposee(s) a l'utilisateur : "
                f"{sorted(expected - answered)}"
            )
            grand_total += len(expected)

        assert (
            grand_total == 123
        ), f"{grand_total} questions parcourues au lieu des 123 mesurees le 2026-09-07."

    def test_generated_context_holds_no_unanswered_question(self):
        """« Non renseigné » dans le contexte = question inatteignable."""
        from promptforge.web.onboarding import ONBOARDING_FLOWS

        for key, flow in ONBOARDING_FLOWS.items():
            context = _walk_whole_flow(flow["name"]).result_text()
            assert "Non renseigné" not in context, (
                f"{key} : au moins une question n'a jamais pu etre saisie, "
                f"le contexte genere la marque « Non renseigné »."
            )

    def test_every_question_label_appears_in_the_generated_context(self):
        from promptforge.web.onboarding import ONBOARDING_FLOWS

        for key, flow in ONBOARDING_FLOWS.items():
            context = _walk_whole_flow(flow["name"]).result_text()
            for step in flow["steps"]:
                for question in step.questions:
                    assert (
                        f"**{question.label}**" in context
                    ), f"{key} : « {question.label} » absente du contexte genere."

    def test_typed_values_survive_until_the_generated_context(self):
        driver = _walk_whole_flow("🔍 SEO Specialist")
        context = driver.result_text()
        typed = [v for v in driver.sentinels.values() if v]
        assert typed, "Le pilote n'a rien saisi : le test ne prouverait rien."
        for value in typed:
            assert value in context, f"Valeur saisie « {value} » perdue en route."


class TestWizardNavigation:
    def test_start_shows_the_first_step_and_hides_the_start_screen(self):
        driver = WizardDriver().start("🔍 SEO Specialist")
        assert driver.header("profession") == "seo-specialist"
        assert driver.header("step") == 0
        assert driver.header("start_group")["visible"] is False
        assert driver.on_questions_screen()
        assert "1/6" in driver.header("progress")

    def test_start_without_profession_stays_idle(self):
        driver = WizardDriver().start("")
        assert driver.header("start_group")["visible"] is True
        assert driver.on_questions_screen() is False
        assert driver.header("error") != ""

    def test_start_with_unknown_profession_stays_idle(self):
        driver = WizardDriver().start("🥐 Boulanger")
        assert driver.header("start_group")["visible"] is True
        assert driver.header("error") != ""

    def test_previous_is_not_an_action_on_the_first_step(self):
        driver = WizardDriver().start("🔍 SEO Specialist")
        assert driver.header("prev_btn")["visible"] is False

    def test_previous_becomes_available_from_the_second_step(self):
        driver = WizardDriver().start("🔍 SEO Specialist")
        driver.fill_visible_step("s1")
        driver.next()
        assert driver.header("step") == 1
        assert driver.header("prev_btn")["visible"] is True

    def test_next_turns_into_an_end_of_journey_on_the_last_step(self):
        from promptforge.web.onboarding import ONBOARDING_FLOWS

        for key, flow in ONBOARDING_FLOWS.items():
            driver = WizardDriver().start(flow["name"])
            last = len(flow["steps"]) - 1
            for index in range(last):
                assert (
                    driver.header("next_btn")["value"] == "Suivant ➡️"
                ), f"{key} etape {index} : le bouton annonce deja la fin."
                driver.fill_visible_step(f"s{index}")
                driver.next()
            assert driver.header("step") == last
            assert driver.header("next_btn")["value"] == "✅ Terminer"

    def test_going_back_keeps_the_answers_already_typed(self):
        driver = WizardDriver().start("🔍 SEO Specialist")
        driver.fill_visible_step("etape1")
        driver.next()
        first_step_answers = dict(driver.header("answers"))
        assert first_step_answers, "Rien n'a ete enregistre a la premiere etape"

        # `fill_visible_step` n'ecrit que cote navigateur (`driver.raw`) : la
        # vue serveur, elle, n'a pas encore vu l'etape 2. D'ou le nom — c'est
        # l'etat AVANT le retour arriere, pas « les reponses de l'etape 2 ».
        driver.fill_visible_step("etape2")
        answers_before_going_back = dict(driver.header("answers"))

        driver.prev()
        assert driver.header("step") == 0
        preserved = driver.header("answers")
        for question_id, value in first_step_answers.items():
            assert preserved[question_id] == value, (
                f"« {question_id} » perdue au retour arriere : "
                f"{preserved.get(question_id)!r} au lieu de {value!r}."
            )
        # Et le retour arriere enregistre aussi l'etape qu'on quitte : sans
        # cela, la saisie de la deuxieme etape partirait a la poubelle.
        assert set(preserved) > set(answers_before_going_back), (
            "Le retour arriere n'a enregistre aucune reponse de l'etape quittee : "
            f"{sorted(preserved)} n'ajoute rien a {sorted(answers_before_going_back)}."
        )

    def test_typing_then_going_back_and_forward_restores_the_typed_values(self):
        """Aller-retour complet : ce qui a ete saisi a l'etape 2 revient a l'ecran."""
        driver = WizardDriver().start("🔍 SEO Specialist")
        driver.fill_visible_step("etape1")
        driver.next()

        driver.fill_visible_step("etape2")
        typed = {index: driver.raw[index] for index, _ in driver.visible_fields}
        assert typed, "Rien n'a ete saisi a la deuxieme etape"

        driver.prev()
        driver.next()

        assert driver.header("step") == 1
        for index, update in driver.visible_fields:
            assert update["value"] == typed[index], (
                f"Champ {index} : {update['value']!r} au lieu de {typed[index]!r}. "
                f"La saisie de l'etape quittee a ete perdue par le retour arriere."
            )

    def test_going_back_repopulates_the_fields_with_previous_answers(self):
        """Le retour arriere reaffiche les valeurs, il ne rend pas des champs vides."""
        driver = WizardDriver().start("🔍 SEO Specialist")
        driver.fill_visible_step("etape1")
        typed = {i: driver.raw[i] for i, _ in driver.visible_fields}
        driver.next()
        driver.fill_visible_step("etape2")
        driver.prev()

        for index, update in driver.visible_fields:
            assert update["value"] == typed[index], (
                f"Champ {index} reaffiche a {update['value']!r} au lieu de "
                f"{typed[index]!r} : la saisie n'est pas restituee."
            )

    def test_previous_on_the_first_step_does_not_go_negative(self):
        driver = WizardDriver().start("🔍 SEO Specialist")
        driver.fill_visible_step("s1")
        driver.prev()
        assert driver.header("step") == 0
        assert driver.on_questions_screen()

    def test_navigation_on_a_lost_state_returns_to_the_start_screen(self):
        from promptforge.web.wizard import WIZARD_FIELD_COUNT, go_next, go_prev

        for handler in (go_next, go_prev):
            view = handler("", 0, {}, *([None] * WIZARD_FIELD_COUNT))
            assert view[3]["visible"] is True  # start_group
            assert view[4]["visible"] is False  # questions_group

    def test_collect_does_not_mutate_the_state_it_receives(self):
        """L'etat Gradio est recopie, jamais mute : sinon deux ecrans le partagent."""
        from promptforge.web.wizard import WIZARD_FIELD_COUNT, collect_answers

        incoming = {"deja": "la"}
        raw = [None] * WIZARD_FIELD_COUNT
        raw[2] = "peu importe"
        merged = collect_answers("seo-specialist", 0, incoming, raw)
        assert incoming == {"deja": "la"}, "L'etat d'entree a ete mute en place"
        assert merged is not incoming

    def test_hidden_fields_never_contaminate_another_question(self):
        """Un champ masque garde sa valeur cote navigateur : elle doit etre ignoree."""
        from promptforge.web.wizard import WIZARD_FIELD_COUNT, collect_answers

        polluted = ["POLLUTION"] * WIZARD_FIELD_COUNT
        answers = collect_answers("seo-specialist", 0, {}, polluted)
        assert set(answers) == {"level", "specialization"}


class TestWizardRequiredFields:
    def test_a_missing_required_answer_blocks_and_explains(self):
        from promptforge.web.wizard import WIZARD_FIELD_COUNT, go_next

        view = go_next("seo-specialist", 0, {}, *([None] * WIZARD_FIELD_COUNT))
        names = _nav_names()
        assert view[names.index("step")] == 0, "Le parcours a avance malgre un champ requis vide"
        assert "obligatoire" in view[names.index("error")].lower()
        assert view[names.index("questions_group")]["visible"] is True

    def test_blocking_does_not_discard_what_was_already_typed(self):
        """L'etape 1 du SEO a un champ requis (« level ») et un champ libre.

        Le blocage sur le requis ne doit pas jeter la reponse au libre :
        c'est exactement le scenario ou l'utilisateur perd sa saisie.
        """
        from promptforge.web.onboarding import ONBOARDING_FLOWS, QuestionType
        from promptforge.web.wizard import (
            FIELDS_PER_SLOT,
            SLOT_TYPE_INDEX,
            WIZARD_FIELD_COUNT,
            go_next,
        )

        questions = ONBOARDING_FLOWS["seo-specialist"]["steps"][0].questions
        slot = next(i for i, q in enumerate(questions) if not q.required)
        question = questions[slot]
        assert (
            question.question_type is QuestionType.MULTISELECT
        ), "Type de « specialization » deplace : reajustez la valeur saisie."

        raw = [None] * WIZARD_FIELD_COUNT
        raw[slot * FIELDS_PER_SLOT + SLOT_TYPE_INDEX[question.question_type]] = ["SEO Technique"]
        view = go_next("seo-specialist", 0, {}, *raw)
        answers = view[_nav_names().index("answers")]
        assert answers[question.id] == ["SEO Technique"]

    def test_answering_the_required_field_unblocks(self):
        from promptforge.web.onboarding import QuestionType
        from promptforge.web.wizard import (
            FIELDS_PER_SLOT,
            SLOT_TYPE_INDEX,
            WIZARD_FIELD_COUNT,
            go_next,
        )

        raw = [None] * WIZARD_FIELD_COUNT
        raw[0 * FIELDS_PER_SLOT + SLOT_TYPE_INDEX[QuestionType.SELECT]] = "Expert (5+ ans)"
        view = go_next("seo-specialist", 0, {}, *raw)
        assert view[_nav_names().index("step")] == 1
        assert view[_nav_names().index("error")] == ""


def _nav_names():
    from promptforge.web.wizard import WIZARD_NAV_OUTPUT_NAMES

    return list(WIZARD_NAV_OUTPUT_NAMES)


class TestWizardRestart:
    def test_restart_really_resets_the_three_states(self):
        from promptforge.web.wizard import WIZARD_RESTART_OUTPUT_NAMES, restart_wizard

        view = restart_wizard()
        names = list(WIZARD_RESTART_OUTPUT_NAMES)
        assert view[names.index("profession")] == ""
        assert view[names.index("step")] == 0
        assert view[names.index("answers")] == {}
        assert view[names.index("start_group")]["visible"] is True
        assert view[names.index("questions_group")]["visible"] is False
        assert view[names.index("result_group")]["visible"] is False
        assert view[names.index("result")]["value"] == ""
        assert view[names.index("project_name")]["value"] == ""
        assert view[names.index("save_status")] == ""

    def test_restart_answers_are_not_the_same_object_twice(self):
        """Deux redemarrages ne doivent pas partager le meme dictionnaire."""
        from promptforge.web.wizard import WIZARD_RESTART_OUTPUT_NAMES, restart_wizard

        index = list(WIZARD_RESTART_OUTPUT_NAMES).index("answers")
        assert restart_wizard()[index] is not restart_wizard()[index]

    def test_a_fresh_walk_after_restart_does_not_inherit_old_answers(self):
        driver = _walk_whole_flow("🔍 SEO Specialist")
        assert driver.header("answers")
        again = WizardDriver().start("📊 Data Analyst")
        assert again.header("answers") == {}


class TestWizardSave:
    """Anti D-054 : une sauvegarde qui echoue le dit."""

    @pytest.fixture
    def sandbox(self, tmp_path):
        from promptforge.web import ollama_helpers

        saved = (ollama_helpers._base_path, ollama_helpers._forge)
        ollama_helpers.set_base_path(str(tmp_path))
        yield tmp_path
        ollama_helpers._base_path, ollama_helpers._forge = saved

    def test_save_creates_a_project_that_can_be_read_back(self, sandbox):
        from promptforge.web.ollama_helpers import get_forge
        from promptforge.web.wizard import save_wizard_project

        context = _walk_whole_flow("🔍 SEO Specialist").result_text()
        status, dropdown, _ = save_wizard_project("Mon Profil SEO", context)

        assert status.startswith("✅"), status
        forge = get_forge()
        project = forge.db.get_project("mon-profil-seo")
        assert project is not None, "Succes annonce mais aucun projet en base"
        assert project.config_content == context
        assert (forge.projects_path / "mon-profil-seo.md").read_text(encoding="utf-8") == context
        assert dropdown["value"] == "mon-profil-seo"

        # Le message annonce « cree ET active ». Verifier la seule creation
        # laissait disparaitre l'activation sans qu'un test ne bouge.
        assert "activé" in status, status
        active = forge.get_current_project()
        assert active is not None and active.name == "mon-profil-seo", (
            f"Activation annoncee mais projet actif = " f"{active.name if active else 'aucun'}."
        )
        # `is_active` remonte de SQLite en entier (1), pas en booleen, malgre
        # l'annotation `bool` de la dataclass : on teste la verite, pas le type.
        assert forge.db.get_project(
            "mon-profil-seo"
        ).is_active, "Le projet est en base mais son drapeau d'activation est faux."

    def test_empty_name_is_refused(self, sandbox):
        """Le refus doit etre prononce AVANT le disque, et pour le bon motif.

        Sans la garde de nom, `normalize_name("   ")` rend une chaine vide :
        le code ecrit un fichier litteralement nomme « .md », puis
        `init_project` le refuse au motif que ce n'est pas un fichier .md. Un
        `startswith("❌")` seul se contente de ce plantage en aval — il
        verrouille le message d'une autre erreur, pas la garde.
        """
        from promptforge.web.ollama_helpers import get_forge
        from promptforge.web.wizard import save_wizard_project

        status, _, _ = save_wizard_project("   ", "du contenu")
        assert "Nom de projet requis" in status, status
        assert not (get_forge().projects_path / ".md").exists(), (
            "Un fichier « .md » a ete ecrit avant le refus : la garde de nom a "
            "saute et l'erreur remontee vient d'un plantage en aval."
        )

    def test_empty_config_is_refused(self, sandbox):
        from promptforge.web.wizard import save_wizard_project

        status, _, _ = save_wizard_project("un-projet", "")
        assert status.startswith("❌")

    def test_a_write_failure_is_reported_not_swallowed(self, sandbox, monkeypatch):
        from pathlib import Path

        from promptforge.web.wizard import save_wizard_project

        def refuse(self, *args, **kwargs):
            raise OSError("disque plein")

        monkeypatch.setattr(Path, "write_text", refuse)
        status, _, _ = save_wizard_project("projet-disque", "du contenu")
        assert status.startswith("❌"), status
        assert "disque plein" in status

    def test_a_registration_failure_is_reported(self, sandbox, monkeypatch):
        from promptforge.web import wizard
        from promptforge.web.ollama_helpers import get_forge

        forge = get_forge()
        monkeypatch.setattr(
            type(forge), "init_project", lambda self, *a, **k: (False, "nom déjà pris")
        )
        status, _, _ = wizard.save_wizard_project("projet-refuse", "du contenu")
        assert status.startswith("❌")
        assert "nom déjà pris" in status

    def test_a_registration_that_raises_is_reported(self, sandbox, monkeypatch):
        from promptforge.web import wizard
        from promptforge.web.ollama_helpers import get_forge

        forge = get_forge()

        def boom(self, *a, **k):
            raise RuntimeError("base verrouillée")

        monkeypatch.setattr(type(forge), "init_project", boom)
        status, _, _ = wizard.save_wizard_project("projet-boom", "du contenu")
        assert status.startswith("❌")
        assert "base verrouillée" in status

    def test_a_silent_non_persistence_is_caught_by_the_read_back(self, sandbox, monkeypatch):
        """Enregistrement « reussi » mais projet absent : le succes est refuse."""
        from promptforge.web import wizard

        monkeypatch.setattr(wizard, "get_projects_list", lambda: ["🔧 Sans projet (prompt seul)"])
        status, _, _ = wizard.save_wizard_project("projet-fantome", "du contenu")
        assert status.startswith("❌"), status
        assert "introuvable" in status

    def test_an_activation_that_never_happened_is_caught_by_the_read_back(
        self, sandbox, monkeypatch
    ):
        """Projet cree mais non actif : le succes est refuse, pas maquille."""
        from promptforge.web import wizard
        from promptforge.web.ollama_helpers import get_forge

        forge = get_forge()
        monkeypatch.setattr(type(forge), "use_project", lambda self, *a, **k: (False, "raté"))
        status, _, _ = wizard.save_wizard_project("projet-inactif", "du contenu")
        assert status.startswith("❌"), status
        assert "non activé" in status
        assert forge.db.get_project("projet-inactif") is not None


class TestWizardIsActuallyWiredInTheInterface:
    """D-064 : `web/onboarding.py` doit etre joignable depuis l'interface."""

    def test_interface_no_longer_imports_the_wizard_without_calling_it(self):
        import promptforge.web.interface as interface

        source = Path(interface.__file__).read_text(encoding="utf-8")
        assert (
            "Logique complète du wizard serait ici" not in source
        ), "L'aveu de non-cablage est toujours dans le fichier."
        for handler in ("start_wizard", "go_next", "go_prev", "restart_wizard"):
            assert f"fn={handler}" in source, f"{handler} n'est branche sur aucun evenement."

    def test_profession_selection_reveals_the_start_button(self):
        from promptforge.web.wizard import on_profession_selected

        welcome, button = on_profession_selected("🔍 SEO Specialist")
        assert "6 étapes, 17 questions" in welcome
        assert button["visible"] is True

    def test_unknown_profession_hides_the_start_button(self):
        from promptforge.web.wizard import on_profession_selected

        welcome, button = on_profession_selected("")
        assert welcome == ""
        assert button["visible"] is False
