"""Préparation du logo de PafOpener (icône de la fenêtre et de l'exécutable) avec Pillow."""
from __future__ import annotations

from pathlib import Path

from PIL import Image


def preparer_logo(image: Image.Image, retirer_marges: bool = True) -> Image.Image:
    """Logo en RGBA, sans marges transparentes, centré dans un carré transparent (rien n'est rogné)."""
    logo = image.convert("RGBA")
    cadre = logo.getchannel("A").getbbox()
    if cadre and retirer_marges:
        logo = logo.crop(cadre)
    cote = max(logo.size)
    carre = Image.new("RGBA", (cote, cote), (0, 0, 0, 0))
    carre.paste(logo, ((cote - logo.width) // 2, (cote - logo.height) // 2))
    return carre


def reduire(logo: Image.Image, taille: int) -> Image.Image:
    """Réduction LANCZOS sur l'alpha prémultiplié (pas de franges sombres sur les bords transparents)."""
    return logo.convert("RGBa").resize((taille, taille), Image.Resampling.LANCZOS).convert("RGBA")


def images_logo(chemin: Path, tailles) -> list[Image.Image]:
    """Une image par taille, chacune réduite directement depuis le logo d'origine."""
    with Image.open(chemin) as source:
        logo = preparer_logo(source)
    return [reduire(logo, t) for t in tailles]
