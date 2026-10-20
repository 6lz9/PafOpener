from dataclasses import replace

import pytest

from wikimaster.page_model import PageSnapshot, View
from wikimaster.page_monitor import PageMonitor, PageStatus, est_verification
from wikimaster.simulation import TEXTE_VERIFICATION

URL = "https://www.wiki-masters.com/pulls"
PAQUETS = PageSnapshot(0.0, URL, View.PAQUETS, disponibles=1, capacite=10, prochain_dans_s=129,
                       bouton_ouvrir_present=True, bouton_ouvrir_actif=True)
REVELATION = PageSnapshot(0.0, URL, View.REVELATION, carte_index=1, carte_total=5,
                          fleche_suivante_active=True, encore_n=4)
REVELATION_FINIE = replace(REVELATION, carte_index=5, fleche_suivante_active=False, encore_n=None,
                           bouton_continuer_present=True)


@pytest.fixture
def monitor():
    return PageMonitor(10, URL)


def test_page_des_paquets_normale(monitor):
    assert monitor.evaluer(PAQUETS).statut is PageStatus.NORMAL


def test_revelation_normale(monitor):
    assert monitor.evaluer(REVELATION).statut is PageStatus.NORMAL
    monitor.oublier_reference()
    assert monitor.evaluer(REVELATION_FINIE).statut is PageStatus.NORMAL


def test_zero_pack_bouton_inactif_normal(monitor):
    snap = replace(PAQUETS, disponibles=0, bouton_ouvrir_actif=False, bouton_achat_visible=True)
    assert monitor.evaluer(snap).statut is PageStatus.NORMAL


def test_plafond_sans_minuteur_normal(monitor):
    snap = replace(PAQUETS, disponibles=10, prochain_dans_s=None)
    assert monitor.evaluer(snap).statut is PageStatus.NORMAL


# --- fenêtre « Vérification rapide » (capture verification.png) --------------------------------------

@pytest.mark.parametrize("texte", [
    TEXTE_VERIFICATION,
    "Vérification rapide",
    "On vérifie que tu es bien humain. Ça ne prend qu'une seconde.",
    "VERIFICATION RAPIDE\n\nVérification...\nAnnuler",
    "Vérification…",
    "Please verify you are human",
])
def test_fenetre_de_verification_reconnue(monitor, texte):
    assert est_verification(texte)
    for vue in (PAQUETS, REVELATION):
        ev = monitor.evaluer(replace(vue, modale_texte=texte))
        assert ev.statut is PageStatus.VERIFICATION
        assert "Vérification automatique" in ev.raison


@pytest.mark.parametrize("texte", ["Nouveau succès débloqué !\nFermer", "Mise à jour disponible", ""])
def test_autre_fenetre_incertaine(monitor, texte):
    assert not est_verification(texte)
    ev = monitor.evaluer(replace(PAQUETS, modale_texte=texte))
    assert ev.statut is PageStatus.INCERTAIN
    assert "Fenêtre inattendue" in ev.raison


def test_verification_prioritaire_sur_le_reste(monitor):
    snap = replace(PAQUETS, vue=View.INCONNUE, disponibles=None, modale_texte=TEXTE_VERIFICATION)
    assert monitor.evaluer(snap).statut is PageStatus.VERIFICATION


# --- page des paquets ---------------------------------------------------------------------------------

@pytest.mark.parametrize("changes, statut, extrait", [
    ({"erreur": "Perte de connexion"}, PageStatus.ERREUR, "connexion"),
    ({"session_expiree": True}, PageStatus.ERREUR, "Session expirée"),
    ({"url": "https://www.wiki-masters.com/login"}, PageStatus.INCERTAIN, "Adresse inattendue"),
    ({"vue": View.INCONNUE}, PageStatus.INCERTAIN, "Interface inattendue"),
    ({"disponibles": None}, PageStatus.INCERTAIN, "illisible"),
    ({"capacite": 12}, PageStatus.INCERTAIN, "Capacité affichée"),
    ({"disponibles": 11}, PageStatus.INCERTAIN, "incohérent"),
    ({"bouton_ouvrir_present": False}, PageStatus.INCERTAIN, "absent"),
    ({"bouton_ouvrir_actif": False}, PageStatus.INCERTAIN, "inactif"),
    ({"disponibles": 0}, PageStatus.INCERTAIN, "actif alors qu'aucun"),
    ({"prochain_dans_s": None}, PageStatus.INCERTAIN, "Minuteur"),
])
def test_page_des_paquets_anormale(monitor, changes, statut, extrait):
    ev = monitor.evaluer(replace(PAQUETS, **changes))
    assert ev.statut is statut
    assert extrait in ev.raison


# --- révélation des cartes ----------------------------------------------------------------------------

@pytest.mark.parametrize("base, changes, extrait", [
    (REVELATION, {"carte_index": None}, "illisible"),
    (REVELATION, {"carte_index": 6}, "incohérent"),
    (REVELATION, {"bouton_continuer_present": True}, "en même temps"),
    (REVELATION, {"encore_n": None}, "Ni « Encore N cartes » ni « Continuer »"),
    (REVELATION, {"encore_n": 5}, "incohérent"),
    (REVELATION, {"fleche_suivante_active": False}, "flèche suivante inactive"),
    (REVELATION_FINIE, {"bouton_continuer_present": False}, "Ni « Encore N cartes »"),
])
def test_revelation_anormale(monitor, base, changes, extrait):
    ev = monitor.evaluer(replace(base, **changes))
    assert ev.statut is PageStatus.INCERTAIN
    assert extrait in ev.raison


# --- changements inexpliqués -------------------------------------------------------------------------

def test_baisse_inexpliquee_suspecte(monitor):
    monitor.evaluer(replace(PAQUETS, disponibles=3))
    ev = monitor.evaluer(replace(PAQUETS, disponibles=2))
    assert ev.statut is PageStatus.INCERTAIN and ev.suspect


def test_baisse_attendue_apres_ouverture(monitor):
    monitor.evaluer(replace(PAQUETS, disponibles=3))
    assert monitor.evaluer(replace(PAQUETS, disponibles=2), action_en_attente="ouvrir").normale


def test_revelation_sans_action_suspecte(monitor):
    monitor.evaluer(PAQUETS)
    ev = monitor.evaluer(REVELATION)
    assert ev.statut is PageStatus.INCERTAIN and ev.suspect
    monitor.evaluer(PAQUETS)
    assert monitor.evaluer(REVELATION, action_en_attente="ouvrir").normale


def test_carte_changee_sans_action_suspecte(monitor):
    monitor.evaluer(REVELATION)
    suivante = replace(REVELATION, carte_index=2, encore_n=3)
    assert monitor.evaluer(suivante).suspect
    monitor.evaluer(REVELATION, comparer=False)
    assert monitor.evaluer(suivante, action_en_attente="suivant").normale


def test_retour_aux_paquets_sans_continuer_suspect(monitor):
    monitor.evaluer(REVELATION_FINIE)
    assert monitor.evaluer(PAQUETS).suspect
    monitor.evaluer(REVELATION_FINIE, comparer=False)
    assert monitor.evaluer(PAQUETS, action_en_attente="continuer").normale


def test_pas_de_comparaison_pendant_une_pause(monitor):
    monitor.evaluer(replace(PAQUETS, disponibles=3))
    assert monitor.evaluer(replace(PAQUETS, disponibles=1), comparer=False).normale


def test_oublier_reference(monitor):
    monitor.evaluer(replace(PAQUETS, disponibles=3))
    monitor.oublier_reference()
    assert monitor.evaluer(replace(PAQUETS, disponibles=1)).normale


def test_nouveau_pack_n_est_pas_suspect(monitor):
    monitor.evaluer(replace(PAQUETS, disponibles=1))
    assert monitor.evaluer(replace(PAQUETS, disponibles=2)).normale
