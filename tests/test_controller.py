"""Machine à états et règles de sécurité du contrôleur, sur page simulée (aucun accès au site)."""
import threading

import pytest

from wikimaster.controller import BotState
from wikimaster.page_model import View
from wikimaster.page_monitor import PageStatus


# --- fonctionnement normal -----------------------------------------------------------------------

def test_un_pack_disponible_est_ouvert_verifie_et_compte(banc):
    banc.ctrl.start()
    assert banc.run_until(lambda: banc.status.ouverts == 1, max_ticks=10)
    assert banc.page.clics_ouvrir == 1
    assert banc.page.packs_ouverts == 1
    assert "Pack ouvert et vérifié" in banc.journal()


def test_aucun_clic_sans_lectures_stables(banc):
    banc.ctrl.start()
    banc.run(1)  # 1re lecture : pas encore 2 lectures identiques
    assert banc.clics() == 0
    banc.run(1)
    assert banc.page.clics_ouvrir == 1


def test_revelation_parcourue_jusqu_au_retour_page_paquets(banc):
    banc.ctrl.start()
    assert banc.run_until(lambda: banc.page.clics_continuer == 1, max_ticks=60)
    assert banc.page.vue is View.PAQUETS
    assert banc.page.clics_ouvrir == 1
    assert banc.page.clics_fleche == 4          # cartes 2 à 5 révélées une par une
    assert banc.page.clics_ignores == 0
    assert banc.status.ouverts == 1
    assert banc.status.etat is BotState.EN_COURS


def test_progression_de_0_a_10_packs_puis_termine(make_banc):
    b = make_banc({"objectif_ouvertures": 10}, disponibles=0, delai_s=180)
    b.ctrl.start()
    vus = []
    assert b.run_until(lambda: b.status.etat is BotState.TERMINE, max_ticks=4000,
                       dt=1.0) or pytest.fail(b.journal())
    for e in b.log.messages():
        if e.startswith("Pack ouvert"):
            vus.append(e)
    assert b.status.ouverts == 10
    assert b.status.restants == 0
    assert b.page.packs_ouverts == 10
    assert b.page.clics_ouvrir == 10
    assert len(vus) == 10
    assert b.page.vue is View.PAQUETS          # navigateur laissé sur la page des paquets
    assert b.page.achats == 0
    clics = b.clics()
    b.run(500)
    assert b.clics() == clics                  # plus aucun clic une fois terminé


def test_minuteur_local_ecoule_mais_site_a_zero_aucun_clic(make_banc):
    b = make_banc({"delai_indicatif_s": 30}, disponibles=0, delai_s=180)
    b.ctrl.start()
    b.run(120)  # le minuteur local (30 s) est largement dépassé, le site affiche toujours 0
    assert b.clics() == 0
    assert b.status.source_minuteur == "site"
    assert b.status.temps_restant_s == pytest.approx(60, abs=1)


def test_estimation_locale_si_minuteur_du_site_absent_au_plafond(make_banc):
    b = make_banc(disponibles=10)
    b.ctrl.start()
    b.run(1)  # une seule lecture : pas encore de clic
    assert b.status.source_minuteur == "plafond atteint"


# --- aucun clic dans les états VÉRIFICATION / INCERTAIN / ERREUR ---------------------------------

def _verification(page):
    page.declencher_verification(10_000)


def _interface_modifiee(page):
    page.interface_modifiee = True


def _minuteur_illisible(page):
    page.minuteur_illisible = True


def _reseau(page):
    page.erreur_reseau = True


def _session(page):
    page.session_expiree = True


def _exception_lecture(page):
    page.exception_prochaine_lecture = RuntimeError("Erreur Playwright simulée")


def _fenetre_inconnue(page):
    page.fenetre_inconnue = True


@pytest.mark.parametrize("incident, etat_attendu, statut_page", [
    (_verification, BotState.VERIFICATION, PageStatus.VERIFICATION),
    (_interface_modifiee, BotState.PAUSE, PageStatus.INCERTAIN),
    (_minuteur_illisible, BotState.PAUSE, PageStatus.INCERTAIN),
    (_fenetre_inconnue, BotState.PAUSE, PageStatus.INCERTAIN),
    (_reseau, BotState.ERREUR, PageStatus.ERREUR),
    (_session, BotState.ERREUR, PageStatus.ERREUR),
    (_exception_lecture, BotState.ERREUR, PageStatus.ERREUR),
])
def test_aucun_clic_si_page_pas_normale_des_le_depart(make_banc, incident, etat_attendu, statut_page):
    b = make_banc(disponibles=5)
    incident(b.page)
    b.ctrl.start()
    b.run(1)
    assert b.status.etat is etat_attendu
    assert b.status.page_statut is statut_page
    b.run(700)  # une vérification qui ne disparaît pas passe en pause manuelle après 600 s (défaut)
    assert b.clics() == 0
    assert b.status.etat is etat_attendu
    assert b.status.confirmation_requise
    assert "PAUSE AUTOMATIQUE" in b.journal()


@pytest.mark.parametrize("incident, etat_attendu", [
    (_verification, BotState.VERIFICATION),
    (_interface_modifiee, BotState.PAUSE),
    (_fenetre_inconnue, BotState.PAUSE),
    (_reseau, BotState.ERREUR),
    (_exception_lecture, BotState.ERREUR),
])
def test_incident_en_cours_de_route_bloque_tout_clic(make_banc, incident, etat_attendu):
    b = make_banc(disponibles=5)
    b.ctrl.start()
    assert b.run_until(lambda: b.status.ouverts == 1, max_ticks=10)
    incident(b.page)
    b.run(1)
    assert b.status.etat is etat_attendu
    clics = b.clics()
    b.run(300)
    assert b.clics() == clics
    assert b.page.clics_pendant_modale == 0


def test_lecture_incertaine_bloque_le_clic_meme_avec_tolerance(make_banc):
    b = make_banc({"lectures_incertaines_tolerees": 5}, disponibles=5)
    b.page.minuteur_illisible = True
    b.ctrl.start()
    b.run(4)
    assert b.status.etat is BotState.EN_COURS  # tolérance pas encore épuisée…
    assert b.status.page_incertaine
    assert b.clics() == 0                      # …mais aucun clic pour autant
    b.run(1)
    assert b.status.etat is BotState.PAUSE


def test_changement_inexplique_met_en_pause_immediatement(make_banc):
    b = make_banc({"lectures_incertaines_tolerees": 5, "seuil_min": 9, "seuil_max": 9}, disponibles=3)
    b.ctrl.start()
    b.run(3)
    b.page.ouverture_manuelle()  # l'utilisateur ouvre un pack lui-même
    b.run(1)
    assert b.status.etat is BotState.PAUSE
    assert "sans action du programme" in b.status.raison
    assert b.clics() == 0


def test_verification_pendant_l_attente_du_resultat(make_banc):
    """Clic « Ouvrir » envoyé, puis la vérification recouvre la page : le résultat n'est constaté
    qu'une fois la fenêtre partie, puis le programme reprend seul."""
    b = make_banc(disponibles=2, latence_ouverture_s=3)
    b.ctrl.start()
    assert b.run_until(lambda: b.page.clics_ouvrir == 1, max_ticks=10)
    b.page.declencher_verification(20)
    b.run(1)
    assert b.status.etat is BotState.VERIFICATION
    b.run(18)
    assert b.page.clics_ouvrir == 1 and b.page.clics_fleche == 0
    assert b.status.ouverts == 0               # révélation cachée par la fenêtre : pas encore constatée
    assert b.run_until(lambda: b.status.etat is BotState.EN_COURS, max_ticks=10)
    assert b.status.ouverts == 1
    assert b.run_until(lambda: b.page.clics_fleche >= 1, max_ticks=20)
    assert b.page.clics_pendant_modale == 0


# --- vérification : attente passive puis reprise automatique ---------------------------------------

def test_verification_attente_passive_puis_reprise_automatique(make_banc):
    b = make_banc(disponibles=5)
    b.ctrl.start()
    assert b.run_until(lambda: b.status.ouverts == 1, max_ticks=10)
    b.page.declencher_verification(5)
    b.run(1)
    assert b.status.etat is BotState.VERIFICATION
    assert not b.status.confirmation_requise          # pas de confirmation demandée
    assert b.status.verification_presente
    clics = b.clics()
    b.run(4)                                          # fenêtre affichée : aucun clic
    assert b.clics() == clics
    assert b.page.clics_pendant_modale == 0
    assert b.run_until(lambda: b.status.etat is BotState.EN_COURS, max_ticks=10)
    assert b.clics() == clics                         # reprise sans clic intermédiaire
    assert "Reprise automatique" in b.journal()
    assert b.run_until(lambda: b.status.ouverts == 2, max_ticks=60)   # le cycle continue seul


def test_reprise_automatique_exige_plusieurs_lectures_normales_consecutives(make_banc):
    b = make_banc({"lectures_normales_reprise": 3}, disponibles=5)
    b.page.declencher_verification(10_000)
    b.ctrl.start()
    b.run(3)
    b.page.terminer_verification()
    b.run(2)                                          # 2 lectures normales : pas encore
    assert b.status.etat is BotState.VERIFICATION
    assert b.status.lectures_normales_reprise == 2
    b.page.declencher_verification(10_000)            # la fenêtre revient : compteur remis à zéro
    b.run(1)
    assert b.status.lectures_normales_reprise == 0
    b.page.terminer_verification()
    b.run(2)
    assert b.status.etat is BotState.VERIFICATION
    b.run(1)                                          # 3e lecture normale consécutive
    assert b.status.etat is BotState.EN_COURS
    assert b.clics() == 0                             # la reprise elle-même ne clique pas


def test_verifications_repetees_toutes_reprises_seules(make_banc):
    b = make_banc(disponibles=8, delai_s=60)
    b.ctrl.start()
    for _ in range(6):
        b.run(25)
        b.page.declencher_verification(4)
    b.run(400)
    assert b.status.etat is BotState.EN_COURS, b.journal()
    assert b.journal().count("Reprise automatique") == 6
    assert b.page.clics_pendant_modale == 0
    assert b.page.clics_ignores == 0
    assert b.status.ouverts >= 8


def test_verification_bloquee_trop_longtemps_pause_manuelle(make_banc):
    b = make_banc({"verification_delai_max_s": 60}, disponibles=5)
    b.page.declencher_verification(10_000)
    b.ctrl.start()
    b.run(60)
    assert b.status.etat is BotState.VERIFICATION and not b.status.confirmation_requise
    b.run(2)
    assert b.status.confirmation_requise
    assert "bloquée depuis plus de 60 s" in b.status.raison
    b.page.terminer_verification()
    b.run(30)                                         # disparue, mais plus de reprise automatique
    assert b.status.etat is BotState.VERIFICATION
    assert b.clics() == 0
    assert b.ctrl.resume() is False
    b.ctrl.confirm_resume()
    b.run(1)
    assert b.status.etat is BotState.EN_COURS


def test_confirmation_refusee_tant_que_la_verification_est_affichee(make_banc):
    b = make_banc({"verification_delai_max_s": 10, "alerte_verification_s": 5}, disponibles=5)
    b.page.declencher_verification(10_000)
    b.ctrl.start()
    assert b.ctrl.confirm_resume() is False          # pas de confirmation pendant l'attente passive
    b.run(15)
    assert b.status.confirmation_requise
    assert b.ctrl.confirm_resume() is True
    b.run(1)
    assert b.status.etat is BotState.VERIFICATION
    assert "Reprise refusée" in b.journal()
    assert b.clics() == 0


def test_page_incertaine_apres_verification_pause_manuelle(make_banc):
    b = make_banc(disponibles=5)
    b.page.declencher_verification(5)
    b.ctrl.start()
    b.run(1)
    b.page.interface_modifiee = True
    b.run(20)
    assert b.status.etat is BotState.PAUSE
    assert b.status.confirmation_requise
    assert "Après la vérification" in b.status.raison
    b.page.retablir()
    b.run(20)
    assert b.status.etat is BotState.PAUSE            # pas de reprise automatique
    assert b.clics() == 0
    b.ctrl.confirm_resume()
    b.run(1)
    assert b.status.etat is BotState.EN_COURS


def test_erreur_apres_verification_pause_manuelle(make_banc):
    b = make_banc(disponibles=5)
    b.page.declencher_verification(5)
    b.ctrl.start()
    b.run(1)
    b.page.erreur_reseau = True
    b.run(10)
    assert b.status.etat is BotState.ERREUR and b.status.confirmation_requise
    b.page.retablir()
    b.run(20)
    assert b.status.etat is BotState.ERREUR
    assert b.clics() == 0


def test_action_non_constatee_apres_verification_pause_manuelle(make_banc):
    b = make_banc(disponibles=5)
    b.page.echec_prochaine_ouverture = True
    b.ctrl.start()
    assert b.run_until(lambda: b.page.clics_ouvrir == 1, max_ticks=10)
    b.page.declencher_verification(3)
    b.run(10)
    assert b.status.etat is BotState.PAUSE
    assert b.status.confirmation_requise
    assert "envoyée avant la vérification" in b.status.raison
    assert b.status.ouverts == 0
    b.run(100)
    assert b.page.clics_ouvrir == 1


def test_pause_manuelle_pendant_l_attente_passive(make_banc):
    b = make_banc(disponibles=5)
    b.page.declencher_verification(5)
    b.ctrl.start()
    b.run(1)
    assert b.ctrl.pause() is True
    b.run(30)
    assert b.status.etat is BotState.PAUSE             # pas de reprise automatique après une pause manuelle
    assert b.clics() == 0
    assert b.ctrl.resume() is True
    assert b.run_until(lambda: b.status.ouverts == 1, max_ticks=10)


def test_reprise_automatique_desactivable(make_banc):
    b = make_banc({"reprise_auto_verification": False}, disponibles=5)
    b.page.declencher_verification(5)
    b.ctrl.start()
    b.run(1)
    assert b.status.confirmation_requise
    b.run(60)
    assert b.status.etat is BotState.VERIFICATION
    assert b.clics() == 0
    assert "En attente de votre confirmation" in b.journal()
    b.ctrl.confirm_resume()
    b.run(1)
    assert b.status.etat is BotState.EN_COURS


def test_reprise_apres_erreur_exige_confirmation(make_banc):
    b = make_banc(disponibles=5)
    b.page.erreur_reseau = True
    b.ctrl.start()
    b.run(3)
    b.page.retablir()
    b.run(10)
    assert b.status.etat is BotState.ERREUR
    assert b.clics() == 0
    assert b.ctrl.resume() is False
    b.ctrl.confirm_resume()
    b.run(1)
    assert b.status.etat is BotState.EN_COURS


# --- anti-double-clic et résultats non vérifiés --------------------------------------------------

def test_double_clic_volontaire_refuse(banc):
    banc.ctrl.request_double_click_test()
    banc.ctrl.start()
    assert banc.run_until(lambda: banc.page.clics_ouvrir >= 1, max_ticks=10)
    assert banc.page.clics_ouvrir == 1
    assert banc.status.clics_refuses == 1
    assert "refusé (anti-double-clic)" in banc.journal()
    banc.run(30)
    assert banc.page.clics_ouvrir == 1
    assert banc.status.ouverts == 1


def test_pas_de_second_clic_tant_que_le_resultat_n_est_pas_constate(make_banc):
    b = make_banc(disponibles=5, latence_ouverture_s=8)
    b.ctrl.start()
    assert b.run_until(lambda: b.page.clics_ouvrir == 1, max_ticks=10)
    b.run(7)
    assert b.page.clics_ouvrir == 1
    assert b.status.action_en_attente == "ouvrir"
    assert b.status.ouverts == 0
    b.run(2)
    assert b.status.ouverts == 1
    assert b.page.clics_ouvrir == 1


def test_echec_d_ouverture_non_compte_et_jamais_repete(make_banc):
    b = make_banc(disponibles=5)
    b.page.echec_prochaine_ouverture = True
    b.ctrl.start()
    assert b.run_until(lambda: b.status.etat is BotState.PAUSE, max_ticks=30)
    assert b.status.confirmation_requise
    assert "non constaté" in b.status.raison
    assert b.status.ouverts == 0
    assert b.status.echecs == 1
    b.run(300)
    assert b.page.clics_ouvrir == 1


def test_exception_pendant_le_clic_non_comptee_et_jamais_repetee(make_banc):
    b = make_banc(disponibles=5)
    b.page.exception_prochain_clic = RuntimeError("Timeout Playwright simulé")
    b.ctrl.start()
    b.run(3)
    assert b.status.etat is BotState.PAUSE
    assert "Échec du clic" in b.status.raison
    assert b.status.ouverts == 0
    b.run(300)
    assert b.page.clics_ouvrir == 1


def test_ouverture_constatee_pendant_une_pause_est_comptee_une_fois(make_banc):
    b = make_banc(disponibles=5, latence_ouverture_s=4)
    b.ctrl.start()
    assert b.run_until(lambda: b.page.clics_ouvrir == 1, max_ticks=10)
    b.ctrl.pause()
    b.run(10)
    assert b.status.ouverts == 1
    b.ctrl.resume()
    b.run(3)
    assert b.status.ouverts == 1


# --- boutons de contrôle ----------------------------------------------------------------------

def test_pause_manuelle_puis_reprendre(make_banc):
    b = make_banc(disponibles=5)
    b.ctrl.start()
    b.ctrl.pause()
    b.run(50)
    assert b.clics() == 0
    assert b.status.etat is BotState.PAUSE
    assert not b.status.confirmation_requise
    assert b.ctrl.confirm_resume() is False
    assert b.ctrl.resume() is True
    assert b.run_until(lambda: b.status.ouverts == 1, max_ticks=10)


def test_arret_immediat(make_banc):
    b = make_banc(disponibles=5)
    b.ctrl.start()
    assert b.run_until(lambda: b.status.ouverts == 1, max_ticks=10)
    b.ctrl.stop()
    clics = b.clics()
    b.run(200)
    assert b.clics() == clics
    assert b.status.etat is BotState.ARRETE
    assert b.ctrl.pause() is False and b.ctrl.resume() is False and b.ctrl.confirm_resume() is False


def test_arret_entre_la_decision_et_le_clic(make_banc):
    """L'arrêt arrive pendant la relecture qui précède le clic : le clic ne doit pas partir."""
    b = make_banc(disponibles=5)
    lecture = b.page.read_snapshot
    appels = {"n": 0}

    def lecture_avec_arret():
        appels["n"] += 1
        snap = lecture()
        if appels["n"] == 3:  # 1re lecture (instable), 2e (décision), 3e = relecture avant clic
            b.ctrl.stop()
        return snap

    b.page.read_snapshot = lecture_avec_arret
    b.ctrl.start()
    b.run(20)
    assert b.page.clics_ouvrir == 0
    assert b.status.etat is BotState.ARRETE


def test_arret_au_tout_dernier_moment_avant_le_clic(make_banc):
    """L'arrêt arrive après la relecture mais avant l'envoi : le contrôle final doit bloquer le clic."""
    b = make_banc(disponibles=5)
    decider = b.ctrl._lire_et_decider
    appels = {"n": 0}

    def decider_puis_arreter(epoch):
        appels["n"] += 1
        action = decider(epoch)
        if action is not None and appels["n"] >= 3:  # relecture avant clic validée
            b.ctrl.stop()
        return action

    b.ctrl._lire_et_decider = decider_puis_arreter
    b.ctrl.start()
    b.run(10)
    assert b.page.clics_ouvrir == 0
    assert "Clic annulé" in b.journal()


def test_reprendre_refuse_apres_pause_automatique_incertaine(make_banc):
    b = make_banc(disponibles=5)
    b.page.interface_modifiee = True
    b.ctrl.start()
    b.run(2)
    assert b.status.etat is BotState.PAUSE and b.status.confirmation_requise
    b.page.retablir()
    assert b.ctrl.resume() is False
    b.run(20)
    assert b.status.etat is BotState.PAUSE
    assert b.clics() == 0
    b.ctrl.confirm_resume()
    b.run(1)
    assert b.status.etat is BotState.EN_COURS


def test_arret_pendant_l_attente_du_resultat_non_compte(make_banc):
    b = make_banc(disponibles=5, latence_ouverture_s=5)
    b.ctrl.start()
    assert b.run_until(lambda: b.page.clics_ouvrir == 1, max_ticks=10)
    b.ctrl.stop()
    b.run(20)
    assert b.status.ouverts == 0
    assert "n'est pas comptée" in b.journal()


def test_redemarrage_remet_les_compteurs_a_zero(make_banc):
    b = make_banc(disponibles=5)
    b.ctrl.start()
    assert b.run_until(lambda: b.status.ouverts == 1, max_ticks=10)
    b.ctrl.stop()
    assert b.ctrl.start() is True
    assert b.status.ouverts == 0


def test_demarrer_deux_fois_ne_cree_qu_un_seul_thread(make_banc):
    b = make_banc({"intervalle_lecture_s": 0.1}, disponibles=0)
    b.ctrl._use_thread = True
    b.ctrl._attente = None
    try:
        assert b.ctrl.start() is True
        assert b.ctrl.start() is False
        workers = [t for t in threading.enumerate() if t.name == "wikimaster-worker"]
        assert len(workers) == 1
    finally:
        b.ctrl.stop()
        b.ctrl.join(timeout=2)
    assert not any(t.name == "wikimaster-worker" for t in threading.enumerate())


def test_parametres_invalides_refuses(banc):
    erreurs = banc.ctrl.apply_settings(banc.ctrl.settings.with_changes(delai_indicatif_s=0))
    assert erreurs
    assert banc.ctrl.settings.delai_indicatif_s == 180
    assert banc.ctrl.apply_settings(banc.ctrl.settings.with_changes(delai_indicatif_s=240)) == []
    assert banc.ctrl.settings.delai_indicatif_s == 240


def test_capacite_differente_du_site_bloque(make_banc):
    b = make_banc({"capacite_packs": 8}, disponibles=5)
    b.ctrl.start()
    b.run(5)
    assert b.status.etat is BotState.PAUSE
    assert "Capacité affichée" in b.status.raison
    assert b.clics() == 0


def test_jamais_de_clic_sur_continuer_avant_la_derniere_carte(make_banc):
    b = make_banc(disponibles=3)
    b.ctrl.start()
    assert b.run_until(lambda: b.status.ouverts == 3 and b.page.vue is View.PAQUETS, max_ticks=300)
    assert b.page.clics_continuer == 3
    assert b.page.clics_fleche == 12
    assert b.page.clics_ignores == 0


def test_carte_changee_par_l_utilisateur_pendant_la_revelation(make_banc):
    b = make_banc(disponibles=3)
    b.ctrl.start()
    assert b.run_until(lambda: b.page.vue is View.REVELATION and b.status.action_en_attente is None,
                       max_ticks=20)
    b.run(1)
    b.page.carte_index += 1  # l'utilisateur clique lui-même sur la flèche
    b.page.cartes_revelees = max(b.page.cartes_revelees, b.page.carte_index)
    b.run(1)
    assert b.status.etat is BotState.PAUSE
    assert "sans action du programme" in b.status.raison


# --- temporisation avant clic et mode observation ------------------------------------------------------

def test_temporisation_aleatoire_avant_chaque_clic(make_banc):
    b = make_banc(disponibles=2)
    b.ctrl.start()
    assert b.run_until(lambda: b.status.ouverts == 2 and b.page.vue is View.PAQUETS, max_ticks=300)
    assert len(b.attentes) == b.clics() == 2 + 2 * 5          # Ouvrir + 4 flèches + Continuer, ×2
    assert all(0.8 <= s <= 1.8 for s in b.attentes)
    assert len({round(s, 3) for s in b.attentes}) > 5          # durées variées, pas une constante


def test_temporisation_parametrable_et_modifiable_en_cours(make_banc):
    b = make_banc({"delai_clic_min_s": 0.3, "delai_clic_max_s": 3.0}, disponibles=2)
    b.ctrl.start()
    assert b.run_until(lambda: b.status.ouverts == 1, max_ticks=100)
    assert b.attentes and all(0.3 <= s <= 3.0 for s in b.attentes)
    assert any(s > 1.8 for s in b.attentes) or any(s < 0.8 for s in b.attentes)
    deja = len(b.attentes)
    b.ctrl.apply_settings(b.ctrl.settings.with_changes(delai_clic_min_s=2.5, delai_clic_max_s=2.5))
    assert b.run_until(lambda: b.status.ouverts == 2, max_ticks=100)
    assert b.attentes[deja:] and all(s == 2.5 for s in b.attentes[deja:])


def test_arret_pendant_la_temporisation_aucun_clic(make_banc):
    b = make_banc(disponibles=5)
    b.ctrl._attente = lambda s: b.ctrl.stop()   # « Arrêter » pressé pendant l'attente
    b.ctrl.start()
    b.run(10)
    assert b.clics() == 0
    assert b.status.etat is BotState.ARRETE


def test_page_relue_apres_la_temporisation(make_banc):
    """Une vérification qui apparaît PENDANT la temporisation empêche le clic."""
    b = make_banc(disponibles=5)
    b.ctrl._attente = lambda s: b.page.declencher_verification(30)
    b.ctrl.start()
    b.run(3)
    assert b.clics() == 0
    assert b.status.etat is BotState.VERIFICATION


def test_mode_observation_aucun_clic(make_banc):
    b = make_banc(disponibles=5, observation=True)
    b.ctrl.start()
    b.run(200)
    assert b.clics() == 0
    assert b.attentes == []
    assert b.status.etat is BotState.EN_COURS
    # une ligne par état de page distinct (ici 5/10 puis 6/10 après un nouveau pack), pas une par lecture
    assert b.journal().count("[Observation] Le programme aurait cliqué sur « ouvrir »") == 2


def test_mode_observation_detecte_quand_meme_la_verification(make_banc):
    b = make_banc(disponibles=5, observation=True)
    b.ctrl.start()
    b.run(3)
    b.page.declencher_verification(5)
    b.run(1)
    assert b.status.etat is BotState.VERIFICATION
    assert b.run_until(lambda: b.status.etat is BotState.EN_COURS, max_ticks=20)
    assert b.clics() == 0
