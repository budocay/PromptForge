#!/usr/bin/env python3
"""
Script helper cross-platform pour Docker.
Fonctionne sur Windows, Linux et macOS.

Resolution du fichier compose
-----------------------------
Toutes les commandes passent `-f <fichier>` EXPLICITEMENT. Le defaut est
`compose.yaml` a la racine, soit le chemin par defaut de DEC-010 : seule
l'interface tourne en conteneur, Ollama reste natif sur l'hote.

Consequence directe, et c'est la regression que ce fichier corrige : ce
compose n'expose qu'un service, `promptforge-web`. Nommer `ollama` ou
`promptforge` dans une commande resolue contre lui echoue avec
`no such service`. Aucune commande ne nomme donc plus que `promptforge-web`,
le seul service present dans les sept fichiers compose du depot.

Pour viser une variante avec Ollama conteneurise (Linux + GPU expose a
Docker) :

    python scripts/docker_helper.py -f docker/compose/docker-compose.yml start
    PROMPTFORGE_COMPOSE=docker/compose/docker-compose.cpu.yml make docker-start
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Couleurs (désactivées sur Windows si pas de support)
try:
    if os.name == "nt":
        os.system("color")  # Active les couleurs ANSI sur Windows 10+
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    NC = "\033[0m"
except Exception:
    GREEN = RED = YELLOW = BLUE = NC = ""


# ============================================================
# Constantes de resolution
# ============================================================

# Chemin par defaut de DEC-010, identique sur les trois systemes.
DEFAULT_COMPOSE_FILE = "compose.yaml"

# Seul service present dans les sept fichiers compose du depot.
WEB_SERVICE = "promptforge-web"

# Present uniquement dans les variantes a Ollama conteneurise
# (nvidia, cpu, amd, amd-max).
OLLAMA_SERVICE = "ollama"

# Modele par defaut. Aligne sur `OLLAMA_MODEL` de `compose.yaml`,
# `docker-compose.yml` et `docker-compose.win-nvidia.yml`. Ce script tirait
# `llama3.1`, qui n'existe nulle part ailleurs dans le depot (D-022).
DEFAULT_MODEL = "qwen3:8b"


def log_info(msg):
    print(f"{GREEN}[INFO]{NC} {msg}")


def log_warn(msg):
    print(f"{YELLOW}[WARN]{NC} {msg}")


def log_error(msg):
    print(f"{RED}[ERROR]{NC} {msg}")


def project_root():
    """Racine du depot, pour que les chemins compose soient stables."""
    return Path(__file__).resolve().parent.parent


def resolve_compose_file(args):
    """Fichier compose vise, par ordre de priorite : -f, env, defaut."""
    return (
        getattr(args, "file", None) or os.environ.get("PROMPTFORGE_COMPOSE") or DEFAULT_COMPOSE_FILE
    )


def get_docker_compose_cmd():
    """Retourne la commande docker compose appropriée."""
    # Essayer docker compose (v2)
    result = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    if result.returncode == 0:
        return ["docker", "compose"]

    # Essayer docker-compose (v1)
    if shutil.which("docker-compose"):
        return ["docker-compose"]

    log_error("Docker Compose n'est pas installé")
    sys.exit(1)


def docker_compose(compose_file, *args, **kwargs):
    """Exécute une commande docker compose sur un fichier explicite."""
    cmd = get_docker_compose_cmd() + ["-f", compose_file] + list(args)
    return subprocess.run(cmd, **kwargs)


def compose_services(compose_file):
    """Services reellement declares par le fichier compose vise.

    On interroge Docker plutot que de parser le YAML : c'est la meme
    resolution que celle qui s'appliquera a la commande suivante, extends et
    surcharges compris.
    """
    result = docker_compose(compose_file, "config", "--services", capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def require_service(compose_file, service):
    """Refuse d'invoquer un service absent du compose vise.

    Contrepartie a l'execution du test de couture de `tests/test_launcher.py`.
    Sans elle, l'erreur remontee a l'utilisateur est un `no such service`
    sec, sans indication de la variante a utiliser.
    """
    services = compose_services(compose_file)
    if service in services:
        return True
    log_error(f"Le service '{service}' n'existe pas dans {compose_file}")
    log_info(f"Services disponibles : {', '.join(services) or '(aucun)'}")
    if service == OLLAMA_SERVICE:
        log_info(
            "Ce compose n'embarque pas Ollama : il est attendu natif sur l'hote "
            "(DEC-010). Pour une variante avec Ollama conteneurise :"
        )
        log_info("  -f docker/compose/docker-compose.yml       # NVIDIA")
        log_info("  -f docker/compose/docker-compose.cpu.yml   # sans GPU")
        log_info("  -f docker/compose/docker-compose.amd.yml   # AMD ROCm")
    return False


def check_docker():
    """Vérifie que Docker est installé et fonctionne."""
    if not shutil.which("docker"):
        log_error("Docker n'est pas installé")
        log_info("Téléchargez Docker sur https://www.docker.com/products/docker-desktop")
        sys.exit(1)

    result = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if result.returncode != 0:
        log_error("Docker n'est pas démarré")
        log_info("Lancez Docker Desktop ou le service Docker")
        sys.exit(1)


def wanted_model():
    """Modele attendu, surchargeable par l'environnement comme dans compose."""
    return os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)


def ensure_model_containerized(compose_file, model):
    """Telecharge le modele dans le conteneur Ollama de la variante visee.

    On passe par `docker compose exec <service>` et non par
    `docker exec <nom_de_conteneur>` : le nom du conteneur change d'une
    variante a l'autre (promptforge-ollama, -amd, -amd-max).
    """
    result = docker_compose(
        compose_file,
        "exec",
        "-T",
        OLLAMA_SERVICE,
        "ollama",
        "list",
        capture_output=True,
        text=True,
    )
    if model in (result.stdout or ""):
        log_info(f"Modèle {model} déjà disponible")
        return
    log_info(f"Téléchargement du modèle {model} (peut prendre plusieurs minutes)...")
    docker_compose(compose_file, "exec", "-T", OLLAMA_SERVICE, "ollama", "pull", model)


def ensure_model_native(model):
    """Verifie le modele sur l'Ollama natif de l'hote (chemin par defaut)."""
    if not shutil.which("ollama"):
        log_warn("Ollama n'est pas installé sur l'hôte.")
        log_info("Ce compose attend un Ollama natif : https://ollama.com/download")
        log_info(f"Puis : ollama pull {model}")
        return
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if model in (result.stdout or ""):
        log_info(f"Modèle {model} déjà disponible")
        return
    log_info(f"Téléchargement du modèle {model} (peut prendre plusieurs minutes)...")
    subprocess.run(["ollama", "pull", model])


def cmd_start(args):
    """Démarre les services du compose visé, puis s'assure du modèle."""
    compose_file = resolve_compose_file(args)
    services = compose_services(compose_file)

    log_info(f"Démarrage des services ({compose_file})...")
    docker_compose(compose_file, "up", "-d")

    model = wanted_model()
    if OLLAMA_SERVICE in services:
        log_info("Attente du démarrage d'Ollama...")
        time.sleep(5)
        ensure_model_containerized(compose_file, model)
    else:
        log_info("Ollama est attendu natif sur l'hôte (DEC-010).")
        ensure_model_native(model)

    log_info("Services prêts !")


def cmd_stop(args):
    """Arrête les services."""
    compose_file = resolve_compose_file(args)
    log_info(f"Arrêt des services ({compose_file})...")
    docker_compose(compose_file, "down")


def cmd_status(args):
    """Affiche le statut."""
    compose_file = resolve_compose_file(args)
    log_info(f"Statut des conteneurs ({compose_file}):")
    docker_compose(compose_file, "ps")

    print()
    log_info("Test de connexion Ollama:")

    try:
        import json
        import urllib.request

        base = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not base.startswith("http"):
            base = f"http://{base}"
        req = urllib.request.Request(f"{base}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                print(f"{GREEN}✓ Ollama accessible{NC}")
                data = json.loads(response.read().decode())
                models = [m["name"] for m in data.get("models", [])]
                if models:
                    print("Modèles disponibles:")
                    for m in models[:5]:
                        print(f"  - {m}")
                else:
                    print("  (aucun modèle)")
    except Exception:
        print(f"{RED}✗ Ollama non accessible{NC}")


def cmd_run(args):
    """Exécute une commande promptforge dans l'image de l'interface.

    L'ancien code visait le service `promptforge`, qui n'existe que dans deux
    des sept compose. L'image `promptforge-web` embarque le meme point
    d'entree console : on la reutilise, avec `--no-deps` pour ne pas demarrer
    Ollama au passage.
    """
    compose_file = resolve_compose_file(args)
    if not require_service(compose_file, WEB_SERVICE):
        return 1
    result = docker_compose(
        compose_file,
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "promptforge",
        WEB_SERVICE,
        "--path",
        "/data",
        *args.cmd,
    )
    return result.returncode


def cmd_web(args):
    """Lance l'interface web."""
    compose_file = resolve_compose_file(args)
    if not require_service(compose_file, WEB_SERVICE):
        return 1
    log_info("Lancement de l'interface web...")
    # `depends_on` demarre Ollama dans les variantes qui l'embarquent.
    docker_compose(compose_file, "up", "-d", WEB_SERVICE)
    log_info(f"Interface disponible sur {BLUE}http://localhost:7860{NC}")
    return 0


def cmd_logs(args):
    """Affiche les logs.

    Defaut : `promptforge-web`. L'ancien defaut etait `ollama`, absent du
    compose par defaut.
    """
    compose_file = resolve_compose_file(args)
    service = args.service or WEB_SERVICE
    if not require_service(compose_file, service):
        return 1
    docker_compose(compose_file, "logs", "-f", service)
    return 0


def cmd_shell(args):
    """Lance un shell interactif dans l'image de l'interface."""
    compose_file = resolve_compose_file(args)
    if not require_service(compose_file, WEB_SERVICE):
        return 1
    log_info("Mode interactif - tapez 'exit' pour quitter")
    docker_compose(
        compose_file, "run", "--rm", "--no-deps", "--entrypoint", "/bin/bash", WEB_SERVICE
    )
    return 0


def cmd_build(args):
    """Construit les images."""
    compose_file = resolve_compose_file(args)
    log_info(f"Construction des images ({compose_file})...")
    docker_compose(compose_file, "build")


def cmd_clean(args):
    """Nettoie tout."""
    compose_file = resolve_compose_file(args)
    log_warn("Ceci va supprimer tous les conteneurs et volumes PromptForge")
    confirm = input("Continuer ? [y/N] ")
    if confirm.lower() == "y":
        docker_compose(compose_file, "down", "-v")
        log_info("Nettoyage terminé")
    else:
        print("Annulé.")


def main():
    parser = argparse.ArgumentParser(
        description="PromptForge Docker Helper (Cross-platform)",
        epilog=(
            f"Fichier compose par defaut : {DEFAULT_COMPOSE_FILE} "
            "(surchargeable par -f ou PROMPTFORGE_COMPOSE)."
        ),
    )
    parser.add_argument(
        "-f",
        "--file",
        default=None,
        help=f"Fichier docker compose a utiliser (defaut: {DEFAULT_COMPOSE_FILE})",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commandes")

    subparsers.add_parser("start", help="Démarrer les services et vérifier le modèle")
    subparsers.add_parser("stop", help="Arrêter tous les services")
    subparsers.add_parser("status", help="Afficher le statut")

    run_parser = subparsers.add_parser("run", help="Exécuter une commande promptforge")
    run_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Commande à exécuter")

    subparsers.add_parser("web", help="Lancer l'interface web")

    logs_parser = subparsers.add_parser("logs", help="Afficher les logs")
    logs_parser.add_argument("service", nargs="?", help=f"Service (défaut: {WEB_SERVICE})")

    subparsers.add_parser("shell", help="Shell interactif")
    subparsers.add_parser("build", help="Construire les images")
    subparsers.add_parser("clean", help="Supprimer conteneurs et volumes")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    check_docker()
    os.chdir(project_root())

    commands = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "run": cmd_run,
        "web": cmd_web,
        "logs": cmd_logs,
        "shell": cmd_shell,
        "build": cmd_build,
        "clean": cmd_clean,
    }

    return commands[args.command](args) or 0


if __name__ == "__main__":
    sys.exit(main())
