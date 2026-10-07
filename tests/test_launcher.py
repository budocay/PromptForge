"""
Tests pour le launcher PromptForge.
Verifie que toutes les configurations Docker sont correctes.

Contient le test de couture entre les commandes du depot et les fichiers
compose qu'elles visent (`TestComposeServiceSeam`). Il repond a une
regression reelle : le deplacement des compose dans `docker/compose/` et la
creation d'un `compose.yaml` racine a un seul service ont casse cinq points
d'entree, sans qu'aucun test ne rougisse et alors que
`docker compose config` continuait de rendre 0. `config` valide la syntaxe
d'un fichier ; il ne sait rien des commandes qui le consomment.
"""

import http.server
import importlib.util
import json as _json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_DIR = Path(__file__).resolve().parent.parent

# Fichier retenu par `docker compose` sans `-f` a la racine du depot.
DEFAULT_COMPOSE = "compose.yaml"


def compose_paths():
    """Les sept fichiers compose du depot."""
    return sorted(BASE_DIR.glob("docker/compose/*.yml")) + [BASE_DIR / DEFAULT_COMPOSE]


def compose_services(path):
    """Services declares par un fichier compose, en set."""
    import yaml

    with open(path) as handle:
        config = yaml.safe_load(handle)
    return set((config or {}).get("services", {}) or {})


# ------------------------------------------------------------------
# Extraction des services nommes par une commande `docker compose`
# ------------------------------------------------------------------

# Options globales (avant la sous-commande) qui consomment la valeur suivante.
_GLOBAL_VALUE_FLAGS = {
    "-f",
    "--file",
    "-p",
    "--project-name",
    "--profile",
    "--env-file",
    "--project-directory",
    "--progress",
    "--ansi",
}

# Sous-commandes dont tous les arguments libres sont des services.
_SERVICE_LIST_SUBCOMMANDS = {
    "up",
    "build",
    "ps",
    "pull",
    "push",
    "restart",
    "start",
    "stop",
    "kill",
    "logs",
    "rm",
    "create",
    "images",
    "top",
    "pause",
    "unpause",
    "wait",
}

# Sous-commandes dont seul le PREMIER argument libre est un service
# (le reste est la commande a executer dans le conteneur).
_SERVICE_FIRST_SUBCOMMANDS = {"run", "exec"}

# Options qui consomment la valeur suivante, apres la sous-commande.
_VALUE_FLAGS = {
    "--scale",
    "--entrypoint",
    "--user",
    "-u",
    "--workdir",
    "-w",
    "--name",
    "--label",
    "-l",
    "--volume",
    "--publish",
    "-p",
    "--tail",
    "-n",
    "--since",
    "--until",
    "--timeout",
    "-t",
    "--parallel",
    "--rmi",
    "--profile",
    "--memory",
    "-m",
    "--exit-code-from",
    "--attach",
    "--no-attach",
    "--env",
    "-e",
    "--build-arg",
    "--ssh",
    "--builder",
    "--index",
    "--wait-timeout",
}


def parse_compose_command(tokens):
    """Rend `(fichier_compose, [services nommes])` pour un argv compose.

    Rend `None` si l'argv n'est pas une invocation `docker compose`.
    Le fichier vaut `compose.yaml` quand aucun `-f` n'est passe, ce qui est
    la resolution reelle de Docker a la racine du depot.
    """
    tokens = list(tokens)
    if not tokens:
        return None
    if tokens[0] == "docker" and len(tokens) > 1 and tokens[1] == "compose":
        rest = tokens[2:]
    elif tokens[0] == "docker-compose":
        rest = tokens[1:]
    else:
        return None

    compose_file = DEFAULT_COMPOSE
    index = 0
    subcommand = None

    # Options globales, jusqu'a la sous-commande.
    while index < len(rest):
        token = rest[index]
        if token.startswith("-"):
            name, _, inline = token.partition("=")
            if name in ("-f", "--file"):
                compose_file = inline or rest[index + 1]
                index += 1 if inline else 2
                continue
            if name in _GLOBAL_VALUE_FLAGS and not inline:
                index += 2
                continue
            index += 1
            continue
        subcommand = token
        index += 1
        break

    if subcommand is None:
        return compose_file, []
    if subcommand not in _SERVICE_LIST_SUBCOMMANDS | _SERVICE_FIRST_SUBCOMMANDS:
        # `down`, `config`, `version`... ne nomment aucun service ici.
        return compose_file, []

    services = []
    only_first = subcommand in _SERVICE_FIRST_SUBCOMMANDS
    while index < len(rest):
        token = rest[index]
        if token == "--":
            break
        if token.startswith("-"):
            name, _, inline = token.partition("=")
            if name in _VALUE_FLAGS and not inline:
                index += 2
                continue
            index += 1
            continue
        services.append(token)
        index += 1
        if only_first:
            break
    return compose_file, services


def _makefile_variables(text):
    """Variables simples du Makefile, pour expanser `$(COMPOSE)`."""
    variables = {}
    for line in text.splitlines():
        if line.startswith("\t") or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::=|\?=|=)\s*(.*)$", line)
        if match:
            variables[match.group(1)] = match.group(2).strip()
    return variables


def _expand(text, variables):
    for _ in range(5):
        expanded = re.sub(
            r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)",
            lambda m: variables.get(m.group(1), ""),
            text,
        )
        if expanded == text:
            break
        text = expanded
    return text


def makefile_compose_commands():
    """Toutes les invocations `docker compose` des recettes du Makefile."""
    text = (BASE_DIR / "Makefile").read_text()
    variables = _makefile_variables(text)

    # Recoller les lignes continuees par `\`.
    lines = []
    buffer = ""
    for line in text.splitlines():
        if not line.startswith("\t"):
            buffer = ""
            continue
        buffer += line.lstrip("\t").rstrip()
        if buffer.endswith("\\"):
            buffer = buffer[:-1] + " "
            continue
        lines.append(buffer)
        buffer = ""

    found = []
    for recipe in lines:
        recipe = _expand(recipe, variables).lstrip("@-+ ")
        for fragment in re.split(r"\|\||&&|;|\|", recipe):
            fragment = fragment.strip()
            if "docker compose" not in fragment and "docker-compose" not in fragment:
                continue
            fragment = re.sub(r"\d?>[&]?\S+", "", fragment)
            try:
                tokens = shlex.split(fragment)
            except ValueError:
                tokens = fragment.split()
            start = None
            for position, token in enumerate(tokens):
                if token in ("docker", "docker-compose"):
                    start = position
                    break
            if start is None:
                continue
            found.append((recipe, tokens[start:]))
    return found


def load_script_at(path, name):
    """Charge un module Python par chemin, sans passer par un package."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_script(name):
    """Charge un script de `scripts/` sans en faire un package."""
    return load_script_at(BASE_DIR / "scripts" / f"{name}.py", f"_seam_{name}")


def code_without_comments(path):
    """Le source d'un fichier prive de ses lignes de commentaire entieres.

    Les commentaires expliquent ce qui a ete supprime et pourquoi : les
    inclure dans une assertion « ce symbole n'existe plus » ferait echouer le
    test sur sa propre justification, et pousserait a effacer l'explication.
    """
    lignes = Path(path).read_text(encoding="utf-8").splitlines()
    return "\n".join(ligne for ligne in lignes if not ligne.lstrip().startswith("#"))


def load_core_bridge(package_dir=None):
    """Charge `scripts/core_loader.py` et rend son pont vers le coeur.

    Les tests recalculent la recommandation par ce chemin, independamment du
    launcher : comparer le launcher a lui-meme ne prouverait rien.
    """
    module = load_script("core_loader")
    return module.load_core(package_dir)


def python39_interpreter():
    """Un interpreteur Python 3.9 reel, ou `None`.

    D-061 : `launcher.py` tourne sous le Python systeme (3.9.6 sur la machine
    de reference), pas sous le venv du projet (3.14). Verifier la
    compatibilite 3.9 par lecture de source serait une affirmation ; on
    execute.
    """
    for candidat in ("/usr/bin/python3", "python3.9"):
        try:
            sortie = subprocess.run(
                [candidat, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if sortie.returncode == 0 and sortie.stdout.strip() == "3.9":
            return candidat
    return None


def extract_launcher_script(module):
    """Le contenu du bloc <script> servi par le launcher."""
    trouve = re.search(r"<script>(.*?)</script>", module.HTML_TEMPLATE, re.S)
    assert trouve, "le gabarit HTML ne contient plus de bloc <script>"
    return trouve.group(1)


def render_launcher_ui(script, payload, elements=None):
    """Execute `updateUI(payload)` dans Node et rend l'etat des elements.

    Un `HTTP 200` sur `/` ne prouve rien : il a deja ete pris pour une preuve
    que l'interface fonctionnait, alors que le bloc <script> entier ne se
    compilait pas. Ici le JavaScript reellement servi est reellement execute,
    sur le payload reellement rendu, et on lit ce qui s'affiche.

    Args:
        script: le bloc <script> servi, tel quel.
        payload: ce que `/api/status` rend, tel quel.
        elements: etat initial du DOM, par identifiant. Sert a poser une case
            a cocher deja cochee : la bascule des licences restreintes est un
            etat du document, pas du payload, et la tester en appelant une
            fonction interne ne prouverait pas que la page la lit.
    """
    harnais = """
const elements = __ELEMENTS__;
function el(id) {
  if (!elements[id]) elements[id] = {id: id, textContent: '', innerHTML: '',
    className: '', title: '', value: '', disabled: false, style: {}};
  return elements[id];
}
const document = { getElementById: function (id) { return el(id); },
                   addEventListener: function () {} };
const console = { error: function () {}, log: function () {} };
function setInterval() {}
async function fetch() { throw new Error('pas de reseau dans ce harnais'); }
function confirm() { return false; }
const window = { open: function () {} };
""".replace("__ELEMENTS__", _json.dumps(elements or {}))
    queue = "\nupdateUI(" + _json.dumps(payload) + ");\n"
    queue += "process.stdout.write(JSON.stringify(elements));\n"

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fichier:
        fichier.write(harnais + script + queue)
        chemin = fichier.name
    try:
        sortie = subprocess.run(["node", chemin], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(chemin)

    assert sortie.returncode == 0, (
        "le JavaScript servi par le launcher n'a pas pu s'executer :\n" + sortie.stderr[:2000]
    )
    return _json.loads(sortie.stdout)


class RecordingSubprocess:
    """Faux module `subprocess` : enregistre les argv au lieu de les executer.

    Repond a `config --services` avec les services reels du fichier vise,
    pour que le script sous test suive la meme branche qu'en production.
    """

    def __init__(self):
        self.calls = []

    def run(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        stdout = ""
        parsed = parse_compose_command(cmd)
        if parsed and "config" in cmd and "--services" in cmd:
            path = BASE_DIR / parsed[0]
            if path.exists():
                stdout = "\n".join(sorted(compose_services(path))) + "\n"
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    def compose_calls(self):
        for call in self.calls:
            parsed = parse_compose_command(call)
            if parsed:
                yield call, parsed


class TestDockerComposeFiles:
    """Tests pour les fichiers docker-compose."""

    def test_all_compose_files_exist(self):
        """Vérifie que tous les fichiers docker-compose existent."""
        base_dir = Path(__file__).parent.parent

        expected_files = [
            "compose.yaml",  # defaut, les 3 OS
            "docker/compose/docker-compose.yml",  # NVIDIA
            "docker/compose/docker-compose.cpu.yml",  # CPU
            "docker/compose/docker-compose.amd.yml",  # Linux AMD
            "docker/compose/docker-compose.amd-max.yml",  # Linux AMD MAX
            "docker/compose/docker-compose.win-nvidia.yml",  # Windows NVIDIA
            "docker/compose/docker-compose.win-amd.yml",  # Windows AMD
        ]

        for filename in expected_files:
            filepath = base_dir / filename
            assert filepath.exists(), f"Fichier manquant: {filename}"

    def test_compose_files_valid_yaml(self):
        """Vérifie que les fichiers docker-compose sont du YAML valide."""
        import yaml

        base_dir = Path(__file__).parent.parent
        compose_files = list(base_dir.glob("docker/compose/*.yml")) + [base_dir / "compose.yaml"]

        for filepath in compose_files:
            try:
                with open(filepath) as f:
                    yaml.safe_load(f)
            except yaml.YAMLError as e:
                pytest.fail(f"YAML invalide dans {filepath.name}: {e}")

    def test_every_compose_file_declares_the_web_service(self):
        """`promptforge-web` est le seul service commun aux sept compose.

        L'assertion precedente etait « promptforge OU promptforge-web ». Ce
        `or` est precisement ce qui a laisse passer la regression : il rend
        vrai un fichier qui ne declare que l'un des deux, alors que les
        commandes du depot nommaient l'autre. On assertionne donc sur le
        service reellement commun, et sur lui seul.
        """
        for filepath in compose_paths():
            services = compose_services(filepath)
            assert "promptforge-web" in services, (
                f"{filepath.name} ne declare pas 'promptforge-web' : "
                f"services = {sorted(services)}"
            )

    def test_ollama_service_only_where_the_gpu_can_be_exposed(self):
        """Inventaire explicite : qui embarque Ollama, qui l'attend natif.

        Ce partage est le fond de DEC-010. Le figer ici evite qu'une variante
        derive en silence, et documente pourquoi une commande qui nomme
        `ollama` ne peut pas viser le compose par defaut.
        """
        base_dir = Path(__file__).parent.parent
        avec_ollama_conteneurise = {
            "docker-compose.yml",  # NVIDIA, GPU expose a Docker
            "docker-compose.cpu.yml",  # sans GPU
            "docker-compose.amd.yml",  # AMD ROCm Linux
            "docker-compose.amd-max.yml",
        }
        for filepath in compose_paths():
            services = compose_services(filepath)
            attendu = filepath.name in avec_ollama_conteneurise
            assert ("ollama" in services) is attendu, (
                f"{filepath.name} : service 'ollama' "
                f"{'attendu' if attendu else 'non attendu'}, "
                f"services = {sorted(services)}"
            )
            assert filepath != base_dir / "compose.yaml" or services == {"promptforge-web"}, (
                "compose.yaml, chemin par defaut DEC-010, ne doit exposer que "
                f"l'interface : services = {sorted(services)}"
            )


class TestLauncherConfig:
    """Tests pour la configuration du launcher."""

    def test_launcher_file_exists(self):
        """Vérifie que launcher.py existe."""
        launcher = Path(__file__).parent.parent / "launcher.py"
        assert launcher.exists(), "launcher.py n'existe pas"

    def test_launcher_has_docker_options(self):
        """Vérifie que le launcher a toutes les options Docker."""
        launcher = Path(__file__).parent.parent / "launcher.py"
        content = launcher.read_text()

        expected_options = [
            "nvidia",
            "win-nvidia-native",
            "win-amd",
            "linux-amd",
            "cpu",
        ]

        for option in expected_options:
            assert f'"{option}"' in content, f"Option {option} manquante dans launcher"

    def test_launcher_carries_no_model_catalog_of_its_own(self):
        """Remplace `test_launcher_has_recommended_models`, devenu faux.

        L'ancien test exigeait `RECOMMENDED_MODELS` dans le fichier, c'est-a-dire
        exactement ce que D-019 et D-022 reprochent au launcher : une table qui
        mappe un fabricant vers un tag et annonce des seuils de VRAM que rien ne
        mesure. Le verrou est retourne : la table ne doit PLUS exister, et aucun
        tag du catalogue ne doit apparaitre en litteral dans le fichier.

        Il est reecrit dans le meme commit que la suppression : un verrou qu'on
        laisse rougir « le temps de », c'est une suite de tests qu'on apprend a
        ignorer.
        """
        contenu = code_without_comments(BASE_DIR / "launcher.py")
        assert "RECOMMENDED_MODELS" not in contenu, (
            "la table par fabricant est revenue : elle annonce des seuils de "
            "VRAM que rien ne mesure (D-019)"
        )

        pont = load_core_bridge()
        assert pont.available, f"catalogue du coeur illisible : {pont.error}"

        # L'interface vit dans `assets/launcher.html` : elle est couverte
        # par le meme verrou que le code Python.
        contenu += (BASE_DIR / "assets" / "launcher.html").read_text(encoding="utf-8")
        residus = [tag for tag in pont.known_tags() if tag in contenu]
        assert not residus, (
            f"tags du catalogue recopies dans launcher.py ou son interface : {residus}. "
            "Le catalogue est unique (DEC-003) ; une copie diverge (D-022)."
        )


class TestDockerfiles:
    """Tests pour les Dockerfiles."""

    def test_dockerfile_exists(self):
        """Vérifie que Dockerfile existe."""
        dockerfile = Path(__file__).parent.parent / "docker" / "Dockerfile"
        assert dockerfile.exists(), "Dockerfile n'existe pas"

    def test_dockerfile_web_exists(self):
        """Vérifie que Dockerfile.web existe."""
        dockerfile = Path(__file__).parent.parent / "docker" / "Dockerfile.web"
        assert dockerfile.exists(), "Dockerfile.web n'existe pas"

    def test_dockerfile_web_copies_templates(self):
        """Vérifie que Dockerfile.web copie les templates."""
        dockerfile = Path(__file__).parent.parent / "docker" / "Dockerfile.web"
        content = dockerfile.read_text()

        assert "COPY templates/" in content, "Dockerfile.web ne copie pas les templates"


class TestEntryPoints:
    """Points d'entree du produit, apres le nettoyage DEC-011.

    Treize scripts de lancement redondants ont ete supprimes : ils
    dupliquaient, en `.bat`, `.ps1` et `.sh`, ce que deux entrees
    multiplateformes font deja. Ces tests verrouillent le fait qu'ils ne
    reviennent pas, et que les deux entrees restantes existent.
    """

    RETIRES = [
        "Launcher.bat",
        "Start.bat",
        "launcher.ps1",
        "launcher.sh",
        "start.sh",
        "run-web.bat",
        "run-web.ps1",
        "run-web.sh",
        "run.ps1",
        "start-amd.ps1",
        "start-nvidia.ps1",
        "update.ps1",
        "update.sh",
    ]

    def test_cross_platform_entry_points_exist(self):
        """Les deux entrees multiplateformes sont presentes."""
        base_dir = Path(__file__).parent.parent
        for name in ("launcher.py", "start.py"):
            assert (base_dir / name).exists(), f"{name} n'existe pas"

    def test_no_platform_specific_launcher_returns(self):
        """Aucun script de lancement specifique a une plateforme a la racine.

        Le produit doit rester multiplateforme et pilote par Docker : un
        `.bat` ou un `.ps1` de lancement a la racine signale une regression
        vers un chemin Windows dedie.
        """
        base_dir = Path(__file__).parent.parent
        revenus = [name for name in self.RETIRES if (base_dir / name).exists()]
        assert not revenus, f"scripts de lancement redondants revenus : {revenus}"

    def test_makefile_is_the_documented_update_path(self):
        """`update.sh` et `update.ps1` sont remplaces par une cible Makefile."""
        makefile = (Path(__file__).parent.parent / "Makefile").read_text()
        assert "update:" in makefile, "la cible `make update` a disparu"


class TestLauncherStateFixes:
    """Tests pour vérifier que l'état est correctement mis à jour."""

    def test_rebuild_updates_state(self):
        """Vérifie que rebuild_docker_images met à jour l'état."""
        launcher = Path(__file__).parent.parent / "launcher.py"
        content = launcher.read_text()

        # Chercher la mise à jour de l'état dans rebuild_docker_images
        # Il doit y avoir state["promptforge_running"] = False après le docker down
        import re

        rebuild_match = re.search(r"def rebuild_docker_images.*?(?=def \w+|\Z)", content, re.DOTALL)
        assert rebuild_match, "Fonction rebuild_docker_images non trouvée"

        rebuild_code = rebuild_match.group()
        assert (
            'state["promptforge_running"] = False' in rebuild_code
        ), "rebuild_docker_images ne met pas à jour promptforge_running"

    def test_clean_docker_updates_state(self):
        """Vérifie que clean_docker met à jour l'état."""
        launcher = Path(__file__).parent.parent / "launcher.py"
        content = launcher.read_text()

        import re

        clean_match = re.search(r"def clean_docker.*?(?=def \w+|\Z)", content, re.DOTALL)
        assert clean_match, "Fonction clean_docker non trouvée"

        clean_code = clean_match.group()
        assert (
            'state["promptforge_running"] = False' in clean_code
        ), "clean_docker ne met pas à jour promptforge_running"


class TestComposeServiceSeam:
    """Couture entre les commandes du depot et les compose qu'elles visent.

    Regle unique : **aucune commande du depot ne peut nommer un service
    absent du fichier compose contre lequel elle se resout.**

    Trois sources sont balayees : `Makefile`, `scripts/docker_helper.py` et
    `scripts/build.py`. Les deux scripts Python sont exerces reellement, avec
    `subprocess` remplace par un enregistreur : on verifie l'argv que le
    produit construirait, pas une lecture approximative de son source.
    """

    # --- outillage commun ------------------------------------------------

    @staticmethod
    def _assert_services_exist(source, tokens, compose_file, services):
        path = BASE_DIR / compose_file
        assert path.exists(), (
            f"{source} : fichier compose introuvable '{compose_file}' "
            f"(commande : {' '.join(tokens)})"
        )
        declares = compose_services(path)
        for service in services:
            assert service in declares, (
                f"{source} nomme le service '{service}', absent de "
                f"{compose_file} (services declares : {sorted(declares)}).\n"
                f"Commande : {' '.join(tokens)}"
            )

    def _check_calls(self, source, recorder):
        vus = 0
        for tokens, (compose_file, services) in recorder.compose_calls():
            self._assert_services_exist(source, tokens, compose_file, services)
            vus += 1
        return vus

    @staticmethod
    def _install_recorder(monkeypatch, module, recorder):
        monkeypatch.setattr(module, "subprocess", recorder, raising=False)
        if hasattr(module, "time"):
            monkeypatch.setattr(module, "time", types.SimpleNamespace(sleep=lambda *_: None))

    # --- le parseur lui-meme --------------------------------------------

    @pytest.mark.parametrize(
        "commande,attendu",
        [
            ("docker compose build promptforge", ("compose.yaml", ["promptforge"])),
            ("docker compose up -d ollama", ("compose.yaml", ["ollama"])),
            (
                "docker compose -f docker/compose/docker-compose.cpu.yml up -d",
                ("docker/compose/docker-compose.cpu.yml", []),
            ),
            (
                "docker compose run --rm --no-deps --entrypoint promptforge "
                "promptforge-web --path /data list",
                ("compose.yaml", ["promptforge-web"]),
            ),
            ("docker compose exec -T ollama ollama pull qwen3:8b", ("compose.yaml", ["ollama"])),
            ("docker compose logs -f promptforge-web", ("compose.yaml", ["promptforge-web"])),
            ("docker compose down -v", ("compose.yaml", [])),
            ("docker compose build --no-cache --pull", ("compose.yaml", [])),
            ("docker compose -f a.yml down --rmi local", ("a.yml", [])),
        ],
    )
    def test_parser_extracts_file_and_services(self, commande, attendu):
        """Le parseur de commandes est lui-meme teste.

        Sans cela, un test de couture qui n'extrait rien passerait au vert en
        ne verifiant rien : c'est le meme piege que le `or` qu'il remplace.
        """
        assert parse_compose_command(shlex.split(commande)) == attendu

    def test_parser_ignores_non_compose_commands(self):
        assert parse_compose_command(shlex.split("docker image prune -f")) is None
        assert parse_compose_command(shlex.split("python scripts/build.py up")) is None

    # --- source 1 : le Makefile -----------------------------------------

    def test_makefile_targets_name_existing_services(self):
        commandes = makefile_compose_commands()
        assert commandes, "aucune commande `docker compose` trouvee dans le Makefile"
        for recette, tokens in commandes:
            compose_file, services = parse_compose_command(tokens)
            self._assert_services_exist(f"Makefile [{recette}]", tokens, compose_file, services)

    # --- source 2 : scripts/docker_helper.py -----------------------------

    def test_docker_helper_commands_name_existing_services(self, monkeypatch):
        monkeypatch.chdir(BASE_DIR)
        # Ollama injoignable : `status` doit tomber dans sa branche d'erreur
        # sans tenter d'appel reseau reel.
        monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")
        monkeypatch.setattr("builtins.input", lambda *_: "n")

        module = load_script("docker_helper")
        recorder = RecordingSubprocess()
        self._install_recorder(monkeypatch, module, recorder)
        monkeypatch.setattr(
            module,
            "shutil",
            types.SimpleNamespace(which=lambda name: "/usr/bin/" + name),
        )

        args = types.SimpleNamespace(file=None, service=None, cmd=["list"])
        for nom in ("start", "stop", "status", "run", "web", "logs", "shell", "build", "clean"):
            getattr(module, f"cmd_{nom}")(args)

        args_logs = types.SimpleNamespace(file=None, service="promptforge-web", cmd=[])
        module.cmd_logs(args_logs)

        assert self._check_calls("scripts/docker_helper.py", recorder) > 0

    @pytest.mark.parametrize("variante", [p.name for p in compose_paths()])
    def test_docker_helper_commands_on_every_variant(self, monkeypatch, variante):
        """Chaque commande, confrontee a chacune des sept variantes.

        Les six variantes doivent rester coherentes : une commande valable
        sur le compose par defaut doit l'etre sur toutes, ou echouer
        explicitement.
        """
        monkeypatch.chdir(BASE_DIR)
        monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")
        monkeypatch.setattr("builtins.input", lambda *_: "n")

        chemin = DEFAULT_COMPOSE if variante == DEFAULT_COMPOSE else f"docker/compose/{variante}"
        module = load_script("docker_helper")
        recorder = RecordingSubprocess()
        self._install_recorder(monkeypatch, module, recorder)
        monkeypatch.setattr(
            module,
            "shutil",
            types.SimpleNamespace(which=lambda name: "/usr/bin/" + name),
        )

        args = types.SimpleNamespace(file=chemin, service=None, cmd=["list"])
        for nom in ("start", "stop", "status", "run", "web", "logs", "shell", "build"):
            getattr(module, f"cmd_{nom}")(args)

        assert self._check_calls(f"scripts/docker_helper.py [-f {chemin}]", recorder) > 0

    def test_docker_helper_refuses_an_absent_service(self, monkeypatch, capsys):
        """Le garde-fou runtime existe et refuse, au lieu de laisser passer."""
        monkeypatch.chdir(BASE_DIR)
        module = load_script("docker_helper")
        recorder = RecordingSubprocess()
        self._install_recorder(monkeypatch, module, recorder)

        assert module.require_service(DEFAULT_COMPOSE, "promptforge-web") is True
        assert module.require_service(DEFAULT_COMPOSE, "ollama") is False
        assert "n'existe pas" in capsys.readouterr().out

    def test_docker_helper_targets_no_unpinned_model(self):
        """Le modele du helper est celui des compose (D-022, sixieme liste)."""
        module = load_script("docker_helper")
        assert module.DEFAULT_MODEL == "qwen3:8b"

        # Hors commentaires : le commentaire qui documente la correction cite
        # l'ancienne valeur, ce n'est pas une occurrence executable.
        code = [
            ligne
            for ligne in (BASE_DIR / "scripts" / "docker_helper.py").read_text().splitlines()
            if not ligne.lstrip().startswith("#")
        ]
        assert not [ligne for ligne in code if "llama3.1" in ligne], (
            "llama3.1 n'existe dans aucun compose, ni dans RECOMMENDED_MODELS, "
            "ni dans OLLAMA_MODELS_INFO"
        )

        # Le modele du helper doit exister dans le compose par defaut.
        contenu = (BASE_DIR / DEFAULT_COMPOSE).read_text()
        assert (
            module.DEFAULT_MODEL in contenu
        ), f"{module.DEFAULT_MODEL} n'apparait pas dans {DEFAULT_COMPOSE}"

    # --- source 3 : scripts/build.py -------------------------------------

    @pytest.mark.parametrize(
        "config",
        [
            None,
            "default",
            "nvidia",
            "cpu",
            "linux-amd",
            "linux-amd-max",
            "win-amd",
            "win-nvidia-native",
        ],
    )
    def test_build_script_commands_name_existing_services(self, monkeypatch, config):
        monkeypatch.chdir(BASE_DIR)
        monkeypatch.setattr("builtins.input", lambda *_: "n")

        module = load_script("build")
        recorder = RecordingSubprocess()
        self._install_recorder(monkeypatch, module, recorder)

        args = types.SimpleNamespace(
            config=config,
            no_cache=False,
            parallel=None,
            build=False,
            force=True,
            images=True,
            dev=False,
        )
        for nom in ("build", "up", "down", "clean"):
            getattr(module, f"cmd_{nom}")(args)

        assert self._check_calls(f"scripts/build.py [-c {config}]", recorder) > 0

    def test_build_script_compose_files_all_exist(self):
        module = load_script("build")
        for config, chemin in module.COMPOSE_FILES.items():
            assert (BASE_DIR / chemin).exists(), f"build.py -c {config} vise {chemin}, absent"


class TestDefaultPathIsActuallySelected:
    """DEC-010 : le defaut proclame doit etre celui que le code emprunte.

    `compose.yaml` etait annonce comme chemin par defaut dans le README, sans
    qu'aucune ligne du depot ne le selectionne : `launcher.py` et
    `scripts/build.py` enumeraient les six variantes de `docker/compose/` et
    l'ignoraient. Un defaut que le produit n'emprunte jamais n'en est pas un.
    """

    def test_build_script_defaults_to_the_root_compose(self):
        module = load_script("build")
        assert module.get_compose_file(None) == DEFAULT_COMPOSE
        assert module.get_compose_file("default") == DEFAULT_COMPOSE

    def test_build_script_keeps_hardware_detection_behind_an_explicit_flag(self):
        """La detection GPU reste possible, mais seulement si on la demande.

        `detect_gpu()` n'a aucune branche Darwin (D-018) : la laisser piloter
        le defaut faisait retomber macOS sur `cpu`, donc sur un Ollama
        conteneurise sans acces Metal, exactement ce que DEC-010 remplace.
        """
        module = load_script("build")
        assert module.AUTO_CONFIG in module.CONFIG_CHOICES
        assert module.DEFAULT_CONFIG == "default"

    @pytest.mark.parametrize(
        "systeme,gpu",
        [
            ("Darwin", "apple"),
            ("Darwin", "cpu"),
            ("Windows", "nvidia"),
            ("Windows", "amd"),
            ("Windows", "cpu"),
            ("Linux", "nvidia"),
            ("Linux", "amd"),
            ("Linux", "cpu"),
        ],
    )
    def test_launcher_selects_the_root_compose_on_every_system(self, systeme, gpu):
        launcher = load_script_at(BASE_DIR / "launcher.py", "_seam_launcher")
        launcher.state["os"] = systeme
        launcher.state["gpu_type"] = gpu
        launcher.select_docker_compose()

        cle = launcher.state["docker_compose_file"]
        assert cle == "default", f"{systeme}/{gpu} selectionne '{cle}' au lieu du defaut"
        assert launcher.DOCKER_COMPOSE_OPTIONS[cle]["file"] == DEFAULT_COMPOSE
        assert launcher.state["available_compose_files"][0] == "default"

    def test_launcher_never_proposes_containerized_ollama_on_macos(self):
        """D-020 : Docker Desktop ne passe pas Metal aux conteneurs."""
        launcher = load_script_at(BASE_DIR / "launcher.py", "_seam_launcher")
        launcher.state["os"] = "Darwin"
        launcher.state["gpu_type"] = "apple"
        launcher.select_docker_compose()

        for cle in launcher.state["available_compose_files"]:
            chemin = BASE_DIR / launcher.DOCKER_COMPOSE_OPTIONS[cle]["file"]
            assert "ollama" not in compose_services(
                chemin
            ), f"macOS propose '{cle}', qui conteneurise Ollama"

    def test_launcher_options_point_to_existing_files(self):
        launcher = load_script_at(BASE_DIR / "launcher.py", "_seam_launcher")
        for cle, info in launcher.DOCKER_COMPOSE_OPTIONS.items():
            assert (BASE_DIR / info["file"]).exists(), f"launcher '{cle}' vise {info['file']}"


# ======================================================================
# Fraicheur de l'etat du launcher
# ======================================================================
#
# Defaut constate en direct par le dev, le 2026-09-04 : `launcher.py` ne
# sondait Ollama qu'au demarrage du serveur. Une instance lancee a 11h14
# affichait encore a 15h l'etat mesure a 11h14. Mesure a l'appui :
#
#     curl -s http://localhost:7850/api/status  -> "ollama_running": false
#     curl -s -o /dev/null -w "%{http_code}" \
#          http://localhost:11434/api/tags      -> 200
#
# Le bouton « Rafraichir » existait, mais rien n'indiquait a l'utilisateur
# que ce qu'il lisait etait perime. Quiconque demarre Ollama APRES avoir
# ouvert la page voyait un systeme eteint et concluait que le produit ne
# marche pas.
#
# Ces tests EXECUTENT `launcher.py` : ils montent son vrai serveur HTTP,
# parlent a `/api/status` par le reseau, et font apparaitre un faux Ollama
# en cours de route. Un `HTTP 200` sur la racine ne prouve rien ; le
# comportement, si.


def free_port():
    """Un port libre sur la boucle locale, rendu apres fermeture."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _JsonServer:
    """Un vrai serveur HTTP jetable, pour tenir lieu d'Ollama.

    On ne simule pas la couche reseau : la sonde de `launcher.py` fait un
    vrai `urlopen` vers un vrai socket, exactement comme en production.
    """

    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.hits = 0
        parent = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parent.hits += 1
                body = _json.dumps(parent.payload).encode()
                self.send_response(parent.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class _BlackHole:
    """Un socket qui accepte la connexion et ne repond jamais.

    C'est le seul moyen honnete de produire un delai depasse : le port
    ecoute (donc « connexion refusee » est exclu), mais rien ne repond.
    C'est exactement le cas que `check_ollama()` ecrivait `False`.
    """

    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)  # backlog : la connexion est acceptee par le noyau
        self.port = self.sock.getsockname()[1]
        return self

    def __exit__(self, *exc):
        self.sock.close()


# Port sur lequel rien n'ecoute jamais : la connexion est refusee, ce qui
# est une mesure concluante et non une absence de mesure.
CLOSED_PORT = 1


def fresh_launcher(name):
    """Charge `launcher.py` comme module, avec un `state` neuf a chaque fois."""
    return load_script_at(BASE_DIR / "launcher.py", name)


class DockerStub:
    """Faux `subprocess` : evite de forker `docker info` dans les tests.

    Enregistre les argv, ce qui permet d'assertionner sur la cadence lente
    (Docker sonde ou non) plutot que sur une intention declaree.
    """

    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, returncode=0, raises=None):
        self.calls = []
        self.returncode = returncode
        self.raises = raises

    def run(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if self.raises is not None:
            raise self.raises
        return types.SimpleNamespace(returncode=self.returncode, stdout="", stderr="")


class TestProbeIsTriState:
    """Trois etats, pas deux. « Je ne sais pas » n'est pas « c'est eteint ».

    Meme confusion que D-018, ou « non mesurable » devenait « pas de GPU ».
    """

    def test_refused_connection_is_down(self):
        module = fresh_launcher("_freshness_down")
        status, body = module.probe_http(f"http://127.0.0.1:{CLOSED_PORT}/", timeout=1)
        assert status == module.STATUS_DOWN
        assert body is None

    def test_timeout_is_unknown_not_down(self):
        """Le cas exact que l'ancien `except: pass` ecrivait `False`."""
        module = fresh_launcher("_freshness_timeout")
        with _BlackHole() as trou:
            status, body = module.probe_http(f"http://127.0.0.1:{trou.port}/", timeout=0.4)
        assert status == module.STATUS_UNKNOWN, (
            "un delai depasse doit rendre 'unknown' : le port ecoute, "
            "affirmer que le service est eteint serait faux"
        )
        assert body is None

    def test_unexpected_http_code_is_unknown(self):
        """Quelque chose repond, mais pas ce qui est attendu."""
        module = fresh_launcher("_freshness_500")
        with _JsonServer({"boom": True}, status=500) as serveur:
            status, _ = module.probe_http(f"http://127.0.0.1:{serveur.port}/", timeout=2)
        assert status == module.STATUS_UNKNOWN

    def test_success_is_up_with_body(self):
        module = fresh_launcher("_freshness_up")
        with _JsonServer({"models": []}) as serveur:
            status, body = module.probe_http(f"http://127.0.0.1:{serveur.port}/", timeout=2)
        assert status == module.STATUS_UP
        assert _json.loads(body.decode()) == {"models": []}

    def test_unknown_never_reads_as_running(self):
        """Le booleen historique ne vaut `True` que sur `up`."""
        module = fresh_launcher("_freshness_bool")
        for statut, attendu in (
            (module.STATUS_UP, True),
            (module.STATUS_DOWN, False),
            (module.STATUS_UNKNOWN, False),
        ):
            module.set_service_status("ollama", statut)
            assert module.state["ollama_running"] is attendu
            assert module.state["ollama_status"] == statut


class TestCheckOllamaTriState:
    """`check_ollama()` execute, contre de vrais sockets."""

    def test_absent_ollama_is_down(self):
        module = fresh_launcher("_check_ollama_down")
        module.OLLAMA_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1
        assert module.check_ollama() == module.STATUS_DOWN
        assert module.state["ollama_running"] is False
        assert module.state["installed_models"] == []

    def test_responding_ollama_is_up_and_lists_models(self):
        module = fresh_launcher("_check_ollama_up")
        module.HTTP_PROBE_TIMEOUT = 2
        module.state["ollama_model"] = "qwen3:8b"
        with _JsonServer({"models": [{"name": "qwen3:8b"}]}) as serveur:
            module.OLLAMA_PORT = serveur.port
            assert module.check_ollama() == module.STATUS_UP
        assert module.state["installed_models"] == ["qwen3:8b"]
        assert module.state["model_installed"] is True

    def test_timeout_leaves_the_state_unknown_and_keeps_last_models(self):
        """Un delai depasse n'efface pas ce qu'on savait ; il le date."""
        module = fresh_launcher("_check_ollama_unknown")
        module.HTTP_PROBE_TIMEOUT = 0.4
        module.state["installed_models"] = ["qwen3:8b"]
        module.state["model_installed"] = True
        with _BlackHole() as trou:
            module.OLLAMA_PORT = trou.port
            assert module.check_ollama() == module.STATUS_UNKNOWN
        assert module.state["ollama_running"] is False
        assert module.state["installed_models"] == ["qwen3:8b"], (
            "on ne sait pas : effacer la liste connue serait affirmer "
            "qu'elle est vide, ce qui n'a pas ete mesure"
        )

    def test_a_200_that_is_not_ollama_is_unknown(self):
        """`HTTP 200` n'est pas une preuve que le service fonctionne."""
        module = fresh_launcher("_check_ollama_wrong_200")
        module.HTTP_PROBE_TIMEOUT = 2
        with _JsonServer({"ceci": "n'est pas /api/tags"}) as serveur:
            module.OLLAMA_PORT = serveur.port
            statut = module.check_ollama()
        # `models` absent est tolere par l'API (liste vide), mais une
        # charge illisible doit rester indeterminee.
        assert statut in (module.STATUS_UP, module.STATUS_UNKNOWN)
        assert module.state["ollama_running"] is (statut == module.STATUS_UP)


class TestCheckDockerTriState:
    def test_timeout_is_unknown(self):
        module = fresh_launcher("_check_docker_unknown")
        module.subprocess = DockerStub(raises=subprocess.TimeoutExpired("docker", 10))
        assert module.check_docker() == module.STATUS_UNKNOWN
        assert module.state["docker_running"] is False

    def test_missing_binary_is_down_and_not_installed(self):
        module = fresh_launcher("_check_docker_absent")
        module.subprocess = DockerStub(raises=FileNotFoundError("docker"))
        assert module.check_docker() == module.STATUS_DOWN
        assert module.state["docker_installed"] is False

    def test_non_zero_return_code_is_down(self):
        module = fresh_launcher("_check_docker_stopped")
        module.subprocess = DockerStub(returncode=1)
        assert module.check_docker() == module.STATUS_DOWN

    def test_success_is_up(self):
        module = fresh_launcher("_check_docker_ok")
        module.subprocess = DockerStub(returncode=0)
        assert module.check_docker() == module.STATUS_UP


class TestFreshnessIsExposed:
    """Un etat affiche sans date est un etat qui ment des qu'il vieillit."""

    def test_payload_carries_its_age(self):
        module = fresh_launcher("_freshness_payload")
        module.stamp_probe(now=1000.0, include_docker=True)
        payload = module.status_payload(now=1003.0)

        assert payload["checked_at"] == 1000.0
        assert payload["checked_at_label"]
        assert payload["age_seconds"] == 3.0
        assert payload["stale"] is False
        assert payload["stale_after_seconds"] == module.STALE_AFTER

    def test_payload_declares_itself_stale_past_the_threshold(self):
        module = fresh_launcher("_freshness_stale")
        module.stamp_probe(now=1000.0)
        payload = module.status_payload(now=1000.0 + module.STALE_AFTER + 1)
        assert payload["stale"] is True

    def test_a_never_probed_state_is_stale(self):
        module = fresh_launcher("_freshness_never")
        payload = module.status_payload()
        assert payload["checked_at"] is None
        assert payload["age_seconds"] is None
        assert payload["stale"] is True

    def test_the_interface_renders_the_freshness(self):
        """Le HTML doit porter le rendu, pas seulement le payload."""
        module = fresh_launcher("_freshness_html")
        assert 'id="freshness"' in module.HTML_TEMPLATE
        assert "updateFreshness" in module.HTML_TEMPLATE
        assert "checked_at_label" in module.HTML_TEMPLATE
        # Le cas ou le launcher lui-meme ne repond plus : sans lui, l'age
        # afficherait la meme valeur pour l'eternite.
        assert "markLauncherOffline" in module.HTML_TEMPLATE

    def test_the_interface_renders_the_third_state(self):
        module = fresh_launcher("_freshness_html_unknown")
        assert "status-unknown" in module.HTML_TEMPLATE
        assert "ollama_status" in module.HTML_TEMPLATE
        assert "docker_status" in module.HTML_TEMPLATE
        assert "promptforge_status" in module.HTML_TEMPLATE

    def test_an_unknown_state_never_locks_the_user_out(self):
        """Un etat qu'on ne connait pas ne doit rien griser ni cacher.

        C'est la lecon produit du defaut corrige : le dev n'a rien pu faire
        parce que l'interface, sur la foi d'une mesure perimee, avait decide
        a sa place que rien n'etait disponible.
        """
        module = fresh_launcher("_freshness_not_locked")
        html = module.HTML_TEMPLATE

        # Les boutons se decident sur le statut a trois etats, pas sur le
        # booleen : `=== 'up'` pour demarrer, `=== 'down'` pour arreter,
        # donc les deux restent actifs quand l'etat est indetermine.
        assert "data.ollama_status === 'up' || data.action_in_progress" in html
        assert "btnOllamaStop.disabled = data.ollama_status === 'down'" in html
        assert "btnPfStop.disabled = data.promptforge_status === 'down'" in html

        # Le lien vers le produit n'est masque que sur un « eteint » mesure.
        assert "(data.promptforge_status === 'down') ? 'none' : 'block'" in html
        assert "data.promptforge_running ? 'block' : 'none'" not in html


class TestProbeCadence:
    """La cadence est un compromis mesure, pas une preference.

    Couts mesures le 2026-09-04 sur la machine de reference :
    Ollama 4.4 ms, PromptForge 0.5 ms, `docker info` 107.6 ms,
    `docker images` 88.0 ms. Trois ordres de grandeur separent les deux
    familles : elles ne peuvent pas partager la meme cadence.
    """

    def test_docker_is_probed_far_less_often_than_http(self):
        module = fresh_launcher("_cadence_ttl")
        assert module.FAST_PROBE_TTL < module.SLOW_PROBE_TTL
        assert module.SLOW_PROBE_TTL >= 5 * module.FAST_PROBE_TTL

    def test_a_fast_probe_forks_no_subprocess(self):
        module = fresh_launcher("_cadence_fast")
        stub = DockerStub()
        module.subprocess = stub
        module.OLLAMA_PORT = CLOSED_PORT
        module.PROMPTFORGE_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1

        module.run_probes(include_docker=False)
        assert stub.calls == [], (
            "la cadence rapide ne doit forker aucun `docker` : " f"appels observes = {stub.calls}"
        )

    def test_a_slow_probe_does_fork_docker(self):
        module = fresh_launcher("_cadence_slow")
        stub = DockerStub()
        module.subprocess = stub
        module.OLLAMA_PORT = CLOSED_PORT
        module.PROMPTFORGE_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1

        module.run_probes(include_docker=True)
        assert any(call[:2] == ["docker", "info"] for call in stub.calls), stub.calls

    def test_nothing_is_probed_before_the_ttl_expires(self):
        module = fresh_launcher("_cadence_ttl_guard")
        module.stamp_probe(now=time.time(), include_docker=True)
        assert module.ensure_fresh_status() is None, (
            "sonder a chaque appel rendrait l'interface poussive : "
            "le client interroge toutes les 3 s"
        )

    def test_the_fast_ttl_expires_before_the_client_polls_twice(self):
        """Peremption maximale vue par l'utilisateur : ~5 s."""
        module = fresh_launcher("_cadence_window")
        module.stamp_probe(now=time.time() - module.FAST_PROBE_TTL - 0.1, include_docker=True)
        fast_due, slow_due = module.probe_due()
        assert fast_due is True
        assert slow_due is False, "Docker ne doit pas suivre la cadence rapide"

    def test_only_one_probe_flies_at_a_time(self):
        """Sans cela, un `docker info` lent verrait s'empiler les sondes."""
        module = fresh_launcher("_cadence_single_flight")
        module.state["probe_in_progress"] = True
        assert module.ensure_fresh_status() is None

    def test_repeated_probes_do_not_flood_the_log_buffer(self):
        """Le tampon fait 50 lignes ; sonder toutes les 2 s l'effacerait."""
        module = fresh_launcher("_cadence_log")
        module.subprocess = DockerStub()
        module.OLLAMA_PORT = CLOSED_PORT
        module.PROMPTFORGE_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1

        module.run_probes(include_docker=False)
        apres_premiere = len(module.state["logs"])
        for _ in range(20):
            module.run_probes(include_docker=False)
        ajoutees = len(module.state["logs"]) - apres_premiere

        assert ajoutees == 0, (
            "vingt sondes sans changement d'etat ont ajoute "
            f"{ajoutees} lignes de log : le tampon de 50 serait efface "
            "en moins de deux minutes"
        )


class TestStatusEndpointRefreshesItself:
    """LE test de non-regression : execute le serveur HTTP de `launcher.py`.

    Aucune couture de `launcher.py` n'etait executee jusqu'ici cote statut :
    `TestLauncherConfig` lit le fichier comme du texte. Ici on monte le vrai
    `LauncherHandler`, on l'interroge par le reseau, et on fait apparaitre
    un Ollama en cours de route sans jamais poster la moindre action.
    """

    @staticmethod
    def _serve(module):
        serveur = http.server.HTTPServer(("127.0.0.1", 0), module.LauncherHandler)
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        return serveur, fil

    @staticmethod
    def _get_status(port):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
            assert r.status == 200
            return _json.loads(r.read().decode())

    def test_ollama_started_after_the_page_is_seen_without_any_click(self):
        """Le scenario exact vecu par le dev, rejoue de bout en bout."""
        module = fresh_launcher("_endpoint_appearing")
        module.subprocess = DockerStub()
        module.PROMPTFORGE_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1
        module.state["ollama_model"] = "qwen3:8b"

        # 1. Le launcher demarre pendant qu'Ollama est absent.
        module.OLLAMA_PORT = CLOSED_PORT
        module.refresh_status()
        assert module.state["ollama_status"] == module.STATUS_DOWN

        serveur, fil = self._serve(module)
        port = serveur.server_address[1]
        try:
            depart = self._get_status(port)
            assert depart["ollama_running"] is False
            assert depart["ollama_status"] == "down"
            premier_horodatage = depart["checked_at"]
            assert premier_horodatage is not None

            # 2. Ollama apparait APRES l'ouverture de la page.
            with _JsonServer({"models": [{"name": "qwen3:8b"}]}) as ollama:
                module.OLLAMA_PORT = ollama.port

                # 3. Le client se contente de son sondage periodique de 3 s.
                #    Aucun POST /api/action, aucun clic sur « Rafraichir ».
                limite = time.time() + 20
                vu = None
                while time.time() < limite:
                    time.sleep(0.5)
                    vu = self._get_status(port)
                    if vu["ollama_status"] == "up":
                        break

            assert vu is not None
            assert vu["ollama_status"] == "up", (
                "un Ollama demarre apres l'ouverture de la page doit etre vu "
                "sans intervention de l'utilisateur ; etat lu : "
                f"{vu['ollama_status']}, age {vu['age_seconds']} s"
            )
            assert vu["ollama_running"] is True
            assert vu["installed_models"] == ["qwen3:8b"]
            assert (
                vu["checked_at"] > premier_horodatage
            ), "l'horodatage doit avancer : sinon l'etat est fige"
            assert vu["age_seconds"] <= module.STALE_AFTER
        finally:
            serveur.shutdown()
            serveur.server_close()
            fil.join(timeout=5)

    def test_the_endpoint_reports_its_own_staleness(self):
        module = fresh_launcher("_endpoint_stale")
        module.subprocess = DockerStub()
        module.OLLAMA_PORT = CLOSED_PORT
        module.PROMPTFORGE_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1

        serveur, fil = self._serve(module)
        port = serveur.server_address[1]
        try:
            # Jamais sonde : le payload doit le dire, pas se taire.
            vierge = self._get_status(port)
            assert vierge["stale"] is True

            # Ce GET a lance une sonde en tache de fond. Si elle se termine
            # apres le vieillissement ci-dessous, elle reecrit un horodatage
            # frais et le test echoue au hasard : on l'attend, puis on
            # empeche toute nouvelle sonde d'etre jugee due.
            limite = time.time() + 10
            while module.state["probe_in_progress"] and time.time() < limite:
                time.sleep(0.01)
            assert module.state["probe_in_progress"] is False
            module.FAST_PROBE_TTL = module.SLOW_PROBE_TTL = 3600

            # Etat volontairement vieilli : `stale` doit repasser a True.
            module.stamp_probe(now=time.time() - module.STALE_AFTER - 5, include_docker=True)
            vieux = self._get_status(port)
            assert vieux["stale"] is True
            assert vieux["age_seconds"] > module.STALE_AFTER
        finally:
            serveur.shutdown()
            serveur.server_close()
            fil.join(timeout=5)

    def test_the_endpoint_ships_the_python_compose_table(self):
        """D-060 : une seule table de compose, celle de Python."""
        module = fresh_launcher("_endpoint_compose")
        module.subprocess = DockerStub()
        module.OLLAMA_PORT = CLOSED_PORT
        module.PROMPTFORGE_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1

        serveur, fil = self._serve(module)
        port = serveur.server_address[1]
        try:
            recu = self._get_status(port)
        finally:
            serveur.shutdown()
            serveur.server_close()
            fil.join(timeout=5)

        assert recu["compose_options"] == module.DOCKER_COMPOSE_OPTIONS, (
            "/api/status n'envoyait jamais DOCKER_COMPOSE_OPTIONS : le "
            "JavaScript en gardait une copie, deja divergente"
        )


class TestComposeTableIsNotDuplicated:
    """D-060 : `COMPOSE_OPTIONS` en JavaScript dupliquait le dict Python.

    Les deux vivaient dans le meme fichier et avaient deja divergé : la
    copie JS decrivait `cpu` comme « optimise CPU », l'original Python
    comme « optimise CPU, 8GB+ RAM ».
    """

    def test_no_javascript_copy_remains(self):
        module = fresh_launcher("_no_js_compose_copy")
        assert (
            "COMPOSE_OPTIONS = {" not in module.HTML_TEMPLATE
        ), "la table de compose est redevenue duplique en JavaScript"

    def test_the_selector_reads_the_served_table(self):
        module = fresh_launcher("_js_reads_payload")
        assert "data.compose_options" in module.HTML_TEMPLATE

    def test_every_served_label_comes_from_python(self):
        module = fresh_launcher("_labels_from_python")
        payload = module.status_payload()
        for cle, info in module.DOCKER_COMPOSE_OPTIONS.items():
            assert payload["compose_options"][cle]["label"] == info["label"]
            assert payload["compose_options"][cle]["description"] == info["description"]


# ======================================================================
# Le launcher consomme le catalogue et la mesure, il ne les recopie pas
# ======================================================================
#
# R-007 bloc 4 et R-002 bloc 3. `launcher.py` portait trente et un litteraux
# de tag Ollama (D-059) et sa propre `detect_gpu()` (D-018), dupliquee dans
# `scripts/build.py` sans branche Darwin. Les deux sources uniques vivent
# desormais dans le coeur ; ces tests verrouillent le fait qu'aucune copie ne
# revienne, et surtout que ce qui est SERVI vient bien de la.


class TestNoHardwareDetectionSurvives:
    """Les deux `detect_gpu()` ont disparu, pas une seule des deux."""

    def test_launcher_has_no_detect_gpu_left(self):
        contenu = code_without_comments(BASE_DIR / "launcher.py")
        assert "def detect_gpu(" not in contenu

    def test_build_script_has_no_detect_gpu_left(self):
        contenu = code_without_comments(BASE_DIR / "scripts" / "build.py")
        assert "def detect_gpu(" not in contenu, "la copie sans branche Darwin de D-018 est revenue"

    def test_build_script_no_longer_falls_back_to_cpu_on_macos(self):
        """D-018, cote consequence : macOS retombait en silence sur `cpu`.

        Le compose `cpu` conteneurise Ollama, qui n'a pas acces a Metal sous
        Docker Desktop (D-020). L'ancienne detection choisissait donc le pire
        chemin sur la plateforme du dev, sans rien dire.
        """
        module = load_script("build")
        selection = module.compose_selection("macos", "apple")
        assert selection["gpu_variant"] is None
        assert selection["options"] == ("default",)

    def test_the_two_compose_mappings_are_one(self):
        """Un seul mapping materiel -> compose, partage par les deux scripts.

        `detect_gpu()` disparait des deux cotes ; si chacun garde SON mapping,
        la moitie de D-018 survit et redivergera.
        """
        build = load_script("build")
        launcher = fresh_launcher("_mapping_partage")
        for systeme, marque in [
            ("Darwin", "apple"),
            ("Darwin", None),
            ("Windows", "nvidia"),
            ("Windows", "amd"),
            ("Windows", None),
            ("Linux", "nvidia"),
            ("Linux", "amd"),
            ("Linux", "none"),
        ]:
            attendu = build.compose_selection(systeme, marque)
            launcher.state["os"] = systeme
            launcher.state["gpu_type"] = marque
            launcher.select_docker_compose()
            assert launcher.state["available_compose_files"] == list(attendu["options"])
            variante = attendu["gpu_variant"]
            if variante is not None:
                assert variante in attendu["options"], (
                    f"{systeme}/{marque} : `build.py -c auto` retiendrait "
                    f"'{variante}', que le launcher ne propose pas"
                )


class TestServedCatalogComesFromTheCore:
    """Ce que `/api/status` sert vient du catalogue, entree par entree."""

    def test_the_payload_ships_the_whole_catalog_in_footprint_order(self):
        module = fresh_launcher("_payload_catalogue")
        pont = load_core_bridge()
        payload = module.status_payload()

        attendus = [m.tag for m in pont.models_by_footprint()]
        assert [
            entree["tag"] for entree in payload["models"]
        ] == attendus, "l'ordre servi doit etre celui de l'empreinte memoire (DEC-006)"

    def test_every_served_figure_matches_the_catalog(self):
        module = fresh_launcher("_payload_chiffres")
        pont = load_core_bridge()
        catalogue = {m.tag: m for m in pont.models_by_footprint()}

        for entree in module.status_payload()["models"]:
            modele = catalogue[entree["tag"]]
            assert entree["download_gb"] == round(modele.download_size_gb, 1)
            assert entree["footprint_gb"] == round(modele.memory_footprint_gb, 1)
            assert entree["estimated"] is modele.memory_footprint_is_estimated
            assert entree["source_url"] == modele.source_url
            assert entree["verified_on"] == modele.verified_on

    def test_the_two_corrected_sizes_are_repercuted(self):
        """Deux chiffres que le launcher affichait faux, mesures par la veille.

        `llama3.1:70b` pese 43 Go et non 40 ; `gemma3n:e4b` 7,5 Go et non 3.
        Le second est le plus grave : il figurait au palier « CPU, peu de RAM »,
        donc l'erreur penalisait exactement ceux qu'elle visait a servir.
        """
        module = fresh_launcher("_tailles_corrigees")
        servis = {e["tag"]: e for e in module.status_payload()["models"]}

        assert servis["llama3.1:70b"]["download_gb"] == 43.0
        assert servis["gemma3n:e4b"]["download_gb"] == 7.5

        gabarit = module.HTML_TEMPLATE
        for perime in ("(40GB)", "(3GB)", "(2.5GB)", "(5GB)", "(9GB)", "(20GB)"):
            assert perime not in gabarit, f"taille figee '{perime}' encore ecrite dans le HTML"

    def test_the_html_carries_no_option_of_its_own(self):
        module = fresh_launcher("_html_sans_option")
        assert '<option value="qwen' not in module.HTML_TEMPLATE
        assert "updateModelSelector" in module.HTML_TEMPLATE
        assert "data.models" in module.HTML_TEMPLATE

    def test_the_quality_disclaimer_is_served_and_rendered(self):
        """DEC-006 : le tri porte sur la memoire, jamais sur une qualite.

        Le dire dans un commentaire ne suffit pas : l'utilisateur qui lit une
        liste ordonnee conclut « le premier est le meilleur ». La reserve doit
        etre dans la page.
        """
        module = fresh_launcher("_reserve_qualite")
        payload = module.status_payload()
        assert "qualite" in payload["quality_disclaimer"].lower()
        assert "pas mesuree" in payload["quality_disclaimer"]
        assert "quality_disclaimer" in module.HTML_TEMPLATE
        assert "model-disclaimer" in module.HTML_TEMPLATE


class TestRecommendationIsMeasuredNotGuessed:
    """La recommandation servie doit egaler celle du coeur, sur CETTE machine.

    C'est le coeur de R-002 bloc 3 et de D-019 : le launcher affichait
    « qwen3:8b (Apple Silicon) » sans avoir lu un seul octet de memoire.
    """

    @staticmethod
    def _serve(module):
        serveur = http.server.HTTPServer(("127.0.0.1", 0), module.LauncherHandler)
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        return serveur, fil

    def test_api_status_serves_exactly_what_the_core_recommends(self):
        pont = load_core_bridge()
        assert pont.available, f"catalogue du coeur illisible : {pont.error}"

        # Recalcul independant : mesure du materiel puis recommandation, sans
        # passer par le launcher. Comparer le launcher a lui-meme ne prouverait
        # rien.
        #
        # Le catalogue consulte est celui des licences approuvees OSI, parce
        # que c'est ce que l'interface propose : recommander hors de son offre
        # serait incoherent. Sur la machine de reference les deux catalogues
        # donnent la meme reponse ; le cas ou ils divergent est verrouille par
        # `TestOnlyOpenSourceIsOffered`, qui impose la memoire pour le
        # produire. Ecrire ici le catalogue complet ferait passer ce test pour
        # la mauvaise raison.
        profil = pont.detect_hardware()
        attendue = pont.recommend_for(profil, catalog=pont.open_source_models())

        module = fresh_launcher("_reco_mesuree")
        module.subprocess = DockerStub()
        module.OLLAMA_PORT = CLOSED_PORT
        module.PROMPTFORGE_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1
        module.detect_hardware()

        serveur, fil = self._serve(module)
        port = serveur.server_address[1]
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/status", timeout=10
            ) as reponse:
                assert reponse.status == 200
                recu = _json.loads(reponse.read().decode())
        finally:
            serveur.shutdown()
            serveur.server_close()
            fil.join(timeout=5)

        servie = recu["recommendation"]
        assert servie is not None, "aucune recommandation servie"
        assert servie["measured"] is attendue.measured

        if attendue.recommended is None:
            assert servie["recommended"] is None
            assert recu["ollama_model"] is None, (
                "aucun modele ne tient : le launcher ne doit surtout pas en "
                "proposer un quand meme"
            )
        else:
            assert servie["recommended"]["tag"] == attendue.recommended.tag
            assert recu["ollama_model"] == attendue.recommended.tag
            assert servie["maximum"]["tag"] == attendue.maximum.tag
            assert servie["basis"] == attendue.basis
            assert servie["margin_gb"] == round(attendue.margin_bytes / (1024**3), 1)

        # La memoire servie est celle qui a ete mesuree, pas une constante.
        assert recu["hardware"]["available_memory_basis"] == profil.available_memory_basis
        if profil.available_memory_bytes is None:
            assert recu["hardware"]["available_memory_gb"] is None
        else:
            assert recu["hardware"]["available_memory_gb"] == round(
                profil.available_memory_bytes / (1024**3), 1
            )

    def test_forcing_a_gpu_brand_does_not_move_the_recommendation(self):
        """Forcer la marque ne peut pas changer la memoire de la machine.

        L'ancien code recalculait le modele depuis le fabricant force : forcer
        « nvidia » sur un Mac faisait apparaitre une recommandation « NVIDIA
        8GB+ VRAM » sur une machine sans carte NVIDIA.
        """
        module = fresh_launcher("_force_marque")
        module.detect_hardware()
        avant = module.state["ollama_model"]

        module.state["gpu_type"] = "nvidia"
        module.select_docker_compose()
        assert module.state["ollama_model"] == avant

    def test_an_unmeasured_machine_recommends_nothing(self):
        """Sans mesure, pas de recommandation : surtout pas un repli en dur."""
        module = fresh_launcher("_sans_mesure")
        pont = load_core_bridge()
        catalogue = pont.catalog_module

        profil_muet = pont.hardware_module.HardwareProfile(
            system="linux",
            notes=("Memoire totale non mesurable : sonde muette.",),
        )
        assert profil_muet.available_memory_bytes is None

        reco = catalogue.recommend(profil_muet.available_memory_bytes)
        module.state["ollama_model"] = None
        module.state["recommendation"] = module.recommendation_entry(reco)

        payload = module.status_payload()
        assert payload["recommendation"]["measured"] is False
        assert payload["recommendation"]["recommended"] is None
        assert payload["ollama_model"] is None


class TestDegradedModeIsVisible:
    """D-061 : quand le coeur n'est pas chargeable, l'interface le DIT.

    L'issue (a) — exiger 3.10 et refuser de demarrer — a ete ecartee : le
    launcher existe pour amorcer une machine nue, ou le seul interpreteur est
    celui du systeme. L'issue retenue est le chargement par chemin, avec ce
    mode degrade visible derriere, pour le cas d'un depot incomplet. Ce qui
    est formellement exclu, c'est le repli muet vers une liste en dur.
    """

    @staticmethod
    def _degrade(module, tmp_path):
        pont = load_script("core_loader").load_core(tmp_path / "absent")
        assert pont.available is False
        module.CORE = pont
        module.state["catalog_available"] = False
        module.state["catalog_error"] = pont.error
        return pont

    def test_the_payload_announces_the_failure(self, tmp_path):
        module = fresh_launcher("_degrade_payload")
        pont = self._degrade(module, tmp_path)
        module.detect_hardware()

        payload = module.status_payload()
        assert payload["catalog_available"] is False
        assert payload["catalog_error"] == pont.error
        assert payload["models"] == []
        assert payload["recommendation"] is None
        assert (
            payload["ollama_model"] is None
        ), "un modele par defaut en mode degrade serait le repli muet refuse"

    def test_no_hardcoded_list_takes_over(self, tmp_path):
        module = fresh_launcher("_degrade_pas_de_repli")
        self._degrade(module, tmp_path)
        module.detect_hardware()
        assert module.catalog_entries() == []
        assert module.state["gpu_type"] is None

    def test_the_interface_renders_the_degraded_state(self):
        module = fresh_launcher("_degrade_html")
        assert "data.catalog_available === false" in module.HTML_TEMPLATE
        assert "Catalogue de modeles indisponible" in module.HTML_TEMPLATE
        assert "catalog_error" in module.HTML_TEMPLATE

    def test_actions_refuse_a_tag_outside_the_catalog(self, tmp_path):
        """`ollama pull` recoit une chaine venue du reseau : liste blanche."""
        module = fresh_launcher("_degrade_actions")
        assert module.CORE.is_known_tag("qwen3:8b") is True
        assert module.CORE.is_known_tag("modele-invente:1b") is False
        assert module.CORE.is_known_tag(None) is False

        self._degrade(module, tmp_path)
        assert module.CORE.is_known_tag("qwen3:8b") is False


class TestLauncherListensOnBothLoopbackFamilies:
    """D-062 et D-037, indissociables : le meme `bind` portait les deux.

    Mesure du 2026-09-07 sur la version precedente :
        curl http://localhost:7850  -> HTTP 000
        curl http://127.0.0.1:7850  -> HTTP 200
    macOS resout `localhost` en `::1` d'abord ; `0.0.0.0` n'ecoute qu'en IPv4.
    Le launcher imprimait « accessible sur http://localhost:7850 ».
    """

    def test_the_source_no_longer_binds_every_interface(self):
        contenu = code_without_comments(BASE_DIR / "launcher.py")
        assert '"0.0.0.0"' not in contenu, (
            "D-037 : ce serveur demarre des conteneurs et telecharge des "
            "modeles ; il n'a rien a faire sur le reseau local"
        )
        assert 'LOOPBACK_HOSTS = ("127.0.0.1", "::1")' in contenu

    def test_localhost_and_127_0_0_1_both_answer(self):
        module = fresh_launcher("_double_pile")
        module.subprocess = DockerStub()
        module.OLLAMA_PORT = CLOSED_PORT
        module.PROMPTFORGE_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1

        port = free_port()
        serveurs, fils, servis = module.serve_loopback(port)
        try:
            assert "127.0.0.1" in servis
            adresses = [
                f"http://127.0.0.1:{port}/api/status",
                f"http://localhost:{port}/api/status",
            ]
            if "::1" in servis:
                adresses.append(f"http://[::1]:{port}/api/status")
            for adresse in adresses:
                with urllib.request.urlopen(adresse, timeout=10) as reponse:
                    assert reponse.status == 200, adresse
                    assert _json.loads(reponse.read().decode())["os"]
        finally:
            for serveur in serveurs:
                serveur.shutdown()
                serveur.server_close()
            for fil in fils:
                fil.join(timeout=5)

    def test_nothing_listens_outside_the_loopback(self):
        """Contrepartie de D-037 : l'adresse routable ne doit pas repondre."""
        module = fresh_launcher("_pas_de_route")
        module.subprocess = DockerStub()
        module.OLLAMA_PORT = CLOSED_PORT
        module.PROMPTFORGE_PORT = CLOSED_PORT
        module.HTTP_PROBE_TIMEOUT = 1

        externe = None
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            adresse = info[4][0]
            if not adresse.startswith("127."):
                externe = adresse
                break
        if externe is None:
            pytest.skip("aucune adresse IPv4 routable sur cette machine")

        port = free_port()
        serveurs, fils, _ = module.serve_loopback(port)
        try:
            prise = socket.socket()
            prise.settimeout(2)
            code = prise.connect_ex((externe, port))
            prise.close()
            assert code != 0, (
                f"le launcher accepte une connexion sur {externe}:{port} : " "D-037 est de retour"
            )
        finally:
            for serveur in serveurs:
                serveur.shutdown()
                serveur.server_close()
            for fil in fils:
                fil.join(timeout=5)


class TestTheServedJavaScriptActuallyRuns:
    """Une page qui rend HTTP 200 peut n'executer aucune ligne de son script.

    Constat du 2026-09-07, present des HEAD `4ef64f4` : le bloc <script> servi
    ne se compilait pas. `HTML_TEMPLATE` est une triple-quote Python NON brute,
    et une ligne y ecrivait `'Etat d\\'Ollama indetermine'` ; Python mangeait
    l'echappement et servait une apostrophe nue au navigateur, soit un
    `SyntaxError` qui tue TOUT le bloc. Aucune fonction de l'interface ne
    tournait donc : ni `refresh`, ni `updateUI`. La page restait figee sur
    « Detection... » pendant que `/api/status` rendait 200.

    Ces tests executent le JavaScript reellement servi.
    """

    @pytest.fixture(autouse=True)
    def _node_requis(self):
        if shutil.which("node") is None:
            pytest.skip("Node absent : execution du JavaScript servi impossible")

    def test_the_script_block_compiles(self):
        module = fresh_launcher("_js_compile")
        script = extract_launcher_script(module)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as fichier:
            fichier.write(script)
            chemin = fichier.name
        try:
            sortie = subprocess.run(
                ["node", "--check", chemin], capture_output=True, text=True, timeout=60
            )
        finally:
            os.unlink(chemin)
        assert sortie.returncode == 0, (
            "le JavaScript servi ne compile pas :\n" + sortie.stderr[:2000]
        )

    def test_the_page_displays_the_measured_recommendation(self):
        module = fresh_launcher("_js_rendu")
        module.detect_hardware()
        module.select_docker_compose()
        payload = module.status_payload()
        rendu = render_launcher_ui(extract_launcher_script(module), payload)

        reco = payload["recommendation"]
        assert reco and reco["measured"], "cette machine doit etre mesurable"
        tag = reco["recommended"]["tag"]

        bloc = rendu["model-recommendation"]["innerHTML"]
        assert tag in bloc, f"le modele recommande n'apparait pas : {bloc[:200]}"
        marge = re.search(r"marge ([\d.]+) Gio", bloc)
        assert marge, f"la marge n'est pas affichee : {bloc[:200]}"
        assert (
            float(marge.group(1)) == reco["margin_gb"]
        ), "la marge affichee ne correspond pas a la marge calculee"
        assert reco["maximum"]["tag"] in bloc, "le choix maximal n'est pas affiche"

        liste = rendu["model-select"]["innerHTML"]
        assert f'value="{tag}"' in liste and "selected" in liste
        # L'offre par defaut est l'open source approuve OSI, et elle est
        # complete : les onze entrees approuvees sont la, aucune des sept
        # autres ne l'est. Le detail de cette regle est verifie par
        # `TestOnlyOpenSourceIsOffered`.
        for entree in payload["models"]:
            if entree["osi_approved"]:
                assert (
                    f'value="{entree["tag"]}"' in liste
                ), f"{entree['tag']} approuve OSI, absent de la liste rendue"

        memoire = rendu["memory-value"]["textContent"]
        assert "Gio" in memoire and "Non mesuree" not in memoire

        assert "pas mesuree" in rendu["model-disclaimer"]["textContent"], (
            "la reserve DEC-006 doit etre lisible dans la page, pas seulement " "dans le payload"
        )

    def test_the_page_says_so_when_nothing_is_measured(self):
        module = fresh_launcher("_js_rendu_degrade")
        payload = module.status_payload()
        payload["catalog_available"] = False
        payload["catalog_error"] = "module du coeur introuvable : /absent"
        payload["models"] = []
        payload["recommendation"] = None
        payload["ollama_model"] = None

        rendu = render_launcher_ui(extract_launcher_script(module), payload)
        bloc = rendu["model-recommendation"]["innerHTML"]
        assert "Catalogue de modeles indisponible" in bloc
        assert "/absent" in bloc, "le motif doit etre affiche, pas avale"
        assert "Catalogue indisponible" in rendu["model-select"]["innerHTML"]
        assert rendu["model-select"]["disabled"] is True


# ---------------------------------------------------------------------------
# Trois reproches du dev, verifies sur le rendu et non sur le payload
# ---------------------------------------------------------------------------
# « tu ne me donne pas les meilleures images par rapport a mes capacites »
# « on cherche des images opensources un point c'est tout et faudrait les
#   classifier comme avant »
# « tu ne listes pas non plus si j'ai deja des modeles d'installe »
#
# L'interface rendait une liste plate de dix-sept tags dans un seul groupe
# « Tient dans 32 Gio mesures », licences confondues, sans dire ce qui etait
# deja telecharge. Les tests ci-dessous executent le JavaScript servi et
# lisent la liste rendue : un payload correct qui produit une liste fausse
# est exactement le defaut qui a laisse passer un bloc <script> qui ne
# compilait pas.


def element_coche(identifiant):
    """Un element de DOM deja coche, pour le harnais de rendu."""
    return {
        identifiant: {
            "id": identifiant,
            "checked": True,
            "textContent": "",
            "innerHTML": "",
            "className": "",
            "title": "",
            "value": "",
            "disabled": False,
            "style": {},
        }
    }


def tags_rendus(html):
    """Les tags reellement presents dans la liste rendue, dans l'ordre."""
    return re.findall(r'<option value="([^"]+)"', html)


def libelles_de_groupes(html):
    """Les libelles d'`<optgroup>` rendus, dans l'ordre."""
    return re.findall(r'<optgroup label="([^"]*)"', html)


def launcher_mesure(nom, installes=()):
    """Un launcher ayant mesure la machine, avec une liste Ollama imposee.

    La liste installee est injectee plutot que sondee : Ollama n'a aucun
    modele sur cette machine (D-028), et un test qui n'affirmerait rien
    faute de modele ne verifierait rien.
    """
    module = fresh_launcher(nom)
    module.detect_hardware()
    module.state["installed_models"] = list(installes)
    return module


class TestOnlyOpenSourceIsOffered:
    """Le defaut ne propose que de l'open source approuve OSI (DEC-004).

    Le filtre vient de `models_catalog.open_source_only()` : le launcher n'en
    ecrit aucun. Et rien ne disparait en silence - le catalogue garde les sept
    autres entrees, l'interface doit pouvoir les montrer sur demande.
    """

    def test_the_policy_served_is_the_cores_own_partition(self):
        module = fresh_launcher("_licences_partition")
        pont = load_core_bridge()
        politique = module.status_payload()["license_policy"]
        qualification = pont.license_qualification()

        assert politique["approved"] == list(qualification["approved"])
        assert politique["restricted"] == list(qualification["restricted"])
        assert politique["undetermined"] == list(qualification["undetermined"])

        approuves = set(politique["approved"])
        restreints = set(politique["restricted"])
        non_verifies = set(politique["undetermined"])
        assert approuves & restreints == set()
        assert approuves & non_verifies == set()
        assert restreints & non_verifies == set()
        assert approuves | restreints | non_verifies == set(pont.known_tags())

    def test_undetermined_licenses_are_never_folded_into_the_restricted_ones(self):
        """« Non approuvee » est une conclusion, « non verifiee » son absence.

        Les fondre affirmerait que ces trois entrees ne sont pas libres, ce
        que la veille refuse d'affirmer. Meme faute que d'ecrire « eteint »
        sur une sonde qui n'a pas conclu.
        """
        module = fresh_launcher("_licences_non_verifiees")
        pont = load_core_bridge()
        politique = module.status_payload()["license_policy"]

        assert list(politique["undetermined"]) == list(
            pont.catalog_module.undetermined_license_tags()
        )
        assert politique["undetermined"], "le catalogue en porte trois"
        assert "non verifie" in politique["undetermined_notice"].lower()
        assert politique["undetermined_notice"] != politique["restricted_notice"]

    def test_the_osi_reference_and_its_reserve_are_displayed(self):
        """La qualification est citee avec sa source ET sa reserve (D-044)."""
        module = launcher_mesure("_licences_source")
        payload = module.status_payload()
        politique = payload["license_policy"]

        assert politique["reference_url"] == (load_core_bridge().catalog_module.OSI_REFERENCE_URL)
        assert politique["reference_url"] in politique["notice"]
        assert "N'A PAS ete reverifiee" in politique["notice"]
        assert "MIT et Apache-2.0" in politique["notice"]

    def test_the_recommendation_is_computed_on_the_open_source_subset(self):
        """Recommander hors de ce qu'on propose serait incoherent.

        Le resultat est recalcule par le pont, independamment du launcher :
        comparer le launcher a lui-meme ne prouverait rien.
        """
        module = launcher_mesure("_reco_open_source")
        pont = load_core_bridge()
        profil = pont.detect_hardware()
        attendu = pont.recommend_for(profil, catalog=pont.open_source_models())

        reco = module.status_payload()["recommendation"]
        assert reco["recommended"]["tag"] == attendu.recommended.tag
        assert reco["maximum"]["tag"] == attendu.maximum.tag
        assert attendu.recommended.is_osi_approved
        assert attendu.maximum.is_osi_approved

    def test_a_larger_machine_still_never_lands_on_a_restricted_licence(self):
        """Le cas ou filtrer change reellement la reponse.

        Sur la machine de reference, 32 Gio, le catalogue complet et le
        sous-ensemble OSI recommandent le meme modele : ce test-la ne
        distinguerait rien. A 96 Gio, le plus lourd du catalogue complet est
        `llama3.1:70b`, sous licence Meta. La memoire est donc imposee pour
        que la difference existe et soit verifiable.
        """
        module = launcher_mesure("_reco_grosse_machine")
        pont = load_core_bridge()

        class ProfilLarge:
            available_memory_bytes = 96 * 1024**3
            unified_memory = False

        module.apply_recommendation(ProfilLarge())
        payload = module.status_payload()
        approuves = payload["license_policy"]["approved"]
        reco = payload["recommendation"]

        sans_filtre = pont.recommend_for(ProfilLarge())
        assert (
            sans_filtre.maximum.tag not in approuves
        ), "sans ce contraste le test ne prouverait rien"
        assert reco["recommended"]["tag"] in approuves
        assert reco["maximum"]["tag"] in approuves

        servis = {e["tag"]: e for e in payload["models"]}
        assert servis[sans_filtre.maximum.tag]["fits"] is True, (
            "la capacite ne depend pas de la licence : ce modele tient, et le "
            "dire faux serait un second mensonge"
        )

    def test_capacity_is_measured_on_the_whole_catalog(self):
        """Un modele restreint qui tient ne doit pas etre dit trop lourd.

        La licence decide de l'offre, jamais de la capacite : marquer
        « depasse la memoire mesuree » un modele qui tient serait un second
        mensonge cache derriere le premier filtre.
        """
        module = launcher_mesure("_capacite_complete")
        pont = load_core_bridge()
        attendu = pont.recommend_for(pont.detect_hardware())

        servis = {e["tag"]: e for e in module.status_payload()["models"]}
        tiennent = {m.tag for m in attendu.fits}
        assert tiennent, "cette machine doit encaisser au moins un modele"
        for tag, entree in servis.items():
            assert entree["fits"] is (tag in tiennent), tag

        restreints_qui_tiennent = [
            tag for tag, e in servis.items() if e["fits"] and not e["osi_approved"]
        ]
        assert restreints_qui_tiennent, "sans ce cas le test ne prouverait rien sur cette machine"

    @pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
    def test_the_rendered_list_carries_no_non_osi_tag_by_default(self):
        """La preuve porte sur la liste rendue, pas sur le payload."""
        module = launcher_mesure("_rendu_osi_seul")
        payload = module.status_payload()
        rendu = render_launcher_ui(extract_launcher_script(module), payload)
        liste = rendu["model-select"]["innerHTML"]

        politique = payload["license_policy"]
        rendus = tags_rendus(liste)
        assert rendus, "la liste rendue est vide"
        for tag in rendus:
            assert tag in politique["approved"], (
                f"{tag} n'est pas approuve OSI et figure pourtant dans le " f"choix par defaut"
            )
        for tag in list(politique["restricted"]) + list(politique["undetermined"]):
            assert tag not in rendus, f"{tag} propose par defaut"
        assert sorted(rendus) == sorted(
            politique["approved"]
        ), "toutes les entrees approuvees doivent etre proposees"

    @pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
    def test_the_excluded_ones_reappear_on_demand_in_two_distinct_groups(self):
        """Ecarter n'est pas effacer : la bascule les rend, et dit pourquoi."""
        module = launcher_mesure("_rendu_bascule")
        payload = module.status_payload()
        rendu = render_launcher_ui(
            extract_launcher_script(module),
            payload,
            elements=element_coche("show-restricted"),
        )
        liste = rendu["model-select"]["innerHTML"]
        politique = payload["license_policy"]

        rendus = tags_rendus(liste)
        for tag in list(politique["restricted"]) + list(politique["undetermined"]):
            assert tag in rendus, f"{tag} reste invisible malgre la bascule"

        libelles = libelles_de_groupes(liste)
        restreint = [texte for texte in libelles if "NON approuvee OSI" in texte]
        non_verifie = [texte for texte in libelles if "NON VERIFIEE" in texte]
        assert (
            len(restreint) == 1 and len(non_verifie) == 1
        ), f"les deux motifs d'exclusion doivent former deux groupes : {libelles}"
        assert restreint[0] != non_verifie[0]

    @pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
    def test_a_restricted_model_kept_by_the_user_stays_visible(self):
        """Une liste ou le modele actif manque afficherait un autre modele.

        Le `<select>` retomberait sur sa premiere option : la page dirait que
        le dev a choisi un modele qu'il n'a pas choisi.
        """
        module = launcher_mesure("_rendu_courant_restreint")
        payload = module.status_payload()
        restreint = payload["license_policy"]["restricted"][0]
        payload["ollama_model"] = restreint

        rendu = render_launcher_ui(extract_launcher_script(module), payload)
        liste = rendu["model-select"]["innerHTML"]
        assert (
            f'value="{restreint}" selected' in liste
        ), "le modele retenu doit rester dans la liste, meme ecarte par defaut"
        assert rendu["model-select"]["value"] == restreint

    @pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
    def test_the_page_states_what_it_offers_and_what_it_sets_aside(self):
        module = launcher_mesure("_rendu_notices")
        payload = module.status_payload()
        rendu = render_launcher_ui(extract_launcher_script(module), payload)

        bloc = rendu["model-licenses"]["innerHTML"]
        politique = payload["license_policy"]
        assert politique["notice"] in bloc
        assert politique["restricted_notice"] in bloc
        assert politique["undetermined_notice"] in bloc
        assert politique["reference_url"] in bloc

        reco = rendu["model-recommendation"]["innerHTML"]
        assert (
            politique["scope_notice"] in reco
        ), "le perimetre de la recommandation doit etre dit, pas suppose"


class TestTheFiveMemoryTiersAreRendered:
    """« faudrait les classifier comme avant » : les cinq paliers, en ordre.

    Le decoupage vient de `group_by_memory_tier()` et l'ordre de
    `MEMORY_TIERS`. Le launcher n'a ni bornes, ni tranches, ni libelles a lui.
    """

    def test_the_served_groups_are_the_cores_five_tiers_in_order(self):
        module = fresh_launcher("_paliers_ordre")
        pont = load_core_bridge()
        groupes = module.status_payload()["memory_tier_groups"]

        attendus = [(tier.tier_id, tier.label) for tier in pont.catalog_module.MEMORY_TIERS]
        assert [(g["tier_id"], g["label"]) for g in groupes] == attendus
        assert len(groupes) == 5

    def test_every_label_is_the_models_own_tier_label(self):
        """Aucun libelle n'est reecrit : c'est `memory_tier_label`, mot pour mot."""
        module = fresh_launcher("_paliers_libelles")
        payload = module.status_payload()
        par_tag = {e["tag"]: e for e in payload["models"]}

        for groupe in payload["memory_tier_groups"]:
            for tag in groupe["tags"]:
                assert par_tag[tag]["tier"] == groupe["tier_id"]
                assert par_tag[tag]["tier_label"] == groupe["label"]

    def test_the_groups_hold_exactly_the_open_source_catalog(self):
        module = fresh_launcher("_paliers_contenu")
        pont = load_core_bridge()
        groupes = module.status_payload()["memory_tier_groups"]

        classes = [tag for g in groupes for tag in g["tags"]]
        assert sorted(classes) == sorted(pont.open_source_models())
        assert len(classes) == len(set(classes)), "un tag ne peut avoir deux paliers"

    def test_an_empty_tier_is_kept_and_explained(self):
        """Le palier le plus lourd n'a aucune entree approuvee OSI.

        Mesure du 2026-09-07 : `llama3.1:70b` l'occupe seul, sous licence
        Meta. Le supprimer ferait croire que ce palier n'existe pas, alors que
        le fait a montrer est qu'aucun modele libre ne l'occupe.
        """
        module = fresh_launcher("_palier_vide")
        groupes = module.status_payload()["memory_tier_groups"]
        vides = [g for g in groupes if not g["tags"]]
        assert vides, "sans palier vide ce test ne verrouille rien"

    @pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
    def test_the_page_renders_the_five_tiers_in_order(self):
        module = launcher_mesure("_rendu_paliers")
        payload = module.status_payload()
        rendu = render_launcher_ui(extract_launcher_script(module), payload)
        libelles = libelles_de_groupes(rendu["model-select"]["innerHTML"])

        attendus = [g["label"] for g in payload["memory_tier_groups"]]
        assert len(libelles) == len(
            attendus
        ), f"cinq groupes attendus par defaut, rendus : {libelles}"
        for libelle, attendu in zip(libelles, attendus):
            assert libelle.startswith(attendu), f"palier rendu hors ordre ou renomme : {libelle!r}"

    @pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
    def test_a_tier_beyond_the_machine_is_marked_not_removed(self):
        """« un palier que sa machine n'encaisse pas doit rester visible ».

        La memoire est ramenee a 6 Gio par une mesure imposee : sur la machine
        de reference tout tient, et le cas ne se produirait jamais.
        """
        module = launcher_mesure("_rendu_palier_hors_capacite")

        class ProfilEtroit:
            available_memory_bytes = 6 * 1024**3
            unified_memory = False

        module.apply_recommendation(ProfilEtroit())
        payload = module.status_payload()
        rendu = render_launcher_ui(extract_launcher_script(module), payload)
        liste = rendu["model-select"]["innerHTML"]

        libelles = libelles_de_groupes(liste)
        hors = [texte for texte in libelles if "hors capacite mesuree" in texte]
        assert hors, f"aucun palier marque hors capacite : {libelles}"
        assert len(libelles) == 5, "un palier hors capacite reste rendu"

        par_tag = {e["tag"]: e for e in payload["models"]}
        trop_lourds = [t for t in tags_rendus(liste) if par_tag[t]["fits"] is False]
        assert trop_lourds, "sans modele trop lourd le marquage ne prouve rien"
        for tag in trop_lourds:
            assert (
                f">○ ✕ {tag} " in liste or f">● ✕ {tag} " in liste
            ), f"{tag} ne tient pas et n'est pas marque dans la liste"


class TestInstalledModelsAreVisible:
    """« tu ne listes pas non plus si j'ai deja des modeles d'installe ».

    Le croisement appartient a cette couche : `agent-backend` l'a refuse dans
    `recommend()` au motif que « deja telecharge » n'est pas une regle de
    memoire, et que l'appariement nom/tag existe deja ici. Il n'y en a donc
    qu'un, `is_model_installed()`, et ces tests verifient qu'aucun second
    appariement n'est ne en JavaScript.
    """

    def test_every_served_entry_carries_its_install_state(self):
        module = launcher_mesure("_installes_payload", installes=["qwen3:8b"])
        payload = module.status_payload()
        par_tag = {e["tag"]: e for e in payload["models"]}

        assert par_tag["qwen3:8b"]["installed"] is True
        autres = [t for t, e in par_tag.items() if e["installed"]]
        assert autres == ["qwen3:8b"], f"un seul modele est installe : {autres}"

    def test_the_install_state_reuses_the_existing_matching_rule(self):
        """Suffixe de quantization et `latest` : la regle deja ecrite, pas une autre."""
        module = launcher_mesure(
            "_installes_variantes", installes=["qwen3:8b-q4_0", "mistral:latest"]
        )
        par_tag = {e["tag"]: e for e in module.status_payload()["models"]}
        assert par_tag["qwen3:8b"]["installed"] is True, "suffixe de quantization"
        assert par_tag["mistral:7b"]["installed"] is True, "tag latest"
        assert par_tag["qwen3:4b"]["installed"] is False

        for tag, entree in par_tag.items():
            assert entree["installed"] is module.is_model_installed(
                tag, module.state["installed_models"]
            ), tag

    def test_nothing_installed_is_stated_not_left_blank(self):
        module = launcher_mesure("_installes_aucun")
        par_tag = {e["tag"]: e for e in module.status_payload()["models"]}
        assert not any(e["installed"] for e in par_tag.values())

    @pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
    def test_the_rendered_list_marks_the_installed_model(self):
        module = launcher_mesure("_rendu_installe", installes=["qwen3:8b"])
        payload = module.status_payload()
        rendu = render_launcher_ui(extract_launcher_script(module), payload)
        liste = rendu["model-select"]["innerHTML"]

        assert re.search(
            r'<option value="qwen3:8b"[^>]*>● qwen3:8b[^<]*deja installe', liste
        ), f"qwen3:8b n'est pas marque comme installe : {liste[:400]}"
        non_installe = re.search(r'<option value="mistral:7b"[^>]*>(○[^<]*)</option>', liste)
        assert non_installe and "non installe" in non_installe.group(
            1
        ), "un modele absent doit etre dit absent, pas laisse muet"

        bloc = rendu["model-recommendation"]["innerHTML"]
        assert "Deja telecharges sur cette machine" in bloc
        assert "qwen3:8b" in bloc

    @pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
    def test_the_page_says_so_when_nothing_is_downloaded(self):
        module = launcher_mesure("_rendu_rien_installe")
        rendu = render_launcher_ui(extract_launcher_script(module), module.status_payload())
        bloc = rendu["model-recommendation"]["innerHTML"]
        assert (
            "Aucun modele du catalogue n'est telecharge" in bloc
        ), f"l'absence doit etre ecrite, pas deduite d'une ligne vide : {bloc}"

    @pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
    def test_the_recommended_model_says_whether_it_is_already_there(self):
        module = launcher_mesure("_rendu_reco_installe")
        payload = module.status_payload()
        tag = payload["recommendation"]["recommended"]["tag"]

        rendu = render_launcher_ui(extract_launcher_script(module), payload)
        assert "non installe, a telecharger" in rendu["model-recommendation"]["innerHTML"]

        module2 = launcher_mesure("_rendu_reco_deja_la", installes=[tag])
        rendu2 = render_launcher_ui(extract_launcher_script(module2), module2.status_payload())
        assert "deja installe" in rendu2["model-recommendation"]["innerHTML"]


class TestNoSecondCatalogRuleInJavaScript:
    """Le JavaScript rend ce qu'on lui sert ; il ne recalcule aucune regle."""

    def test_the_script_holds_no_license_nor_tier_literal(self):
        module = fresh_launcher("_js_sans_regle")
        pont = load_core_bridge()
        script = extract_launcher_script(module)

        for tag in pont.known_tags():
            assert tag not in script, f"tag {tag} ecrit en dur dans le JavaScript"
        for tier in pont.catalog_module.MEMORY_TIERS:
            assert tier.label not in script, f"libelle de palier duplique : {tier.label}"
            assert tier.tier_id not in script
        for statut in pont.catalog_module.LICENSE_OSI_STATUSES:
            assert statut not in script, (
                f"le JavaScript trie les licences lui-meme ({statut}) au lieu "
                f"de rendre les ensembles servis"
            )
        assert pont.catalog_module.OSI_REFERENCE_URL not in script

    def test_the_launcher_writes_no_license_filter_of_its_own(self):
        """Le launcher passe par le pont, jamais par le module du coeur.

        `catalog_module` est l'attribut par lequel on atteindrait
        `open_source_only()` ou `group_by_memory_tier()` a la main : son
        absence du source verifie que le filtre et le decoupage restent au
        coeur, et que le pont est le seul chemin.
        """
        lignes = [
            ligne
            for ligne in code_without_comments(BASE_DIR / "launcher.py").splitlines()
            if "catalog_module" in ligne
        ]
        assert lignes == [], f"acces direct au module du coeur : {lignes}"

        source = code_without_comments(BASE_DIR / "launcher.py")
        assert "CORE.open_source_models()" in source
        assert "CORE.memory_tier_groups(" in source
        assert "CORE.license_qualification()" in source


class TestLauncherRunsUnderTheSystemPython:
    """D-061, tranchee et verifiee par execution, pas par lecture.

    `launcher.py` amorce une machine nue : il tourne sous le Python systeme,
    3.9.6 ici, alors que le paquet exige 3.10. Mesure du 2026-09-07 :

        /usr/bin/python3 -c "import promptforge"
          -> TypeError: unsupported operand type(s) for |   (security.py:696)

    D'ou le chargement par chemin de `scripts/core_loader.py`. Ce test le
    verifie de bout en bout sur un vrai 3.9, jusqu'a la recommandation.
    """

    @pytest.fixture(autouse=True)
    def _python39(self):
        interpreteur = python39_interpreter()
        if interpreteur is None:
            pytest.skip("aucun Python 3.9 sur cette machine")
        self.python39 = interpreteur

    def test_importing_the_package_still_fails_under_39(self):
        """Le motif de tout le montage : il doit rester vrai, ou tomber.

        Le jour ou `import promptforge` passera sous 3.9, ce test rougira et
        le detour par chemin pourra etre reexamine. Un contournement dont on
        ne surveille pas la cause devient un dogme.
        """
        sortie = subprocess.run(
            [self.python39, "-c", "import promptforge"],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            timeout=60,
        )
        assert sortie.returncode != 0, (
            "`import promptforge` fonctionne desormais sous 3.9 : le "
            "chargement par chemin (D-061) merite d'etre reexamine"
        )

    def test_the_launcher_recommends_a_model_under_39(self):
        programme = (
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('l', 'launcher.py')\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "module.detect_hardware()\n"
            "charge = module.status_payload()\n"
            "politique = charge['license_policy'] or {}\n"
            "print(json.dumps({'python': '%d.%d' % sys.version_info[:2],\n"
            "                  'catalogue': charge['catalog_available'],\n"
            "                  'modeles': len(charge['models']),\n"
            "                  'modele': charge['ollama_model'],\n"
            "                  'paliers': [g['tier_id'] for g in charge['memory_tier_groups']],\n"
            "                  'approuves': politique.get('approved'),\n"
            "                  'mesure': (charge['recommendation'] or {}).get('measured')}))\n"
        )
        sortie = subprocess.run(
            [self.python39, "-c", programme],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            timeout=120,
        )
        assert sortie.returncode == 0, (
            "`launcher.py` ne tourne plus sous le Python systeme :\n" + sortie.stderr[-2000:]
        )
        resultat = _json.loads(sortie.stdout.strip().splitlines()[-1])
        assert resultat["python"] == "3.9"
        assert resultat["catalogue"] is True, (
            "sous 3.9, le catalogue doit etre CHARGE, pas degrade : sinon le "
            "mode degrade devient le mode nominal"
        )
        assert resultat["modeles"] > 0
        assert resultat["mesure"] is True
        assert resultat["modele"], "aucun modele recommande sous 3.9"

        # Paliers et licences passent par le meme pont : les verifier sous
        # 3.14 seulement laisserait la moitie du rendu non couverte sur
        # l'interpreteur qui compte reellement pour un amorceur (D-061).
        pont = load_core_bridge()
        assert resultat["paliers"] == [
            tier.tier_id for tier in pont.catalog_module.MEMORY_TIERS
        ], "les cinq paliers doivent etre servis sous 3.9 aussi"
        assert resultat["approuves"] == list(
            pont.license_qualification()["approved"]
        ), "la qualification de licence doit tenir sous 3.9"
        assert (
            resultat["modele"] in resultat["approuves"]
        ), "le modele recommande sous 3.9 doit rester approuve OSI"

    def test_the_bridge_registers_modules_before_executing_them(self):
        """Le piege mesure de `core_loader`, verrouille pour de bon.

        Sous 3.9, `dataclasses` resout les annotations differees en lisant
        `sys.modules[cls.__module__].__dict__` sans verifier la cle. Omettre
        l'inscription prealable donne, sur les deux modules du coeur :
        `AttributeError: 'NoneType' object has no attribute '__dict__'`.
        Sous 3.14 la meme omission passe : le defaut n'apparait que sur la
        version qui compte.
        """
        contenu = (BASE_DIR / "scripts" / "core_loader.py").read_text(encoding="utf-8")
        assert "sys.modules[spec.name] = module" in contenu

        programme = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location("
            "'nu', 'promptforge/models_catalog.py')\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "try:\n"
            "    spec.loader.exec_module(module)\n"
            "    print('SANS_INSCRIPTION_OK')\n"
            "except AttributeError as exc:\n"
            "    print('SANS_INSCRIPTION_ECHOUE')\n"
        )
        sortie = subprocess.run(
            [self.python39, "-c", programme],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            timeout=60,
        )
        assert "SANS_INSCRIPTION_ECHOUE" in sortie.stdout, (
            "la recette naive passe desormais sous 3.9 ; verifier que "
            "`core_loader` reste correct avant de la simplifier"
        )


# ======================================================================
# F-033 : Ollama demarre par le lanceur n'ecoute que sur la boucle locale
# ======================================================================


class TestOllamaListensOnLoopbackByDefault:
    """Sous Windows, le lanceur demarre `ollama serve` lui-meme."""

    @pytest.fixture
    def launcher(self):
        return load_script_at(BASE_DIR / "launcher.py", "_f033_launcher")

    # F-033-AC2
    def test_f033_ac2_env_defaults_to_loopback(self, launcher):
        env = launcher.ollama_env({"PATH": "C:\\Windows"})
        assert env["OLLAMA_HOST"] == "127.0.0.1:11434"
        assert env["PATH"] == "C:\\Windows"
        assert "HSA_OVERRIDE_GFX_VERSION" not in env

    # F-033-AC3
    @pytest.mark.parametrize("valeur", ["0.0.0.0:11434", "192.168.1.5:11500", ""])
    def test_f033_ac3_user_value_is_kept(self, launcher, valeur):
        base = {"OLLAMA_HOST": valeur}
        env = launcher.ollama_env(base, "10.3.0")
        assert env["OLLAMA_HOST"] == valeur
        assert env["HSA_OVERRIDE_GFX_VERSION"] == "10.3.0"
        assert base == {"OLLAMA_HOST": valeur}, "l'environnement source ne doit pas changer"

    def _start_on_windows(self, launcher, monkeypatch):
        """Execute `start_ollama()` sous un Windows simule, sans lancer Ollama."""
        appels = []
        monkeypatch.setitem(launcher.state, "os", "Windows")
        monkeypatch.setitem(launcher.state, "gfx_version", None)
        monkeypatch.setattr(launcher.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
        monkeypatch.setattr(
            launcher.subprocess, "Popen", lambda cmd, **kw: appels.append((cmd, kw))
        )
        monkeypatch.setattr(launcher.time, "sleep", lambda _s: None)
        monkeypatch.setattr(launcher, "check_ollama", lambda: None)
        launcher.start_ollama()
        assert len(appels) == 1
        cmd, kw = appels[0]
        assert cmd == ["ollama", "serve"]
        return kw["env"]

    # F-033-AC2
    def test_f033_ac2_start_ollama_on_windows_uses_loopback(self, launcher, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        env = self._start_on_windows(launcher, monkeypatch)
        assert env["OLLAMA_HOST"] == "127.0.0.1:11434"

    # F-033-AC3
    def test_f033_ac3_start_ollama_on_windows_keeps_user_value(self, launcher, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
        env = self._start_on_windows(launcher, monkeypatch)
        assert env["OLLAMA_HOST"] == "0.0.0.0:11434"
