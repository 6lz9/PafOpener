"""Rythme d'ouverture aléatoire : seuil tiré entre min et max, vidage jusqu'à 0, nouveau tirage."""
import random
import re

import pytest

from wikimaster.controller import BotState
from wikimaster.pack_manager import ACCUMULATION, VIDAGE, CycleAleatoire
from wikimaster.page_model import View

ALEATOIRE = {"seuil_min": 5, "seuil_max": 8}


# --- CycleAleatoire seul --------------------------------------------------------------------------

def test_seuil_toujours_dans_les_bornes():
    cycle = CycleAleatoire(5, 8, random.Random(1))
    tirages = {cycle.tirer() for _ in range(500)}
    assert tirages == {5, 6, 7, 8}


def test_accumulation_puis_vidage_puis_nouveau_tirage():
    cycle = CycleAleatoire(5, 8, random.Random(3))
    seuil = cycle.seuil
    for dispo in range(seuil):
        assert cycle.faut_il_ouvrir(dispo) == (False, "")
        assert cycle.phase == ACCUMULATION
    ouvrir, evenement = cycle.faut_il_ouvrir(seuil)
    assert ouvrir and "Seuil aléatoire atteint" in evenement and cycle.phase == VIDAGE
    for dispo in range(seuil - 1, 0, -1):          # on ouvre jusqu'à 0, même sous le seuil
        assert cycle.faut_il_ouvrir(dispo)[0] is True
    ouvrir, evenement = cycle.faut_il_ouvrir(0)
    assert not ouvrir and "Nouveau seuil aléatoire" in evenement
    assert cycle.phase == ACCUMULATION and cycle.cycles_termines == 1
    assert 5 <= cycle.seuil <= 8


def test_seuil_fixe_si_min_egal_max():
    cycle = CycleAleatoire(6, 6)
    assert {cycle.tirer() for _ in range(50)} == {6}


# --- avec le contrôleur -----------------------------------------------------------------------------

def test_attend_le_seuil_sans_ouvrir(make_banc):
    b = make_banc(ALEATOIRE, disponibles=0, delai_s=180)
    b.ctrl.start()
    seuil = b.status.seuil_actuel
    assert 5 <= seuil <= 8
    assert b.status.phase == ACCUMULATION
    # juste avant que le seuil soit atteint : aucun clic
    b.run(int(seuil * 180) - 5)
    assert b.page.disponibles == seuil - 1
    assert b.clics() == 0
    assert b.status.attente_seuil_s is not None and b.status.attente_seuil_s <= 6
    # le seuil est atteint : ouverture
    assert b.run_until(lambda: b.page.clics_ouvrir == 1, max_ticks=20)
    assert b.status.phase == VIDAGE
    assert "Seuil aléatoire atteint" in b.journal()


def test_vide_le_stock_jusqu_a_zero_puis_retire_un_seuil(make_banc):
    b = make_banc(ALEATOIRE, disponibles=8, delai_s=180)
    b.ctrl.start()
    assert b.run_until(lambda: "Stock vidé" in b.journal(), max_ticks=2000)
    assert b.page.disponibles == 0
    assert b.page.vue is View.PAQUETS
    assert b.status.ouverts == b.page.packs_ouverts >= 8
    assert b.status.phase == ACCUMULATION
    assert 5 <= b.status.seuil_actuel <= 8
    # plus aucune ouverture tant que le nouveau seuil n'est pas atteint
    ouverts = b.page.packs_ouverts
    b.run(4 * 180)
    assert b.page.packs_ouverts == ouverts
    assert b.status.etat is BotState.EN_COURS


def test_six_heures_jamais_au_plafond_et_rythme_aleatoire(make_banc):
    b = make_banc(ALEATOIRE, graine=7, disponibles=0, delai_s=180, alea_s=60, seed=11)
    b.ctrl.start()
    b.run(6 * 3600)  # 6 heures simulées
    assert b.status.etat is BotState.EN_COURS, b.journal()
    assert b.page.max_disponibles <= 8 < 10
    # « Seuil aléatoire atteint (stock ≥ seuil) » : un message par début de cycle
    debuts = [tuple(map(int, re.search(r"\((\d+) ≥ (\d+)\)", m).groups()))
              for m in b.log.messages() if m.startswith("Seuil aléatoire atteint")]
    assert len(debuts) >= 10
    assert all(stock == seuil and 5 <= seuil <= 8 for stock, seuil in debuts), debuts
    assert len({s for _, s in debuts}) >= 3, f"seuils pas assez variés : {debuts}"
    assert b.journal().count("Stock vidé") >= len(debuts) - 1
    # chaque ouverture du stock réel a bien eu lieu quand le stock était entre 1 et 8
    assert all(1 <= s <= 8 for _, s in b.page.historique_ouvertures)
    assert b.page.clics_ignores == 0 and b.page.achats == 0


def test_demarrage_avec_stock_deja_au_dessus_du_seuil(make_banc):
    b = make_banc(ALEATOIRE, disponibles=9)
    b.ctrl.start()
    assert b.run_until(lambda: b.page.clics_ouvrir == 1, max_ticks=10)


def test_changement_des_bornes_retire_un_seuil(make_banc):
    b = make_banc(ALEATOIRE, disponibles=0)
    b.ctrl.start()
    assert b.ctrl.apply_settings(b.ctrl.settings.with_changes(seuil_min=2, seuil_max=3)) == []
    assert 2 <= b.status.seuil_actuel <= 3


@pytest.mark.parametrize("reglages", [{"seuil_min": 9, "seuil_max": 10}, {"seuil_min": 6, "seuil_max": 5},
                                      {"seuil_min": 0, "seuil_max": 5}])
def test_bornes_invalides_refusees(banc, reglages):
    assert banc.ctrl.apply_settings(banc.ctrl.settings.with_changes(**reglages))


def test_journal_explique_l_attente_du_seuil(make_banc):
    b = make_banc({**ALEATOIRE, "seuil_min": 8, "seuil_max": 8}, disponibles=2, delai_s=180)
    b.ctrl.start()
    b.run(5)
    lignes = [m for m in b.log.messages() if m.startswith("En attente du seuil aléatoire")]
    assert lignes == ["En attente du seuil aléatoire : 2 / 10 disponibles, seuil tiré 8 → encore 6 pack(s), "
                      "environ 17 min 59 s. Aucun clic avant."]
    b.run(180)                                   # un nouveau pack : une seule nouvelle ligne
    lignes = [m for m in b.log.messages() if m.startswith("En attente du seuil aléatoire")]
    assert len(lignes) == 2 and "3 / 10" in lignes[1]
    assert b.clics() == 0


def test_par_defaut_le_bot_tourne_sans_fin(make_banc):
    """Objectif 0 (défaut) : cycle après cycle, bien au-delà de 10 packs, sans jamais s'arrêter seul."""
    from wikimaster.config import Settings
    assert Settings().objectif_ouvertures == 0
    b = make_banc(ALEATOIRE, disponibles=8, delai_s=60)
    b.ctrl.start()
    assert b.status.restants is None                     # affiché « ∞ »
    b.run(4 * 3600)
    assert b.page.packs_ouverts >= 60
    assert b.status.etat is BotState.EN_COURS
    assert "TERMINÉ" not in b.journal()
