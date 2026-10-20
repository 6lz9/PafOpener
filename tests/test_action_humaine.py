"""Case à cocher Cloudflare : le bot ne clique jamais dessus, alerte l'utilisateur et reprend seul ensuite."""
from wikimaster.config import Settings
from wikimaster.controller import BotState
from wikimaster.page_monitor import est_verification
from wikimaster.simulation import TEXTE_VERIFICATION_CASE


def banc_avec_alerte(make_banc, **reglages):
    b = make_banc(reglages, disponibles=5)
    b.bips = []
    b.releves = []
    b.ctrl._alerte = lambda: b.bips.append(b.clock())
    b.ctrl._sur_verification = lambda: b.releves.append(b.clock())
    return b


def test_texte_turnstile_reconnu():
    assert est_verification(TEXTE_VERIFICATION_CASE)
    assert est_verification("Vérifiez que vous êtes humain")
    assert est_verification("Cloudflare")


def test_valeurs_par_defaut():
    s = Settings()
    assert s.alerte_verification_s == 10 and s.verification_delai_max_s == 600


def test_pas_d_alerte_si_la_verification_passe_seule(make_banc):
    b = banc_avec_alerte(make_banc)
    b.ctrl.start()
    b.run(3)
    b.page.declencher_verification(5)
    assert b.run_until(lambda: "Reprise automatique" in b.journal(), max_ticks=30)
    assert b.bips == []
    assert not b.status.action_humaine_requise
    assert len(b.releves) == 1                          # page relevée à l'apparition


def test_case_cloudflare_alerte_apres_10_s_puis_reprise_automatique(make_banc):
    b = banc_avec_alerte(make_banc)
    b.ctrl.start()
    assert b.run_until(lambda: b.status.ouverts == 1, max_ticks=10)
    b.page.declencher_case_cloudflare()
    b.run(1)
    assert b.status.etat is BotState.VERIFICATION
    debut = b.clock() - 1                                # détection lors de la lecture précédente
    clics = b.clics()
    b.run(9)
    assert b.bips == [] and not b.status.action_humaine_requise      # pas avant 10 s
    b.run(2)
    assert len(b.bips) == 1 and b.bips[0] - debut >= 10                # un seul bip
    assert b.status.action_humaine_requise
    assert "ACTION HUMAINE REQUISE" in b.journal()
    b.run(120)                                                         # l'utilisateur prend son temps
    assert len(b.bips) == 1
    assert b.status.etat is BotState.VERIFICATION and not b.status.confirmation_requise
    assert b.clics() == clics and b.page.clics_pendant_modale == 0     # jamais de clic sur la case
    b.page.cocher_case_humain()                                        # l'utilisateur coche la case
    assert b.run_until(lambda: b.status.etat is BotState.EN_COURS, max_ticks=10)
    assert not b.status.action_humaine_requise
    assert "Reprise automatique" in b.journal()
    assert b.run_until(lambda: b.status.ouverts == 2, max_ticks=60)    # le cycle continue


def test_nouvelle_verification_nouvelle_alerte(make_banc):
    b = banc_avec_alerte(make_banc)
    b.ctrl.start()
    b.run(3)
    for _ in range(2):
        b.page.declencher_case_cloudflare()
        b.run(15)
        b.page.cocher_case_humain()
        assert b.run_until(lambda: b.status.etat is BotState.EN_COURS, max_ticks=10)
    assert len(b.bips) == 2 and len(b.releves) == 2


def test_personne_ne_coche_pause_manuelle_apres_le_delai_max(make_banc):
    b = banc_avec_alerte(make_banc, verification_delai_max_s=120)
    b.ctrl.start()
    b.run(3)
    b.page.declencher_case_cloudflare()
    b.run(130)
    assert b.status.confirmation_requise
    b.page.cocher_case_humain()
    b.run(20)
    assert b.status.etat is BotState.VERIFICATION                      # plus de reprise automatique
    assert b.clics() <= 2


def test_bip_ou_releve_defaillant_sans_consequence(make_banc):
    b = make_banc(disponibles=5)
    b.ctrl._alerte = lambda: 1 / 0
    b.ctrl._sur_verification = lambda: 1 / 0
    b.ctrl.start()
    b.run(3)
    b.page.declencher_case_cloudflare()
    b.run(15)
    assert b.status.etat is BotState.VERIFICATION and b.status.action_humaine_requise
    assert "Signal sonore impossible" in b.journal() and "Relevé de la vérification impossible" in b.journal()
    b.page.cocher_case_humain()
    assert b.run_until(lambda: b.status.etat is BotState.EN_COURS, max_ticks=10)
