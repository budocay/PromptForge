# Contribuer à PromptForge

Merci de l'intérêt. Ce document dit comment monter l'environnement, ce qui est
vérifié et ce qui ne l'est pas.

---

## Monter l'environnement

```bash
git clone https://github.com/budocay/PromptForge.git
cd PromptForge
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -e ".[all]"
```

`[all]` installe Gradio (interface web), tiktoken (comptage de tokens) et les
outils de dev (pytest, pytest-cov, black, ruff).

Vérifie :

```bash
python start.py --check
```

Le Makefile appelle `python3 -m pytest` / `-m ruff` / `-m black` : avec le venv
actif, c'est celui du venv. Sinon, indique-le : `make test PYTHON=.venv/bin/python`.

---

## Lancer les tests

```bash
make test                      # toute la suite
pytest tests/ -q               # idem, en plus court
pytest tests/test_core.py -v   # un fichier
make test-cov                  # couverture, rapport HTML
```

Les tests unitaires simulent Ollama et sont rapides. Les tests d'intégration de
`tests/test_ollama_integration.py` appellent un vrai modèle : ils sont ignorés
si Ollama ne répond pas, et allongent nettement la suite s'il répond.

**Un test rouge bloque.** Si tu ne peux pas exécuter un test dans ton
environnement, dis-le explicitement dans la PR avec la commande à lancer,
plutôt que d'annoncer qu'il passe.

---

## Style de code

- Formateur : **black**, `line-length = 100`
- Linter : **ruff**, règles `E, F, W, I, N, UP`
- Python 3.10, 3.11, 3.12
- Docstrings : style Google
- Annotations de type : encouragées, pas imposées

```bash
make format         # black, réécrit
make lint           # ruff
make format-check   # black en lecture seule
```

`make lint` et `make format-check` sont verts sur toute la base : garde-les
verts. `make check` enchaîne lint, format-check et tests.

---

## Intégration continue

`.github/workflows/ci.yml` tourne sur chaque PR et chaque push sur `main` :

- `ruff check` et `black --check` (versions figées dans le workflow) ;
- `pytest -m "not integration"` sous Python 3.10, 3.11 et 3.12.

Aucun Ollama ne tourne sur le runner : ses tests d'intégration sont ignorés, et
les tests marqués `integration` (appels réels à OSV.dev) sont exclus. Lance-les
en local si tu touches à ces chemins, et dis-le dans la PR.

Avant de proposer une modification :

```bash
make check
```

---

## Organisation du code

```
promptforge/
├── core.py          orchestration, CRUD projets, format_prompt()
├── providers.py     client HTTP Ollama, conversion Markdown ↔ XML
├── database.py      SQLite
├── profiles.py      9 profils de modèles cibles
├── cli.py           interface argparse
├── tokens.py        estimation de tokens (tiktoken ou heuristique)
├── scanner.py       scanner de projets
├── security.py      CVE via OSV.dev, règles de sécurité
├── models_catalog.py  catalogue des modèles Ollama locaux
├── hardware.py      mesure de la machine
└── web/             paquet de l'interface Gradio, découpé par responsabilité

tests/               pytest
docker/              Dockerfile, Dockerfile.web, compose/ (6 variantes GPU)
compose.yaml         compose par défaut, à la racine
scripts/             outils de build
docs/                documentation
```

`promptforge/web/` est un paquet découpé par responsabilité : `interface.py`
assemble l'UI, les autres modules portent la logique (`analysis.py`,
`recommendations.py`, `scanner_helpers.py`, `onboarding.py`...).

---

## Quelques pièges

**Ajouter un profil de modèle** ne se limite pas à `profiles.py`. Il faut aussi :

- `web/profiles_ui.py::PROFILE_DESCRIPTIONS` — les clés sont couplées par chaîne
  à `PRESET_PROFILES`, et `get_profile()` retombe **silencieusement** sur
  `universel`. Un décalage sert le mauvais prompt sans lever d'erreur.
- `web/recommendations.py::DOMAIN_EXPERTISE` — chaque membre de `TargetModel` y
  est câblé au niveau module. Une entrée manquante lève un `KeyError` à
  l'exécution et casse l'import de tout le paquet `web`.

**Les sept fichiers compose doivent rester cohérents.** Modifier une seule
variante en laissant les six autres derrière crée une divergence silencieuse.
`promptforge-web` est le seul service commun aux sept ; le fichier par défaut ne
déclare **que** celui-là. Aucune commande du dépôt ne doit nommer `ollama` ou
`promptforge` sans passer un `-f` vers une variante qui les déclare.
`tests/test_launcher.py::TestComposeServiceSeam` verrouille ce point.

**Les images de base sont épinglées** sur une version exacte
(`python:3.12-slim`). Ne jamais passer à `latest`.

**Aucun secret en clair**, jamais, dans un compose, un Dockerfile ou un script.
PromptForge n'a besoin d'aucune clé d'API pour fonctionner : si tu en ajoutes
une, c'est probablement un signe que la conception dérive.

---

## Ouvrir une pull request

1. Branche depuis `main`.
2. Un sujet par PR.
3. Tests inclus, couvrant les cas d'erreur et les limites, pas seulement le
   chemin nominal.
4. `make test` vert.
5. Dans la description : ce que tu as changé, **les commandes que tu as
   exécutées et leur sortie**, et ce que tu n'as pas pu vérifier avec la raison.

Une vérification impossible dans ton environnement se déclare comme telle. Elle
ne se déclare pas comme réussie.

---

## Licence

En contribuant, tu acceptes que ta contribution soit publiée sous licence MIT,
comme le reste du projet. Voir [LICENSE](LICENSE).
