"""
Utilitaires cross-platform pour PromptForge.
Gère les différences entre Windows, Linux et macOS.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_platform() -> str:
    """Retourne le nom de la plateforme."""
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    else:
        return "linux"


def copy_to_clipboard(text: str) -> bool:
    """
    Copie du texte dans le presse-papier.
    Fonctionne sur Windows, macOS et Linux.

    Returns:
        True si succès, False sinon
    """
    platform = get_platform()

    try:
        if platform == "windows":
            # Windows: utiliser clip.exe
            process = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            process.communicate(text.encode("utf-16-le"))
            return process.returncode == 0

        elif platform == "macos":
            # macOS: utiliser pbcopy
            process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-8"))
            return process.returncode == 0

        else:
            # Linux: essayer plusieurs options
            # 1. xclip
            if shutil.which("xclip"):
                process = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE
                )
                process.communicate(text.encode("utf-8"))
                return process.returncode == 0

            # 2. xsel
            if shutil.which("xsel"):
                process = subprocess.Popen(
                    ["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE
                )
                process.communicate(text.encode("utf-8"))
                return process.returncode == 0

            # 3. wl-copy (Wayland)
            if shutil.which("wl-copy"):
                process = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
                process.communicate(text.encode("utf-8"))
                return process.returncode == 0

            return False

    except Exception:
        return False


def get_clipboard_tool() -> str | None:
    """Retourne le nom de l'outil de presse-papier disponible."""
    platform = get_platform()

    if platform == "windows":
        return "clip.exe"
    elif platform == "macos":
        return "pbcopy"
    else:
        for tool in ["xclip", "xsel", "wl-copy"]:
            if shutil.which(tool):
                return tool
        return None


def get_data_dir() -> Path:
    """
    Retourne le répertoire de données approprié pour l'OS.

    - Windows: %APPDATA%/promptforge
    - macOS: ~/Library/Application Support/promptforge
    - Linux: ~/.local/share/promptforge
    """
    platform = get_platform()

    if platform == "windows":
        base = os.environ.get("APPDATA", str(Path.home()))
        return Path(base) / "promptforge"
    elif platform == "macos":
        return Path.home() / "Library" / "Application Support" / "promptforge"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return Path(xdg_data) / "promptforge"


def get_config_dir() -> Path:
    """
    Retourne le répertoire de configuration approprié pour l'OS.

    - Windows: %APPDATA%/promptforge
    - macOS: ~/Library/Application Support/promptforge
    - Linux: ~/.config/promptforge
    """
    platform = get_platform()

    if platform == "windows":
        base = os.environ.get("APPDATA", str(Path.home()))
        return Path(base) / "promptforge"
    elif platform == "macos":
        return Path.home() / "Library" / "Application Support" / "promptforge"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(xdg_config) / "promptforge"


def open_file_explorer(path: Path) -> bool:
    """
    Ouvre l'explorateur de fichiers au chemin spécifié.

    Returns:
        True si succès, False sinon
    """
    platform = get_platform()

    try:
        if platform == "windows":
            os.startfile(str(path))
        elif platform == "macos":
            subprocess.run(["open", str(path)])
        else:
            subprocess.run(["xdg-open", str(path)])
        return True
    except Exception:
        return False


def open_url(url: str) -> bool:
    """
    Ouvre une URL dans le navigateur par défaut.

    Returns:
        True si succès, False sinon
    """
    import webbrowser

    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def ensure_directory(path: Path) -> Path:
    """Crée un répertoire s'il n'existe pas et retourne le chemin."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_wsl() -> bool:
    """Vérifie si on est dans WSL (Windows Subsystem for Linux)."""
    if get_platform() != "linux":
        return False

    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def get_ollama_default_url() -> str:
    """Retourne l'URL par défaut d'Ollama selon la plateforme."""
    # Sur WSL, Ollama tourne généralement côté Windows
    if is_wsl():
        return "http://host.docker.internal:11434"
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")
