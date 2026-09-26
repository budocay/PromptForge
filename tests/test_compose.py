"""
Coherence des fichiers compose avec les variables lues par le code.

Un service qui fixe OLLAMA_MODEL fait tourner le code de reformatage, qui lit
aussi OLLAMA_TIMEOUT. Si le compose ne transmet pas cette variable, la regler
dans `.env` (comme le documente `.env.example`) reste sans effet.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILES = [ROOT / "compose.yaml", *sorted((ROOT / "docker" / "compose").glob("*.yml"))]


@pytest.mark.parametrize("compose_file", COMPOSE_FILES, ids=lambda p: p.name)
def test_every_service_with_a_model_also_receives_the_timeout(compose_file):
    lignes = compose_file.read_text(encoding="utf-8").splitlines()
    modeles = [i for i, ligne in enumerate(lignes) if re.search(r"-\s*OLLAMA_MODEL=", ligne)]
    assert modeles, f"{compose_file.name} ne fixe aucun OLLAMA_MODEL"

    for i in modeles:
        # Meme bloc `environment` : on cherche jusqu'a la prochaine cle de
        # premier niveau du service (indentation plus faible qu'un element).
        indent = len(lignes[i]) - len(lignes[i].lstrip())
        bloc = []
        for ligne in lignes[i + 1 :]:
            if ligne.strip() and len(ligne) - len(ligne.lstrip()) < indent:
                break
            bloc.append(ligne)
        assert any(
            "OLLAMA_TIMEOUT=${OLLAMA_TIMEOUT:-600}" in ligne for ligne in bloc
        ), f"{compose_file.name}:{i + 1} fixe OLLAMA_MODEL sans transmettre OLLAMA_TIMEOUT"
