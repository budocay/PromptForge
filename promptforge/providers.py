"""
Provider Ollama pour le reformatage intelligent des prompts.
Gère la communication avec Ollama en local.
"""

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .logging_config import get_logger

logger = get_logger(__name__)


class OllamaError(Exception):
    """Erreur de communication avec Ollama."""


class OllamaTimeoutError(OllamaError, TimeoutError):
    """Ollama n'a pas repondu dans le delai imparti.

    Herite aussi de ``TimeoutError`` : avant cette correction, un depassement
    de delai remontait un ``TimeoutError`` brut jusqu'a l'appelant. Un appelant
    qui s'en protegeait deja par ``except TimeoutError`` (ou ``except OSError``)
    continue donc de fonctionner a l'identique.

    Attributes:
        model: Le modele qui n'a pas repondu.
        timeout: Le delai depasse, en secondes.
    """

    def __init__(self, model: str, timeout: int) -> None:
        self.model = model
        self.timeout = timeout
        super().__init__(build_timeout_message(model, timeout))


class OllamaModelNotFoundError(OllamaError):
    """Ollama a repondu 404 : le modele demande n'est pas installe.

    Avant cette classe, ce cas remontait comme un ``None`` indistinct et
    l'utilisateur ne voyait que ``HTTP Error 404: Not Found``, sans savoir
    quel modele manquait ni comment l'installer.

    Attributes:
        model: Le modele introuvable.
    """

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(
            f"Le modele '{model}' n'est pas installe dans Ollama. "
            f"Installe-le avec `ollama pull {model}`, ou choisis un modele "
            f"deja present (`ollama list`) via OLLAMA_MODEL ou --model."
        )


# Delai par defaut, en secondes, pour une generation Ollama.
#
# Justification chiffree. Mesure de premiere main du 2026-09-07 sur cette
# machine, via `OllamaProvider.generate()` et un prompt de reformatage
# realiste, trois passages par modele :
#     qwen3:14b -> 83,34 s | 195,23 s | 98,20 s
#     qwen3:8b  ->  30,41 s |  51,36 s |  63,30 s
# Le passage a 195,23 s vaut 1,63 fois l'ancien defaut de 120 s, sans aucune
# charge artificielle et sur un prompt nominal : l'ancienne valeur etait donc
# franchie par une generation parfaitement normale, et l'utilisateur perdait
# son reformatage alors que le modele repondait. C'est le defaut signale.
# Le depot avait par ailleurs deja releve 457,48 s en charge (dette D-073).
#
# 600 s couvre la plus longue generation jamais mesuree ici (457,48 s) avec
# 31 % de marge, et 3,07 fois le maximum mesure ce jour. Cette valeur rejoint
# le budget deja retenu dans ce fichier pour l'autre operation Ollama longue,
# `pull_model` (600 s). Un delai trop long ne coute plus grand-chose depuis
# que le depassement est rattrape, nomme et reglable : l'utilisateur presse
# abaisse OLLAMA_TIMEOUT, l'utilisateur patient ne perd plus son travail.
DEFAULT_OLLAMA_TIMEOUT = 600

# Variable d'environnement de reglage, meme convention que OLLAMA_HOST et
# OLLAMA_MODEL : lecture directe dans os.environ, sans fichier de config.
OLLAMA_TIMEOUT_ENV_VAR = "OLLAMA_TIMEOUT"

# Modele par defaut, identique pour la CLI, l'interface web et Docker
# (`compose.yaml`). La CLI utilisait auparavant `llama3.1`, que peu de gens
# ont installe : `promptforge format` echouait alors sur un 404.
DEFAULT_OLLAMA_MODEL = "qwen3:8b"
OLLAMA_MODEL_ENV_VAR = "OLLAMA_MODEL"


def get_default_ollama_model() -> str:
    """Modele Ollama par defaut : ``OLLAMA_MODEL`` s'il est defini et non vide."""
    return os.environ.get(OLLAMA_MODEL_ENV_VAR, "").strip() or DEFAULT_OLLAMA_MODEL


def get_default_ollama_timeout() -> int:
    """Recupere le delai de generation depuis l'environnement.

    Lit ``OLLAMA_TIMEOUT`` (en secondes). Une valeur absente, non entiere ou
    nulle/negative retombe sur `DEFAULT_OLLAMA_TIMEOUT` avec un avertissement
    journalise : un delai invalide ne doit ni faire echouer le demarrage, ni
    passer inapercu.
    """
    raw = os.environ.get(OLLAMA_TIMEOUT_ENV_VAR)
    if raw is None or raw.strip() == "":
        return DEFAULT_OLLAMA_TIMEOUT

    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning(
            "%s=%r n'est pas un entier, repli sur %s s",
            OLLAMA_TIMEOUT_ENV_VAR,
            raw,
            DEFAULT_OLLAMA_TIMEOUT,
        )
        return DEFAULT_OLLAMA_TIMEOUT

    if value <= 0:
        logger.warning(
            "%s=%s doit etre strictement positif, repli sur %s s",
            OLLAMA_TIMEOUT_ENV_VAR,
            value,
            DEFAULT_OLLAMA_TIMEOUT,
        )
        return DEFAULT_OLLAMA_TIMEOUT

    return value


def build_timeout_message(model: str, timeout: int) -> str:
    """Construit le message rendu a l'utilisateur en cas de depassement de delai.

    Le message doit etre distinguable d'un Ollama absent et d'une erreur
    reseau, dire ce qui a ete perdu, et donner les deux leviers d'action.

    Il ne consulte volontairement ni `hardware.py` ni `models_catalog.py` :
    `detect_hardware()` lance plusieurs sous-processus (sysctl, nvidia-smi,
    lspci) sur un chemin que l'utilisateur n'atteint qu'apres avoir deja
    attendu `timeout` secondes, et ces sous-processus peuvent bloquer a leur
    tour. Le chemin d'erreur reste donc sans entree-sortie.
    """
    return (
        f"Le modele '{model}' n'a pas repondu dans le delai de {timeout} s. "
        f"Ollama est joignable : c'est la generation qui a ete trop longue, "
        f"pas le service qui est tombe. Rien n'a ete sauvegarde. "
        f"Deux leviers : allonger le delai "
        f"({OLLAMA_TIMEOUT_ENV_VAR}={timeout * 2} par exemple), "
        f"ou choisir un modele plus leger via OLLAMA_MODEL."
    )


def get_default_ollama_url() -> str:
    """Récupère l'URL Ollama depuis l'environnement ou détecte automatiquement."""
    if "OLLAMA_HOST" in os.environ:
        return os.environ["OLLAMA_HOST"]

    # Détecter WSL
    try:
        with open("/proc/version") as f:
            if "microsoft" in f.read().lower():
                return "http://host.docker.internal:11434"
    except OSError:
        pass

    return "http://localhost:11434"


@dataclass
class OllamaConfig:
    base_url: str = field(default_factory=get_default_ollama_url)
    model: str = field(default_factory=get_default_ollama_model)
    timeout: int = field(default_factory=get_default_ollama_timeout)


class OllamaProvider:
    def __init__(self, config: OllamaConfig | None = None):
        self.config = config or OllamaConfig()

    def is_available(self) -> bool:
        """Vérifie si Ollama est disponible et répond."""
        try:
            req = urllib.request.Request(f"{self.config.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            return False

    def list_models(self) -> list[str]:
        """Liste les modèles disponibles dans Ollama."""
        try:
            req = urllib.request.Request(f"{self.config.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                return [model["name"] for model in data.get("models", [])]
        except TimeoutError:
            # `TimeoutError` derive d'`OSError`, pas d'`URLError` : sans cette
            # clause il remontait brut jusqu'a l'appelant. Ici la liste vide
            # reste le contrat d'echec (comme `is_available()` rend False),
            # mais elle est desormais journalisee au lieu d'etre muette.
            logger.warning(
                "Ollama n'a pas liste ses modeles dans le delai de 10 s (%s)",
                self.config.base_url,
            )
            return []
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            logger.warning("Liste des modeles Ollama indisponible: %s", e)
            return []

    def generate(self, prompt: str, system_prompt: str = "", num_ctx: int = 16384) -> str | None:
        """Génère une réponse via Ollama.

        Args:
            prompt: Le prompt à envoyer
            system_prompt: Le system prompt optionnel
            num_ctx: Taille du contexte (défaut: 16384 pour supporter les gros projets)

        Returns:
            Le texte genere, ou None si Ollama est injoignable ou repond mal
            (contrat inchange pour ces deux cas).

        Raises:
            OllamaTimeoutError: si le modele n'a pas repondu dans
                `config.timeout` secondes. Ce cas n'est volontairement PAS
                rendu comme `None` : un depassement de delai n'est pas un
                echec reseau, et l'appelant doit pouvoir le dire a
                l'utilisateur. Avant cette correction ce cas remontait un
                `TimeoutError` brut non rattrape ; `OllamaTimeoutError` en
                derive, donc aucun appelant existant ne casse.
        """
        try:
            payload = {
                "model": self.config.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,  # Plus déterministe pour le reformatage
                    "top_p": 0.9,
                    "num_ctx": num_ctx,  # Utiliser plus de contexte pour les gros prompts
                },
            }

            if system_prompt:
                payload["system"] = system_prompt

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.config.base_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self.config.timeout) as response:
                result = json.loads(response.read().decode())
                return result.get("response")

        except TimeoutError as e:
            # Depassement du delai de lecture. `TimeoutError` derive d'`OSError`
            # et d'aucune des erreurs urllib : il n'etait rattrape par personne.
            logger.warning(
                "Depassement du delai Ollama: modele=%s timeout=%ss",
                self.config.model,
                self.config.timeout,
            )
            raise OllamaTimeoutError(self.config.model, self.config.timeout) from e

        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Ollama repond 404 sur /api/generate quand le modele n'existe
                # pas localement. C'est le cas le plus frequent d'echec apres
                # une installation : on le nomme au lieu de rendre un None muet.
                logger.error("Modele Ollama introuvable: %s", self.config.model)
                raise OllamaModelNotFoundError(self.config.model) from e
            logger.error("Ollama a repondu %s: %s", e.code, e)
            return None

        except urllib.error.URLError as e:
            # Un depassement de delai a la connexion arrive emballe dans URLError,
            # contrairement au depassement a la lecture attrape plus haut.
            if isinstance(e.reason, TimeoutError):
                logger.warning(
                    "Depassement du delai Ollama a la connexion: modele=%s timeout=%ss",
                    self.config.model,
                    self.config.timeout,
                )
                raise OllamaTimeoutError(self.config.model, self.config.timeout) from e
            logger.error("Ollama injoignable (%s): %s", self.config.base_url, e)
            return None

        except json.JSONDecodeError as e:
            logger.error("Reponse Ollama illisible: %s", e)
            return None

    def pull_model(self, model: str) -> bool:
        """Télécharge un modèle si nécessaire."""
        try:
            result = subprocess.run(
                ["ollama", "pull", model],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes max pour le téléchargement
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False


# Bloc de raisonnement des modèles « thinking » (qwen3, deepseek-r1...). Selon
# la version d'Ollama et le modèle, il peut arriver dans `response` au lieu du
# champ `thinking` : il ne doit jamais atteindre le prompt rendu.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_RE = re.compile(r"^\s*<think>.*", re.DOTALL | re.IGNORECASE)
_FENCED_RE = re.compile(r"^```[\w-]*\s*\n(.*?)\n?```\s*$", re.DOTALL)
# Phrases d'annonce qu'un modèle place avant le prompt (« Voici le prompt
# reformaté : »). Elles ne sont retirées que seules sur leur ligne et courtes.
_PREAMBLE_RE = re.compile(
    r"^\s*(voici|voil[aà]|bien s[uû]r|d'accord|ok|parfait|here is|here's|sure|certainly)\b.{0,160}$",
    re.IGNORECASE,
)


def clean_model_output(text: str, expected_syntax: str = "any") -> str:
    """Retire de la sortie du modèle ce qui n'appartient pas au prompt.

    Dans l'ordre : blocs `<think>` de raisonnement, clôture de code qui
    emballe toute la réponse, lignes d'annonce en tête. Pour une sortie XML,
    le texte libre avant la première balise et après la dernière est aussi
    retiré s'il est court : c'est de l'emballage, pas du contenu.
    """
    if not text:
        return text
    text = _THINK_BLOCK_RE.sub("", text)
    if _UNCLOSED_THINK_RE.match(text) and "</think>" not in text.lower():
        # Raisonnement tronqué (délai, limite de tokens) : il n'y a pas de
        # prompt après, seulement du raisonnement.
        return ""
    text = text.strip()

    fenced = _FENCED_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    lines = text.split("\n")
    while lines and (not lines[0].strip() or _PREAMBLE_RE.match(lines[0])):
        lines.pop(0)
    text = "\n".join(lines).strip()

    if expected_syntax == "xml":
        first = re.search(r"<[A-Za-z_][\w-]*>", text)
        last = None
        for last in re.finditer(r"</[A-Za-z_][\w-]*>", text):
            pass
        if first and last:
            head, tail = text[: first.start()], text[last.end() :]
            if len(head.strip()) <= 200:
                text = text[first.start() :]
                tail_start = last.end() - first.start()
            else:
                tail_start = last.end()
            if tail.strip() and len(tail.strip()) <= 300 and "<" not in tail:
                text = text[:tail_start]
        text = text.strip()

    return text


def is_markdown_format(text: str) -> bool:
    """
    Détecte si le texte est au format Markdown plutôt que XML.
    """
    # Patterns Markdown typiques
    markdown_patterns = [
        r"^#{1,6}\s+",  # Headers: # ## ### etc.
        r"\*\*[^*]+\*\*",  # Bold: **text**
        r"^\s*[-*]\s+",  # Lists: - item ou * item
        r"^\s*\d+\.\s+",  # Numbered lists: 1. item
        r"^---+$",  # Horizontal rules: ---
        r"```",  # Code blocks
    ]

    # Si on trouve plusieurs patterns Markdown, c'est du Markdown
    markdown_count = 0
    for pattern in markdown_patterns:
        if re.search(pattern, text, re.MULTILINE):
            markdown_count += 1

    # Vérifier si des balises XML existent
    has_xml = bool(re.search(r"<\w+>.*?</\w+>", text, re.DOTALL))

    # C'est du Markdown si on a 2+ patterns Markdown ET pas de XML
    return markdown_count >= 2 and not has_xml


def convert_markdown_to_xml(text: str, profile_name: str | None = None) -> str:
    """
    Convertit le Markdown généré par un petit modèle en XML structuré.

    Cette fonction est un filet de sécurité pour les modèles qui ne suivent pas
    les instructions de format XML.
    """
    # Nettoyer le texte
    text = text.strip()

    # Supprimer les blocs de code Markdown
    text = re.sub(r"```\w*\n?", "", text)
    text = re.sub(r"```", "", text)

    # Supprimer les lignes de séparation ---
    text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)

    # Mapping des headers Markdown vers balises XML universelles (v2.0)
    # Balises harmonisées: <task>, <context>, <instructions>, <constraints>, <output_format>
    section_mapping = {
        # Task / Objectif
        "objectif": "task",
        "objective": "task",
        "but": "task",
        "task": "task",
        "tâche": "task",
        "principal": "task",
        "main": "task",
        "goal": "task",
        "définition": "task",
        "definition": "task",
        # Context
        "contexte": "context",
        "context": "context",
        "background": "context",
        "technologies": "context",
        "stack": "context",
        "projet": "context",
        "project": "context",
        "environnement": "context",
        "environment": "context",
        # Instructions / Steps
        "instructions": "instructions",
        "étapes": "instructions",
        "steps": "instructions",
        "procedure": "instructions",
        "procédure": "instructions",
        "actions": "instructions",
        "process": "instructions",
        "workflow": "instructions",
        # Requirements / Specifications
        "specifications": "requirements",
        "spécifications": "requirements",
        "requirements": "requirements",
        "exigences": "requirements",
        "besoins": "requirements",
        "needs": "requirements",
        "features": "requirements",
        "fonctionnalités": "requirements",
        # Constraints
        "contraintes": "constraints",
        "constraints": "constraints",
        "limites": "constraints",
        "limits": "constraints",
        "règles": "constraints",
        "rules": "constraints",
        "bonnes pratiques": "constraints",
        "best practices": "constraints",
        "restrictions": "constraints",
        # Output format
        "format": "output_format",
        "output": "output_format",
        "sortie": "output_format",
        "résultat": "output_format",
        "result": "output_format",
        "attendu": "output_format",
        "expected": "output_format",
        "livrables": "output_format",
        "deliverables": "output_format",
        # Thinking (pour GPT-5 Pro)
        "thinking": "thinking",
        "raisonnement": "thinking",
        "reasoning": "thinking",
        "réflexion": "thinking",
        "analyse": "thinking",
        "analysis": "thinking",
        # Examples (few-shot)
        "exemples": "examples",
        "examples": "examples",
        "exemple": "examples",
        "example": "examples",
        # Autres
        "fichiers": "files",
        "files": "files",
        "ressources": "resources",
        "resources": "resources",
    }

    # Trouver les sections avec headers Markdown
    sections = {}
    current_section = None
    current_content = []

    lines = text.split("\n")

    for line in lines:
        # Ignorer les lignes vides de séparation
        if re.match(r"^---+\s*$", line):
            continue

        # Détecter les headers Markdown (# ## ### etc.)
        header_match = re.match(r"^#{1,6}\s+\**(.+?)\**\s*$", line)

        if header_match:
            # Sauvegarder la section précédente
            if current_section and current_content:
                content = "\n".join(current_content).strip()
                # Nettoyer les --- restants
                content = re.sub(r"\n---+\s*$", "", content)
                content = re.sub(r"^---+\s*\n", "", content)
                if content:
                    sections[current_section] = content

            # Nouvelle section
            header_text = header_match.group(1).lower()
            header_text = re.sub(r"\*+", "", header_text).strip()

            # Trouver le tag XML correspondant
            current_section = None
            for key, tag in section_mapping.items():
                if key in header_text:
                    current_section = tag
                    break

            # Si pas trouvé, utiliser un tag générique basé sur le header
            if not current_section:
                # Créer un tag à partir du header
                tag_name = re.sub(r"[^a-z0-9]+", "_", header_text)
                tag_name = tag_name.strip("_")
                if tag_name:
                    current_section = tag_name
                else:
                    current_section = "section"

            current_content = []
        else:
            # Nettoyer le contenu
            cleaned_line = line
            # Supprimer le bold Markdown
            cleaned_line = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned_line)
            # Convertir les tirets de liste
            cleaned_line = re.sub(r"^\s*[-*]\s+", "- ", cleaned_line)
            # Supprimer les backticks inline
            cleaned_line = re.sub(r"`([^`]+)`", r"\1", cleaned_line)

            if cleaned_line.strip():
                current_content.append(cleaned_line)

    # Sauvegarder la dernière section
    if current_section and current_content:
        content = "\n".join(current_content).strip()
        content = re.sub(r"\n---+\s*$", "", content)
        content = re.sub(r"^---+\s*\n", "", content)
        if content:
            sections[current_section] = content

    # Si pas de sections trouvées, créer une structure minimale
    if not sections:
        # Nettoyer le Markdown
        cleaned = re.sub(r"#{1,6}\s+", "", text)
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"^[-*]\s+", "- ", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^---+\s*$", "", cleaned, flags=re.MULTILINE)

        sections = {
            "task": "Accomplir la tâche demandée par l'utilisateur.",
            "context": "Contexte extrait de la demande.",
            "instructions": cleaned.strip(),
            "output_format": "Réponse structurée et complète.",
        }

    # Construire le XML
    xml_parts = []

    # Ordre préféré des balises (format universel v2.0)
    preferred_order = [
        "task",
        "context",
        "thinking",
        "instructions",
        "requirements",
        "constraints",
        "examples",
        "output_format",
        "files",
        "resources",
    ]

    # D'abord les sections dans l'ordre préféré
    for tag in preferred_order:
        if tag in sections:
            content = sections[tag]
            xml_parts.append(f"<{tag}>\n{content}\n</{tag}>")

    # Puis les autres sections
    for tag, content in sections.items():
        if tag not in preferred_order:
            xml_parts.append(f"<{tag}>\n{content}\n</{tag}>")

    return "\n\n".join(xml_parts)


REFORMAT_SYSTEM_PROMPT = """Tu transformes des demandes utilisateur en prompts XML ultra-structurés.

RÈGLE ABSOLUE: Ta réponse DOIT être UNIQUEMENT des balises XML.
❌ INTERDIT: #, ##, **, -, ```, Markdown
✅ OBLIGATOIRE: <balise>contenu</balise>

BALISES XML À UTILISER:
<task>          Objectif principal clair
<context>       Informations contextuelles projet/technique
<instructions>  Étapes numérotées (1. 2. 3.)
<constraints>   Limites et règles à respecter
<output_format> Format de sortie attendu

EXEMPLE DE TRANSFORMATION:

Demande: "j'ai besoin d'une page de login"

<task>
Créer une page de connexion sécurisée et responsive pour l'application web.
</task>

<context>
Application web nécessitant un système d'authentification utilisateur.
Page de login comme point d'entrée principal.
</context>

<instructions>
1. Créer le formulaire avec champs email et mot de passe
2. Implémenter la validation côté client
3. Gérer les états de chargement et d'erreur
4. Ajouter la redirection après connexion réussie
5. Styliser de manière responsive (mobile/desktop)
</instructions>

<constraints>
Ne pas stocker le mot de passe en clair
Utiliser HTTPS pour la transmission
Protéger contre les attaques CSRF
Messages d'erreur non révélateurs
</constraints>

<output_format>
Composant de formulaire avec validation, gestion d'erreurs, styles responsives
et tests unitaires.
</output_format>

RAPPEL:
- Commence DIRECTEMENT par <task>
- PAS de texte avant ou après le XML
- MÊME LANGUE que l'utilisateur"""


def format_prompt_with_ollama(
    raw_prompt: str,
    project_context: str,
    provider: OllamaProvider | None = None,
    profile_name: str | None = None,
    return_conversion_info: bool = False,
) -> str | None:
    """
    Reformate un prompt en utilisant Ollama.

    Args:
        raw_prompt: Le prompt brut de l'utilisateur
        project_context: Le contenu du fichier de configuration projet
        provider: Instance OllamaProvider (créée si non fournie)
        profile_name: Clé de `PRESET_PROFILES` (claude_opus_5, gpt_5.1, universel, etc.)
        return_conversion_info: Si True, retourne un tuple (result, was_converted_from_markdown)

    Returns:
        Le prompt reformaté ou None en cas d'erreur
        Si return_conversion_info=True: tuple (prompt, was_converted)

    Raises:
        OllamaModelNotFoundError: propage tel quel quand le modele n'est pas
            installe, pour que le message dise lequel et comment l'installer.
        OllamaTimeoutError: propage volontairement le depassement de delai de
            `OllamaProvider.generate()`, au lieu de l'aplatir en None. C'est ce
            qui permet a `PromptForge.format_prompt()` de distinguer « le
            modele a mis trop de temps » de « Ollama est injoignable ».
    """
    if provider is None:
        provider = OllamaProvider()

    if not provider.is_available():
        return (None, False) if return_conversion_info else None

    # Utiliser un profil si spécifié
    if profile_name:
        from .profiles import build_reformat_prompt, get_profile

        profile = get_profile(profile_name)
        system_prompt, full_prompt = build_reformat_prompt(raw_prompt, project_context, profile)
    else:
        # Sans profil : prompt XML générique, mêmes règles communes.
        from .profiles import NO_BULLSHIT_RULE, REFORMAT_RULES, build_user_prompt

        system_prompt = REFORMAT_SYSTEM_PROMPT + REFORMAT_RULES + NO_BULLSHIT_RULE
        full_prompt = build_user_prompt(raw_prompt, project_context)

    # Générer avec Ollama
    result = provider.generate(full_prompt, system_prompt)

    from .profiles import SYNTAX_XML, get_expected_syntax

    expected_syntax = get_expected_syntax(profile_name)

    # POST-TRAITEMENT
    # 1. Retirer ce qui n'est pas le prompt : raisonnement, emballage, annonce.
    # 2. Convertir Markdown -> XML, et seulement quand le profil attend du XML.
    #    Les petits modèles (8B et moins) rendent souvent du Markdown même
    #    quand on leur demande du XML ; mais un profil GPT demande justement
    #    du Markdown, et le convertir trahirait son prompt système.
    was_converted = False
    if result:
        result = clean_model_output(result, expected_syntax) or None
    if result and expected_syntax == SYNTAX_XML and is_markdown_format(result):
        result = convert_markdown_to_xml(result, profile_name)
        was_converted = True

    if return_conversion_info:
        return (result, was_converted)
    return result
