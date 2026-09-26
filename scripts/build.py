#!/usr/bin/env python3
"""
PromptForge Build System
========================
Script central pour construire les images Docker et gérer les dépendances.

Usage:
    python scripts/build.py [command] [options]

Commands:
    build       Construire les images Docker
    rebuild     Reconstruire les images (avec cache)
    clean       Nettoyer les images et conteneurs
    status      Afficher l'état des images
    deps        Installer les dépendances Python
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# `detect_gpu()` vivait ici en 45 lignes, sans branche Darwin : sur macOS elle
# retombait silencieusement sur `cpu` (D-018), donc sur un Ollama conteneurise
# sans acces Metal. Elle est supprimee au profit de `promptforge/hardware.py`,
# qui mesure. Le chargement passe par `scripts/core_loader.py`, qui documente
# pourquoi il se fait par chemin plutot que par `import promptforge`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core_loader import compose_selection, load_core  # noqa: E402

CORE = load_core()

# Configurations Docker Compose disponibles
#
# `default` est le chemin par defaut de DEC-010 : seule l'interface tourne en
# conteneur, Ollama reste natif sur l'hote. Identique sur Windows, macOS et
# Linux. C'est la valeur retenue quand `-c` n'est pas passe : le defaut du
# produit est desormais celui que le produit selectionne reellement.
#
# Les autres entrees embarquent Ollama en conteneur et ne se justifient que
# sur une machine dont le GPU est expose a Docker. Elles restent accessibles
# explicitement, ou par `-c auto` qui rejoue la detection GPU.
COMPOSE_FILES = {
    "default": "compose.yaml",
    "nvidia": "docker/compose/docker-compose.yml",
    "linux-amd": "docker/compose/docker-compose.amd.yml",
    "linux-amd-max": "docker/compose/docker-compose.amd-max.yml",
    "cpu": "docker/compose/docker-compose.cpu.yml",
    "win-amd": "docker/compose/docker-compose.win-amd.yml",
    "win-nvidia-native": "docker/compose/docker-compose.win-nvidia.yml",
}

# Configuration retenue en l'absence de `-c`.
DEFAULT_CONFIG = "default"

# Valeur speciale de `-c` : rejoue la detection materielle.
AUTO_CONFIG = "auto"

# Choix acceptes par `-c`.
CONFIG_CHOICES = [AUTO_CONFIG] + list(COMPOSE_FILES.keys())


# Couleurs pour le terminal
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_status(msg, status="info"):
    """Affiche un message avec couleur."""
    colors = {
        "info": Colors.BLUE,
        "success": Colors.GREEN,
        "warning": Colors.YELLOW,
        "error": Colors.RED,
    }
    color = colors.get(status, Colors.RESET)
    print(f"{color}{msg}{Colors.RESET}")


def run_cmd(cmd, capture=False):
    """Exécute une commande shell."""
    print_status(f"  → {' '.join(cmd)}", "info")
    result = subprocess.run(
        cmd, capture_output=capture, text=True, encoding="utf-8", errors="replace"
    )
    return result


def get_project_root():
    """Retourne le chemin racine du projet."""
    return Path(__file__).parent.parent


def detect_config():
    """Rend la cle de compose deduite du materiel reellement mesure.

    Ne devine plus un fabricant : `detect_hardware()` mesure, et dit ce qu'elle
    n'a pas pu mesurer. Quand rien n'est mesurable, ou quand aucune variante
    GPU n'a de sens (macOS, D-020), on rend `default` — le chemin de DEC-010,
    jamais `cpu` par depit.

    La regle de correspondance est celle de `core_loader.compose_selection()`,
    partagee avec `launcher.py` : deux tables separees redivergeraient.
    """
    if not CORE.available:
        print_status(
            f"Mesure materielle indisponible ({CORE.error}) : configuration "
            f"'{DEFAULT_CONFIG}' retenue",
            "warning",
        )
        return DEFAULT_CONFIG

    profile = CORE.detect_hardware()
    selection = compose_selection(profile.system, profile.gpu_vendor)
    variante = selection["gpu_variant"]

    memoire = profile.available_memory_bytes
    lisible = f"{memoire / (1024 ** 3):.1f} Gio" if memoire else "non mesuree"
    print_status(
        f"Materiel mesure : {profile.system} / GPU "
        f"{profile.gpu_vendor or 'non mesure'} / memoire {lisible}",
        "info",
    )
    for note in profile.notes:
        print_status(f"  non mesure : {note}", "warning")

    return variante or selection["default"]


def get_compose_file(config=None):
    """Retourne le fichier docker-compose approprié.

    Sans `-c`, on ne devine plus : on prend le chemin par defaut de DEC-010,
    identique sur les trois systemes. L'ancienne `detect_gpu()` n'avait aucune
    branche Darwin (D-018) et retombait silencieusement sur `cpu` sur macOS,
    c'est-a-dire sur
    un Ollama conteneurise sans acces Metal — exactement ce que DEC-010
    remplace. La detection reste disponible, mais seulement si on la demande.
    """
    if config is None:
        config = DEFAULT_CONFIG
    elif config == AUTO_CONFIG:
        config = detect_config()
        print_status(f"Detection materielle : configuration '{config}'", "info")

    if config not in COMPOSE_FILES:
        print_status(
            f"Configuration '{config}' inconnue, utilisation de '{DEFAULT_CONFIG}'", "warning"
        )
        config = DEFAULT_CONFIG

    return COMPOSE_FILES[config]


def compose_services(compose_file):
    """Services declares par le fichier compose vise.

    Interroge Docker plutot que de parser le YAML : meme resolution que celle
    qui s'appliquera aux commandes suivantes.
    """
    result = subprocess.run(
        ["docker", "compose", "-f", compose_file, "config", "--services"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def cmd_status(args):
    """Affiche l'état des images Docker."""
    print_status("\n📦 État des images Docker PromptForge\n", "info")

    result = run_cmd(
        [
            "docker",
            "images",
            "--filter",
            "reference=*promptforge*",
            "--format",
            "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}",
        ]
    )

    if result.returncode != 0:
        print_status("Erreur lors de la vérification des images", "error")
        return 1

    print()

    # Vérifier les conteneurs
    print_status("\n🐳 Conteneurs actifs\n", "info")
    run_cmd(
        [
            "docker",
            "ps",
            "--filter",
            "name=promptforge",
            "--format",
            "table {{.Names}}\t{{.Status}}\t{{.Ports}}",
        ]
    )

    return 0


def cmd_build(args):
    """Construit les images Docker."""
    os.chdir(get_project_root())
    compose_file = get_compose_file(args.config)

    print_status(f"\n🔨 Construction des images ({compose_file})\n", "info")

    cmd = ["docker", "compose", "-f", compose_file, "build"]
    if args.no_cache:
        cmd.append("--no-cache")
    if args.parallel:
        cmd.extend(["--parallel", str(args.parallel)])

    result = run_cmd(cmd)

    if result.returncode == 0:
        print_status("\n✅ Images construites avec succès!", "success")
    else:
        print_status("\n❌ Erreur lors de la construction", "error")

    return result.returncode


def cmd_clean(args):
    """Nettoie les images et conteneurs."""
    os.chdir(get_project_root())

    print_status("\n🗑️ Nettoyage Docker\n", "warning")

    if not args.force:
        confirm = input("Confirmer le nettoyage? (y/N): ")
        if confirm.lower() != "y":
            print_status("Annulé", "info")
            return 0

    # Arrêter tous les conteneurs
    print_status("\nArrêt des conteneurs...", "info")
    for config, file in COMPOSE_FILES.items():
        if os.path.exists(file):
            run_cmd(["docker", "compose", "-f", file, "down", "-v"])

    # Supprimer les images
    if args.images:
        print_status("\nSuppression des images...", "info")
        for config, file in COMPOSE_FILES.items():
            if os.path.exists(file):
                run_cmd(["docker", "compose", "-f", file, "down", "--rmi", "local"])

    # Nettoyer les ressources orphelines
    print_status("\nNettoyage des ressources orphelines...", "info")
    run_cmd(["docker", "image", "prune", "-f"])
    run_cmd(["docker", "volume", "prune", "-f"])

    print_status("\n✅ Nettoyage terminé!", "success")
    return 0


def cmd_deps(args):
    """Installe les dépendances Python."""
    os.chdir(get_project_root())

    print_status("\n📦 Installation des dépendances\n", "info")

    # Installer avec pip
    cmd = [sys.executable, "-m", "pip", "install", "-e", "."]
    if args.dev:
        cmd.append("[dev]")

    result = run_cmd(cmd)

    if result.returncode == 0:
        print_status("\n✅ Dépendances installées!", "success")
    else:
        print_status("\n❌ Erreur lors de l'installation", "error")

    return result.returncode


def cmd_up(args):
    """Démarre les services."""
    os.chdir(get_project_root())
    compose_file = get_compose_file(args.config)

    print_status(f"\n▶️ Démarrage des services ({compose_file})\n", "info")

    cmd = ["docker", "compose", "-f", compose_file, "up", "-d"]
    if args.build:
        cmd.append("--build")

    result = run_cmd(cmd)

    if result.returncode == 0:
        print_status("\n✅ Services démarrés!", "success")
        print_status("   → PromptForge: http://localhost:7860", "info")
        if "ollama" in compose_services(compose_file):
            print_status("   → Ollama (conteneur): http://localhost:11434", "info")
        else:
            print_status("   → Ollama: natif sur l'hote (DEC-010)", "info")

    return result.returncode


def cmd_down(args):
    """Arrête les services."""
    os.chdir(get_project_root())
    compose_file = get_compose_file(args.config)

    print_status(f"\n⏹️ Arrêt des services ({compose_file})\n", "info")

    result = run_cmd(["docker", "compose", "-f", compose_file, "down"])

    if result.returncode == 0:
        print_status("\n✅ Services arrêtés!", "success")

    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="PromptForge Build System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/build.py status              # Voir l'état des images
  python scripts/build.py build               # Construire (compose.yaml, defaut DEC-010)
  python scripts/build.py build -c auto       # Construire avec detection GPU
  python scripts/build.py build -c nvidia     # Construire pour NVIDIA
  python scripts/build.py build --no-cache    # Reconstruire sans cache
  python scripts/build.py up                  # Démarrer les services
  python scripts/build.py down                # Arrêter les services
  python scripts/build.py clean               # Nettoyer
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commande à exécuter")

    # status
    p_status = subparsers.add_parser("status", help="Afficher l'état des images")
    p_status.set_defaults(func=cmd_status)

    # build
    p_build = subparsers.add_parser("build", help="Construire les images")
    p_build.add_argument(
        "-c",
        "--config",
        choices=CONFIG_CHOICES,
        help=f"Configuration (defaut: {DEFAULT_CONFIG}, " f"'{AUTO_CONFIG}' pour la detection GPU)",
    )
    p_build.add_argument(
        "--no-cache", action="store_true", help="Reconstruire sans utiliser le cache"
    )
    p_build.add_argument("--parallel", type=int, default=None, help="Nombre de builds en parallèle")
    p_build.set_defaults(func=cmd_build)

    # clean
    p_clean = subparsers.add_parser("clean", help="Nettoyer les images et conteneurs")
    p_clean.add_argument(
        "-f", "--force", action="store_true", help="Ne pas demander de confirmation"
    )
    p_clean.add_argument("--images", action="store_true", help="Supprimer aussi les images")
    p_clean.set_defaults(func=cmd_clean)

    # deps
    p_deps = subparsers.add_parser("deps", help="Installer les dépendances")
    p_deps.add_argument(
        "--dev", action="store_true", help="Inclure les dépendances de développement"
    )
    p_deps.set_defaults(func=cmd_deps)

    # up
    p_up = subparsers.add_parser("up", help="Démarrer les services")
    p_up.add_argument(
        "-c",
        "--config",
        choices=CONFIG_CHOICES,
        help=f"Configuration (defaut: {DEFAULT_CONFIG}, " f"'{AUTO_CONFIG}' pour la detection GPU)",
    )
    p_up.add_argument("--build", action="store_true", help="Reconstruire avant de démarrer")
    p_up.set_defaults(func=cmd_up)

    # down
    p_down = subparsers.add_parser("down", help="Arrêter les services")
    p_down.add_argument(
        "-c",
        "--config",
        choices=CONFIG_CHOICES,
        help=f"Configuration (defaut: {DEFAULT_CONFIG}, " f"'{AUTO_CONFIG}' pour la detection GPU)",
    )
    p_down.set_defaults(func=cmd_down)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
