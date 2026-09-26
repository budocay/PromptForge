"""
PromptForge Launcher - Interface de contrôle
Lance avec: python launcher.py
"""

import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Port du launcher
LAUNCHER_PORT = 7850
PROMPTFORGE_PORT = 7860
OLLAMA_PORT = 11434

# ---------------------------------------------------------------------------
# Le launcher ne connait ni les modeles, ni le materiel : il les demande
# ---------------------------------------------------------------------------
# Il portait trente et un litteraux de tag Ollama (D-059) et sa propre
# `detect_gpu()` (D-018), qui annoncait des seuils de VRAM que rien ne mesurait
# (D-019). Les deux sources uniques sont desormais dans le coeur :
# `promptforge/models_catalog.py` (DEC-003) et `promptforge/hardware.py`
# (DEC-001). Elles sont chargees par `scripts/core_loader.py`, qui documente
# pourquoi le chargement se fait par chemin plutot que par `import promptforge`
# (D-061 : ce fichier tourne sous le Python systeme, 3.9.6 ici).
#
# Rien n'est recopie ici. Si le pont est indisponible, l'interface le dit :
# aucune liste en dur ne prend le relais, sinon D-022 renaitrait a l'endroit
# meme ou on la ferme.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from core_loader import compose_selection, load_core  # noqa: E402

CORE = load_core()

# ---------------------------------------------------------------------------
# Trois etats de service, jamais deux
# ---------------------------------------------------------------------------
# `check_ollama()` ecrivait `False` sur toute exception, delai depasse compris :
# « je ne sais pas » devenait « c'est eteint », et l'utilisateur concluait que
# le produit ne marchait pas. Meme confusion que D-018, ou « non mesurable »
# devenait « pas de GPU ».
#
#   STATUS_UP      : sonde reussie, le service repond comme attendu.
#   STATUS_DOWN    : sonde concluante et negative (connexion refusee, binaire
#                    absent, code de retour non nul). C'est une connaissance.
#   STATUS_UNKNOWN : la sonde n'a pas conclu (delai depasse, reponse illisible,
#                    erreur inattendue). Ce n'est PAS un service eteint.
STATUS_UP = "up"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Cadence de rafraichissement de l'etat
# ---------------------------------------------------------------------------
# Le client interroge deja `/api/status` toutes les 3 s, mais le serveur rendait
# le meme dictionnaire fige depuis son demarrage : une instance lancee a 11h14
# affichait encore a 15h l'etat mesure a 11h14. Le rafraichissement est donc
# fait cote serveur, declenche par `/api/status`, avec deux cadences distinctes
# justifiees par le cout mesure de chaque sonde sur la machine de reference :
#
#   ollama /api/tags     4.4 ms   | sondes HTTP sur la boucle locale
#   promptforge /        0.5 ms   |
#   docker info        107.6 ms   | sous-processus vers le demon
#   docker images       88.0 ms   |
#
# (mesure du 2026-09-04, moyenne de 5 appels pour le HTTP, 3 pour Docker)
#
# Les sondes HTTP coutent trois ordres de grandeur de moins que les sondes
# Docker : les separer evite de payer 200 ms de sous-processus toutes les
# deux secondes pour observer un demon qui, lui, ne demarre ni ne s'arrete
# plusieurs fois par minute.
FAST_PROBE_TTL = 2.0  # Ollama + PromptForge : cadence utile au client (3 s)
SLOW_PROBE_TTL = 15.0  # Docker : evenement rare et lent, 15 s suffisent
STALE_AFTER = 10.0  # Au-dela, l'interface declare son etat perime

# Delai des sondes HTTP. Court, parce que la boucle locale ne justifie pas
# davantage : soit rien n'ecoute et l'echec est immediat, soit le service
# repond en quelques millisecondes. Un delai long ne ferait que bloquer plus
# longtemps sur le seul cas ambigu, qui est desormais rendu STATUS_UNKNOWN.
HTTP_PROBE_TIMEOUT = 2.0

# État global
state = {
    "os": platform.system(),
    "gpu": None,
    "gpu_type": None,  # "amd", "nvidia", "cpu"
    "gfx_version": None,
    "docker_installed": True,  # Par défaut True, vérifié après
    "docker_running": False,
    "docker_status": STATUS_UNKNOWN,  # up | down | unknown
    "ollama_installed": True,  # Par défaut True, vérifié après
    "ollama_running": False,
    "ollama_status": STATUS_UNKNOWN,  # up | down | unknown
    "promptforge_running": False,
    "promptforge_status": STATUS_UNKNOWN,  # up | down | unknown
    # Aucun modele par defaut : tant que la memoire n'est pas mesuree, il n'y
    # a rien a recommander. Ecrire un tag ici serait presenter un defaut cable
    # comme une recommandation, ce que D-019 reprochait a l'ancien code.
    "ollama_model": None,
    "installed_models": [],  # Liste des modèles Ollama installés
    "model_installed": False,  # True si le modèle recommandé est installé
    # Mesure materielle (DEC-001) et recommandation (DEC-003/DEC-006).
    "hardware": None,  # Instantane serialisable de HardwareProfile
    "recommendation": None,  # Instantane serialisable de Recommendation
    # Tags tenant dans la memoire mesuree, catalogue COMPLET : sert a marquer
    # ce que la machine encaisse, licence comprise. `None` = rien de mesure,
    # ce qui ne veut dire ni « tient » ni « ne tient pas ».
    "fitting_tags": None,
    "catalog_available": CORE.available,
    "catalog_error": CORE.error,
    "docker_compose_file": None,  # Fichier docker-compose sélectionné
    "available_compose_files": [],  # Fichiers disponibles
    "docker_images": {},  # État des images Docker {name: {exists, created, size}}
    "rebuild_needed": False,  # True si les images doivent être reconstruites
    "last_build_time": None,  # Timestamp du dernier build
    "checked_at": None,  # Epoch de la derniere sonde rapide (None = jamais)
    "checked_at_label": None,  # Meme instant, en HH:MM:SS, pour l'interface
    "docker_checked_at": None,  # Epoch de la derniere sonde Docker
    "probe_in_progress": False,  # Une sonde est en vol (evite l'empilement)
    "logs": [],
    "action_in_progress": False,
}

# ---------------------------------------------------------------------------
# Presentation du catalogue, jamais une copie du catalogue
# ---------------------------------------------------------------------------
# `RECOMMENDED_MODELS` mappait un fabricant vers un tag et annoncait des seuils
# (« NVIDIA 8GB+ VRAM ») que rien ne mesurait : une carte de 2 Go se voyait
# proposer un modele de 5 Go (D-019). Il est supprime. La recommandation vient
# desormais de `recommend()` du catalogue, alimentee par la memoire reellement
# mesuree par `detect_hardware()`.
#
# Les fonctions ci-dessous ne font que **mettre en forme** ce que le coeur
# rend. Aucun tag, aucune taille, aucun seuil n'est ecrit dans ce fichier.


#: Ce que le classement ne dit pas, ecrit noir sur blanc dans l'interface.
#:
#: DEC-006 : les modeles sont ordonnes sur leur empreinte memoire, un fait
#: source. Les notes de qualite maison de `OLLAMA_MODELS_INFO` ont ete
#: supprimees (D-021) parce qu'aucune source ne les etayait. Taire cette
#: limite laisserait croire que le premier de la liste est « le meilleur ».
QUALITY_DISCLAIMER = (
    "Classement par empreinte memoire, pas par qualite. La qualite de "
    "reformatage de ces modeles n'est pas mesuree a ce jour : le premier de "
    "la liste est le plus lourd que la machine encaisse, pas le meilleur."
)


def _bytes_to_gb(num_bytes):
    """Octets en Go binaires, dans l'unite qu'affichent les fiches sources."""
    if num_bytes is None:
        return None
    return round(num_bytes / (1024**3), 1)


def model_entry(model):
    """Instantane serialisable d'une entree de catalogue, pour l'interface.

    `estimated` est expose parce qu'il change la force de ce qui est affiche :
    recommander sur un chiffre publie par l'editeur n'a pas la meme valeur que
    recommander sur une estimation d'ingenierie.
    """
    return {
        "tag": model.tag,
        "download_gb": _bytes_to_gb(model.download_size_bytes),
        "footprint_gb": _bytes_to_gb(model.memory_footprint_bytes),
        "footprint_low_gb": _bytes_to_gb(model.memory_footprint_low_bytes),
        "estimated": model.memory_footprint_is_estimated,
        "context_tokens": model.context_window_tokens,
        "license": model.license_name,
        # Qualification OSI et palier viennent du modele lui-meme : ce sont
        # deux proprietes du catalogue, pas deux tables paralleles a tenir.
        "osi_status": model.license_osi_status,
        "osi_approved": model.is_osi_approved,
        "tier": model.memory_tier,
        "tier_label": model.memory_tier_label,
        "source_url": model.source_url,
        "verified_on": model.verified_on,
    }


def catalog_entries():
    """Le catalogue, du plus lourd au plus leger (DEC-006), annote.

    L'ordre est celui de l'empreinte memoire, **jamais** celui d'une note de
    qualite : aucune source n'en publie, et les scores maison ont ete
    supprimes (D-021).

    Deux annotations s'ajoutent aux faits du catalogue, et une seule des deux
    est une opinion de cette couche :

    * `fits` croise l'empreinte avec la memoire mesuree. La regle appartient au
      coeur : c'est `recommend().fits`, recopie ici, jamais recalculee.
      ``None`` tant que rien n'est mesure — ni « tient », ni « ne tient pas ».
    * `installed` croise le tag avec ce qu'`ollama /api/tags` a rendu. Le
      coeur a explicitement refuse ce croisement : « deja telecharge » n'est
      pas une regle de memoire, et l'appariement nom/tag existe deja ici, dans
      `is_model_installed()`. Il n'y en a donc qu'un, et il est a cet etage.
    """
    tiennent = state.get("fitting_tags")
    installes = state.get("installed_models") or []
    entrees = []
    for model in CORE.models_by_footprint():
        entree = model_entry(model)
        entree["fits"] = None if tiennent is None else (model.tag in tiennent)
        entree["installed"] = is_model_installed(model.tag, installes)
        entrees.append(entree)
    return entrees


def memory_tier_entries():
    """Les cinq paliers memoire de l'offre par defaut, prets a rendre.

    Le regroupement et l'ordre viennent de `group_by_memory_tier()` et de
    `MEMORY_TIERS` : l'interface ne decoupe aucune tranche elle-meme, sinon
    elle porterait une seconde classification a cote de celle de la veille
    (D-022). Le catalogue passe est celui des licences approuvees OSI, parce
    que c'est ce que l'interface propose par defaut.

    Les cinq paliers sont rendus **meme vides**. Sur le catalogue du
    2026-09-04 le palier le plus lourd n'a aucune entree approuvee OSI : le
    taire ferait croire a un palier inexistant, alors que le fait a montrer
    est qu'il existe et qu'aucun modele libre ne l'occupe.
    """
    return [
        {"tier_id": tier_id, "label": label, "tags": [m.tag for m in modeles]}
        for tier_id, label, modeles in CORE.memory_tier_groups(CORE.open_source_models())
    ]


#: Ce que l'interface propose par defaut, et pourquoi elle ecarte le reste.
#:
#: Trois etats de licence, jamais deux : approuvee OSI, non approuvee, et **non
#: verifiee**. Fondre le troisieme dans le deuxieme affirmerait qu'une licence
#: n'est pas libre alors que la veille refuse de trancher — la meme faute que
#: `STATUS_UNKNOWN` corrige pour les services.
LICENSE_NOTICE = (
    "Par defaut, seules les licences approuvees OSI sont proposees : "
    "{approuves} modeles sur {total}. Qualification d'apres {url} ; "
    "l'appartenance de MIT et Apache-2.0 a cette liste est citee de cette "
    "source et N'A PAS ete reverifiee en ligne."
)
LICENSE_RESTRICTED_NOTICE = (
    "{restreints} modeles a licence non approuvee OSI : poids diffuses "
    "publiquement, mais restrictions contractuelles d'usage. Ecartes du choix "
    "par defaut, pas du catalogue."
)
LICENSE_UNDETERMINED_NOTICE = (
    "{non_verifies} modeles dont la qualification OSI n'a pas pu etre "
    "tranchee. Ni libres ni non libres : non verifies. Le motif de chacun est "
    "inscrit au catalogue."
)
LICENSE_SCOPE_NOTICE = (
    "Recommandation et choix maximal sont calcules sur les {approuves} "
    "modeles a licence approuvee OSI uniquement."
)


def license_policy():
    """La politique de licence servie a l'interface, ou ``None``.

    Les trois ensembles de tags viennent de `CoreBridge.license_qualification()`,
    donc des filtres du coeur. Les phrases sont ici parce qu'elles s'adressent
    a l'utilisateur de ce launcher ; les comptes qu'elles portent sont
    calcules, jamais ecrits.
    """
    qualification = CORE.license_qualification()
    if qualification is None:
        return None
    comptes = {
        "approuves": len(qualification["approved"]),
        "restreints": len(qualification["restricted"]),
        "non_verifies": len(qualification["undetermined"]),
        "total": qualification["total"],
        "url": qualification["reference_url"],
    }
    return {
        "reference_url": qualification["reference_url"],
        "approved": list(qualification["approved"]),
        "restricted": list(qualification["restricted"]),
        "undetermined": list(qualification["undetermined"]),
        "notice": LICENSE_NOTICE.format(**comptes),
        "restricted_notice": LICENSE_RESTRICTED_NOTICE.format(**comptes),
        "undetermined_notice": LICENSE_UNDETERMINED_NOTICE.format(**comptes),
        "scope_notice": LICENSE_SCOPE_NOTICE.format(**comptes),
    }


# Mapping des docker-compose par configuration
#
# `default` est le chemin par defaut de DEC-010 : seule l'interface tourne en
# conteneur, Ollama reste natif sur l'hote, a l'identique sur Windows, macOS et
# Linux. C'est la valeur retenue par `select_docker_compose()` sur les trois
# systemes. Les autres entrees embarquent Ollama en conteneur et ne se
# justifient que si le GPU est expose a Docker, donc jamais sur macOS.
#
# Les descriptions ne nomment plus de modele : le tag servi par une variante
# conteneurisee est celui de son `OLLAMA_MODEL`, qui vit dans le fichier
# compose. Le recopier ici en faisait un quatrieme lieu de verite (D-022) et
# il avait deja divergé.
DOCKER_COMPOSE_OPTIONS = {
    "default": {
        "file": "compose.yaml",
        "label": "Par defaut (Ollama natif)",
        "description": "Interface en conteneur, Ollama natif sur l'hote - Windows, macOS, Linux",
    },
    "nvidia": {
        "file": "docker/compose/docker-compose.yml",
        "label": "NVIDIA (Docker)",
        "description": "GPU NVIDIA expose a Docker - Ollama conteneurise",
    },
    "win-nvidia-native": {
        "file": "docker/compose/docker-compose.win-nvidia.yml",
        "label": "Windows NVIDIA (Ollama natif)",
        "description": "Si conflit de port: utilise Ollama natif Windows",
    },
    "win-amd": {
        "file": "docker/compose/docker-compose.win-amd.yml",
        "label": "Windows + AMD (Ollama natif)",
        "description": "Pour Windows avec GPU AMD - Ollama tourne en natif",
    },
    "linux-amd": {
        "file": "docker/compose/docker-compose.amd.yml",
        "label": "Linux + AMD",
        "description": "Linux + GPU AMD (ROCm) - Ollama conteneurise",
    },
    "linux-amd-max": {
        "file": "docker/compose/docker-compose.amd-max.yml",
        "label": "Linux + AMD MAX (32B)",
        "description": "Linux + GPU AMD (ROCm), variante large - Ollama conteneurise",
    },
    "cpu": {
        "file": "docker/compose/docker-compose.cpu.yml",
        "label": "CPU uniquement",
        "description": "Sans GPU expose - Ollama conteneurise, inference sur processeur",
    },
}


def log(message):
    """Ajoute un message aux logs."""
    timestamp = time.strftime("%H:%M:%S")
    state["logs"].append(f"[{timestamp}] {message}")
    # Garder seulement les 50 derniers logs
    if len(state["logs"]) > 50:
        state["logs"] = state["logs"][-50:]
    print(f"[{timestamp}] {message}")


# Dernier message journalise par sonde, pour n'ecrire qu'aux transitions.
_last_logged = {}


def log_change(key, message):
    """Journalise seulement si le message differe du precedent pour cette cle.

    Les sondes tournent desormais toutes les deux secondes. Les faire ecrire a
    chaque passage noierait en quelques secondes le tampon de cinquante lignes
    et effacerait precisement ce que l'utilisateur cherche a y lire.
    """
    if _last_logged.get(key) == message:
        return False
    _last_logged[key] = message
    log(message)
    return True


def probe_http(url, timeout=HTTP_PROBE_TIMEOUT):
    """Sonde HTTP a trois etats. Rend `(statut, corps)`.

    - `STATUS_DOWN` seulement quand la sonde conclut : rien n'ecoute sur le
      port (connexion refusee), ou l'hote est injoignable.
    - `STATUS_UNKNOWN` des que la sonde ne conclut pas : delai depasse, code
      HTTP inattendu, erreur non prevue. Le corps vaut alors `None`.
    """
    try:
        request = urllib.request.Request(url)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status == 200:
                return STATUS_UP, response.read()
            # Quelque chose repond, mais pas ce qui est attendu : on ne sait pas.
            return STATUS_UNKNOWN, None
    except urllib.error.HTTPError:
        # Le serveur a repondu : il tourne, mais pas comme prevu.
        return STATUS_UNKNOWN, None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ConnectionRefusedError):
            return STATUS_DOWN, None
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return STATUS_UNKNOWN, None
        if isinstance(reason, OSError):
            # Hote introuvable, reseau coupe : le service n'est pas la.
            return STATUS_DOWN, None
        return STATUS_UNKNOWN, None
    # `socket.timeout` n'est un alias de `TimeoutError` qu'a partir de 3.10.
    # `launcher.py` amorce une machine nue et tourne sous le Python systeme,
    # soit 3.9.6 ici (D-061), ou les deux classes sont distinctes : appliquer
    # la simplification suggeree par ruff (UP041) casserait silencieusement la
    # distinction entre « delai depasse » et « service eteint » sur la seule
    # machine ou elle compte. Mesure : sous 3.9, `socket.timeout is
    # TimeoutError` rend False ; sous 3.14, True.
    except (socket.timeout, TimeoutError):  # noqa: UP041
        return STATUS_UNKNOWN, None
    except ConnectionRefusedError:
        return STATUS_DOWN, None
    except Exception:
        return STATUS_UNKNOWN, None


def set_service_status(service, status):
    """Ecrit le statut a trois etats et le booleen historique qui en derive.

    Le booleen `<service>_running` est conserve : il est lu ailleurs dans le
    fichier. Il ne vaut `True` que sur `STATUS_UP`, donc « inconnu » n'est
    jamais confondu avec « actif ». L'interface, elle, lit le statut a trois
    etats et distingue « eteint » de « indetermine ».
    """
    state[f"{service}_status"] = status
    state[f"{service}_running"] = status == STATUS_UP
    return status


def check_installations():
    """Vérifie si Docker et Ollama sont installés (Windows uniquement pour Ollama)."""
    # Vérifier Docker (nécessaire partout)
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            encoding="utf-8",
            errors="replace",
        )
        state["docker_installed"] = result.returncode == 0
        if state["docker_installed"]:
            log(f"Docker: {result.stdout.strip()[:40]}")
    except FileNotFoundError:
        state["docker_installed"] = False
        log("Docker: Non installe")
    except (OSError, subprocess.SubprocessError):
        state["docker_installed"] = True  # En cas d'erreur, on suppose installé

    # Vérifier Ollama (seulement sur Windows car sur Linux c'est dans Docker)
    if state["os"] == "Windows":
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=3,
                encoding="utf-8",
                errors="replace",
            )
            state["ollama_installed"] = result.returncode == 0
            if state["ollama_installed"]:
                log(f"Ollama: {result.stdout.strip()[:40]}")
        except FileNotFoundError:
            state["ollama_installed"] = False
            log("Ollama: Non installe")
        except (OSError, subprocess.SubprocessError):
            state["ollama_installed"] = True
    else:
        # Sur Linux, Ollama est dans Docker, pas besoin de l'installer
        state["ollama_installed"] = True


def install_ollama_windows():
    """Ouvre la page de téléchargement Ollama pour Windows."""
    log("Ouverture page telechargement Ollama...")
    import webbrowser

    webbrowser.open("https://ollama.com/download/windows")
    log("Installez Ollama puis cliquez 'Rafraichir'")


def install_docker():
    """Ouvre la page de téléchargement Docker."""
    log("Ouverture page telechargement Docker...")
    import webbrowser

    if state["os"] == "Windows":
        webbrowser.open("https://docs.docker.com/desktop/install/windows-install/")
    elif state["os"] == "Darwin":
        webbrowser.open("https://docs.docker.com/desktop/install/mac-install/")
    else:
        webbrowser.open("https://docs.docker.com/engine/install/")
    log("Installez Docker puis cliquez 'Rafraichir'")


# ---------------------------------------------------------------------------
# Mesure materielle : une seule implementation, celle du coeur
# ---------------------------------------------------------------------------
# `detect_gpu()` vivait ici en 110 lignes et une seconde fois, differente, dans
# `scripts/build.py` (D-018). Les deux devinaient un fabricant et ne mesuraient
# aucune capacite. `promptforge/hardware.py` mesure, et dit ce qu'il n'a pas pu
# mesurer. Les deux copies sont supprimees.

# Correspondance entre la marque rendue par la mesure et la classe d'affichage
# CSS historique de l'interface. `None` reste `None` : une marque non mesuree
# n'est pas un « cpu », c'est une absence de mesure (le defaut meme de D-018).
_GPU_TYPE_BY_VENDOR = {
    "apple": "apple",
    "nvidia": "nvidia",
    "amd": "amd",
    "intel": "cpu",
}


def hardware_entry(profile):
    """Instantane serialisable d'un `HardwareProfile`, pour l'interface.

    Tout ce qui n'a pas ete mesure vaut `None` et est rendu tel quel : c'est
    l'interface qui affichera « non mesure », jamais une valeur de confort.
    """
    if profile is None:
        return None
    return {
        "system": profile.system,
        "machine": profile.machine,
        "cpu_brand": profile.cpu_brand,
        "gpu_vendor": profile.gpu_vendor,
        "gpu_name": profile.gpu_name,
        "total_memory_gb": _bytes_to_gb(profile.total_memory_bytes),
        "total_memory_source": profile.total_memory_source,
        "vram_gb": _bytes_to_gb(profile.vram_bytes),
        "vram_source": profile.vram_source,
        "unified_memory": profile.unified_memory,
        "available_memory_gb": _bytes_to_gb(profile.available_memory_bytes),
        "available_memory_basis": profile.available_memory_basis,
        "notes": list(profile.notes),
    }


def recommendation_entry(reco):
    """Instantane serialisable d'une `Recommendation`, pour l'interface."""
    if reco is None:
        return None
    return {
        "measured": reco.measured,
        "recommended": model_entry(reco.recommended) if reco.recommended else None,
        "maximum": model_entry(reco.maximum) if reco.maximum else None,
        "fits": [model.tag for model in reco.fits],
        "unified": reco.unified,
        "available_memory_gb": _bytes_to_gb(reco.available_memory_bytes),
        "reserved_gb": _bytes_to_gb(reco.reserved_bytes),
        "margin_gb": _bytes_to_gb(reco.margin_bytes),
        "basis": reco.basis,
        "reason": reco.reason,
    }


def detect_hardware():
    """Mesure la machine et en deduit la recommandation de modele.

    Ne devine rien : si le pont vers le coeur est indisponible, ou si la
    memoire n'est pas mesurable, l'etat le dit et aucun modele n'est
    recommande. Le repli muet vers un tag en dur est precisement ce que
    D-019 reprochait au code precedent.
    """
    if not CORE.available:
        state["catalog_available"] = False
        state["catalog_error"] = CORE.error
        state["hardware"] = None
        state["recommendation"] = None
        state["fitting_tags"] = None
        state["gpu_type"] = None
        state["gpu"] = "Non mesure"
        log(f"Mesure materielle indisponible : {CORE.error}")
        return None

    profile = CORE.detect_hardware()
    state["catalog_available"] = True
    state["catalog_error"] = None
    state["hardware"] = hardware_entry(profile)
    state["gpu_type"] = _GPU_TYPE_BY_VENDOR.get(profile.gpu_vendor)
    state["gpu"] = profile.gpu_name or profile.cpu_brand or "Non mesure"

    # `gfx_version` ne sert qu'a `HSA_OVERRIDE_GFX_VERSION` sous Windows+AMD.
    # Aucune sonde du depot ne la mesure : elle reste absente plutot que
    # devinee depuis un numero de modele, ce que faisait l'ancien code.
    state["gfx_version"] = None

    memoire = state["hardware"]["available_memory_gb"]
    if memoire is None:
        log("Memoire disponible : non mesurable sur cette machine")
    else:
        log(
            f"Materiel mesure : {profile.system} {profile.machine or ''} - "
            f"{memoire} Gio disponibles ({profile.available_memory_basis})"
        )
    for note in profile.notes:
        log(f"Non mesure : {note}")

    apply_recommendation(profile)
    return profile


def apply_recommendation(profile=None):
    """Ecrit la recommandation de modele deduite de la mesure memoire.

    Le classement est celui de DEC-006 : empreinte memoire, jamais une note de
    qualite. Aucune qualite de reformatage n'est mesuree a ce jour ;
    l'interface doit le dire, et le dit.

    **Deux appels a `recommend()`, deux questions differentes.**

    * La **decision** — que proposer par defaut — porte sur le sous-catalogue a
      licence approuvee OSI. Recommander un modele que l'interface n'offre pas
      serait incoherent, et l'offre par defaut est open source.
    * La **capacite** — ce que la machine encaisse — porte sur le catalogue
      complet. Elle ne depend pas de la licence : marquer « depasse la memoire
      mesuree » un modele restreint qui tient serait un mensonge de plus,
      cache derriere un filtre juridique.

    Aucune des deux ne reimplemente quoi que ce soit : c'est la meme fonction
    du coeur, appelee sur deux catalogues.
    """
    if not CORE.available:
        state["recommendation"] = None
        state["fitting_tags"] = None
        return None

    capacite = CORE.recommend_for(profile) if profile is not None else None
    state["fitting_tags"] = (
        [m.tag for m in capacite.fits] if capacite is not None and capacite.measured else None
    )

    reco = (
        CORE.recommend_for(profile, catalog=CORE.open_source_models())
        if profile is not None
        else None
    )
    if reco is None:
        state["recommendation"] = None
        return None

    state["recommendation"] = recommendation_entry(reco)

    if reco.recommended is None:
        # Rien ne tient : on n'ecrit surtout pas un tag arbitraire.
        state["ollama_model"] = None
        state["model_installed"] = False
        log(f"Aucun modele recommande. {reco.reason}")
        return reco

    state["ollama_model"] = reco.recommended.tag
    state["model_installed"] = is_model_installed(
        reco.recommended.tag, state.get("installed_models", [])
    )
    log(f"Modele recommande : {reco.reason}")
    if reco.maximum is not None and reco.maximum.tag != reco.recommended.tag:
        log(f"Choix maximal possible : {reco.maximum.tag} (marge reduite)")
    return reco


def select_docker_compose():
    """Selectionne le fichier docker-compose approprie selon l'environnement.

    Le choix par defaut est `default` (compose.yaml) sur les trois systemes,
    conformement a DEC-010. Les variantes a Ollama conteneurise restent
    proposees la ou elles ont un sens, c'est-a-dire la ou le GPU peut etre
    expose a Docker. Sur macOS, elles ne sont pas proposees du tout : Docker
    Desktop ne passe pas Metal aux conteneurs, un Ollama conteneurise y
    tournerait CPU-only (D-020).

    La regle elle-meme vit dans `scripts/core_loader.compose_selection()`,
    partagee avec `scripts/build.py -c auto`. Deux mappings separes, c'est
    la moitie de D-018 qui survit a la disparition de `detect_gpu()`.
    """
    selection = compose_selection(state["os"], state["gpu_type"])

    state["docker_compose_file"] = selection["default"]
    state["available_compose_files"] = list(selection["options"])

    compose_info = DOCKER_COMPOSE_OPTIONS.get(state["docker_compose_file"], {})
    log(f"Docker Compose selectionne: {compose_info.get('label', state['docker_compose_file'])}")


def check_docker():
    """Sonde le demon Docker. Rend un des trois statuts.

    `TimeoutExpired` ne veut pas dire « Docker est eteint » : le demon peut
    etre en train de demarrer. Ce cas rend `STATUS_UNKNOWN`. Un code de
    retour non nul, lui, conclut : le client a parle, le demon n'a pas
    repondu, c'est `STATUS_DOWN`.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        log_change("docker", "Docker: indetermine (delai depasse)")
        return set_service_status("docker", STATUS_UNKNOWN)
    except FileNotFoundError:
        state["docker_installed"] = False
        log_change("docker", "Docker: binaire absent")
        return set_service_status("docker", STATUS_DOWN)
    except Exception as e:
        log_change("docker", f"Docker: indetermine - {e}")
        return set_service_status("docker", STATUS_UNKNOWN)

    if result.returncode == 0:
        log_change("docker", "Docker: OK")
        return set_service_status("docker", STATUS_UP)
    log_change("docker", "Docker: demon non demarre")
    return set_service_status("docker", STATUS_DOWN)


def check_ollama():
    """Sonde Ollama et liste les modeles installes. Rend un des trois statuts.

    Le `except: pass` d'origine ecrasait tout en `False` : un delai depasse,
    donc « je ne sais pas », s'affichait « Ollama non disponible » et
    l'utilisateur en concluait que le produit ne marchait pas.
    """
    status, payload = probe_http(
        f"http://localhost:{OLLAMA_PORT}/api/tags", timeout=HTTP_PROBE_TIMEOUT
    )

    if status == STATUS_UP:
        try:
            data = json.loads(payload.decode("utf-8"))
            models = [m["name"] for m in data.get("models", []) if "name" in m]
        except (ValueError, AttributeError, TypeError, UnicodeDecodeError) as e:
            # Quelque chose ecoute et rend 200, mais pas l'API d'Ollama.
            log_change("ollama", f"Ollama: reponse illisible, etat indetermine - {e}")
            return set_service_status("ollama", STATUS_UNKNOWN)

        state["installed_models"] = models
        current_model = state.get("ollama_model")
        if not current_model:
            # Aucun modele retenu : soit la memoire n'a pas ete mesuree, soit
            # rien ne tient. Ne rien affirmer sur un modele inexistant.
            state["model_installed"] = False
            log_change("ollama", f"Ollama: OK - {len(models)} modele(s) - aucun modele retenu")
            return set_service_status("ollama", STATUS_UP)

        model_installed = is_model_installed(current_model, models)
        state["model_installed"] = model_installed

        if model_installed:
            log_change("ollama", f"Ollama: OK - {len(models)} modele(s) - {current_model} ✓")
        else:
            log_change(
                "ollama", f"Ollama: OK - {len(models)} modele(s) - ⚠️ {current_model} non installe!"
            )
        return set_service_status("ollama", STATUS_UP)

    if status == STATUS_DOWN:
        # Rien n'ecoute : aucun modele n'est joignable, l'affirmer est exact.
        state["installed_models"] = []
        state["model_installed"] = False
        log_change("ollama", "Ollama: arrete (aucune ecoute sur le port)")
        return set_service_status("ollama", STATUS_DOWN)

    # Indetermine : on ne sait pas, donc on n'efface pas la derniere liste
    # connue et on ne pretend pas non plus qu'elle est a jour.
    log_change("ollama", "Ollama: etat indetermine (pas de reponse concluante)")
    return set_service_status("ollama", STATUS_UNKNOWN)


def is_model_installed(target_model, installed_models):
    """Verifie si un modele cible est installe.

    Gere les trois facons dont Ollama peut nommer un meme modele :
    correspondance exacte du tag, tag suffixe d'une quantization
    (``<famille>:<taille>-q4_0``), et tag ``latest``.

    Aucun tag n'est cite en exemple ici : les tags connus sont ceux du
    catalogue (DEC-003), et un exemple fige dans une docstring est la
    premiere marche vers la copie qui diverge (D-022).
    """
    if not target_model or not installed_models:
        return False

    # Normaliser le modèle cible
    if ":" in target_model:
        target_base, target_tag = target_model.split(":", 1)
    else:
        target_base, target_tag = target_model, "latest"

    for installed in installed_models:
        # Normaliser le modèle installé
        if ":" in installed:
            inst_base, inst_tag = installed.split(":", 1)
        else:
            inst_base, inst_tag = installed, "latest"

        # Cas 1: Correspondance exacte
        if target_model == installed:
            return True

        # Cas 2: Même base, tags compatibles
        if target_base == inst_base:
            # Le tag installé commence par le tag cible (ex: 8b vs 8b-q4_0)
            if inst_tag.startswith(target_tag) or target_tag.startswith(inst_tag):
                return True
            # Le modèle cible est le base et latest est installé
            if target_tag == "latest" or inst_tag == "latest":
                return True

    return False


def check_promptforge():
    """Sonde l'interface PromptForge. Rend un des trois statuts."""
    status, _ = probe_http(f"http://localhost:{PROMPTFORGE_PORT}/", timeout=HTTP_PROBE_TIMEOUT)
    if status == STATUS_UP:
        log_change("promptforge", "PromptForge: OK")
    elif status == STATUS_DOWN:
        log_change("promptforge", "PromptForge: arrete")
    else:
        log_change("promptforge", "PromptForge: etat indetermine")
    return set_service_status("promptforge", status)


# ---------------------------------------------------------------------------
# Ordonnancement des sondes
# ---------------------------------------------------------------------------
# Une seule sonde en vol a la fois : sans cela, un `docker info` lent
# (10 s de delai) verrait s'empiler derriere lui une sonde toutes les
# deux secondes. `_probe_lock` protege la decision, pas l'execution.
_probe_lock = threading.Lock()


def stamp_probe(now=None, include_docker=False):
    """Horodate la derniere sonde. C'est ce que l'interface affiche."""
    now = time.time() if now is None else now
    state["checked_at"] = now
    state["checked_at_label"] = time.strftime("%H:%M:%S", time.localtime(now))
    if include_docker:
        state["docker_checked_at"] = now
    return now


def run_probes(include_docker=True, now=None):
    """Execute les sondes et horodate le resultat.

    `include_docker` separe la cadence lente (sous-processus vers le demon)
    de la cadence rapide (deux requetes HTTP sur la boucle locale).
    """
    if include_docker:
        check_docker()
        check_docker_images()
    check_ollama()
    check_promptforge()
    return stamp_probe(now=now, include_docker=include_docker)


def probe_due(now=None):
    """Rend `(sonde_rapide_due, sonde_docker_due)` pour l'instant donne."""
    now = time.time() if now is None else now
    fast_due = now - (state["checked_at"] or 0) >= FAST_PROBE_TTL
    slow_due = now - (state["docker_checked_at"] or 0) >= SLOW_PROBE_TTL
    return fast_due, slow_due


def ensure_fresh_status(now=None):
    """Declenche une sonde en tache de fond si l'etat a vieilli.

    Appele par `/api/status`, donc a la cadence du client (3 s). Rend le
    `Thread` lance, ou `None` si rien n'etait du. La reponse HTTP n'attend
    jamais la sonde : elle rend l'instantane courant avec son horodatage, et
    le client obtient la valeur fraiche au sondage suivant. Peremption
    maximale observee par l'utilisateur : environ 5 s.
    """
    with _probe_lock:
        if state["probe_in_progress"]:
            return None
        fast_due, slow_due = probe_due(now)
        if not fast_due and not slow_due:
            return None
        state["probe_in_progress"] = True

    thread = threading.Thread(target=_probe_worker, args=(slow_due,), daemon=True)
    thread.start()
    return thread


def _probe_worker(include_docker):
    try:
        run_probes(include_docker=include_docker)
    finally:
        with _probe_lock:
            state["probe_in_progress"] = False


def status_payload(now=None):
    """L'instantane servi par `/api/status`, augmente de sa fraicheur.

    Un etat affiche sans date est un etat qui ment des qu'il vieillit : le
    payload porte donc toujours l'age de la mesure et le drapeau `stale`.
    """
    now = time.time() if now is None else now
    payload = dict(state)
    payload["logs"] = list(state["logs"])
    checked_at = state.get("checked_at")
    payload["age_seconds"] = None if not checked_at else round(now - checked_at, 1)
    payload["stale"] = checked_at is None or (now - checked_at) > STALE_AFTER
    payload["stale_after_seconds"] = STALE_AFTER
    payload["server_time"] = now
    # D-060 : la table de compose n'existe qu'ici, en Python. Elle est
    # envoyee au client au lieu d'etre recopiee en JavaScript.
    payload["compose_options"] = DOCKER_COMPOSE_OPTIONS
    # D-059 / DEC-003 : la liste de modeles n'existe pas dans ce fichier. Elle
    # est lue au catalogue du coeur et envoyee au client, qui ne porte plus
    # aucun `<option>` en dur. Ordre : empreinte memoire decroissante (DEC-006).
    payload["models"] = catalog_entries()
    # Les cinq paliers de `group_by_memory_tier()`, dans l'ordre de
    # `MEMORY_TIERS`. Le client rend ces groupes tels quels : il ne decoupe
    # aucune tranche, il n'en connait meme pas les bornes.
    payload["memory_tier_groups"] = memory_tier_entries()
    # Ce qui est propose par defaut, ce qui est ecarte, et pourquoi. Un modele
    # absent sans explication serait une decision prise a la place du dev.
    payload["license_policy"] = license_policy()
    # DEC-006, dit a l'utilisateur au lieu d'etre suppose : le tri porte sur la
    # memoire, aucune qualite de reformatage n'est mesuree a ce jour.
    payload["quality_disclaimer"] = QUALITY_DISCLAIMER
    payload["catalog_source"] = CORE.catalog_source() if CORE.available else None
    return payload


def refresh_status():
    """Rafraichit tous les statuts, sans condition de fraicheur.

    Chemin synchrone : demarrage du launcher et bouton « Rafraichir ».
    """
    return run_probes(include_docker=True)


def check_docker_images():
    """Vérifie l'état des images Docker du projet."""
    if not state["docker_installed"] or not state["docker_running"]:
        state["docker_images"] = {}
        state["rebuild_needed"] = True
        return

    try:
        # Lister les images du projet
        result = subprocess.run(
            [
                "docker",
                "images",
                "--format",
                "{{.Repository}}:{{.Tag}}|{{.CreatedAt}}|{{.Size}}",
                "--filter",
                "reference=*promptforge*",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )

        images = {}
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                if line and "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        name = parts[0]
                        images[name] = {"exists": True, "created": parts[1], "size": parts[2]}

        state["docker_images"] = images

        # Vérifier si un rebuild est nécessaire
        state["rebuild_needed"] = check_rebuild_needed()

        if images:
            log_change("images", f"Images Docker: {len(images)} trouvee(s)")
        else:
            log_change("images", "Images Docker: Aucune (build necessaire)")

    except Exception as e:
        log_change("images", f"Erreur verification images: {e}")
        state["docker_images"] = {}
        state["rebuild_needed"] = True


def check_rebuild_needed():
    """Vérifie si les images doivent être reconstruites."""
    # Si aucune image n'existe, rebuild nécessaire
    if not state["docker_images"]:
        return True

    # Vérifier si les Dockerfiles ont été modifiés après le dernier build
    try:
        dockerfiles = ["Dockerfile", "Dockerfile.web"]
        latest_dockerfile_time = 0

        for df in dockerfiles:
            if os.path.exists(df):
                mtime = os.path.getmtime(df)
                latest_dockerfile_time = max(latest_dockerfile_time, mtime)

        # Vérifier aussi les fichiers source Python
        src_dir = "promptforge"
        if os.path.isdir(src_dir):
            for f in os.listdir(src_dir):
                if f.endswith(".py"):
                    mtime = os.path.getmtime(os.path.join(src_dir, f))
                    latest_dockerfile_time = max(latest_dockerfile_time, mtime)

        # La date de creation des images n'est pas encore comparee aux
        # fichiers sources : la fonction se contente d'horodater le dernier
        # changement et rend False.

        state["last_build_time"] = latest_dockerfile_time
        return False

    except Exception:
        return True


def rebuild_docker_images(force=False):
    """Reconstruit les images Docker."""
    compose_key = state.get("docker_compose_file", "default")
    compose_info = DOCKER_COMPOSE_OPTIONS.get(compose_key, DOCKER_COMPOSE_OPTIONS["default"])
    compose_file = compose_info["file"]

    if not os.path.exists(compose_file):
        log(f"ERREUR: Fichier {compose_file} non trouve!")
        return False

    log(f"Reconstruction des images Docker{' (no-cache)' if force else ''}...")

    # Arrêter les conteneurs existants d'abord
    log("Arret des conteneurs existants...")
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "down", "--remove-orphans"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    # IMPORTANT: Mettre à jour l'état immédiatement après l'arrêt
    # pour que le bouton d'accès UI soit masqué
    state["promptforge_running"] = False
    state["ollama_running"] = False
    # Le statut a trois etats suit le booleen : on vient de les arreter,
    # ce n'est pas une mesure indeterminee.
    state["promptforge_status"] = STATUS_DOWN
    state["ollama_status"] = STATUS_DOWN

    # Construire les images
    cmd = ["docker", "compose", "-f", compose_file, "build"]
    if force:
        cmd.append("--no-cache")

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    if result.returncode == 0:
        log("Images reconstruites avec succes")
        check_docker_images()
        state["rebuild_needed"] = False
        return True
    else:
        error_msg = result.stderr[:200] if result.stderr else "Erreur inconnue"
        log(f"Erreur build: {error_msg}")
        return False


def clean_docker():
    """Nettoie les images et conteneurs Docker du projet."""
    log("Nettoyage Docker en cours...")

    # IMPORTANT: Mettre à jour l'état immédiatement
    # pour que le bouton d'accès UI soit masqué pendant le nettoyage
    state["promptforge_running"] = False
    state["ollama_running"] = False
    # Le statut a trois etats suit le booleen : on vient de les arreter,
    # ce n'est pas une mesure indeterminee.
    state["promptforge_status"] = STATUS_DOWN
    state["ollama_status"] = STATUS_DOWN

    # Arrêter tous les conteneurs du projet
    for key, info in DOCKER_COMPOSE_OPTIONS.items():
        if os.path.exists(info["file"]):
            subprocess.run(
                ["docker", "compose", "-f", info["file"], "down", "-v", "--rmi", "local"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )

    # Supprimer les images orphelines
    subprocess.run(
        ["docker", "image", "prune", "-f"], capture_output=True, encoding="utf-8", errors="replace"
    )

    log("Nettoyage termine")
    check_docker_images()


def start_ollama():
    """Démarre Ollama."""
    if state["os"] == "Windows":
        # Sur Windows, lancer Ollama nativement
        log("Demarrage d'Ollama...")
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "0.0.0.0:11434"
        if state["gfx_version"]:
            env["HSA_OVERRIDE_GFX_VERSION"] = state["gfx_version"]

        subprocess.Popen(
            ["ollama", "serve"],
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if state["os"] == "Windows" else 0,
        )
        time.sleep(5)
        check_ollama()
    else:
        log("Sur Linux/Mac, Ollama est gere par Docker")


def stop_ollama():
    """Arrête Ollama."""
    if state["os"] == "Windows":
        log("Arret d'Ollama...")
        subprocess.run(
            ["taskkill", "/IM", "ollama.exe", "/F"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        time.sleep(2)
        check_ollama()


def start_promptforge():
    """Démarre PromptForge via Docker."""
    log("Demarrage de PromptForge...")

    # Utiliser le docker-compose sélectionné
    compose_key = state.get("docker_compose_file", "default")
    compose_info = DOCKER_COMPOSE_OPTIONS.get(compose_key, DOCKER_COMPOSE_OPTIONS["default"])
    compose_file = compose_info["file"]

    log(f"Utilisation de {compose_file} ({compose_info['label']})")

    # Vérifier que le fichier existe
    if not os.path.exists(compose_file):
        log(f"ERREUR: Fichier {compose_file} non trouve!")
        return

    # Créer le dossier data s'il n'existe pas (pour la persistance SQLite)
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/projects", exist_ok=True)
    os.makedirs("data/history", exist_ok=True)

    # Sur Windows, arrêter Ollama natif si on utilise une config Docker avec Ollama
    # (pour éviter le conflit de port 11434)
    if state["os"] == "Windows" and compose_key not in ["default", "win-nvidia-native", "win-amd"]:
        log("Arret d'Ollama natif (liberation port 11434)...")
        subprocess.run(
            ["taskkill", "/IM", "ollama.exe", "/F"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        # Aussi arrêter le service Ollama s'il existe
        subprocess.run(
            ["sc", "stop", "ollama"], capture_output=True, encoding="utf-8", errors="replace"
        )
        time.sleep(2)  # Attendre la libération du port

    # Arrêter les conteneurs existants pour éviter les conflits
    log("Nettoyage des conteneurs existants...")
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "down", "--remove-orphans"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    # Démarrer les services
    log("Lancement des services...")
    result = subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "-d", "--build"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode == 0:
        log("Docker compose demarre")
        time.sleep(10)
    else:
        error_msg = result.stderr[:200] if result.stderr else "Erreur inconnue"
        log(f"Erreur: {error_msg}")

    check_promptforge()


def stop_promptforge():
    """Arrête PromptForge."""
    log("Arret de PromptForge...")

    # Arrêter avec le fichier actuel
    compose_key = state.get("docker_compose_file", "default")
    compose_info = DOCKER_COMPOSE_OPTIONS.get(compose_key, DOCKER_COMPOSE_OPTIONS["default"])
    compose_file = compose_info["file"]

    subprocess.run(
        ["docker", "compose", "-f", compose_file, "down"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    # Aussi essayer les autres au cas où
    for key, info in DOCKER_COMPOSE_OPTIONS.items():
        if key != compose_key:
            subprocess.run(
                ["docker", "compose", "-f", info["file"], "down"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )

    time.sleep(2)
    check_promptforge()


def pull_model(model_name):
    """Télécharge un modèle Ollama."""
    log(f"Telechargement de {model_name}...")
    state["ollama_model"] = model_name

    try:
        result = subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode == 0:
            log(f"Modele {model_name} pret")
            # Rafraîchir la liste des modèles installés
            check_ollama()
        else:
            error_msg = result.stderr[:100] if result.stderr else "Erreur inconnue"
            log(f"Erreur telechargement: {error_msg}")
    except Exception as e:
        log(f"Erreur pull: {str(e)[:100]}")


# === HTML de l'interface ===
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PromptForge Launcher</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCIgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0Ij4KICA8ZGVmcz4KICAgIDxsaW5lYXJHcmFkaWVudCBpZD0iZmlyZSIgeDE9IjAlIiB5MT0iMTAwJSIgeDI9IjAlIiB5Mj0iMCUiPgogICAgICA8c3RvcCBvZmZzZXQ9IjAlIiBzdHlsZT0ic3RvcC1jb2xvcjojZmY0ZDAwIi8+CiAgICAgIDxzdG9wIG9mZnNldD0iMTAwJSIgc3R5bGU9InN0b3AtY29sb3I6I2ZmYjM0NyIvPgogICAgPC9saW5lYXJHcmFkaWVudD4KICAgIDxsaW5lYXJHcmFkaWVudCBpZD0ibWV0YWwiIHgxPSIwJSIgeTE9IjAlIiB4Mj0iMCUiIHkyPSIxMDAlIj4KICAgICAgPHN0b3Agb2Zmc2V0PSIwJSIgc3R5bGU9InN0b3AtY29sb3I6IzVhNWE1YSIvPgogICAgICA8c3RvcCBvZmZzZXQ9IjEwMCUiIHN0eWxlPSJzdG9wLWNvbG9yOiMyZDJkMmQiLz4KICAgIDwvbGluZWFyR3JhZGllbnQ+CiAgPC9kZWZzPgogIDxyZWN0IHdpZHRoPSI2NCIgaGVpZ2h0PSI2NCIgcng9IjEyIiBmaWxsPSIjMWExYTJlIi8+CiAgPGVsbGlwc2UgY3g9IjMyIiBjeT0iNTAiIHJ4PSIxOCIgcnk9IjYiIGZpbGw9IiNmZjZiMzUiIG9wYWNpdHk9IjAuNCIvPgogIDxwYXRoIGQ9Ik0xOCA0OCBMMjIgNDAgTDQyIDQwIEw0NiA0OCBaIiBmaWxsPSJ1cmwoI21ldGFsKSIvPgogIDxyZWN0IHg9IjIwIiB5PSIzNiIgd2lkdGg9IjI0IiBoZWlnaHQ9IjYiIHJ4PSIxIiBmaWxsPSIjNGE0YTRhIi8+CiAgPHBhdGggZD0iTTI2IDM4IEwyMiA0MiBMMjYgNDYiIHN0cm9rZT0iI2ZmNmIzNSIgc3Ryb2tlLXdpZHRoPSIyLjUiIGZpbGw9Im5vbmUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgogIDxwYXRoIGQ9Ik0zOCAzOCBMNDIgNDIgTDM4IDQ2IiBzdHJva2U9IiNmZjZiMzUiIHN0cm9rZS13aWR0aD0iMi41IiBmaWxsPSJub25lIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KICA8ZyB0cmFuc2Zvcm09InJvdGF0ZSgtNDAsIDQwLCAyNCkiPgogICAgPHJlY3QgeD0iMzYiIHk9IjE4IiB3aWR0aD0iNCIgaGVpZ2h0PSIyNCIgcng9IjEiIGZpbGw9IiMzZDNkM2QiLz4KICAgIDxyZWN0IHg9IjMwIiB5PSIxMiIgd2lkdGg9IjE2IiBoZWlnaHQ9IjgiIHJ4PSIyIiBmaWxsPSIjNGE0YTRhIi8+CiAgPC9nPgogIDxjaXJjbGUgY3g9IjI4IiBjeT0iMzAiIHI9IjIiIGZpbGw9IiNmZmRkMDAiLz4KICA8Y2lyY2xlIGN4PSIzNiIgY3k9IjI4IiByPSIyIiBmaWxsPSIjZmZhYTAwIi8+CiAgPGNpcmNsZSBjeD0iMjQiIGN5PSIzNCIgcj0iMS41IiBmaWxsPSIjZmY4ODAwIi8+CiAgPGNpcmNsZSBjeD0iNDAiIGN5PSIzMiIgcj0iMS41IiBmaWxsPSIjZmZjYzAwIi8+Cjwvc3ZnPg==">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            background: linear-gradient(90deg, #00d4ff, #7b2cbf);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .card {
            background: rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
        }
        .card h2 {
            margin-bottom: 15px;
            font-size: 1.3em;
            color: #00d4ff;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        .status-item {
            background: rgba(0,0,0,0.3);
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }
        .status-item .icon {
            font-size: 2em;
            margin-bottom: 10px;
        }
        .status-item .label {
            font-size: 0.9em;
            color: #aaa;
        }
        .status-item .value {
            font-size: 1.1em;
            margin-top: 5px;
        }
        .status-ok { color: #00ff88; }
        .status-error { color: #ff4757; }
        .status-warning { color: #ffa502; }
        /* Troisieme etat : ni actif, ni eteint. La sonde n'a pas conclu. */
        .status-unknown { color: #b0b8c4; font-style: italic; }
        /* Fraicheur de la mesure affichee, a cote du titre de la carte. */
        .freshness {
            font-size: 0.75em;
            font-weight: normal;
            color: #8ea0b5;
            margin-left: 10px;
        }
        .freshness-stale { color: #ffa502; }
        .freshness-offline { color: #ff4757; }
        .btn-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin-top: 15px;
        }
        .btn {
            padding: 12px 20px;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: 600;
        }
        .btn:hover { transform: translateY(-2px); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .btn-primary {
            background: linear-gradient(90deg, #00d4ff, #0099cc);
            color: #fff;
        }
        .btn-success {
            background: linear-gradient(90deg, #00ff88, #00cc6a);
            color: #000;
        }
        .btn-danger {
            background: linear-gradient(90deg, #ff4757, #cc3344);
            color: #fff;
        }
        .btn-secondary {
            background: rgba(255,255,255,0.2);
            color: #fff;
        }
        .btn-large {
            padding: 20px 40px;
            font-size: 1.3em;
            width: 100%;
        }
        .logs {
            background: #000;
            border-radius: 10px;
            padding: 15px;
            height: 200px;
            overflow-y: auto;
            font-family: 'Consolas', monospace;
            font-size: 0.85em;
            color: #0f0;
        }
        .gpu-amd { border-left: 4px solid #ed1c24; }
        .gpu-nvidia { border-left: 4px solid #76b900; }
        .gpu-apple { border-left: 4px solid #a3aaae; }
        .gpu-cpu { border-left: 4px solid #888; }
        select {
            padding: 10px;
            border-radius: 8px;
            border: none;
            background: #2a2a4e;
            color: #fff;
            font-size: 1em;
            cursor: pointer;
        }
        select option {
            background: #1a1a2e;
            color: #fff;
            padding: 8px;
        }
        select optgroup {
            background: #0a0a1e;
            color: #4dabf7;
            font-weight: bold;
            font-style: normal;
            padding: 5px;
        }
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .hidden { display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1 style="display: flex; align-items: center; justify-content: center; gap: 15px;">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="48" height="48" style="flex-shrink: 0;">
                <defs>
                    <linearGradient id="fire" x1="0%" y1="100%" x2="0%" y2="0%">
                        <stop offset="0%" style="stop-color:#ff4d00"/>
                        <stop offset="100%" style="stop-color:#ffb347"/>
                    </linearGradient>
                    <linearGradient id="metal" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:#5a5a5a"/>
                        <stop offset="100%" style="stop-color:#2d2d2d"/>
                    </linearGradient>
                </defs>
                <rect width="64" height="64" rx="12" fill="#1a1a2e"/>
                <ellipse cx="32" cy="50" rx="18" ry="6" fill="#ff6b35" opacity="0.4"/>
                <path d="M18 48 L22 40 L42 40 L46 48 Z" fill="url(#metal)"/>
                <rect x="20" y="36" width="24" height="6" rx="1" fill="#4a4a4a"/>
                <path d="M26 38 L22 42 L26 46" stroke="#ff6b35" stroke-width="2.5" fill="none" stroke-linecap="round"/>
                <path d="M38 38 L42 42 L38 46" stroke="#ff6b35" stroke-width="2.5" fill="none" stroke-linecap="round"/>
                <g transform="rotate(-40, 40, 24)">
                    <rect x="36" y="18" width="4" height="24" rx="1" fill="#3d3d3d"/>
                    <rect x="30" y="12" width="16" height="8" rx="2" fill="#4a4a4a"/>
                </g>
                <circle cx="28" cy="30" r="2" fill="#ffdd00"/>
                <circle cx="36" cy="28" r="2" fill="#ffaa00"/>
                <circle cx="24" cy="34" r="1.5" fill="#ff8800"/>
                <circle cx="40" cy="32" r="1.5" fill="#ffcc00"/>
            </svg>
            <span>Prompt<span style="color: #ff6b35;">Forge</span> Launcher</span>
        </h1>

        <!-- Détection système -->
        <div class="card" id="system-card">
            <h2>🖥️ Systeme detecte<span class="freshness" id="freshness">Etat jamais verifie</span></h2>
            <div class="status-grid">
                <div class="status-item" id="gpu-status">
                    <div class="icon">🎮</div>
                    <div class="label">GPU</div>
                    <div class="value" id="gpu-value">Mesure...</div>
                </div>
                <div class="status-item" id="memory-status">
                    <div class="icon">🧠</div>
                    <div class="label">Memoire pour l'inference</div>
                    <div class="value" id="memory-value">Mesure...</div>
                </div>
                <div class="status-item">
                    <div class="icon">🐳</div>
                    <div class="label">Docker</div>
                    <div class="value" id="docker-value">Verification...</div>
                </div>
                <div class="status-item">
                    <div class="icon">🦙</div>
                    <div class="label">Ollama</div>
                    <div class="value" id="ollama-value">Verification...</div>
                </div>
                <div class="status-item">
                    <div class="icon">🔧</div>
                    <div class="label">PromptForge</div>
                    <div class="value" id="promptforge-value">Verification...</div>
                </div>
            </div>
        </div>

        <!-- Alertes d'installation (Windows uniquement) -->
        <div class="card" id="install-alert" style="display: none; border-left: 4px solid #ffa502;">
            <h2>⚠️ Installation requise</h2>
            <div id="alert-content"></div>
        </div>

        <!-- Contrôles -->
        <div class="card">
            <h2>⚡ Controles</h2>

            <!-- Configuration Docker Compose -->
            <div class="config-section" style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 10px; margin-bottom: 15px;">
                <div style="display: flex; align-items: center; gap: 15px; flex-wrap: wrap;">
                    <div>
                        <label style="display: block; font-size: 0.85em; color: #aaa; margin-bottom: 5px;">Configuration Docker:</label>
                        <select id="compose-select" onchange="selectCompose(this.value)" style="min-width: 250px;">
                            <!-- Options générées dynamiquement -->
                        </select>
                    </div>
                    <div>
                        <label style="display: block; font-size: 0.85em; color: #aaa; margin-bottom: 5px;">Modele IA:</label>
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <!-- D-059 : aucun <option> en dur. La liste est
                                 rendue par updateModelSelector() a partir de
                                 data.models, servi par /api/status depuis le
                                 catalogue du coeur. -->
                            <select id="model-select" onchange="onModelChange(this.value)" style="min-width: 420px;"></select>
                            <span id="model-status" style="font-size: 1.2em;" title="Statut du modele"></span>
                        </div>
                        <div id="model-recommendation" style="margin-top: 6px; font-size: 0.78em; color: #aaa; max-width: 640px;"></div>
                        <!-- Les licences ecartees ne disparaissent pas en
                             silence : cette bascule les fait reapparaitre,
                             groupees par motif d'exclusion. -->
                        <div style="margin-top: 6px; font-size: 0.74em; color: #888;">
                            <label style="cursor: pointer;">
                                <input type="checkbox" id="show-restricted" onchange="onToggleRestricted()">
                                Afficher aussi les licences restreintes et non verifiees
                            </label>
                        </div>
                        <div id="model-licenses" style="margin-top: 4px; font-size: 0.72em; color: #888; max-width: 640px;"></div>
                        <div id="model-disclaimer" style="margin-top: 4px; font-size: 0.72em; color: #888; max-width: 640px;"></div>
                    </div>
                </div>
                <div id="compose-description" style="margin-top: 10px; font-size: 0.85em; color: #888;"></div>
            </div>

            <div class="btn-grid">
                <button class="btn btn-primary" onclick="action('start_ollama')" id="btn-ollama-start">
                    ▶️ Demarrer Ollama
                </button>
                <button class="btn btn-danger" onclick="action('stop_ollama')" id="btn-ollama-stop">
                    ⏹️ Arreter Ollama
                </button>
                <button class="btn btn-primary" onclick="action('start_promptforge')" id="btn-pf-start">
                    ▶️ Demarrer PromptForge
                </button>
                <button class="btn btn-danger" onclick="action('stop_promptforge')" id="btn-pf-stop">
                    ⏹️ Arreter PromptForge
                </button>
                <button class="btn btn-secondary" onclick="action('pull_model')" id="btn-pull">
                    📥 Telecharger modele
                </button>
                <button class="btn btn-secondary" onclick="action('refresh')">
                    🔄 Rafraichir
                </button>
            </div>

            <!-- Outils Docker -->
            <div style="margin-top: 20px; padding: 15px; background: rgba(0,0,0,0.2); border-radius: 10px;">
                <h3 style="margin-bottom: 10px; font-size: 1em; color: #aaa;">🐳 Outils Docker</h3>
                <div id="docker-images-status" style="font-size: 0.85em; margin-bottom: 10px; color: #888;"></div>
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <button class="btn btn-secondary" onclick="action('rebuild')" id="btn-rebuild" style="font-size: 0.9em;">
                        🔨 Rebuild images
                    </button>
                    <button class="btn btn-secondary" onclick="action('rebuild_force')" id="btn-rebuild-force" style="font-size: 0.9em;">
                        🔥 Rebuild (no-cache)
                    </button>
                    <button class="btn btn-danger" onclick="confirmClean()" id="btn-clean" style="font-size: 0.9em;">
                        🗑️ Nettoyer
                    </button>
                    <button class="btn btn-secondary" onclick="action('detect_hardware')" style="font-size: 0.9em;">
                        🔍 Re-mesurer la machine
                    </button>
                </div>
            </div>

            <div style="margin-top: 15px;">
                <label title="N'affecte que le choix du fichier compose. La recommandation de modele depend de la memoire mesuree, pas de la marque.">Forcer la marque du GPU (choix du compose uniquement):</label>
                <select id="force-gpu" onchange="forceGpu(this.value)">
                    <option value="">-- Auto --</option>
                    <option value="amd">AMD (ROCm)</option>
                    <option value="nvidia">NVIDIA (CUDA)</option>
                    <option value="cpu">CPU uniquement</option>
                </select>
            </div>
        </div>

        <!-- Accès PromptForge -->
        <div class="card" id="access-card" style="display: none;">
            <h2>✅ Tout est pret!</h2>
            <button class="btn btn-success btn-large" onclick="openPromptForge()">
                🚀 Acceder a PromptForge
            </button>
        </div>

        <!-- Logs -->
        <div class="card">
            <h2>📋 Logs</h2>
            <div class="logs" id="logs"></div>
            <div id="debug" style="margin-top:10px; padding:10px; background:#330; color:#ff0; font-family:monospace; font-size:12px; border-radius:5px;">JS Loading...</div>
        </div>
    </div>

    <script>
        function updateUI(data) {
            try {
                // GPU et memoire : ce qui est mesure, et ce qui ne l'est pas.
                //
                // L'ancien code ecrivait 'cpu' des que la sonde ne concluait
                // pas : « non mesurable » devenait « pas de GPU » (D-018).
                // Une marque absente s'affiche desormais comme telle.
                const gpuEl = document.getElementById('gpu-value');
                const gpuCard = document.getElementById('gpu-status');
                const hw = data.hardware || null;
                if (gpuEl) {
                    if (!hw) {
                        gpuEl.textContent = 'Non mesure';
                        gpuEl.title = data.catalog_error || 'Aucune mesure disponible';
                    } else if (hw.gpu_vendor) {
                        gpuEl.textContent = hw.gpu_name || hw.cpu_brand || hw.gpu_vendor;
                        gpuEl.title = 'Marque mesuree : ' + hw.gpu_vendor
                            + ((hw.notes || []).length ? ' | ' + hw.notes.join(' | ') : '');
                    } else {
                        gpuEl.textContent = 'Marque non mesuree';
                        gpuEl.title = (hw.notes || []).join(' | ');
                    }
                }
                if (gpuCard) gpuCard.className = 'status-item gpu-' + (data.gpu_type || 'unknown');
                updateMemory(data);

                // Fraicheur de la mesure affichee
                updateFreshness(data);

                // Docker (trois etats)
                const dockerEl = document.getElementById('docker-value');
                if (dockerEl) {
                    if (!data.docker_installed) {
                        dockerEl.textContent = '❌ Non installe';
                        dockerEl.className = 'value status-error';
                    } else if (data.docker_status === 'up') {
                        dockerEl.textContent = '✅ Actif';
                        dockerEl.className = 'value status-ok';
                    } else if (data.docker_status === 'unknown') {
                        dockerEl.textContent = '❔ Indetermine';
                        dockerEl.className = 'value status-unknown';
                    } else {
                        dockerEl.textContent = '⚠️ Non demarre';
                        dockerEl.className = 'value status-warning';
                    }
                }

                // Ollama (trois etats)
                const ollamaEl = document.getElementById('ollama-value');
                if (ollamaEl) {
                    if (data.os === 'Windows' && !data.ollama_installed) {
                        ollamaEl.textContent = '❌ Non installe';
                        ollamaEl.className = 'value status-error';
                    } else if (data.ollama_status === 'up') {
                        ollamaEl.textContent = '✅ Actif';
                        ollamaEl.className = 'value status-ok';
                    } else if (data.ollama_status === 'unknown') {
                        ollamaEl.textContent = '❔ Indetermine';
                        ollamaEl.className = 'value status-unknown';
                    } else {
                        ollamaEl.textContent = data.os === 'Windows' ? '⚠️ Non demarre' : '⏳ Via Docker';
                        ollamaEl.className = 'value ' + (data.os === 'Windows' ? 'status-warning' : 'status-ok');
                    }
                }

                // PromptForge (trois etats)
                const pfEl = document.getElementById('promptforge-value');
                if (pfEl) {
                    if (data.promptforge_status === 'up') {
                        pfEl.textContent = '✅ Actif';
                        pfEl.className = 'value status-ok';
                    } else if (data.promptforge_status === 'unknown') {
                        pfEl.textContent = '❔ Indetermine';
                        pfEl.className = 'value status-unknown';
                    } else {
                        pfEl.textContent = '❌ Inactif';
                        pfEl.className = 'value status-error';
                    }
                }

                // Alertes d'installation
                updateInstallAlerts(data);

                // Bouton accès
                const accessCard = document.getElementById('access-card');
                // Masque seulement sur un « eteint » mesure. Sur un etat
                // indetermine on laisse le lien : au pire il ne repond pas,
                // au mieux il marche - et cacher l'acces au produit sur une
                // absence de mesure est precisement le defaut corrige ici.
                if (accessCard) accessCard.style.display = (data.promptforge_status === 'down') ? 'none' : 'block';

                // Docker Compose selector
                updateComposeSelector(data);

                // État des images Docker
                updateDockerImagesStatus(data);

                // Liste des modeles, recommandation, licences et reserve de
                // DEC-006. `updateLicenses` vient apres la liste : elle dit
                // ce que la liste propose, et ce qu'elle ecarte.
                updateModelSelector(data);
                updateRecommendation(data);
                updateLicenses(data);

                var modelStatus = document.getElementById('model-status');
                if (modelStatus) {
                    if (data.ollama_status === 'unknown') {
                        modelStatus.textContent = '❔';
                        // Chaine JS entre guillemets doubles : `\'` dans une
                        // triple-quote Python NON brute est mange par Python et
                        // produit une apostrophe nue, donc un `SyntaxError` qui
                        // tue TOUT le bloc <script>. Verifie par `node --check`.
                        modelStatus.title = "Etat d'Ollama indetermine - la liste des modeles peut etre perimee";
                    } else if (data.ollama_status !== 'up') {
                        modelStatus.textContent = '⏸️';
                        modelStatus.title = 'Ollama non demarre';
                    } else if (data.model_installed) {
                        modelStatus.textContent = '✅';
                        modelStatus.title = 'Modele installe et pret';
                    } else {
                        modelStatus.textContent = '⚠️';
                        modelStatus.title = 'Modele non installe - cliquez sur Telecharger';
                    }
                }

                // Logs
                const logsEl = document.getElementById('logs');
                if (logsEl && data.logs) {
                    logsEl.innerHTML = data.logs.map(function(l) { return '<div>' + l + '</div>'; }).join('');
                    logsEl.scrollTop = logsEl.scrollHeight;
                }

                // Boutons
                const btnOllamaStart = document.getElementById('btn-ollama-start');
                const btnOllamaStop = document.getElementById('btn-ollama-stop');
                const btnPfStart = document.getElementById('btn-pf-start');
                const btnPfStop = document.getElementById('btn-pf-stop');

                // Sur un etat indetermine, les DEUX boutons restent actifs :
                // un etat qu'on ne connait pas ne doit jamais verrouiller
                // l'utilisateur hors de son produit.
                if (btnOllamaStart) btnOllamaStart.disabled = data.ollama_status === 'up' || data.action_in_progress || (data.os === 'Windows' && !data.ollama_installed);
                if (btnOllamaStop) btnOllamaStop.disabled = data.ollama_status === 'down' || data.action_in_progress;
                if (btnPfStart) btnPfStart.disabled = data.promptforge_status === 'up' || data.action_in_progress || !data.docker_installed;
                if (btnPfStop) btnPfStop.disabled = data.promptforge_status === 'down' || data.action_in_progress;
            } catch (e) {
                console.error('Erreur updateUI:', e);
            }
        }

        function updateInstallAlerts(data) {
            try {
                const alertCard = document.getElementById('install-alert');
                const alertContent = document.getElementById('alert-content');
                if (!alertCard || !alertContent) return;

                let alerts = [];

            // Docker non installé (tous OS)
            if (!data.docker_installed) {
                alerts.push(
                    '<div style="display: flex; align-items: center; gap: 15px; padding: 15px; background: rgba(0,0,0,0.2); border-radius: 8px; margin-bottom: 10px;">' +
                    '<span style="font-size: 2.5em;">🐳</span>' +
                    '<div style="flex: 1;"><strong>Docker non installe</strong><p style="margin: 5px 0 0 0; color: #aaa;">Docker est necessaire pour lancer PromptForge.</p></div>' +
                    '<button class="btn btn-primary" onclick="action(&#39;install_docker&#39;)">📥 Installer Docker</button>' +
                    '</div>'
                );
            }

            // Ollama non installé (Windows seulement, car sur Linux c'est dans Docker)
            if (data.os === 'Windows' && !data.ollama_installed) {
                alerts.push(
                    '<div style="display: flex; align-items: center; gap: 15px; padding: 15px; background: rgba(0,0,0,0.2); border-radius: 8px; margin-bottom: 10px;">' +
                    '<span style="font-size: 2.5em;">🦙</span>' +
                    '<div style="flex: 1;"><strong>Ollama non installe</strong><p style="margin: 5px 0 0 0; color: #aaa;">Sur Windows avec AMD, Ollama doit etre installe separement.</p></div>' +
                    '<button class="btn btn-primary" onclick="action(&#39;install_ollama&#39;)">📥 Installer Ollama</button>' +
                    '</div>'
                );
            }

            // Modèle non installé (quand Ollama est actif)
            if (data.ollama_running && !data.model_installed && data.ollama_model) {
                var modelName = data.ollama_model;
                var installedList = (data.installed_models || []).join(', ') || 'aucun';
                alerts.push(
                    '<div style="display: flex; align-items: center; gap: 15px; padding: 15px; background: rgba(255,152,0,0.15); border: 1px solid #ff9800; border-radius: 8px; margin-bottom: 10px;">' +
                    '<span style="font-size: 2.5em;">⚠️</span>' +
                    '<div style="flex: 1;"><strong>Modele ' + modelName + ' non installe</strong>' +
                    '<p style="margin: 5px 0 0 0; color: #aaa;">Modeles disponibles: ' + installedList + '</p></div>' +
                    '<button class="btn btn-primary" onclick="action(&#39;pull_model&#39;)" style="background: #ff9800;">📥 Telecharger ' + modelName + '</button>' +
                    '</div>'
                );
            }

            if (alerts.length > 0) {
                alertCard.style.display = 'block';
                alertContent.innerHTML = alerts.join('');
            } else {
                alertCard.style.display = 'none';
            }
            } catch (e) {
                console.error('Erreur updateInstallAlerts:', e);
            }
        }

        // Fraicheur de l'etat affiche.
        //
        // Un etat sans date ment des qu'il vieillit. Trois rendus :
        //   - frais       : horodatage + age en secondes ;
        //   - perime      : au-dela de stale_after_seconds, en orange ;
        //   - hors ligne  : le launcher lui-meme ne repond plus, en rouge.
        // Le dernier cas compte : sans lui, l'age afficherait la meme valeur
        // pour l'eternite pendant que le serveur est mort.
        function updateFreshness(data) {
            const el = document.getElementById('freshness');
            if (!el) return;
            if (!data.checked_at_label) {
                el.textContent = 'Etat jamais verifie';
                el.className = 'freshness freshness-stale';
                return;
            }
            var age = (data.age_seconds === null || data.age_seconds === undefined)
                ? '?' : Math.round(data.age_seconds);
            var suffixe = data.probe_in_progress ? ' - verification en cours' : '';
            el.textContent = 'Etat verifie a ' + data.checked_at_label
                + ' (il y a ' + age + ' s)' + suffixe;
            el.className = data.stale ? 'freshness freshness-stale' : 'freshness';
        }

        function markLauncherOffline(message) {
            const el = document.getElementById('freshness');
            if (!el) return;
            el.textContent = 'Launcher injoignable - etat fige (' + message + ')';
            el.className = 'freshness freshness-offline';
        }

        // D-060 : la table des compose n'existe qu'en Python
        // (DOCKER_COMPOSE_OPTIONS). Elle arrive par /api/status dans
        // data.compose_options. La copie JavaScript qui vivait ici a ete
        // supprimee : elle avait deja divergee de son original.
        function updateComposeSelector(data) {
            try {
                const select = document.getElementById('compose-select');
                const descEl = document.getElementById('compose-description');
                if (!select || !descEl) return;

                const options = data.compose_options || {};
                const available = data.available_compose_files || ['default'];
                const current = data.docker_compose_file || 'default';

                select.innerHTML = available.map(function(key) {
                    var opt = options[key] || { label: key };
                    var selected = key === current ? ' selected' : '';
                    return '<option value="' + key + '"' + selected + '>' + (opt.label || key) + '</option>';
                }).join('');

                // Mettre à jour la description
                const currentOpt = options[current] || {};
                descEl.textContent = currentOpt.description || '';
            } catch (e) {
                console.error('Erreur updateComposeSelector:', e);
            }
        }

        // ------------------------------------------------------------------
        // Materiel mesure, catalogue et recommandation
        // ------------------------------------------------------------------
        // Aucune de ces trois choses n'existe en JavaScript : elles arrivent
        // par /api/status, depuis `promptforge/hardware.py` et
        // `promptforge/models_catalog.py`. La copie JS de la table de compose
        // avait deja divergé de son original (D-060) ; on ne recommence pas
        // avec les modeles.

        function gb(value) {
            return (value === null || value === undefined) ? null : value + ' Gio';
        }

        function updateMemory(data) {
            var el = document.getElementById('memory-value');
            if (!el) return;
            var hw = data.hardware || null;
            if (!hw || hw.available_memory_gb === null || hw.available_memory_gb === undefined) {
                el.textContent = '❔ Non mesuree';
                el.className = 'value status-unknown';
                el.title = hw ? (hw.notes || []).join(' | ')
                              : (data.catalog_error || 'Aucune mesure disponible');
                return;
            }
            var bases = {
                'unified_memory': 'memoire unifiee (CPU et GPU partagent le meme reservoir)',
                'dedicated_vram': 'VRAM dediee du GPU',
                'system_ram': 'RAM systeme (inference sur processeur)'
            };
            el.textContent = gb(hw.available_memory_gb);
            el.className = 'value status-ok';
            el.title = 'Base : ' + (bases[hw.available_memory_basis] || hw.available_memory_basis)
                + (hw.total_memory_source ? ' | sonde : ' + hw.total_memory_source : '');
        }

        // Le dernier etat servi, garde pour re-rendre la liste quand la
        // bascule de licence change, sans attendre le prochain /api/status.
        var dernierEtat = null;

        function modelesParTag(data) {
            var carte = {};
            (data.models || []).forEach(function (m) { carte[m.tag] = m; });
            return carte;
        }

        function modelesDe(tags, carte) {
            return (tags || []).map(function (t) { return carte[t]; })
                               .filter(function (m) { return !!m; });
        }

        function modelLabel(model) {
            // Trois faits par ligne, dans cet ordre : est-il deja la, que
            // coute-t-il en memoire, que coute-t-il a telecharger. Le premier
            // est celui qui manquait : la liste ne disait pas ce qui etait
            // deja installe. `installed` est calcule cote serveur par
            // is_model_installed(), le seul appariement nom/tag du depot.
            var marque = model.installed ? '●' : '○';
            if (model.fits === false) marque += ' ✕';
            var texte = marque + ' ' + model.tag + ' - ' + gb(model.footprint_gb) + ' en memoire';
            if (model.estimated) texte += ' (estimation)';
            texte += ', ' + gb(model.download_gb) + ' de telechargement';
            texte += model.installed ? ' - deja installe' : ' - non installe';
            if (model.fits === false) texte += ', depasse la memoire mesuree';
            else if (model.fits !== true) texte += ', capacite non mesuree';
            return texte;
        }

        function optionModele(model, courant) {
            var choisi = (model.tag === courant) ? ' selected' : '';
            return '<option value="' + model.tag + '"' + choisi + '>'
                + modelLabel(model) + '</option>';
        }

        function groupeOptions(libelle, modeles, courant) {
            return '<optgroup label="' + libelle + '">'
                + modeles.map(function (m) { return optionModele(m, courant); }).join('')
                + '</optgroup>';
        }

        function updateModelSelector(data) {
            try {
                dernierEtat = data;
                var select = document.getElementById('model-select');
                if (!select) return;

                var modeles = data.models || [];
                if (modeles.length === 0) {
                    // Aucune liste inventee : on dit que le catalogue manque.
                    select.innerHTML = '<option value="">Catalogue indisponible</option>';
                    select.disabled = true;
                    return;
                }
                select.disabled = false;

                var carte = modelesParTag(data);
                var politique = data.license_policy || {};
                var restreints = politique.restricted || [];
                var nonVerifies = politique.undetermined || [];
                var courant = data.ollama_model || null;

                // La bascule fait reapparaitre les licences ecartees. Elle est
                // forcee quand le modele retenu en fait partie : une liste ou
                // le modele actif n'apparait pas afficherait un AUTRE modele
                // comme selectionne, ce qui serait faux.
                var ecarte = !!courant
                    && (restreints.indexOf(courant) !== -1 || nonVerifies.indexOf(courant) !== -1);
                var bascule = document.getElementById('show-restricted');
                var montrerEcartes = !!(bascule && bascule.checked) || ecarte;

                // Les cinq paliers, dans l'ordre servi par le coeur. Aucun
                // n'est supprime : un palier vide, ou hors de portee de la
                // machine, reste visible et marque - c'est une information,
                // pas un trou. Le decoupage vient de group_by_memory_tier(),
                // ce fichier n'en connait meme pas les bornes.
                var html = '';
                (data.memory_tier_groups || []).forEach(function (groupe) {
                    var membres = modelesDe(groupe.tags, carte);
                    var libelle = groupe.label;
                    if (membres.length === 0) {
                        libelle += ' - aucun modele a licence approuvee OSI';
                    } else if (membres.every(function (m) { return m.fits === false; })) {
                        libelle += ' - hors capacite mesuree';
                    }
                    html += groupeOptions(libelle, membres, courant);
                });

                if (montrerEcartes) {
                    // Deux groupes distincts, jamais fondus : « non approuvee »
                    // est une conclusion, « non verifiee » est son absence.
                    var horsOsi = modelesDe(restreints, carte);
                    var nonTranches = modelesDe(nonVerifies, carte);
                    if (horsOsi.length) {
                        html += groupeOptions(
                            'Licence NON approuvee OSI - ecartes du choix par defaut',
                            horsOsi, courant);
                    }
                    if (nonTranches.length) {
                        html += groupeOptions(
                            'Licence NON VERIFIEE - qualification OSI non tranchee',
                            nonTranches, courant);
                    }
                }

                select.innerHTML = html;
                if (courant) select.value = courant;
            } catch (e) {
                console.error('Erreur updateModelSelector:', e);
            }
        }

        function onToggleRestricted() {
            if (dernierEtat) updateModelSelector(dernierEtat);
        }

        function updateLicenses(data) {
            var el = document.getElementById('model-licenses');
            if (!el) return;
            var politique = data.license_policy || null;
            if (!politique) {
                el.innerHTML = '';
                return;
            }
            // La qualification est citee avec sa reference, et la reserve sur
            // sa reverification est affichee avec elle : une source citee sans
            // reverification se declare, elle ne se sous-entend pas.
            el.innerHTML = [politique.notice,
                            politique.restricted_notice,
                            politique.undetermined_notice].join('<br>');
        }

        function updateRecommendation(data) {
            var el = document.getElementById('model-recommendation');
            var dis = document.getElementById('model-disclaimer');
            if (dis) dis.textContent = data.quality_disclaimer || '';
            if (!el) return;

            if (data.catalog_available === false) {
                // Mode degrade VISIBLE : ni liste en dur, ni silence.
                el.innerHTML = '⛔ <strong>Catalogue de modeles indisponible</strong> - aucun modele '
                    + 'ne peut etre recommande ni propose.<br><span style="color:#888;">'
                    + (data.catalog_error || 'motif inconnu') + '</span>';
                el.style.color = '#ff6b35';
                return;
            }

            var reco = data.recommendation || null;
            if (!reco || !reco.measured) {
                el.innerHTML = "❔ <strong>Memoire non mesuree</strong> - aucun modele n'est "
                    + 'recommande. Choisir au hasard reviendrait a presenter un defaut cable '
                    + 'comme une recommandation.';
                el.style.color = '#ffa502';
                return;
            }

            if (!reco.recommended) {
                el.innerHTML = '⚠️ ' + reco.reason;
                el.style.color = '#ffa502';
                return;
            }

            var nature = reco.basis === 'official'
                ? 'chiffre officiel de la fiche du modele'
                : "estimation d'ingenierie, non mesuree sur cette machine";
            // `installed` est porte par l'entree de catalogue servie, pas
            // recalcule ici : un second appariement nom/tag en JavaScript
            // serait la copie qui diverge.
            var carte = modelesParTag(data);
            function etatInstall(tag) {
                var entree = carte[tag];
                if (!entree) return '';
                return entree.installed ? ' - <strong>deja installe</strong>'
                                        : ' - non installe, a telecharger';
            }
            var lignes = [];
            lignes.push('✅ <strong>' + reco.recommended.tag + '</strong> recommande - '
                + gb(reco.recommended.footprint_gb) + ' en memoire (' + nature + ')'
                + (reco.margin_gb !== null ? ', marge ' + gb(reco.margin_gb) : '')
                + etatInstall(reco.recommended.tag));
            if (reco.maximum && reco.maximum.tag !== reco.recommended.tag) {
                lignes.push('⬆️ Choix maximal tenant dans la memoire mesuree : <strong>'
                    + reco.maximum.tag + '</strong> (' + gb(reco.maximum.footprint_gb)
                    + ', marge reduite)' + etatInstall(reco.maximum.tag));
            }
            // Ce que la machine porte deja, en une ligne. C'est la question
            // que la liste ne repondait pas : l'utilisateur ne savait pas ce
            // qu'il avait avant d'ouvrir un terminal.
            var installes = (data.models || []).filter(function (m) { return m.installed; })
                                               .map(function (m) { return m.tag; });
            lignes.push(installes.length
                ? '💾 Deja telecharges sur cette machine : <strong>'
                    + installes.join('</strong>, <strong>') + '</strong>'
                : "💾 Aucun modele du catalogue n'est telecharge sur cette machine.");
            if (reco.unified) {
                lignes.push('Memoire unifiee : ' + gb(reco.reserved_gb)
                    + ' laisses au systeme et aux applications pour le choix par defaut.');
            }
            if (data.license_policy) {
                lignes.push('<span style="color:#777;">'
                    + data.license_policy.scope_notice + '</span>');
            }
            if (data.catalog_source) {
                lignes.push('<span style="color:#777;">Source du catalogue : '
                    + data.catalog_source.source + ', verifie le '
                    + data.catalog_source.verified_on + '.</span>');
            }
            el.innerHTML = lignes.join('<br>');
            el.style.color = '#aaa';
        }

        async function onModelChange(model) {
            try {
                const resp = await fetch('/api/action', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'select_model', model: model})
                });
                const data = await resp.json();
                updateUI(data);
            } catch (e) {
                console.error('Erreur onModelChange:', e);
            }
        }

        async function selectCompose(composeKey) {
            try {
                const resp = await fetch('/api/action', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'select_compose', compose_key: composeKey})
                });
                const data = await resp.json();
                updateUI(data);
            } catch (e) {
                console.error('Erreur selectCompose:', e);
            }
        }

        async function action(act) {
            try {
                // Pas de tag de repli : si aucun modele n'est retenu, le
                // serveur doit refuser l'action, pas en telecharger un autre.
                const modelEl = document.getElementById('model-select');
                const model = (modelEl && modelEl.value) ? modelEl.value : null;
                const resp = await fetch('/api/action', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: act, model: model})
                });
                const data = await resp.json();
                updateUI(data);
            } catch (e) {
                console.error('Erreur action:', e);
            }
        }

        function openPromptForge() {
            window.open('http://localhost:7860', '_blank');
        }

        function confirmClean() {
            if (confirm('⚠️ Ceci va supprimer toutes les images Docker du projet.\\nVous devrez les reconstruire.\\n\\nContinuer?')) {
                action('clean_docker');
            }
        }

        function updateDockerImagesStatus(data) {
            var el = document.getElementById('docker-images-status');
            if (!el) return;

            var images = data.docker_images || {};
            var imageCount = Object.keys(images).length;
            var rebuildNeeded = data.rebuild_needed;

            if (imageCount === 0) {
                el.innerHTML = '⚠️ Aucune image - <strong>Build necessaire</strong>';
                el.style.color = '#ff9800';
            } else if (rebuildNeeded) {
                el.innerHTML = '📦 ' + imageCount + ' image(s) - <span style="color:#ff9800">Rebuild recommande</span>';
                el.style.color = '#aaa';
            } else {
                el.innerHTML = '✅ ' + imageCount + ' image(s) prete(s)';
                el.style.color = '#4caf50';
            }
        }

        async function forceGpu(gpuType) {
            if (!gpuType) {
                action('detect_hardware');
                return;
            }
            const resp = await fetch('/api/action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action: 'force_gpu', gpu_type: gpuType})
            });
            const data = await resp.json();
            updateUI(data);
        }

        async function refresh() {
            var dbg = document.getElementById('debug');
            try {
                if (dbg) dbg.innerHTML = 'Fetching...';
                const resp = await fetch('/api/status');
                if (dbg) dbg.innerHTML = 'Got response: ' + resp.status;
                const data = await resp.json();
                if (dbg) dbg.innerHTML = 'Parsed JSON. GPU: ' + (data.gpu || 'null');
                updateUI(data);
                if (dbg) dbg.innerHTML = 'UI Updated! GPU: ' + (data.gpu || 'null') + ', Docker: ' + data.docker_running;
            } catch (e) {
                console.error('Erreur refresh:', e);
                markLauncherOffline(e.message);
                if (dbg) dbg.innerHTML = 'ERROR: ' + e.message;
            }
        }

        // Cadence du client : 3 s.
        //
        // Le serveur ne resonde pas a chaque appel. `/api/status` declenche
        // une sonde seulement si l'etat a depasse son TTL (2 s pour Ollama et
        // PromptForge, 15 s pour Docker), en tache de fond et une seule a la
        // fois. Un Ollama demarre apres l'ouverture de la page est donc vu
        // en 5 s au pire, sans que l'utilisateur ait rien a cliquer, et sans
        // lancer 200 ms de sous-processus Docker toutes les deux secondes.
        setInterval(refresh, 3000);

        // Premier appel
        document.addEventListener('DOMContentLoaded', function() {
            var dbg = document.getElementById('debug');
            if (dbg) dbg.innerHTML = 'DOM Ready, calling refresh...';
            refresh();
        });
    </script>
</body>
</html>
"""


class LauncherHandler(SimpleHTTPRequestHandler):
    """Handler HTTP pour le launcher."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif self.path == "/api/status":
            # L'etat se recalcule tout seul : le client n'a rien a cliquer.
            # La sonde part en tache de fond, la reponse est immediate et
            # porte son propre horodatage.
            ensure_fresh_status()
            self.send_json(status_payload())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/action":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)
            action = data.get("action")
            model = data.get("model") or state.get("ollama_model")

            state["action_in_progress"] = True

            if action == "start_ollama":
                threading.Thread(target=start_ollama).start()
            elif action == "stop_ollama":
                threading.Thread(target=stop_ollama).start()
            elif action == "start_promptforge":
                threading.Thread(target=start_promptforge).start()
            elif action == "stop_promptforge":
                threading.Thread(target=stop_promptforge).start()
            elif action == "pull_model":
                if CORE.is_known_tag(model):
                    threading.Thread(target=pull_model, args=(model,)).start()
                else:
                    # `ollama pull` recoit ici une chaine venue du reseau : la
                    # confronter au catalogue est la seule liste blanche
                    # disponible, et elle est deja la source unique.
                    log(f"Telechargement refuse : {model!r} n'est pas au catalogue")
            elif action == "refresh":
                refresh_status()
            elif action == "detect_hardware":
                detect_hardware()
                select_docker_compose()
            elif action == "force_gpu":
                gpu_type = data.get("gpu_type", "cpu")
                state["gpu_type"] = gpu_type
                if gpu_type == "amd":
                    state["gpu"] = "AMD (force manuellement)"
                    state["gfx_version"] = "11.0.0"
                elif gpu_type == "nvidia":
                    state["gpu"] = "NVIDIA (force manuellement)"
                    state["gfx_version"] = None
                else:
                    state["gpu"] = "CPU (force manuellement)"
                    state["gfx_version"] = None
                # Forcer la marque ne change PAS la recommandation : celle-ci
                # depend de la memoire mesuree, pas du fabricant. Le seul effet
                # est le choix des fichiers compose proposes.
                log(f"GPU force: {gpu_type} (sans effet sur la recommandation de modele)")
                select_docker_compose()  # Recalculer le docker-compose
            elif action == "select_compose":
                compose_key = data.get("compose_key", "default")
                if compose_key in DOCKER_COMPOSE_OPTIONS:
                    state["docker_compose_file"] = compose_key
                    compose_info = DOCKER_COMPOSE_OPTIONS[compose_key]
                    log(f"Docker Compose change: {compose_info['label']}")
            elif action == "select_model":
                new_model = data.get("model")
                if not CORE.is_known_tag(new_model):
                    log(f"Modele refuse : {new_model!r} n'est pas au catalogue")
                else:
                    state["ollama_model"] = new_model
                    installed = state.get("installed_models", [])
                    state["model_installed"] = is_model_installed(new_model, installed)
                    log(
                        f"Modele selectionne: {new_model}"
                        + (" ✓" if state["model_installed"] else " (non installe)")
                    )
            elif action == "rebuild":
                threading.Thread(target=rebuild_docker_images, args=(False,)).start()
            elif action == "rebuild_force":
                threading.Thread(target=rebuild_docker_images, args=(True,)).start()
            elif action == "clean_docker":
                threading.Thread(target=clean_docker).start()
            elif action == "install_ollama":
                install_ollama_windows()
            elif action == "install_docker":
                install_docker()
            elif action == "check_install":
                check_installations()

            time.sleep(1)
            state["action_in_progress"] = False
            self.send_json(status_payload())
        else:
            self.send_error(404)

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Désactiver les logs HTTP


# ---------------------------------------------------------------------------
# Ecoute : boucle locale, et les DEUX familles d'adresses
# ---------------------------------------------------------------------------
# Le code faisait `HTTPServer(("0.0.0.0", LAUNCHER_PORT))`, ce qui cumulait
# deux defauts :
#
#   D-037 - un serveur qui demarre des conteneurs et telecharge des modeles
#           etait offert a tout le reseau local, sans aucune authentification
#           et sans la moindre raison fonctionnelle ;
#   D-062 - `0.0.0.0` n'ecoute qu'en IPv4, alors que `/etc/hosts` de macOS
#           declare `localhost` en IPv4 ET en IPv6 et que `getaddrinfo` rend
#           `::1` EN PREMIER. Mesure du 2026-09-07 :
#               curl http://localhost:7850    -> HTTP 000
#               curl http://127.0.0.1:7850    -> HTTP 200
#           Le launcher imprimait pourtant « accessible sur
#           http://localhost:7850 » : il promettait une adresse qu'il ne
#           servait pas.
#
# Passer simplement a `127.0.0.1` fermerait D-037 et laisserait D-062 entiere.
# Et `::` avec `IPV6_V6ONLY=0` donnerait bien la double pile, mais sur toutes
# les interfaces, donc rouvrirait D-037. Aucune adresse unique ne satisfait les
# deux : la seule cible correcte est DEUX sockets d'ecoute, une par famille,
# toutes deux sur la boucle locale.
LOOPBACK_HOSTS = ("127.0.0.1", "::1")


class _HTTPServerV6(HTTPServer):
    """`HTTPServer` en IPv6, avec `V6ONLY` force.

    `V6ONLY` est explicite parce que son defaut varie selon les systemes :
    a 0, le socket `::1` ne prendrait de toute facon pas les connexions vers
    `127.0.0.1` (le mode double pile ne s'applique qu'a `::`), mais il pourrait
    entrer en conflit avec l'autre socket sur certaines plateformes. On ne
    laisse pas ce comportement au hasard.
    """

    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        except (AttributeError, OSError):
            pass
        HTTPServer.server_bind(self)


def serve_loopback(port, handler=None):
    """Monte un serveur par famille d'adresses sur la boucle locale.

    Rend `(serveurs, fils, hotes_servis)`. Un echec sur une famille est
    journalise et n'empeche pas l'autre : une machine sans IPv6 doit rester
    utilisable. Si aucune famille ne repond, l'exception de la derniere est
    relancee, parce qu'un launcher qui n'ecoute nulle part doit le dire.
    """
    handler = handler or LauncherHandler
    servers = []
    threads = []
    served = []
    derniere_erreur = None

    for host in LOOPBACK_HOSTS:
        classe = _HTTPServerV6 if ":" in host else HTTPServer
        try:
            server = classe((host, port), handler)
        except OSError as exc:
            derniere_erreur = exc
            log(f"Ecoute impossible sur {host}:{port} - {exc}")
            continue
        fil = threading.Thread(target=server.serve_forever, daemon=True)
        fil.start()
        servers.append(server)
        threads.append(fil)
        served.append(host)

    if not servers:
        raise derniere_erreur if derniere_erreur else OSError("aucune ecoute possible")

    return servers, threads, served


def main():
    """Point d'entrée principal."""
    print("=" * 50)
    print("  PromptForge Launcher")
    print("=" * 50)
    print()

    # Mesure initiale
    log("Demarrage du launcher...")
    detect_hardware()
    check_installations()
    select_docker_compose()
    refresh_status()

    servers, threads, served = serve_loopback(LAUNCHER_PORT)
    log(f"Launcher accessible sur http://localhost:{LAUNCHER_PORT}")
    log("Ecoute sur " + ", ".join(f"{h}:{LAUNCHER_PORT}" for h in served))
    if "::1" not in served:
        # A dire, pas a taire : sur un systeme qui resout `localhost` en IPv6
        # d'abord, l'adresse imprimee ci-dessus ne repondrait pas.
        log(
            f"IPv6 indisponible : utiliser http://127.0.0.1:{LAUNCHER_PORT} "
            "si `localhost` ne repond pas"
        )

    # Ouvrir le navigateur
    import webbrowser

    webbrowser.open(f"http://localhost:{LAUNCHER_PORT}")

    print()
    print(f"Interface: http://localhost:{LAUNCHER_PORT}")
    print("Appuie sur Ctrl+C pour quitter")
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nArret du launcher...")
        for server in servers:
            server.shutdown()
            server.server_close()
        for fil in threads:
            fil.join(timeout=5)


if __name__ == "__main__":
    main()
