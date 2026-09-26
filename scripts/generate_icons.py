#!/usr/bin/env python3
"""
Générateur d'icônes PNG pour PromptForge
=========================================

Convertit les fichiers SVG en PNG à différentes résolutions.

Dépendances:
    pip install cairosvg Pillow

Usage:
    python scripts/generate_icons.py
"""

import os
import sys
from pathlib import Path

# Vérifier les dépendances
try:
    import cairosvg
    from PIL import Image

    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    print("⚠️  Dépendances manquantes. Installation...")
    os.system(f"{sys.executable} -m pip install cairosvg Pillow")
    try:
        import cairosvg
        from PIL import Image

        HAS_DEPS = True
    except ImportError:
        print("❌ Impossible d'installer les dépendances.")
        print("   Installez manuellement: pip install cairosvg Pillow")
        sys.exit(1)

# Configuration
ASSETS_DIR = Path(__file__).parent.parent / "assets"
SIZES = [512, 256, 128, 64, 32, 16]


def svg_to_png(svg_path, png_path, size):
    """Convertit un SVG en PNG à la taille spécifiée."""
    try:
        cairosvg.svg2png(
            url=str(svg_path), write_to=str(png_path), output_width=size, output_height=size
        )
        return True
    except Exception as e:
        print(f"  ❌ Erreur: {e}")
        return False


def create_ico(png_files, ico_path):
    """Crée un fichier ICO multi-résolution."""
    try:
        images = []
        for png_file in png_files:
            if png_file.exists():
                img = Image.open(png_file)
                images.append(img)

        if images:
            # Sauvegarder en ICO avec toutes les tailles
            images[0].save(
                ico_path, format="ICO", sizes=[(img.width, img.height) for img in images]
            )
            return True
    except Exception as e:
        print(f"  ❌ Erreur ICO: {e}")
    return False


def main():
    print("🔨 Générateur d'icônes PromptForge")
    print("=" * 40)

    if not ASSETS_DIR.exists():
        print(f"❌ Dossier assets non trouvé: {ASSETS_DIR}")
        sys.exit(1)

    # Fichiers SVG source
    svg_files = {
        "icon": ASSETS_DIR / "icon.svg",
        "favicon": ASSETS_DIR / "favicon.svg",
        "logo-full": ASSETS_DIR / "logo-full.svg",
    }

    # Vérifier que les SVG existent
    for name, path in svg_files.items():
        if not path.exists():
            print(f"⚠️  {name}.svg non trouvé")

    # Générer les PNG pour icon.svg
    print("\n📦 Génération des icônes (icon.svg)")
    icon_svg = svg_files["icon"]
    if icon_svg.exists():
        png_files = []
        for size in SIZES:
            png_path = ASSETS_DIR / f"icon-{size}.png"
            print(f"  → icon-{size}.png ({size}×{size})...", end=" ")
            if svg_to_png(icon_svg, png_path, size):
                print("✅")
                png_files.append(png_path)
            else:
                print("❌")

        # Créer le fichier ICO
        print("\n📦 Création du favicon.ico")
        ico_path = ASSETS_DIR / "favicon.ico"
        ico_sizes = [ASSETS_DIR / f"icon-{s}.png" for s in [32, 16]]
        if create_ico(ico_sizes, ico_path):
            print("  → favicon.ico ✅")

    # Générer le logo complet haute résolution
    print("\n📦 Génération du logo (logo-full.svg)")
    logo_svg = svg_files["logo-full"]
    if logo_svg.exists():
        for size in [1024, 512]:
            png_path = ASSETS_DIR / f"logo-{size}.png"
            print(f"  → logo-{size}.png ({size}×{size})...", end=" ")
            if svg_to_png(logo_svg, png_path, size):
                print("✅")

    # Générer le favicon simplifié
    print("\n📦 Génération du favicon simplifié")
    favicon_svg = svg_files["favicon"]
    if favicon_svg.exists():
        for size in [64, 32, 16]:
            png_path = ASSETS_DIR / f"favicon-{size}.png"
            print(f"  → favicon-{size}.png ({size}×{size})...", end=" ")
            if svg_to_png(favicon_svg, png_path, size):
                print("✅")

    print("\n" + "=" * 40)
    print("✅ Génération terminée!")
    print(f"   Fichiers dans: {ASSETS_DIR}")

    # Lister les fichiers générés
    print("\n📁 Fichiers générés:")
    for f in sorted(ASSETS_DIR.glob("*.png")):
        size = os.path.getsize(f)
        print(f"   {f.name:20} ({size:,} bytes)")

    ico_file = ASSETS_DIR / "favicon.ico"
    if ico_file.exists():
        print(f"   {'favicon.ico':20} ({os.path.getsize(ico_file):,} bytes)")


if __name__ == "__main__":
    main()
