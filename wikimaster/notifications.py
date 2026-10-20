"""Notifications Discord (webhook), facultatives.

`notifier()` ne fait que déposer le message dans une file et rend la main immédiatement : l'envoi HTTP se fait
dans un thread dédié. Un Discord lent ou injoignable ne retarde donc jamais la boucle de lecture ni les clics.
Un échec d'envoi est seulement journalisé (jamais de nouvelle tentative). L'URL du webhook est un secret :
elle n'apparaît jamais dans le journal.
"""
from __future__ import annotations

import json
import queue
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable

from .logger import ActivityLog

# Niveaux → couleur de la bande latérale Discord.
ALERTE = "alerte"
PAUSE = "pause"
BILAN = "bilan"
TEST = "test"
COULEURS = {ALERTE: 0xDC2626, PAUSE: 0xD97706, BILAN: 0x2563EB, TEST: 0x82C8E5}

NOM_EXPEDITEUR = "6lz9"
DELAI_HTTP_S = 10.0
TAILLE_FILE = 20
# Discord (Cloudflare) refuse les requêtes portant l'agent par défaut « Python-urllib ».
AGENT = "DiscordBot (PafOpener, 1.0)"


def construire_message(niveau: str, titre: str, message: str, mode: str = "") -> dict:
    """Corps JSON d'un message de webhook Discord : un seul encadré, aucune mention (@everyone, @here…)."""
    encadre = {
        "title": titre[:256],
        "description": message[:4000],
        "color": COULEURS.get(niveau, COULEURS[TEST]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if mode:
        encadre["footer"] = {"text": mode[:2048]}
    return {"username": NOM_EXPEDITEUR, "allowed_mentions": {"parse": []}, "embeds": [encadre]}


def contexte_ssl() -> ssl.SSLContext | None:
    """Certificats de `certifi` s'il est installé (nécessaire dans l'application Mac : le Python embarqué n'y
    trouve pas les certificats du système). Sinon None : certificats du système (Windows)."""
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def envoyer_http(url: str, corps: dict, delai_s: float = DELAI_HTTP_S) -> None:
    """POST JSON vers le webhook. Lève une exception si Discord ne répond pas 2xx."""
    requete = urllib.request.Request(url, data=json.dumps(corps).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": AGENT})
    with urllib.request.urlopen(requete, timeout=delai_s, context=contexte_ssl()) as reponse:
        if not 200 <= reponse.status < 300:
            raise RuntimeError(f"réponse HTTP {reponse.status}")


def decrire_erreur(exc: Exception) -> str:
    """Description courte d'un échec, sans l'URL du webhook."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"réseau : {exc.reason}"
    return f"{type(exc).__name__} : {exc}"


class NotificateurDiscord:
    """File d'envoi vers un webhook Discord, vidée par un unique thread de fond (démarré au premier message)."""

    def __init__(self, log: ActivityLog, mode: str = "",
                 envoyer: Callable[[str, dict], None] = envoyer_http, taille_file: int = TAILLE_FILE):
        self._log = log
        self.mode = mode
        self._envoyer = envoyer
        self._file: queue.Queue[tuple[str, str, dict]] = queue.Queue(maxsize=taille_file)
        self._verrou = threading.Lock()
        self._thread: threading.Thread | None = None
        self.envoyees = 0
        self.echecs = 0

    def notifier(self, url: str, niveau: str, titre: str, message: str) -> bool:
        """Dépose un message à envoyer. Ne bloque jamais. False si aucune URL ou file pleine."""
        if not url:
            return False
        try:
            self._file.put_nowait((url, titre, construire_message(niveau, titre, message, self.mode)))
        except queue.Full:
            self._log.warning(f"Notification Discord abandonnée (trop de messages en attente) : {titre}")
            return False
        self._demarrer()
        return True

    def attendre(self, delai_s: float) -> bool:
        """Attend (au plus `delai_s`) que les messages en file soient envoyés. True si la file est vide."""
        fin = time.monotonic() + delai_s
        with self._file.all_tasks_done:
            while self._file.unfinished_tasks:
                reste = fin - time.monotonic()
                if reste <= 0:
                    return False
                self._file.all_tasks_done.wait(reste)
        return True

    def _demarrer(self) -> None:
        with self._verrou:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._boucle, name="wikimaster-discord", daemon=True)
                self._thread.start()

    def _boucle(self) -> None:
        while True:
            url, titre, corps = self._file.get()
            try:
                self._envoyer(url, corps)
                self.envoyees += 1
                self._log.info(f"Notification Discord envoyée : {titre}")
            except Exception as exc:
                self.echecs += 1
                self._log.warning(f"Notification Discord non envoyée ({decrire_erreur(exc)}) : {titre}")
            finally:
                self._file.task_done()
