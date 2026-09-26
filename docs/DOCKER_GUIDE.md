# Guide Docker

Ce guide détaille les sept fichiers compose du dépôt. Pour démarrer vite, le
[README](../README.md#2a-avec-docker--le-chemin-le-plus-court) suffit :
`docker compose up` à la racine.

Toutes les commandes se lancent **depuis la racine du dépôt**.

---

## Deux architectures

| | Ollama | Fichiers | Pour qui |
|---|---|---|---|
| **Ollama natif** (défaut) | sur l'hôte, hors conteneur | `compose.yaml`, `win-nvidia`, `win-amd` | macOS, Windows, et tout Linux où Ollama est déjà installé |
| **Ollama conteneurisé** | dans un conteneur `ollama` | `docker-compose.yml` (NVIDIA), `cpu`, `amd`, `amd-max` | Linux avec un GPU exposé à Docker, ou sans GPU |

Pourquoi le natif par défaut : Ollama est le seul composant qui a besoin du GPU.
Docker Desktop ne donne pas accès à Metal sur macOS, et l'accès GPU sous
Windows dépend du pilote. Un Ollama conteneurisé y perdrait l'accélération.

---

## Ollama natif (`compose.yaml`)

```bash
ollama serve             # sur l'hôte (l'app macOS/Windows le fait seule)
ollama pull qwen3:8b
docker compose up        # interface sur http://localhost:7860
```

Le conteneur `promptforge-web` rejoint l'Ollama de l'hôte via
`host.docker.internal:11434`. Il n'y a **pas** de service `ollama` dans ce
fichier : `docker compose exec ollama …` y échoue avec `no such service`.

Les variantes Windows font la même chose, avec un modèle par défaut différent :

```bash
docker compose -f docker/compose/docker-compose.win-nvidia.yml up -d   # qwen3:8b
docker compose -f docker/compose/docker-compose.win-amd.yml up -d      # qwen3:14b
```

---

## Ollama conteneurisé (Linux)

| Fichier | GPU | Modèle | Téléchargement du modèle |
|---|---|---|---|
| `docker/compose/docker-compose.yml` | NVIDIA | `qwen3:8b` | automatique (service `ollama-pull`) |
| `docker/compose/docker-compose.cpu.yml` | aucun | `phi4-mini` | automatique (service `ollama-pull`) |
| `docker/compose/docker-compose.amd.yml` | AMD ROCm | `qwen3:14b` | manuel, voir plus bas |
| `docker/compose/docker-compose.amd-max.yml` | AMD ROCm | `qwen3:32b` | manuel, voir plus bas |

```bash
# NVIDIA : nécessite le NVIDIA Container Toolkit
docker compose -f docker/compose/docker-compose.yml up -d
docker compose -f docker/compose/docker-compose.yml logs -f ollama-pull

# Sans GPU
docker compose -f docker/compose/docker-compose.cpu.yml up -d
```

Pour AMD, le modèle n'est pas téléchargé tout seul :

```bash
docker compose -f docker/compose/docker-compose.amd.yml up -d
docker compose -f docker/compose/docker-compose.amd.yml exec ollama ollama pull qwen3:14b
```

Le fichier AMD fixe `HSA_OVERRIDE_GFX_VERSION=11.0.0`, valeur des RX 7900
(gfx1100). Pour une autre carte, ajuste-la dans le fichier.

Vérifier que le GPU NVIDIA est vu par Docker :

```bash
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

---

## Configuration

`compose.yaml` et toutes les variantes lisent ces variables depuis
l'environnement ou un fichier `.env` (modèle : `.env.example`) :

| Variable | Défaut | Effet |
|---|---|---|
| `OLLAMA_MODEL` | `qwen3:8b` | modèle utilisé (`compose.yaml` seulement ; les variantes le fixent en dur) |
| `OLLAMA_TIMEOUT` | `600` | secondes accordées à une génération |
| `HOSTFS_PATH` | dossier parent du dépôt | dossier de l'hôte visible par le Scanner, en lecture seule sur `/hostfs` |

```bash
cp .env.example .env     # puis décommente ce dont tu as besoin
docker compose up --force-recreate
```

Contrôler ce que Compose va réellement appliquer, sans rien démarrer :

```bash
docker compose config | grep -A6 environment
```

---

## Données

| Hôte | Conteneur | Contenu |
|---|---|---|
| `./data` | `/data` | base SQLite, projets et historique : **à sauvegarder** |
| `./projects` | `/app/example-projects` (lecture seule) | projets d'exemple |
| `HOSTFS_PATH` | `/hostfs` (lecture seule) | dossiers analysables par le Scanner |

Les modèles des variantes conteneurisées vivent dans un volume Docker
(`promptforge-ollama-data` pour NVIDIA et CPU) : `docker compose down` les
conserve, `docker compose down -v` les supprime.

---

## Commandes utiles

```bash
docker compose ps                       # état
docker compose logs -f promptforge-web  # journaux de l'interface
docker compose down                     # arrêt
docker compose build --no-cache         # reconstruire après une mise à jour
```

Le `Makefile` enveloppe ces commandes et accepte une variante :

```bash
make docker-start
make docker-start COMPOSE_FILE=docker/compose/docker-compose.cpu.yml
make help
```

---

## Dépannage

- **L'interface affiche Ollama indisponible** (mode natif) : `curl
  http://localhost:11434/api/tags` sur l'hôte doit répondre. Sinon, lance
  `ollama serve`.
- **« Le modèle '…' n'est pas installé »** : `ollama pull <modèle>` sur l'hôte,
  ou via `docker compose -f <variante> exec ollama ollama pull <modèle>` pour
  une variante conteneurisée.
- **Port 7860 occupé** : un autre conteneur PromptForge tourne sans doute.
  `docker compose ps`, puis `docker compose down`.
- **Le Scanner ne voit pas un projet** : il ne voit que `HOSTFS_PATH`. Voir
  Configuration.

Le [README](../README.md#dépannage) détaille aussi les délais de génération et
les erreurs courantes.
