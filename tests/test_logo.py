"""Préparation du logo : détection du fichier à la racine, format réel, .ico multi-tailles sans perte."""
import importlib.util
import os
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).resolve().parent.parent / "assets" / "fabriquer_icone.py"


def charger_script():
    spec = importlib.util.spec_from_file_location("fabriquer_icone", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dessin(cote=500):
    image = Image.new("RGBA", (cote, cote), (0, 0, 0, 0))
    image.paste((200, 100, 50, 255), (cote // 5, cote // 10, cote * 4 // 5, cote * 9 // 10))
    return image


def tailles_ico(chemin):
    with Image.open(chemin) as ico:
        return set(ico.info["sizes"])


def test_logo_le_plus_recent_choisi(tmp_path):
    fab = charger_script()
    ancien, recent = tmp_path / "logo.jpg", tmp_path / "logo.png"
    Image.new("RGB", (10, 10)).save(ancien)
    dessin().save(recent)
    (tmp_path / "logo.txt").write_text("pas une image")
    os.utime(ancien, (1_000_000, 1_000_000))
    assert fab.trouver_logo(tmp_path) == recent


def test_png_copie_octet_pour_octet(tmp_path):
    fab = charger_script()
    source = tmp_path / "logo.png"
    dessin().save(source)
    sortie = tmp_path / "assets"
    sortie.mkdir()
    fab.fabriquer(source, sortie)
    assert (sortie / "logo.png").read_bytes() == source.read_bytes()
    assert {(t, t) for t in fab.TAILLES} == tailles_ico(sortie / "logo.ico")


def test_format_reel_lu_dans_le_fichier(tmp_path):
    """Un PNG nommé .ico est traité comme un PNG (format lu dans le contenu, pas dans l'extension)."""
    fab = charger_script()
    source = tmp_path / "logo.ico"
    dessin().save(source, format="PNG")
    sortie = tmp_path / "assets"
    sortie.mkdir()
    fab.fabriquer(source, sortie)
    assert (sortie / "logo.png").read_bytes() == source.read_bytes()


def test_ico_source_tailles_existantes_reprises_sans_redimensionnement(tmp_path):
    fab = charger_script()
    grand = dessin(256)
    petit = Image.new("RGBA", (32, 32), (10, 200, 30, 255))   # 32 px dessiné à la main, différent du 256
    source = tmp_path / "logo.ico"
    grand.save(source, format="ICO", sizes=[(256, 256), (32, 32)], append_images=[petit])
    sortie = tmp_path / "assets"
    sortie.mkdir()
    fab.fabriquer(source, sortie)
    assert {(t, t) for t in fab.TAILLES} == tailles_ico(sortie / "logo.ico")
    with Image.open(sortie / "logo.ico") as ico:
        ico.size = (32, 32)
        ico.load()
        assert ico.convert("RGBA").tobytes() == petit.tobytes()      # 32 px repris tel quel
    with Image.open(sortie / "logo.png") as png:
        assert png.size == (256, 256)                               # plus grande image de l'ICO


def test_logo_du_projet_a_jour():
    """assets/logo.png et assets/logo.ico existent ; l'ico contient toutes les tailles en pleine qualité."""
    fab = charger_script()
    assets = SCRIPT.parent
    with Image.open(assets / "logo.png") as logo:
        assert min(logo.size) >= 256
    assert {(t, t) for t in fab.TAILLES} == tailles_ico(assets / "logo.ico")
