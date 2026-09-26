# PromptForge

**Reformateur de prompts, 100 % local.** Tu écris un prompt court, PromptForge
le réécrit en prompt structuré (XML ou Markdown) en y injectant le contexte de
ton projet. Tout tourne sur ta machine via [Ollama](https://ollama.com) : aucun
prompt ne sort du réseau local, aucune clé d'API, aucun compte.

Pour qui : les gens qui écrivent beaucoup de prompts (dev, SEO, marketing, data,
produit, support) et qui répètent le même contexte à chaque fois.

Version 0.1.0 — alpha. Licence MIT.

---

## Ce que ça donne

Exemple mesuré le 2026-09-07, modèle `qwen3:8b`, avec un projet dont la config
tient en trois lignes (`Site: exemple.fr`, `Niche: jardinage`).

**Entrée** — 38 caractères :

```
trouve moi des mots cles pour mon site
```

**Sortie** — 1 331 caractères :

```xml
<task>
Identifier des mots-clés pertinents pour optimiser le référencement du site de jardinage exemple.fr.
</task>

<context>
Site web exemple.fr spécialisé dans le jardinage (jardinage, plantes, arrosage, entretien, etc.)
</context>

<instructions>
1. Réaliser une recherche de mots-clés via des outils SEO (Google Keyword Planner, Ahrefs)
2. Analyser les mots-clés concurrents des sites similaires dans le domaine du jardinage
...
</instructions>

<constraints>
- Prioriser les termes utiles pour le référencement naturel
...
</constraints>

<output_format>
Liste structurée de mots-clés avec catégorie, volume de recherche, pertinence
</output_format>
```

La sortie dépend du modèle, du prompt et de la config du projet : ce n'est pas
un gabarit fixe et le facteur d'enrichissement varie d'un appel à l'autre.

---

## Prérequis

| Composant | Version vérifiée | Nécessaire pour |
|---|---|---|
| [Ollama](https://ollama.com/download) | 0.33.3 | tous les modes — c'est le moteur |
| [Docker](https://docs.docker.com/get-docker/) + Compose | 29.7.2 / v5.5.0 | mode Docker uniquement |
| Python | 3.10+ (testé 3.12 en conteneur, 3.14 en natif) | mode natif uniquement |

### De quoi as-tu besoin comme machine

Chiffres du catalogue interne (`promptforge/models_catalog.py`, source
ollama.com, relevé le 2026-09-04). Les empreintes mémoire y sont marquées
`estimated` : ce sont des ordres de grandeur, pas des mesures.

| Modèle | Téléchargement | Mémoire à prévoir |
|---|---|---|
| `qwen3:4b` | 2,7 Go | ~3 Gio — machines sans GPU / faible RAM |
| `phi4-mini` | 2,7 Go | ~3,5 Gio — machines sans GPU / faible RAM |
| `qwen3:8b` | 5,6 Go | ~6,5 Gio — **le défaut**, GPU 8 Go ou RAM courante |
| `qwen3:14b` | 10,0 Go | ~11 Gio — meilleure qualité, GPU 12-16 Go |

Le catalogue en contient 18. `python launcher.py` mesure ta machine et te dit
lesquels y tiennent (voir plus bas).

Ollama tourne **sur la machine hôte, pas dans un conteneur**, y compris en mode
Docker. C'est le seul composant qui a besoin du GPU : Docker Desktop ne donne
pas accès à Metal sur macOS, et l'accès GPU sous Windows dépend du pilote. Un
Ollama conteneurisé y perdrait l'accélération matérielle. Le conteneur
PromptForge le rejoint sur l'hôte via `host.docker.internal`.

---

## Démarrage

### 1. Préparer Ollama (obligatoire, une fois)

```bash
ollama serve          # démarre le serveur, port 11434
ollama pull qwen3:8b  # ~5,6 Go
ollama list           # vérifie
```

Sur macOS et Windows, l'application Ollama lance `serve` toute seule.

### 2a. Avec Docker — le chemin le plus court

```bash
git clone https://github.com/budocay/PromptForge.git
cd PromptForge
docker compose up
```

L'interface s'ouvre sur **http://localhost:7860**.

Le port est volontairement lié à `127.0.0.1` : l'interface n'est joignable que
depuis ta machine, pas depuis le réseau.

Pour arrêter : `Ctrl-C`, ou `docker compose down` si tu as lancé avec `-d`.

### 2b. Sans Docker

```bash
git clone https://github.com/budocay/PromptForge.git
cd PromptForge
python3 -m venv .venv
source .venv/bin/activate         # Windows : .venv\Scripts\activate
pip install -e ".[all]"

python start.py --check           # diagnostic de l'installation
python start.py                   # lance l'interface sur http://localhost:7860
```

`python start.py --check` affiche l'état de Python, du package, de Gradio et
d'Ollama avant de tenter quoi que ce soit. C'est le premier réflexe si ça
coince.

### 2c. Le launcher — si tu ne sais pas quel modèle prendre

```bash
python launcher.py    # ouvre un tableau de bord sur http://localhost:7850
```

Le launcher **mesure ta machine** (CPU, mémoire, GPU, mémoire unifiée Apple
Silicon) et te dit quels modèles y tiennent, à partir d'un catalogue de 18
modèles renseignés avec leur empreinte mémoire et leur licence. Il pilote aussi
le démarrage et l'arrêt des conteneurs.

Par défaut il ne propose que les 11 modèles dont la licence est approuvée OSI ;
les autres restent au catalogue mais sont écartés du choix par défaut.

---

## Utiliser l'interface web

L'interface a huit onglets :

| Onglet | À quoi il sert |
|---|---|
| ✨ Reformater | l'écran principal : prompt brut → prompt structuré |
| 📁 Projets | créer, uploader ou écrire la config d'un projet |
| 🔍 Scanner | analyser un dossier de code et en générer la config |
| 👔 Templates Métiers | assistant guidé + templates pré-remplis |
| 📜 Historique | retrouver les prompts déjà reformatés |
| 🎯 Générer config | un prompt à donner à une IA pour qu'elle écrive ta config |
| 💰 Comparaison | tarifs des modèles commerciaux + calculateur de coût |
| ❓ Aide | rappels et dépannage |

Le sélecteur de modèle Ollama est en haut de la page, au-dessus des onglets. Il
liste les modèles réellement installés sur ta machine.

### Premier parcours

1. **Onglet `👔 Templates Métiers` → sous-onglet `🚀 Assistant Guidé`.**
   Choisis ton métier parmi les huit disponibles et réponds aux questions.
   L'assistant écrit la config du projet pour toi.
   Huit métiers : SEO Specialist, Marketing Digital, Dev Backend,
   Product Manager, Commercial / Sales, RH / Recruteur, Data Analyst,
   Support Client.

   *Variantes :* le sous-onglet `📄 Templates Manuels` donne six configs
   pré-remplies à éditer, et l'onglet `🔍 Scanner` génère la config
   automatiquement à partir d'un dossier de code existant.

2. **Onglet `✨ Reformater`.** Sélectionne ton projet, colle ton prompt brut,
   clique sur Reformater, copie le résultat.

---

## Ligne de commande

Onze commandes, disponibles après `pip install -e .` :

```bash
promptforge init <nom> --config <fichier.md>  # créer un projet
promptforge use <nom>                          # activer un projet
promptforge list                               # lister les projets
promptforge delete <nom>                       # supprimer un projet
promptforge reload <nom>                       # recharger sa config
promptforge scan <chemin> --name <nom>         # scanner un projet existant
promptforge format [prompt]                    # reformater un prompt
promptforge history [--limit N]                # consulter l'historique
promptforge status                             # état d'Ollama et des projets
promptforge template                           # afficher le template de config
promptforge web [--port 7860]                  # lancer l'interface web
```

`--path <dir>` choisit où sont stockées les données (base SQLite +
historique). C'est une option **globale**, elle se place avant la sous-commande :

```bash
promptforge --path ~/mes-prompts list
```

Par défaut, le dossier courant.

### Choisir le modèle en CLI

La CLI prend le même modèle que l'interface web : `OLLAMA_MODEL` s'il est
défini, sinon `qwen3:8b`. `--model` le remplace pour une commande :

```bash
promptforge format "ton prompt" --model qwen3:14b
```

Si le modèle n'est pas installé, le message le dit et donne la commande
`ollama pull` à lancer.

`--profile` choisit le LLM **cible**, celui à qui tu enverras le prompt
reformaté : il fixe le format produit (XML pour Claude et Gemini, Markdown
pour GPT, au choix pour `universel`). Sans `--profile`, la CLI produit un
prompt XML générique.

```bash
promptforge format "écris un email de relance client" --profile gpt_5.1
promptforge format --help     # liste des profils
```

Exemple complet :

```bash
promptforge init mon-projet --config config.md
promptforge use mon-projet
promptforge format "trouve moi des mots cles pour mon site"
```

Le cœur de la CLI n'utilise que la bibliothèque standard. Gradio et tiktoken
sont optionnels : `promptforge` fonctionne sans eux.

---

## Variables d'environnement

Elles n'ont pas toutes la même portée. C'est mesuré, pas supposé :

| Variable | Défaut | Lue par |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | interface web **et** CLI |
| `OLLAMA_MODEL` | `qwen3:8b` | interface web **et** CLI (`--model` le remplace) |
| `OLLAMA_TIMEOUT` | `600` (secondes) | interface web **et** CLI |
| `PROMPTFORGE_DATA_PATH` | dossier courant | interface web **et** CLI (`--path` le remplace) |
| `HOSTFS_PATH` | `../` | Docker : dossier monté en lecture seule pour le Scanner |

En CLI, `--model` et `--path` priment sur ces variables pour une commande.

En Docker, `compose.yaml` fixe déjà `OLLAMA_HOST`, `OLLAMA_MODEL`,
`OLLAMA_TIMEOUT` et `PROMPTFORGE_DATA_PATH`. Pour changer de modèle sans éditer le fichier :

```bash
OLLAMA_MODEL=qwen3:14b docker compose up
```

Le fichier `.env.example` documente les trois variables que `compose.yaml` lit
depuis un `.env` : `OLLAMA_MODEL`, `OLLAMA_TIMEOUT` et `HOSTFS_PATH`. Copie-le pour t'en servir :

```bash
cp .env.example .env
```

`.env` est ignoré par git. **Aucun secret n'est nécessaire au fonctionnement de
PromptForge — ni clé d'API, ni jeton, ni mot de passe. N'en mets pas dans ce
fichier.**

Le délai d'attente d'une réponse Ollama est de **600 secondes** par défaut et
se règle par `OLLAMA_TIMEOUT`. Ce défaut vient d'une mesure : sur un Mac M1 Max,
`qwen3:14b` a mis jusqu'à 195 s pour un reformatage ordinaire, sans charge
particulière. Voir la section Dépannage.

---

## Variantes Docker

Le chemin par défaut (`docker compose up`, fichier `compose.yaml`) fait tourner
l'interface en conteneur et rejoint l'Ollama natif de l'hôte. C'est le seul
chemin proposé sur macOS.

Sur Linux avec un GPU exposé à Docker, Ollama peut aussi tourner en conteneur :

```bash
docker compose -f docker/compose/docker-compose.yml up      # NVIDIA
docker compose -f docker/compose/docker-compose.amd.yml up  # AMD ROCm
docker compose -f docker/compose/docker-compose.cpu.yml up  # sans GPU
```

Sept fichiers compose au total. Les services qu'ils déclarent, mesurés avec
`docker compose -f <fichier> config --services` :

| Fichier | Ollama | Services déclarés |
|---|---|---|
| `compose.yaml` (défaut) | natif sur l'hôte | `promptforge-web` |
| `docker/compose/docker-compose.yml` | conteneur, NVIDIA | `ollama`, `ollama-pull`, `promptforge`, `promptforge-web` |
| `docker/compose/docker-compose.cpu.yml` | conteneur, CPU | `ollama`, `ollama-pull`, `promptforge`, `promptforge-web` |
| `docker/compose/docker-compose.amd.yml` | conteneur, ROCm | `ollama`, `promptforge-web` |
| `docker/compose/docker-compose.amd-max.yml` | conteneur, ROCm | `ollama`, `promptforge-web` |
| `docker/compose/docker-compose.win-amd.yml` | natif sur l'hôte | `promptforge-web` |
| `docker/compose/docker-compose.win-nvidia.yml` | natif sur l'hôte | `promptforge-web` |

**Conséquence pratique :** avec le fichier par défaut, il n'y a **pas** de
service `ollama`. Toute commande de la forme `docker compose exec ollama ...`
échoue avec `no such service: ollama`. Elle n'a de sens qu'avec un `-f` vers une
variante qui déclare ce service.

Les cibles `make` visent le compose par défaut, surchargeable :

```bash
make docker-start                                                   # compose.yaml
make docker-status                                                  # images + conteneurs
make docker-stop
make docker-start COMPOSE_FILE=docker/compose/docker-compose.cpu.yml
make help                                                           # toutes les cibles
```

---

## Développement

```bash
source .venv/bin/activate
pip install -e ".[all]"

make check                    # lint + format-check + tests
make test                     # suite complète
make test-fast                # sans les tests `integration` (réseau)
make test-cov                 # avec couverture HTML
pytest tests/test_core.py -v  # un fichier
```

Le Makefile appelle `python3 -m pytest`, `-m ruff`, `-m black` : il utilise le
Python du venv actif. Sans venv, `make test PYTHON=.venv/bin/python`.

Les tests d'intégration Ollama (`tests/test_ollama_integration.py`) appellent un
vrai modèle. Ils sont ignorés si Ollama ne répond pas, et allongent nettement la
suite s'il répond : mesuré ici, 8 min 37 avec Ollama disponible.

Parmi eux, `TestPerformance::test_formatting_speed` compare le temps de
réponse moyen à un budget de 60 s, réglable par `PROMPTFORGE_PERF_BUDGET` sur
une machine lente ou avec un gros modèle.

### Mesurer le reformatage

`make eval` lance le banc d'évaluation (`scripts/evaluate_prompt_quality.py`)
sur un vrai Ollama : douze demandes de métiers différents, dont trois pièges
(une demande qu'un petit modèle a tendance à exécuter, une consigne adressée au
reformateur, une demande en anglais), reformatées pour quatre profils par le
même chemin que l'interface web.

Chaque sortie passe des contrôles nommés, en oui ou non avec leur raison
(`promptforge/conformance.py`) : format attendu par le profil, pas d'annonce en
tête, pas de raisonnement `<think>` qui fuit, demande réécrite et non exécutée,
termes de la demande conservés, même langue, aucun pourcentage inventé. Le
rapport donne le taux de conformité par contrôle et par profil, **sans score
global** : aucun chiffre ne mesure « la qualité » d'un prompt.

```bash
make eval ARGS="--json avant.json"                    # avant une modification
make eval ARGS="--json apres.json"                    # après, puis comparer
make eval ARGS="--model qwen3:14b --profiles gpt_5.1"
```

`make lint` et `make format-check` sont verts. La CI GitHub Actions
(`.github/workflows/ci.yml`) les relance sur chaque PR, avec la suite de tests
sous Python 3.10, 3.11 et 3.12 (sans les tests `integration`, et sans Ollama :
ses tests sont ignorés d'eux-mêmes).

Voir [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Dépannage

Les messages d'erreur cités ci-dessous ont été reproduits sur une machine
réelle, sauf mention contraire. Ils sont recopiés tels quels.

### « Ollama : Non disponible »

`promptforge status` affiche :

```
  ✗ Ollama: Non disponible
      Lancez 'ollama serve' pour démarrer
```

Le serveur n'écoute pas sur `http://localhost:11434`. Lance `ollama serve`, ou
ouvre l'application Ollama. Vérifie avec :

```bash
curl http://localhost:11434/api/tags
```

### « Le modèle '…' n'est pas installé dans Ollama »

Ollama a répondu 404 : le modèle demandé n'existe pas sur ta machine.

```bash
ollama list              # ce que tu as vraiment
ollama pull qwen3:8b     # installer
```

Ou choisis un modèle déjà présent via `OLLAMA_MODEL` (ou `--model` en CLI).

### « Le modèle n'a pas répondu dans le délai »

Le message le dit : Ollama est joignable, c'est la **génération** qui a été trop
longue — pas le service qui est tombé. Rien n'est sauvegardé dans ce cas.

Le premier appel après le démarrage doit charger le modèle en mémoire et coûte
nettement plus cher que les suivants. Mesures sur un Mac M1 Max, prompt de
reformatage identique :

| Modèle | Appels successifs |
|--------|-------------------|
| `qwen3:14b` | 83 s · 195 s · 98 s |
| `qwen3:8b` | 30 s · 51 s · 63 s |

Trois leviers, du plus simple au plus radical :

```bash
ollama run qwen3:8b "ok"          # precharger le modele avant de s'en servir
OLLAMA_TIMEOUT=900 promptforge web  # allonger le delai
OLLAMA_MODEL=qwen3:8b promptforge web  # prendre un modele plus leger
```

Un modèle plus petit (`phi4-mini`, `qwen3:4b`) ou un contexte de projet plus
court réduisent aussi le temps de génération.

### Port 7860 déjà occupé

```
OSError: Cannot find empty port in range: 7860-7860.
```

Quelque chose écoute déjà — souvent un conteneur PromptForge resté allumé.

```bash
docker compose ps          # voir si le conteneur tourne
docker compose down        # l'arrêter
promptforge web --port 7861   # ou changer de port
```

En Docker, change la partie hôte du mapping dans `compose.yaml`
(`"127.0.0.1:7861:7860"`).

### `no such service: ollama` / `no such service: ollama-pull`

Attendu avec le fichier compose par défaut, qui ne déclare que
`promptforge-web`. Voir le tableau des variantes plus haut.

### L'onglet Scanner ne voit pas mes projets (Docker)

Le conteneur ne voit que le dossier monté sur `/hostfs`, en lecture seule. Par
défaut c'est le **dossier parent du dépôt** : si tu as cloné dans
`~/Dev/PromptForge`, le Scanner ne voit que ce qu'il y a dans `~/Dev`.

Pour l'élargir, mets `HOSTFS_PATH` dans `.env` puis recrée le conteneur :

```bash
cp .env.example .env      # puis décommente et règle HOSTFS_PATH
docker compose up --force-recreate
```

Tu peux contrôler ce qui sera monté **sans rien démarrer** :

```bash
docker compose config | grep -A1 hostfs
```

---

## Où vont mes données

Tout reste sur ta machine.

| Chemin | Contenu |
|---|---|
| `promptforge.db` | base SQLite : projets, historique |
| `history/` | un fichier Markdown par prompt reformaté |
| `data/` | même chose, en mode Docker (volume monté) |

Rien n'est envoyé nulle part, à une exception explicite : la vérification de CVE
interroge l'API publique [OSV.dev](https://osv.dev). Elle envoie des noms et des
versions de paquets, jamais ton code ni tes prompts.

| Où | État par défaut |
|---|---|
| Onglet `🔍 Scanner` de l'interface | **activée** — case « 🔒 Vérifier les CVE », décochable |
| `promptforge format --check-cves` | désactivée, il faut l'option |
| `promptforge scan` | pas de vérification CVE |

---

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — mettre en place l'environnement, ouvrir une PR
- [docs/SOURCES_METHODOLOGY.md](docs/SOURCES_METHODOLOGY.md) — sources des benchmarks et des tarifs
- [docs/DOCKER_GUIDE.md](docs/DOCKER_GUIDE.md) — les sept fichiers compose,
  Ollama natif ou conteneurisé, données et dépannage

---

## Licence

MIT — voir [LICENSE](LICENSE).
