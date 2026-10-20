"""Pilote réel (browser.RealPage) testé sur des copies locales de la vraie page, dans un Chrome headless.

Aucune connexion à wiki-masters.com : les pages viennent de tests/fixtures/ (zone <main> relevée le
14/10/2026 + quelques pages synthétiques). Chaque clic réellement reçu par la page est enregistré dans
window.__clics, ce qui permet de prouver qu'aucun bouton interdit n'est jamais cliqué.
"""
from pathlib import Path

import pytest

from wikimaster.browser import CibleInterdite, RealPage, cible_autorisee, snapshot_depuis_donnees
from wikimaster.page_model import View
from wikimaster.page_monitor import PageMonitor, PageStatus

FIXTURES = Path(__file__).resolve().parent / "fixtures"
URL = "https://www.wiki-masters.com/pulls"

# Ordre des boutons de <main> dans les fixtures (relevé indépendamment du pilote).
#   page des paquets : 0 « Comment ça marche ? », 1 « Ouvrir »
#   révélation       : 0 favoris, 1 flèche ‹, 2-6 points, 7 flèche ›, 8 « Encore N » / « Continuer »
INDEX_OUVRIR = 1
INDEX_FLECHE_DROITE = 7
INDEX_CONTINUER = 8


class FournisseurContenu:
    """Ouvre une fixture dans un Chrome headless local (même thread que le pilote)."""

    def __init__(self, fichier: str):
        self.fichier = fichier
        self._pw = self._navigateur = self._page = None

    def page(self):
        if self._page is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._navigateur = self._pw.chromium.launch(channel="chrome", headless=True)
            self._page = self._navigateur.new_page(viewport={"width": 1920, "height": 945})
            self._page.route("**/*", lambda route: route.abort())   # aucun accès réseau
            self._page.set_content((FIXTURES / self.fichier).read_text(encoding="utf-8"))
        return self._page

    def clics(self):
        return self._page.evaluate("() => window.__clics")

    def fermer(self):
        if self._pw is not None:
            self._navigateur.close()
            self._pw.stop()
            self._pw = None


@pytest.fixture
def pilote():
    ouverts = []

    def ouvrir(fichier: str) -> RealPage:
        fournisseur = FournisseurContenu(fichier)
        p = RealPage(fournisseur=lambda: fournisseur, timeout_clic_ms=800)
        p.fournisseur = fournisseur
        p.clics = lambda: p._executer(fournisseur.clics)
        try:
            p.read_snapshot()
        except Exception as exc:  # Chrome indisponible sur la machine
            p.fermer()
            pytest.skip(f"Chrome headless indisponible : {exc}")
        ouverts.append(p)
        return p

    yield ouvrir
    for p in ouverts:
        p.fermer()


# --- lecture des vrais écrans ------------------------------------------------------------------------

def _url(snap):
    # set_content donne l'URL about:blank : on vérifie le reste et on remet l'URL attendue.
    from dataclasses import replace
    return replace(snap, url=URL)


def test_lecture_page_des_paquets(pilote):
    s = pilote("paquets_6.html").read_snapshot()
    assert s.vue is View.PAQUETS
    assert (s.disponibles, s.capacite, s.prochain_dans_s) == (6, 10, 62)   # « 1:02 » au moment du relevé
    assert s.bouton_ouvrir_present and s.bouton_ouvrir_actif
    assert not s.bouton_achat_visible and not s.ouverture_en_cours and s.modale_texte is None
    assert PageMonitor(10, URL).evaluer(_url(s)).normale


def test_lecture_pret(pilote):
    s = pilote("paquets_pret.html").read_snapshot()
    assert (s.disponibles, s.prochain_dans_s) == (6, 0)          # « Prochain dans Prêt ! »
    assert PageMonitor(10, URL).evaluer(_url(s)).normale


def test_lecture_ouverture_en_cours(pilote):
    s = pilote("paquets_ouverture.html").read_snapshot()
    assert s.vue is View.PAQUETS and s.ouverture_en_cours
    assert not s.bouton_ouvrir_present and s.disponibles == 7
    m = PageMonitor(10, URL)
    assert m.evaluer(_url(s), action_en_attente="ouvrir").normale    # attendu après notre clic
    m.oublier_reference()
    assert m.evaluer(_url(s)).statut is PageStatus.INCERTAIN          # sinon : suspect


@pytest.mark.parametrize("fichier, index, encore, fleche, continuer", [
    ("carte_1.html", 1, 4, True, False),
    ("carte_4.html", 4, 1, True, False),          # « Encore 1 carte » (singulier)
    ("carte_5.html", 5, None, False, True),
])
def test_lecture_revelation(pilote, fichier, index, encore, fleche, continuer):
    s = pilote(fichier).read_snapshot()
    assert s.vue is View.REVELATION
    assert (s.carte_index, s.carte_total, s.encore_n) == (index, 5, encore)
    assert s.fleche_suivante_active is fleche and s.bouton_continuer_present is continuer
    m = PageMonitor(10, URL)
    assert m.evaluer(_url(s)).normale


def test_lecture_stock_zero_avec_achat(pilote):
    s = pilote("synth_paquets_0_achat.html").read_snapshot()
    assert (s.disponibles, s.bouton_ouvrir_actif, s.bouton_achat_visible) == (0, False, True)
    assert PageMonitor(10, URL).evaluer(_url(s)).normale


def test_lecture_verification_rapide(pilote):
    s = pilote("synth_verification.html").read_snapshot()
    assert "Vérification rapide" in s.modale_texte
    assert PageMonitor(10, URL).evaluer(_url(s)).statut is PageStatus.VERIFICATION


# --- clics autorisés : exactement le bon bouton --------------------------------------------------------

def test_clic_ouvrir(pilote):
    p = pilote("paquets_6.html")
    p.click_open()
    assert [c["index"] for c in p.clics()] == [INDEX_OUVRIR]


def test_clic_fleche_droite(pilote):
    p = pilote("carte_1.html")
    p.click_next_card()
    assert [c["index"] for c in p.clics()] == [INDEX_FLECHE_DROITE]


def test_clic_continuer(pilote):
    p = pilote("carte_5.html")
    p.click_continue()
    assert p.clics() == [{"index": INDEX_CONTINUER, "texte": "Continuer", "aria": None}]


def test_ouvrir_ignore_le_piege_du_pack_pro(pilote):
    p = pilote("synth_pack_pro_ouvrir.html")
    p.click_open()
    clics = p.clics()
    assert len(clics) == 1 and clics[0]["index"] == INDEX_OUVRIR


# --- clics refusés : rien n'est envoyé -----------------------------------------------------------------

@pytest.mark.parametrize("fichier, methode", [
    ("synth_paquets_0_achat.html", "click_open"),      # « Ouvrir » désactivé, bouton d'achat présent
    ("synth_deux_ouvrir.html", "click_open"),          # ambigu
    ("carte_1.html", "click_continue"),                # « Continuer » pas encore là (« Encore 4 » inactif)
    ("carte_1.html", "click_open"),
    ("carte_5.html", "click_next_card"),               # flèche › désactivée sur la dernière carte
    ("paquets_6.html", "click_next_card"),
    ("paquets_6.html", "click_continue"),
    ("paquets_ouverture.html", "click_open"),          # « Ouverture... » inactif
    ("synth_verification.html", "click_open"),         # bouton recouvert par la fenêtre
])
def test_clic_refuse_sans_rien_envoyer(pilote, fichier, methode):
    p = pilote(fichier)
    with pytest.raises(Exception) as info:
        getattr(p, methode)()
    if fichier != "synth_verification.html":
        assert isinstance(info.value, CibleInterdite)
    assert p.clics() == []


@pytest.mark.parametrize("fichier", sorted(f.name for f in FIXTURES.glob("*.html")))
def test_aucun_bouton_interdit_jamais_clique(pilote, fichier):
    """Toutes les méthodes de clic, sur toutes les pages : seuls Ouvrir, › et Continuer peuvent être reçus."""
    p = pilote(fichier)
    for methode in ("click_open", "click_next_card", "click_continue"):
        try:
            getattr(p, methode)()
        except Exception:
            pass
    for clic in p.clics():
        autorise = (clic["texte"] in ("Ouvrir", "Continuer") and clic["index"] in (INDEX_OUVRIR, INDEX_CONTINUER)) \
            or (clic["texte"] == "" and clic["index"] == INDEX_FLECHE_DROITE and fichier.startswith("carte_"))
        assert autorise, f"clic interdit reçu sur {fichier} : {clic}"
        assert clic["aria"] is None


# --- liste blanche (sans navigateur) --------------------------------------------------------------------

BON = {"tag": "button", "texte": "Ouvrir", "aria": "", "titre": "", "desactive": False, "dans_main": True,
       "dans_pack_pro": False, "est_fleche_droite": False, "visible": True}


@pytest.mark.parametrize("action, changes, extrait", [
    ("ouvrir", {"texte": "Rechargez 10 paquets — 1,99 $ CAD"}, "interdit"),
    ("ouvrir", {"texte": "Comment ça marche ?"}, "interdit"),
    ("ouvrir", {"dans_pack_pro": True}, "Pack PRO"),
    ("ouvrir", {"texte": "Réclamer le Pack PRO"}, "interdit"),
    ("ouvrir", {"texte": "Ouvrir", "aria": "Acheter"}, "interdit"),
    ("ouvrir", {"desactive": True}, "désactivé"),
    ("ouvrir", {"dans_main": False}, "hors"),
    ("ouvrir", {"tag": "a"}, "bouton"),
    ("ouvrir", {"visible": False}, "invisible"),
    ("ouvrir", {"texte": "Ouverture..."}, "texte"),
    ("continuer", {"texte": "Encore 4 cartes"}, "texte"),
    ("suivant", {"texte": "", "aria": "Ajouter aux favoris (verrouille la carte : ni défausse)"}, "interdit"),
    ("suivant", {"texte": "", "est_fleche_droite": False}, "flèche droite"),
    ("acheter", {}, "inconnue"),
])
def test_liste_blanche_refuse(action, changes, extrait):
    ok, raison = cible_autorisee(action, {**BON, **changes})
    assert not ok and extrait in raison


def test_liste_blanche_accepte():
    assert cible_autorisee("ouvrir", BON) == (True, "")
    assert cible_autorisee("continuer", {**BON, "texte": "Continuer"}) == (True, "")
    assert cible_autorisee("suivant", {**BON, "texte": "", "est_fleche_droite": True}) == (True, "")


def test_snapshot_session_expiree_et_hors_ligne():
    s = snapshot_depuis_donnees({"url": "https://www.wiki-masters.com/login"}, 0.0)
    assert s.session_expiree
    s = snapshot_depuis_donnees({"url": URL, "en_ligne": False}, 0.0)
    assert s.erreur and "hors ligne" in s.erreur
    s = snapshot_depuis_donnees({"url": URL, "en_ligne": True}, 0.0)
    assert s.vue is View.INCONNUE


def test_releve_automatique_de_la_verification(pilote, tmp_path, monkeypatch):
    import wikimaster.browser as browser
    monkeypatch.setattr(browser, "INSPECTION_DIR", tmp_path)
    p = pilote("synth_verification.html")
    base = p.capturer("verification")
    assert base.with_suffix(".png").exists() and base.with_suffix(".html").exists()
    assert "Vérification rapide" in base.with_suffix(".json").read_text(encoding="utf-8")
    assert p.clics() == []                                   # relevé sans aucun clic
