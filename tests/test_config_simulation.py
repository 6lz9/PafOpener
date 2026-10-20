import json

import pytest

from wikimaster.config import Settings
from wikimaster.logger import ActivityLog
from wikimaster.page_model import View
from wikimaster.simulation import AcceleratedClock, ManualClock, SimulatedPage


# --- paramètres ----------------------------------------------------------------------------------

def test_valeurs_par_defaut():
    s = Settings()
    assert s.delai_indicatif_s == 180 and s.capacite_packs == 10 and s.validate() == []


def test_enregistrement_et_relecture(tmp_path):
    path = tmp_path / "settings.json"
    Settings(delai_indicatif_s=200, objectif_ouvertures=7).save(path)
    s = Settings.load(path)
    assert s.delai_indicatif_s == 200 and s.objectif_ouvertures == 7


def test_fichier_absent_valeurs_par_defaut(tmp_path):
    assert Settings.load(tmp_path / "absent.json") == Settings()


def test_cle_inconnue_ignoree(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"delai_indicatif_s": 150, "inconnue": 1}), encoding="utf-8")
    assert Settings.load(path).delai_indicatif_s == 150


@pytest.mark.parametrize("contenu", ['{"delai_indicatif_s": 0}', '{"delai_indicatif_s": "vite"}',
                                     '{"capacite_packs": 2.5}', "pas du json", "[]"])
def test_fichier_invalide_refuse(tmp_path, contenu):
    path = tmp_path / "settings.json"
    path.write_text(contenu, encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.load(path)


def test_seuils_aleatoires_par_defaut_5_a_8():
    s = Settings()
    assert (s.seuil_min, s.seuil_max) == (5, 8)


@pytest.mark.parametrize("reglages", [{"seuil_max": 10}, {"seuil_min": 9, "seuil_max": 8},
                                      {"seuil_min": 0}, {"capacite_packs": 8}])
def test_seuils_invalides_refuses(reglages):
    assert Settings(**reglages).validate()


def test_ancien_parametre_seuil_ouverture_ignore(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"seuil_ouverture": 1}', encoding="utf-8")
    assert Settings.load(path) == Settings()


# --- journal ---------------------------------------------------------------------------------------

def test_journal_horodate_et_fichier(tmp_path):
    log = ActivityLog(tmp_path / "logs" / "a.log")
    log.info("bonjour")
    log.warning("attention")
    entrees = log.drain()
    assert [e.niveau for e in entrees] == ["INFO", "ATTENTION"]
    assert log.drain() == []
    assert entrees[0].format().startswith("[")
    contenu = (tmp_path / "logs" / "a.log").read_text(encoding="utf-8")
    assert "bonjour" in contenu and "attention" in contenu


# --- page simulée ------------------------------------------------------------------------------------

def test_generation_d_un_pack_toutes_les_180_s():
    clock = ManualClock()
    page = SimulatedPage(clock, disponibles=0, delai_s=180)
    assert page.read_snapshot().prochain_dans_s == 180
    clock.advance(179)
    assert page.read_snapshot().disponibles == 0
    clock.advance(1)
    snap = page.read_snapshot()
    assert snap.disponibles == 1 and snap.prochain_dans_s == 180


def test_plafond_bloque_la_generation():
    clock = ManualClock()
    page = SimulatedPage(clock, disponibles=9, delai_s=180)
    clock.advance(10_000)
    snap = page.read_snapshot()
    assert snap.disponibles == 10 and snap.prochain_dans_s is None


def test_bouton_achat_visible_a_zero_mais_jamais_cliquable():
    page = SimulatedPage(ManualClock(), disponibles=0)
    snap = page.read_snapshot()
    assert snap.bouton_achat_visible and not snap.bouton_ouvrir_actif
    page.click_open()
    assert page.clics_ignores == 1 and page.achats == 0
    assert not hasattr(page, "click_purchase")


def test_revelation_fleche_puis_encore_n_puis_continuer():
    page = SimulatedPage(ManualClock(), disponibles=1)
    page.click_open()
    snap = page.read_snapshot()
    assert snap.vue is View.REVELATION and snap.carte_index == 1
    assert snap.encore_n == 4 and not snap.bouton_continuer_present and snap.fleche_suivante_active
    page.click_continue()                      # « Continuer » n'existe pas encore : sans effet
    assert page.clics_ignores == 1 and page.read_snapshot().vue is View.REVELATION
    for i, encore in zip(range(2, 5), (3, 2, 1)):
        page.click_next_card()
        snap = page.read_snapshot()
        assert (snap.carte_index, snap.encore_n, snap.bouton_continuer_present) == (i, encore, False)
    page.click_next_card()
    snap = page.read_snapshot()
    assert snap.carte_index == 5 and snap.encore_n is None and snap.bouton_continuer_present
    assert not snap.fleche_suivante_active
    page.click_continue()
    snap = page.read_snapshot()
    assert snap.vue is View.PAQUETS and snap.disponibles == 0


def test_verification_rapide_disparait_seule():
    clock = ManualClock()
    page = SimulatedPage(clock)
    page.declencher_verification(5)
    snap = page.read_snapshot()
    assert snap.modale_texte.startswith("Vérification rapide")
    assert snap.vue is View.PAQUETS            # la page reste derrière, floutée
    page.click_open()
    assert page.clics_pendant_modale == 1 and page.packs_ouverts == 0
    clock.advance(5)
    assert page.read_snapshot().modale_texte is None


def test_horloge_acceleree_sans_saut():
    clock = AcceleratedClock(100)
    t1 = clock()
    clock.set_vitesse(1)
    assert clock() >= t1


def test_temporisation_par_defaut_et_validation():
    s = Settings()
    assert (s.delai_clic_min_s, s.delai_clic_max_s) == (0.8, 1.8)
    assert Settings(delai_clic_min_s=2, delai_clic_max_s=1).validate()
    assert Settings(delai_clic_max_s=30).validate()
    assert Settings(delai_clic_min_s=-1).validate()


def test_dossier_application_exe_a_cote_du_exe(monkeypatch, tmp_path):
    """Exécutable PyInstaller : settings.json, logs/ et chrome_profile/ à côté du .exe, pas dans le dossier temporaire."""
    import sys

    from wikimaster.config import dossier_application
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "PafOpener.exe"))
    assert dossier_application() == tmp_path.resolve()


def test_dossier_application_mac_hors_du_app(monkeypatch, tmp_path):
    """Application Mac : données dans ~/Library/Application Support/PafOpener, jamais dans PafOpener.app."""
    import sys
    from pathlib import Path

    from wikimaster.config import dossier_application
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "PafOpener.app/Contents/MacOS/PafOpener"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "maison")
    dossier = dossier_application()
    assert dossier == tmp_path / "maison" / "Library" / "Application Support" / "PafOpener"
    assert dossier.is_dir()


def test_dossier_application_projet_hors_exe():
    from pathlib import Path

    from wikimaster.config import dossier_application
    assert dossier_application() == Path(__file__).resolve().parent.parent
