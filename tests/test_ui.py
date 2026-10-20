"""Test de fumée de l'interface Tkinter avec la page simulée et le vrai thread de travail."""
import time
import tkinter as tk

import pytest

from wikimaster.config import Settings
from wikimaster.controller import BotState, Controller
from wikimaster.logger import ActivityLog
from wikimaster.simulation import AcceleratedClock, SimulatedPage, URL_SIMULEE
from wikimaster.ui import App, format_duree


@pytest.fixture(scope="module")
def racine_tk():
    # Un seul tk.Tk() par processus : en créer plusieurs de suite échoue parfois sous Windows
    # (« invalid command name tcl_findLibrary »). Chaque test ouvre sa fenêtre en Toplevel.
    try:
        racine = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Pas d'affichage disponible : {exc}")
    racine.withdraw()
    yield racine
    racine.destroy()


@pytest.fixture
def app(tmp_path, monkeypatch, racine_tk):
    # Une boîte de dialogue modale bloquerait les tests : on la transforme en échec immédiat.
    def boite_interdite(titre, message, **_):
        raise AssertionError(f"Boîte de dialogue inattendue « {titre} » : {message}")
    monkeypatch.setattr("wikimaster.ui.messagebox.showerror", boite_interdite)
    root = tk.Toplevel(racine_tk)
    root.withdraw()
    clock = AcceleratedClock(50)
    page = SimulatedPage(clock, disponibles=3)
    log = ActivityLog()
    ctrl = Controller(page, Settings(intervalle_lecture_s=0.1, seuil_min=1, seuil_max=2,
                                     verification_delai_max_s=3600), log,
                      clock=clock, prefixe_url=URL_SIMULEE)
    application = App(root, ctrl, log, simulation=page, clock=clock, settings_path=tmp_path / "s.json")
    yield application
    try:
        application.fermer()
    except tk.TclError:
        pass


def pomper(app, secondes, condition=lambda: False):
    fin = time.monotonic() + secondes
    while time.monotonic() < fin:
        app.root.update()
        if condition():
            break
        time.sleep(0.02)
    # laisser passer au moins un rafraîchissement de l'interface (250 ms)
    fin = time.monotonic() + 0.35
    while time.monotonic() < fin:
        app.root.update()
        time.sleep(0.02)
    return condition()


def test_boutons_et_affichage(app):
    assert app.lbl_etat.cget("text") == "En attente"
    assert str(app.btn_pause.cget("state")) == "disabled"
    app.btn_demarrer.invoke()
    assert pomper(app, 10, lambda: app.controller.status().ouverts >= 1)
    assert app.lbl_etat.cget("text") == "En cours"
    assert int(app.compteurs["ouverts"].cget("text")) >= 1
    assert "Seuil aléatoire actuel" in app.lbl_seuil.cget("text")
    assert str(app.btn_demarrer.cget("state")) == "disabled"

    app.btn_pause.invoke()
    pomper(app, 0.3)
    assert app.lbl_etat.cget("text") == "En pause"
    assert str(app.btn_reprendre.cget("state")) == "normal"
    assert str(app.btn_confirmer.cget("state")) == "disabled"
    app.btn_reprendre.invoke()
    pomper(app, 0.3)
    assert app.lbl_etat.cget("text") == "En cours"

    app.simulation.declencher_verification(10_000)
    assert pomper(app, 5, lambda: app.controller.state is BotState.VERIFICATION)
    pomper(app, 0.3)
    assert app.lbl_etat.cget("text") == "Vérification détectée"
    assert "⚠" in app.lbl_page.cget("text")
    assert "attente passive" in app.lbl_raison.cget("text")
    assert str(app.btn_reprendre.cget("state")) == "disabled"
    assert str(app.btn_confirmer.cget("state")) == "disabled"   # pas de confirmation à donner
    assert str(app.btn_pause.cget("state")) == "normal"
    clics = app.simulation.clics_total
    pomper(app, 0.5)
    assert app.simulation.clics_total == clics

    app.simulation.terminer_verification()                    # disparaît d'elle-même
    assert pomper(app, 5, lambda: app.controller.state is BotState.EN_COURS)
    assert "Reprise automatique" in app.journal.get("1.0", "end")

    app.btn_arreter.invoke()
    pomper(app, 0.3)
    assert app.lbl_etat.cget("text") == "Arrêté"
    assert "ARRÊT" in app.journal.get("1.0", "end")


def test_parametres_depuis_l_interface(app):
    app.var_delai.set("240")
    app.var_objectif.set("4")
    app.var_seuil_min.set("6")
    app.var_seuil_max.set("7")
    assert app.appliquer_parametres() is True
    assert (app.controller.settings.seuil_min, app.controller.settings.seuil_max) == (6, 7)
    assert app.controller.status().seuil_actuel in (6, 7)
    assert app.controller.settings.delai_indicatif_s == 240
    assert app.controller.settings.objectif_ouvertures == 4
    app.enregistrer_parametres()
    assert Settings.load(app.settings_path).delai_indicatif_s == 240


def test_curseurs_temporisation_avant_clic(app):
    assert (app.var_clic_min.get(), app.var_clic_max.get()) == (0.8, 1.8)
    assert app.lbl_clic_valeurs["Minimum"].cget("text") == "0,8 s"
    app.var_clic_min.set(0.3)
    app.var_clic_max.set(3.0)
    app._curseur_clic(False)
    assert "entre 0,3 s et 3,0 s" in app.lbl_clic_resume.cget("text")
    assert app.appliquer_parametres() is True
    assert (app.controller.settings.delai_clic_min_s, app.controller.settings.delai_clic_max_s) == (0.3, 3.0)
    app.enregistrer_parametres()
    relu = Settings.load(app.settings_path)
    assert (relu.delai_clic_min_s, relu.delai_clic_max_s) == (0.3, 3.0)


def test_curseur_minimum_au_dessus_du_maximum_entraine_le_maximum(app):
    app.var_clic_min.set(4.2)
    app._curseur_clic(True)
    assert app.var_clic_max.get() == 4.2
    app.var_clic_max.set(1.0)
    app._curseur_clic(False)
    assert app.var_clic_min.get() == 1.0


def test_onglet_discord(app, monkeypatch):
    assert app.var_webhook.get() == "" and app.var_bilan.get() is False
    url = "https://discord.com/api/webhooks/1/abc"
    app.var_webhook.set(f"  {url} ")
    app.var_bilan.set(True)
    assert app.appliquer_parametres() is True
    assert app.controller.settings.discord_webhook_url == url
    assert app.controller.settings.discord_bilan_session is True
    app.enregistrer_parametres()
    assert Settings.load(app.settings_path).discord_webhook_url == url

    testes = []
    monkeypatch.setattr(app.controller, "tester_notification", lambda u: testes.append(u) or True)
    assert app.tester_webhook() is True and testes == [url]


def test_webhook_invalide_refuse(app, monkeypatch):
    erreurs = []
    monkeypatch.setattr("wikimaster.ui.messagebox.showerror", lambda titre, message, **_: erreurs.append(message))
    app.var_webhook.set("http://pas-securise.example")
    assert app.appliquer_parametres() is False
    assert app.tester_webhook() is False
    assert len(erreurs) == 2 and "https://" in erreurs[0]
    assert app.controller.settings.discord_webhook_url == ""


def test_format_duree():
    assert format_duree(129) == "2:09"
    assert format_duree(None) == "--:--"


def test_bandeau_action_humaine(app):
    app.btn_demarrer.invoke()
    pomper(app, 0.5)
    app.simulation.declencher_case_cloudflare()
    assert pomper(app, 5, lambda: app.controller.status().action_humaine_requise)
    assert app.lbl_action_humaine.winfo_manager() == "pack"
    assert "Action humaine requise : cochez la case dans Chrome" in app.lbl_action_humaine.cget("text")
    app.simulation.cocher_case_humain()
    assert pomper(app, 5, lambda: app.controller.state is BotState.EN_COURS)
    assert app.lbl_action_humaine.winfo_manager() == ""


def test_logo_reduit_aux_tailles_exactes(tmp_path):
    """Le logo est mis au carré puis réduit à chaque taille demandée, sans repasser par une autre taille."""
    from PIL import Image

    from wikimaster.logo import images_logo
    source = tmp_path / "logo.jpg"
    Image.new("RGB", (826, 555), "white").save(source)
    images = images_logo(source, [256, 40, 20, 16])
    assert [im.size for im in images] == [(256, 256), (40, 40), (20, 20), (16, 16)]
    assert all(im.mode == "RGBA" for im in images)


def test_logo_marges_transparentes_retirees():
    """Le dessin remplit le carré : les marges transparentes sont retirées, rien n'est rogné."""
    from PIL import Image

    from wikimaster.logo import preparer_logo
    image = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
    image.paste((200, 100, 50, 255), (100, 50, 400, 450))     # dessin 300 × 400 au milieu de marges vides
    logo = preparer_logo(image)
    assert logo.size == (400, 400)
    assert logo.getchannel("A").getbbox() == (50, 0, 350, 400)


def test_reduction_sans_frange_sombre():
    """Alpha prémultiplié : un bord transparent noir ne fonce pas les pixels colorés après réduction."""
    from PIL import Image

    from wikimaster.logo import reduire
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    image.paste((255, 255, 255, 255), (0, 0, 32, 64))
    r, g, b, a = reduire(image, 16).getpixel((8, 8))
    assert a > 0 and min(r, g, b) >= 250


def test_tailles_icone_triees_avec_tailles_usuelles():
    from wikimaster.ui import tailles_icone
    tailles = tailles_icone()
    assert tailles == sorted(tailles, reverse=True)
    assert {16, 20, 24, 32, 40, 48}.issubset(tailles)


def test_logo_et_icone_fournis():
    """Le logo d'origine (pleine résolution) et un .ico contenant toutes les tailles Windows existent."""
    from PIL import Image

    from wikimaster.config import ICONE_PATH, LOGO_PATH
    with Image.open(LOGO_PATH) as logo:
        assert min(logo.size) >= 256
    with Image.open(ICONE_PATH) as icone:
        assert {(t, t) for t in (16, 20, 24, 32, 40, 48, 256)}.issubset(icone.info["sizes"])


def test_icone_appliquee_a_la_fenetre(app):
    assert len(app.root._photos_icone) >= 7
    assert app.root._photos_icone[0].width() == max(p.width() for p in app.root._photos_icone)
