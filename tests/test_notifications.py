"""Notifications Discord : facultatives, asynchrones, envoyées aux moments clés uniquement."""
import json
import threading
import time
import urllib.error

import pytest

from wikimaster.config import Settings
from wikimaster.controller import BotState, Controller
from wikimaster.logger import ActivityLog
from wikimaster.notifications import (ALERTE, BILAN, PAUSE, TEST, NotificateurDiscord, construire_message,
                                      decrire_erreur)
from wikimaster.simulation import URL_SIMULEE, ManualClock, SimulatedPage

URL = "https://discord.com/api/webhooks/123/secret-jeton"


class FauxNotificateur:
    """Enregistre les notifications au lieu de les envoyer."""

    def __init__(self):
        self.recues: list[tuple[str, str, str, str]] = []

    def notifier(self, url, niveau, titre, message):
        self.recues.append((url, niveau, titre, message))
        return True

    def attendre(self, delai_s):
        return True

    def niveaux(self):
        return [n for _, n, _, _ in self.recues]


def banc_discord(make_banc, reglages=None, **page):
    page.setdefault("disponibles", 5)
    b = make_banc({"discord_webhook_url": URL, **(reglages or {})}, **page)
    b.notifs = FauxNotificateur()
    b.ctrl._notificateur = b.notifs
    return b


# --- paramètres ----------------------------------------------------------------------------------

def test_discord_desactive_par_defaut():
    s = Settings()
    assert s.discord_webhook_url == "" and s.discord_bilan_session is False and s.validate() == []


@pytest.mark.parametrize("url", ["http://discord.com/api/webhooks/1/a", "discord.com/api/webhooks/1/a",
                                 "https://discord.com/api/webhooks/1/a b", "https://" + "x" * 600])
def test_url_webhook_invalide_refusee(url):
    assert Settings(discord_webhook_url=url).validate()


def test_url_webhook_enregistree_et_relue(tmp_path):
    path = tmp_path / "settings.json"
    Settings(discord_webhook_url=URL, discord_bilan_session=True, delai_clic_min_s=0.3,
             delai_clic_max_s=3.0).save(path)
    s = Settings.load(path)
    assert (s.discord_webhook_url, s.discord_bilan_session) == (URL, True)
    assert (s.delai_clic_min_s, s.delai_clic_max_s) == (0.3, 3.0)


def test_url_webhook_espaces_retires_et_type_verifie(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"discord_webhook_url": f"  {URL}\n"}), encoding="utf-8")
    assert Settings.load(path).discord_webhook_url == URL
    path.write_text(json.dumps({"discord_webhook_url": 42}), encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.load(path)


def test_ancien_fichier_sans_discord_toujours_valide(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"seuil_min": 3, "seuil_max": 8}), encoding="utf-8")
    assert Settings.load(path).discord_webhook_url == ""


# --- notificateur --------------------------------------------------------------------------------

def test_message_discret_sans_mention():
    corps = construire_message(ALERTE, "⚠ Action humaine requise", "Cochez la case", mode="Mode observation")
    assert corps["allowed_mentions"] == {"parse": []}
    encadre = corps["embeds"][0]
    assert encadre["title"] == "⚠ Action humaine requise" and encadre["description"] == "Cochez la case"
    assert encadre["footer"]["text"] == "Mode observation"
    assert construire_message(PAUSE, "t", "m")["embeds"][0]["color"] != encadre["color"]


def test_sans_url_rien_n_est_envoye():
    envois = []
    n = NotificateurDiscord(ActivityLog(), envoyer=lambda url, corps: envois.append(url))
    assert n.notifier("", PAUSE, "t", "m") is False
    assert n.attendre(1) and envois == []


def test_envoi_asynchrone_ne_bloque_jamais():
    """Même si Discord met 1 s à répondre, `notifier()` rend la main immédiatement."""
    libere = threading.Event()
    envois = []

    def envoyer_lent(url, corps):
        libere.wait(5)
        envois.append((url, corps))

    log = ActivityLog()
    n = NotificateurDiscord(log, envoyer=envoyer_lent)
    debut = time.monotonic()
    for i in range(3):
        assert n.notifier(URL, PAUSE, f"titre {i}", "m")
    assert time.monotonic() - debut < 0.2
    assert n.attendre(0.1) is False                      # toujours en cours d'envoi
    libere.set()
    assert n.attendre(5)
    assert [c["embeds"][0]["title"] for _, c in envois] == ["titre 0", "titre 1", "titre 2"]   # ordre conservé
    assert n.envoyees == 3
    assert "Notification Discord envoyée : titre 2" in log.messages()


def test_echec_journalise_sans_l_url_secrete():
    def envoyer_refuse(url, corps):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    log = ActivityLog()
    n = NotificateurDiscord(log, envoyer=envoyer_refuse)
    n.notifier(URL, PAUSE, "Pause", "m")
    assert n.attendre(5)
    journal = "\n".join(log.messages())
    assert "non envoyée (HTTP 404 Not Found)" in journal
    assert "secret-jeton" not in journal and n.echecs == 1


def test_file_pleine_message_abandonne_sans_bloquer():
    libere = threading.Event()
    log = ActivityLog()
    n = NotificateurDiscord(log, envoyer=lambda url, corps: libere.wait(5), taille_file=2)
    resultats = [n.notifier(URL, PAUSE, f"t{i}", "m") for i in range(6)]
    assert resultats.count(False) >= 1
    assert "abandonnée" in "\n".join(log.messages())
    libere.set()
    assert n.attendre(5)


def test_decrire_erreur_reseau():
    assert decrire_erreur(urllib.error.URLError("timed out")) == "réseau : timed out"


# --- contrôleur : moments clés -------------------------------------------------------------------

def test_aucune_notification_sans_webhook(make_banc):
    b = make_banc(disponibles=5)
    b.notifs = FauxNotificateur()
    b.ctrl._notificateur = b.notifs
    b.ctrl.start()
    b.run(3)
    b.page.session_expiree = True
    b.run(3)
    assert b.status.confirmation_requise
    assert b.notifs.recues == []


def test_notification_a_chaque_pause_de_securite(make_banc):
    b = banc_discord(make_banc)
    b.ctrl.start()
    b.run(3)
    b.page.session_expiree = True
    b.run(3)
    assert b.status.confirmation_requise
    assert b.notifs.niveaux() == [PAUSE]
    url, _, titre, message = b.notifs.recues[0]
    assert url == URL and "Pause de sécurité" in titre and "Confirmer la reprise" in message


def test_notification_action_humaine_requise_une_seule_fois(make_banc):
    b = banc_discord(make_banc)
    b.ctrl.start()
    b.run(3)
    b.page.declencher_case_cloudflare()
    b.run(5)
    assert b.notifs.recues == []                              # vérification brève : pas d'alerte
    b.run(60)
    assert b.notifs.niveaux() == [ALERTE]
    assert "Action humaine requise" in b.notifs.recues[0][2]
    b.page.cocher_case_humain()
    assert b.run_until(lambda: b.status.etat is BotState.EN_COURS, max_ticks=10)
    assert b.notifs.niveaux() == [ALERTE]                     # reprise automatique : rien de plus


def test_verification_qui_passe_seule_pas_de_notification(make_banc):
    b = banc_discord(make_banc)
    b.ctrl.start()
    b.run(3)
    b.page.declencher_verification(5)
    assert b.run_until(lambda: "Reprise automatique" in b.journal(), max_ticks=30)
    assert b.notifs.recues == []


def test_bilan_de_session_a_l_arret(make_banc):
    b = banc_discord(make_banc, {"discord_bilan_session": True})
    b.ctrl.start()
    assert b.run_until(lambda: b.status.ouverts == 2, max_ticks=120)
    b.ctrl.stop()
    assert b.notifs.niveaux() == [BILAN]
    _, _, titre, message = b.notifs.recues[0]
    assert "Arrêt manuel" in titre and "Packs ouverts : 2" in message


def test_bilan_envoye_une_seule_fois_quand_l_objectif_est_atteint(make_banc):
    b = banc_discord(make_banc, {"discord_bilan_session": True, "objectif_ouvertures": 1})
    b.ctrl.start()
    assert b.run_until(lambda: b.status.etat is BotState.TERMINE, max_ticks=120)
    b.ctrl.stop()                                             # fermeture de la fenêtre après « Terminé »
    assert b.notifs.niveaux() == [BILAN]
    assert "Objectif atteint" in b.notifs.recues[0][2]


def test_bilan_desactive_par_defaut(make_banc):
    b = banc_discord(make_banc)
    b.ctrl.start()
    b.run(5)
    b.ctrl.stop()
    assert b.notifs.recues == []


def test_discord_lent_ne_retarde_pas_la_boucle():
    """Bout en bout avec le vrai notificateur : une pause est notifiée pendant que Discord « rame »."""
    libere = threading.Event()
    clock = ManualClock()
    page = SimulatedPage(clock, disponibles=5)
    log = ActivityLog()
    notif = NotificateurDiscord(log, envoyer=lambda url, corps: libere.wait(5))
    ctrl = Controller(page, Settings(seuil_min=1, seuil_max=1, discord_webhook_url=URL), log, clock=clock,
                      use_thread=False, prefixe_url=URL_SIMULEE, attente=lambda s: None, notificateur=notif)
    ctrl.start()
    for _ in range(3):
        ctrl.tick()
        clock.advance(1)
    page.session_expiree = True
    debut = time.monotonic()
    for _ in range(3):
        ctrl.tick()
        clock.advance(1)
    assert time.monotonic() - debut < 0.5
    assert ctrl.status().confirmation_requise
    libere.set()
    assert ctrl.attendre_notifications(5)
    assert notif.envoyees == 1


def test_notificateur_defaillant_sans_consequence(make_banc):
    b = make_banc({"discord_webhook_url": URL}, disponibles=5)

    class Casse:
        def notifier(self, *args):
            raise RuntimeError("boum")

    b.ctrl._notificateur = Casse()
    b.ctrl.start()
    b.run(3)
    b.page.session_expiree = True
    b.run(3)
    assert b.status.confirmation_requise
    assert "Notification Discord impossible" in b.journal()


def test_message_de_test(make_banc):
    b = make_banc()
    b.notifs = FauxNotificateur()
    b.ctrl._notificateur = b.notifs
    assert b.ctrl.tester_notification(URL)
    assert b.notifs.niveaux() == [TEST]
    assert b.ctrl.tester_notification("") is False


def test_contexte_ssl_certifi_ou_systeme(monkeypatch):
    """Avec certifi (application Mac) : ses certificats ; sans : None, donc les certificats du système."""
    import ssl
    import sys
    import types

    from wikimaster.notifications import contexte_ssl
    monkeypatch.setitem(sys.modules, "certifi", None)
    assert contexte_ssl() is None
    vu = {}
    faux = types.SimpleNamespace(where=lambda: "/faux/cacert.pem")
    monkeypatch.setitem(sys.modules, "certifi", faux)
    monkeypatch.setattr(ssl, "create_default_context", lambda cafile=None: vu.setdefault("cafile", cafile))
    assert contexte_ssl() == "/faux/cacert.pem" and vu["cafile"] == "/faux/cacert.pem"
