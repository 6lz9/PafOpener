"""Prépare le logo de PafOpener : assets/logo.png (logo d'origine) et assets/logo.ico (icône de PafOpener.exe).

    .venv\\Scripts\\python.exe assets\\fabriquer_icone.py              # logo le plus récent de C:\\Users\\Lee\\Desktop\\Bot
    .venv\\Scripts\\python.exe assets\\fabriquer_icone.py chemin\\logo  # ou un fichier précis

Le format est lu dans le fichier lui-même (PNG, ICO, JPG…), pas déduit de son extension.
- Source PNG : copiée telle quelle, octet pour octet. Autre format : converti en PNG sans perte.
- Source ICO : on part de sa plus grande image. Chaque taille que l'ICO contient déjà est reprise telle quelle,
  et les tailles manquantes sont calculées depuis la plus grande.
Toutes les réductions sont faites en LANCZOS depuis l'original (voir wikimaster/logo.py). Les tailles 20, 40 et
96 servent aux affichages à 125 %, 150 % et 200 %.
"""
import shutil
import sys
from pathlib import Path

from PIL import Image

DOSSIER = Path(__file__).resolve().parent
RACINE = DOSSIER.parent.parent   # C:\Users\Lee\Desktop\Bot, où l'on dépose le logo
sys.path.insert(0, str(DOSSIER.parent))

from wikimaster.logo import preparer_logo, reduire  # noqa: E402

TAILLES = (256, 128, 96, 64, 48, 40, 32, 24, 20, 16)
EXTENSIONS = {".png", ".ico", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def trouver_logo(racine: Path = RACINE) -> Path:
    """Le fichier « logo.* » le plus récent de la racine."""
    candidats = [p for p in racine.glob("logo.*") if p.suffix.lower() in EXTENSIONS]
    if not candidats:
        raise SystemExit(f"Aucun fichier logo.* dans {racine}")
    return max(candidats, key=lambda p: p.stat().st_mtime)


def images_ico(source: Image.Image) -> dict[int, Image.Image]:
    """Images carrées déjà présentes dans un ICO, par taille (sans aucun redimensionnement)."""
    images = {}
    for largeur, hauteur in sorted(source.info.get("sizes", ())):
        if largeur == hauteur:
            source.size = (largeur, hauteur)
            source.load()
            images[largeur] = source.convert("RGBA")
    return images


def fabriquer(chemin: Path, dossier: Path = DOSSIER) -> None:
    """Écrit dossier/logo.png et dossier/logo.ico à partir du logo `chemin`."""
    with Image.open(chemin) as source:
        format_reel = source.format
        if format_reel == "ICO":
            existantes = images_ico(source)
            original = existantes[max(existantes)]
        else:
            existantes = {}
            original = source.convert("RGBA")
    print(f"Logo : {chemin.name} (format réel {format_reel}, {original.width}×{original.height} px)")
    if min(original.size) < max(TAILLES):
        print(f"Attention : logo plus petit que {max(TAILLES)} px, les grandes tailles seront agrandies (moins nettes).")

    if format_reel == "PNG":
        shutil.copyfile(chemin, dossier / "logo.png")
    else:
        original.save(dossier / "logo.png", format="PNG", optimize=True)

    # Un ICO est déjà cadré par son auteur : on garde son cadrage pour que toutes les tailles se ressemblent.
    logo = preparer_logo(original, retirer_marges=format_reel != "ICO")
    images = [existantes[t] if t in existantes and t != max(existantes) else reduire(logo, t) for t in TAILLES]
    images[0].save(dossier / "logo.ico", format="ICO", sizes=[(t, t) for t in TAILLES], append_images=images[1:])
    reprises = sorted(t for t in TAILLES if t in existantes and t != max(existantes))
    print(f"logo.ico : {', '.join(str(t) for t in TAILLES)} px"
          + (f" (reprises de l'ICO d'origine : {reprises})" if reprises else ""))


if __name__ == "__main__":
    fabriquer(Path(sys.argv[1]) if len(sys.argv) > 1 else trouver_logo())
