import pytest

from wikimaster.page_model import PageSnapshot, View
from wikimaster.pack_manager import OUVRIR, SUIVANT, PackManager


def snap(t=0.0, dispo=1, prochain=120):
    return PageSnapshot(t, "u", View.PAQUETS, disponibles=dispo, capacite=10, prochain_dans_s=prochain,
                        bouton_ouvrir_present=True, bouton_ouvrir_actif=dispo > 0)


@pytest.fixture
def pm():
    return PackManager(capacite=10, objectif=3, delai_indicatif_s=180)


def test_un_seul_clic_a_la_fois(pm):
    a = pm.commencer(OUVRIR, snap(), 0.0, 2.0)
    assert a is not None
    assert pm.commencer(OUVRIR, snap(), 0.0, 2.0) is None
    assert pm.commencer(SUIVANT, snap(), 100.0, 2.0) is None   # même longtemps après
    ok, raison = pm.peut_cliquer(100.0, 2.0)
    assert not ok and "attend encore" in raison


def test_intervalle_minimum_entre_deux_clics(pm):
    a = pm.commencer(OUVRIR, snap(), 0.0, 2.0)
    pm.valider(a.id)
    assert pm.commencer(SUIVANT, snap(), 1.0, 2.0) is None
    assert pm.commencer(SUIVANT, snap(), 2.5, 2.0) is not None


def test_validation_comptee_une_seule_fois(pm):
    a = pm.commencer(OUVRIR, snap(), 0.0, 2.0)
    assert pm.valider(a.id) is True
    assert pm.valider(a.id) is False
    assert pm.ouverts == 1


def test_suivant_ne_compte_pas_comme_ouverture(pm):
    a = pm.commencer(SUIVANT, snap(), 0.0, 2.0)
    pm.valider(a.id)
    assert pm.ouverts == 0


def test_abandon_non_compte(pm):
    pm.commencer(OUVRIR, snap(), 0.0, 2.0)
    pm.abandonner()
    assert pm.ouverts == 0 and pm.echecs == 1 and pm.en_cours is None


def test_objectif_et_restants(pm):
    assert pm.restants == 3
    for t in range(3):
        a = pm.commencer(OUVRIR, snap(), t * 10.0, 2.0)
        pm.valider(a.id)
    assert pm.restants == 0 and pm.objectif_atteint


def test_sans_objectif():
    pm = PackManager(10, 0, 180)
    assert pm.restants is None and not pm.objectif_atteint


def test_minuteur_du_site_prioritaire(pm):
    pm.observer(snap(t=0.0, prochain=120))
    assert pm.temps_restant(30.0) == (90.0, "site")


def test_estimation_locale_si_minuteur_absent(pm):
    pm.observer(snap(t=0.0, dispo=1, prochain=None))
    restant, source = pm.temps_restant(60.0)
    assert source == "estimation locale" and restant == 120.0


def test_nouveau_pack_detecte(pm):
    assert pm.observer(snap(dispo=1)) is False
    assert pm.observer(snap(dispo=2)) is True
    assert pm.observer(snap(dispo=1)) is False
    assert pm.max_disponibles_vu == 2
