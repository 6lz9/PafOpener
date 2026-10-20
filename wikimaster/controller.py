"""Orchestration : machine à états, boucle de lecture et clics sécurisés.

Règles de sécurité appliquées à chaque itération :
  1. Lire la page, l'évaluer (NORMAL / VÉRIFICATION / INCERTAIN / ERREUR).
  2. Tout statut autre que NORMAL → aucun clic ; VÉRIFICATION et ERREUR → pause immédiate.
  3. Une action en attente de résultat bloque tout autre clic. Si son résultat n'est pas constaté
     dans le délai imparti → état incertain, pause, AUCUNE nouvelle tentative.
  4. Avant un clic : N lectures normales identiques + une relecture immédiate juste avant le clic.
  5. Rythme : seuil aléatoire tiré entre seuil_min et seuil_max ; attente jusqu'au seuil,
     ouverture jusqu'à 0, puis nouveau tirage (voir `CycleAleatoire`).
  6. Fenêtre « Vérification rapide » : clics suspendus, attente passive (aucune interaction avec la fenêtre).
     Reprise AUTOMATIQUE seulement quand elle a disparu d'elle-même et que la page est NORMALE sur
     plusieurs lectures consécutives, sans action en attente de résultat. Si elle dure trop longtemps,
     ou si la page n'est pas normale après sa disparition : pause avec confirmation manuelle.
  7. Après toute autre pause automatique (INCERTAIN, ERREUR), seule la confirmation manuelle permet
     de reprendre, et seulement si la page est redevenue normale.

Threads : l'interface appelle les commandes (start, pause, …), qui ne font que changer l'état.
Toutes les lectures et tous les clics se font dans un unique thread de travail (contrainte de
Playwright). Les tests appellent `tick()` directement, sans thread.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .config import Settings
from .logger import ActivityLog
from .notifications import ALERTE, BILAN, PAUSE, TEST
from .page_model import PageDriver, PageSnapshot, View
from .page_monitor import Evaluation, PageMonitor, PageStatus
from .pack_manager import CONTINUER, OUVRIR, SUIVANT, VIDAGE, Attempt, CycleAleatoire, PackManager


class BotState(Enum):
    ATTENTE = "En attente"
    EN_COURS = "En cours"
    PAUSE = "En pause"
    VERIFICATION = "Vérification détectée"
    ERREUR = "Erreur"
    TERMINE = "Terminé"
    ARRETE = "Arrêté"


ETATS_INACTIFS = (BotState.ATTENTE, BotState.ARRETE, BotState.TERMINE)
ETATS_PAUSE = (BotState.PAUSE, BotState.VERIFICATION, BotState.ERREUR)


@dataclass(frozen=True)
class StatusView:
    """Photographie de l'état, lue par l'interface."""

    etat: BotState
    raison: str
    confirmation_requise: bool
    confirmation_demandee: bool
    page_statut: PageStatus | None
    page_raison: str
    page_incertaine: bool
    verification_presente: bool
    ouverts: int
    disponibles: int | None
    capacite: int
    restants: int | None
    echecs: int
    temps_restant_s: float | None
    source_minuteur: str
    action_en_attente: str | None
    clics_envoyes: int
    clics_refuses: int
    seuil_actuel: int
    phase: str
    attente_seuil_s: float | None   # estimation du temps avant d'atteindre le seuil
    verification_depuis_s: float | None   # durée de la vérification en cours (attente passive)
    action_humaine_requise: bool          # vérification bloquée : il faut cocher la case dans Chrome
    lectures_normales_reprise: int        # lectures normales consécutives déjà constatées


class Controller:
    def __init__(self, driver: PageDriver, settings: Settings, log: ActivityLog,
                 clock: Callable[[], float] = time.monotonic, use_thread: bool = True,
                 prefixe_url: str | None = None, rng: random.Random | None = None,
                 attente: Callable[[float], None] | None = None, observation: bool = False,
                 alerte: Callable[[], None] | None = None,
                 sur_verification: Callable[[], None] | None = None, notificateur=None):
        """
        attente : fonction d'attente (secondes) utilisée pour la temporisation avant clic ;
                  par défaut une attente interrompue immédiatement par « Arrêter ».
        observation : True = lecture seule, le programme journalise les clics qu'il AURAIT faits
                      mais n'en envoie aucun.
        alerte : signal sonore quand une vérification attend une action humaine (bip Windows ou Mac).
        sur_verification : appelé à l'apparition d'une vérification (relevé de la page en lecture seule).
        notificateur : `NotificateurDiscord` (ou équivalent). Il ne sert que si `discord_webhook_url` est
                       renseigné ; son envoi est asynchrone et ne retarde jamais la boucle de travail.
        """
        self._driver = driver
        self._settings = settings
        self._log = log
        self._clock = clock
        self._use_thread = use_thread
        self._lock = threading.RLock()

        self._monitor = PageMonitor(settings.capacite_packs, prefixe_url)
        self._packs = PackManager(settings.capacite_packs, settings.objectif_ouvertures,
                                  settings.delai_indicatif_s)
        self._rng = rng or random.Random()
        self._cycle = CycleAleatoire(settings.seuil_min, settings.seuil_max, self._rng)
        self._attente = attente
        self.observation = observation
        self._derniere_observation: tuple | None = None
        self._dernier_etat_attente: tuple | None = None
        self._alerte = alerte
        self._sur_verification = sur_verification
        self._action_humaine_requise = False
        self._notificateur = notificateur
        self._debut_session: float | None = None
        self._pauses_auto = 0
        self._verifications = 0
        self._bilan_envoye = True
        self._state = BotState.ATTENTE
        self._raison = ""
        self._confirmation_requise = False
        self._confirmation_demandee = False
        self._epoch = 0                  # change à chaque transition : invalide les décisions en cours
        self._derniere_eval: Evaluation | None = None
        self._dernier_snap_normal: PageSnapshot | None = None
        self._dernier_statut_journalise: tuple | None = None
        self._verification_presente = False
        self._verification_debut: float | None = None
        self._lectures_normales_verif = 0
        self._cle_stable: tuple | None = None
        self._lectures_stables = 0
        self._lectures_incertaines = 0
        self._clics_envoyes = 0
        self._clics_refuses = 0
        self._test_double_clic = False
        self._worker: threading.Thread | None = None
        self._halt: threading.Event | None = None

    # ============================================================================================
    # Commandes (appelées depuis l'interface)
    # ============================================================================================

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def state(self) -> BotState:
        return self._state

    def start(self) -> bool:
        with self._lock:
            if self._state not in ETATS_INACTIFS:
                self._log.warning(f"Démarrer ignoré : le programme est déjà « {self._state.value} ».")
                return False
            if self._worker is not None and self._worker.is_alive():
                self._log.warning("Démarrer ignoré : l'arrêt précédent n'est pas encore terminé, réessayez.")
                return False
            errors = self._settings.validate()
            if errors:
                self._log.error("Paramètres invalides : " + " ".join(errors))
                return False
            self._packs.reinitialiser_session()
            self._monitor.oublier_reference()
            self._reset_compteurs_lecture()
            self._clics_refuses = 0
            self._debut_session = self._clock()
            self._pauses_auto = self._verifications = 0
            self._bilan_envoye = False
            self._cycle.tirer()
            self._set_state(BotState.EN_COURS, "")
            objectif = (f"objectif {self._settings.objectif_ouvertures} ouverture(s)"
                        if self._settings.objectif_ouvertures else "sans objectif (arrêt manuel)")
            self._log.info(f"Démarrage — {objectif}, seuil aléatoire entre {self._settings.seuil_min} et "
                           f"{self._settings.seuil_max} (tiré : {self._cycle.seuil}), "
                           f"capacité {self._settings.capacite_packs}.")
            if self._use_thread:
                self._halt = threading.Event()
                self._worker = threading.Thread(target=self._run, args=(self._halt,),
                                                name="wikimaster-worker", daemon=True)
                self._worker.start()
            return True

    def pause(self) -> bool:
        with self._lock:
            attente_passive = self._state is BotState.VERIFICATION and not self._confirmation_requise
            if self._state is not BotState.EN_COURS and not attente_passive:
                return False
            self._set_state(BotState.PAUSE, "Pause manuelle")
            self._log.info("Pause manuelle : plus aucun clic jusqu'à « Reprendre ».")
            return True

    def resume(self) -> bool:
        """Reprendre après une pause MANUELLE uniquement."""
        with self._lock:
            if self._state is not BotState.PAUSE:
                return False
            if self._confirmation_requise:
                self._log.warning("Reprendre refusé : cette pause est automatique, utilisez "
                                  "« Confirmer la reprise ».")
                return False
            self._reset_compteurs_lecture()
            self._set_state(BotState.EN_COURS, "")
            self._log.info("Reprise après pause manuelle.")
            return True

    def confirm_resume(self) -> bool:
        """Confirmation manuelle après une interruption. La page est relue avant de reprendre."""
        with self._lock:
            if self._state not in ETATS_PAUSE or not self._confirmation_requise:
                return False
            self._confirmation_demandee = True
            self._log.info("Confirmation reçue : vérification de l'état de la page avant de reprendre…")
            return True

    def stop(self) -> bool:
        with self._lock:
            if self._state in (BotState.ATTENTE, BotState.ARRETE):
                return False
            abandon = self._packs.abandonner()
            self._set_state(BotState.ARRETE, "Arrêt manuel")
            if self._halt is not None:
                self._halt.set()
            self._log.info("ARRÊT : plus aucune action ne sera effectuée. Le navigateur est laissé tel quel.")
            if abandon is not None:
                self._log.warning(f"L'action « {abandon.type} » en attente de résultat n'est pas comptée.")
            self._envoyer_bilan("Arrêt manuel")
            return True

    def apply_settings(self, settings: Settings) -> list[str]:
        errors = settings.validate()
        if errors:
            return errors
        with self._lock:
            self._settings = settings
            self._monitor.capacite_attendue = settings.capacite_packs
            self._packs.capacite = settings.capacite_packs
            self._packs.objectif = settings.objectif_ouvertures
            self._packs.delai_indicatif_s = settings.delai_indicatif_s
            bornes_changees = (self._cycle.seuil_min, self._cycle.seuil_max) != (settings.seuil_min,
                                                                               settings.seuil_max)
            self._cycle.seuil_min, self._cycle.seuil_max = settings.seuil_min, settings.seuil_max
            if bornes_changees and self._cycle.phase != VIDAGE:
                self._cycle.tirer()
            self._log.info(f"Paramètres appliqués : capacité {settings.capacite_packs}, délai pour un nouveau pack "
                           f"{settings.delai_indicatif_s} s, objectif {settings.objectif_ouvertures or 'illimité'}, "
                           f"seuil aléatoire {settings.seuil_min}–{settings.seuil_max} "
                           f"(actuel : {self._cycle.seuil}).")
        return []

    def request_double_click_test(self) -> None:
        """Mode simulation : au prochain clic décidé, tente volontairement un second clic immédiat."""
        with self._lock:
            self._test_double_clic = True
            self._log.info("Test : le prochain clic sera envoyé deux fois de suite (le second doit être refusé).")

    def tester_notification(self, url: str) -> bool:
        """Envoie un message de test au webhook donné (bouton « Tester » de l'interface)."""
        if self._notificateur is None or not url:
            return False
        self._log.info("Envoi d'une notification Discord de test…")
        return self._notificateur.notifier(url, TEST, "Test de notification",
                                           "Les alertes de PafOpener arriveront ici.")

    def attendre_notifications(self, timeout: float) -> bool:
        """À la fermeture : laisse partir les derniers messages (bilan) pendant au plus `timeout` secondes."""
        return self._notificateur is None or self._notificateur.attendre(timeout)

    def join(self, timeout: float | None = None) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def status(self) -> StatusView:
        with self._lock:
            ev = self._derniere_eval
            restant, source = self._packs.temps_restant(self._clock())
            attente = self._packs.en_cours
            return StatusView(
                etat=self._state,
                raison=self._raison,
                confirmation_requise=self._confirmation_requise,
                confirmation_demandee=self._confirmation_demandee,
                page_statut=ev.statut if ev else None,
                page_raison=ev.raison if ev else "",
                page_incertaine=ev is not None and ev.statut is not PageStatus.NORMAL,
                verification_presente=self._verification_presente,
                ouverts=self._packs.ouverts,
                disponibles=self._packs.disponibles,
                capacite=self._settings.capacite_packs,
                restants=self._packs.restants,
                echecs=self._packs.echecs,
                temps_restant_s=restant,
                source_minuteur=source,
                action_en_attente=attente.type if attente else None,
                clics_envoyes=self._clics_envoyes,
                clics_refuses=self._clics_refuses,
                seuil_actuel=self._cycle.seuil,
                phase=self._cycle.phase,
                attente_seuil_s=self._attente_seuil(restant),
                verification_depuis_s=(self._clock() - self._verification_debut
                                       if self._state is BotState.VERIFICATION
                                       and self._verification_debut is not None else None),
                lectures_normales_reprise=self._lectures_normales_verif,
                action_humaine_requise=(self._action_humaine_requise and self._state is BotState.VERIFICATION
                                        and self._verification_presente),
            )

    def _attente_seuil(self, prochain: float | None) -> float | None:
        if self._cycle.phase == VIDAGE:
            return 0.0
        dispo = self._packs.disponibles
        if dispo is None:
            return None
        manquants = self._cycle.seuil - dispo
        if manquants <= 0:
            return 0.0
        if prochain is None:
            return None
        return prochain + (manquants - 1) * self._settings.delai_indicatif_s

    # ============================================================================================
    # Boucle de travail
    # ============================================================================================

    def _run(self, halt: threading.Event) -> None:
        while not halt.is_set():
            try:
                self.tick()
            except Exception as exc:  # filet de sécurité : jamais de boucle folle
                with self._lock:
                    if self._state not in ETATS_INACTIFS:
                        self._pause_auto(BotState.ERREUR, f"Erreur interne inattendue : {exc!r}")
            with self._lock:
                if self._state in ETATS_INACTIFS:
                    return
            halt.wait(self._settings.intervalle_lecture_s)

    def tick(self) -> None:
        """Une itération : lecture, évaluation, éventuellement UN clic."""
        with self._lock:
            if self._state in ETATS_INACTIFS:
                return
            epoch = self._epoch
        action = self._lire_et_decider(epoch)
        if action is None:
            return
        if not self.observation:
            # Temporisation : pas d'enchaînement instantané des clics. Interrompue par « Arrêter ».
            self._attendre(self._rng.uniform(self._settings.delai_clic_min_s, self._settings.delai_clic_max_s))
        # Vérification immédiate avant le clic : nouvelle lecture, même décision exigée.
        confirmation = self._lire_et_decider(epoch)
        if confirmation != action:
            return
        with self._lock:
            double = self._test_double_clic
            self._test_double_clic = False
        self._cliquer(action, epoch)
        if double:
            self._cliquer(action, epoch)

    def _attendre(self, secondes: float) -> None:
        if secondes <= 0:
            return
        if self._attente is not None:
            self._attente(secondes)
        elif self._halt is not None:
            self._halt.wait(secondes)   # se termine immédiatement si « Arrêter » est pressé
        else:
            time.sleep(secondes)

    # --- lecture et décision ---------------------------------------------------------------------

    def _lire_et_decider(self, epoch: int) -> str | None:
        try:
            snap = self._driver.read_snapshot()
        except Exception as exc:
            with self._lock:
                self._erreur_lecture(exc)
            return None
        with self._lock:
            if epoch != self._epoch and self._state is BotState.EN_COURS:
                return None  # l'état a changé pendant la lecture (ex. reprise) : on recommence au tick suivant
            return self._traiter(snap)

    def _traiter(self, snap: PageSnapshot) -> str | None:
        en_cours = self._state is BotState.EN_COURS
        attente = self._packs.en_cours
        ev = self._monitor.evaluer(snap, attente.type if attente else None,
                                   comparer=en_cours and not self.observation)
        self._derniere_eval = ev
        self._dernier_snap_normal = snap if ev.normale else None
        self._journaliser_statut_page(ev)
        if snap.vue is View.PAQUETS and ev.statut in (PageStatus.NORMAL, PageStatus.INCERTAIN):
            if self._packs.observer(snap) and snap.disponibles is not None:
                self._log.info(f"Nouveau pack disponible : {snap.disponibles} / {snap.capacite}.")
                if snap.disponibles >= self._settings.capacite_packs:
                    self._log.warning("Plafond atteint : le site ne génère plus de pack tant qu'aucun n'est ouvert.")
                elif not en_cours and snap.disponibles >= self._settings.capacite_packs - 1:
                    self._log.warning(f"Stock à {snap.disponibles} / {snap.capacite} pendant la pause : "
                                      "le plafond sera bientôt atteint.")

        if not en_cours:
            self._traiter_en_pause(ev, snap)
            return None

        # --- en cours ---
        if ev.statut is PageStatus.VERIFICATION:
            self._verification_presente = True
            self._entrer_verification(ev)
            return None
        if ev.statut is PageStatus.ERREUR:
            self._pause_auto(BotState.ERREUR, ev.raison)
            return None
        if ev.statut is PageStatus.INCERTAIN:
            self._cle_stable, self._lectures_stables = None, 0
            self._lectures_incertaines += 1
            if ev.suspect or self._lectures_incertaines >= self._settings.lectures_incertaines_tolerees:
                self._pause_auto(BotState.PAUSE, f"État de la page incertain : {ev.raison}")
            return None
        self._lectures_incertaines = 0

        if attente is not None:
            self._suivre_resultat(attente, snap)
            return None

        cle = (snap.vue, snap.disponibles, snap.carte_index, snap.encore_n, snap.bouton_continuer_present)
        if cle == self._cle_stable:
            self._lectures_stables += 1
        else:
            self._cle_stable, self._lectures_stables = cle, 1
        if self._lectures_stables < self._settings.lectures_stables_requises:
            return None

        if snap.vue is View.REVELATION:
            if snap.bouton_continuer_present:
                return CONTINUER
            if snap.encore_n is not None and snap.fleche_suivante_active:
                return SUIVANT
            return None
        if self._packs.objectif_atteint:
            self._set_state(BotState.TERMINE, "Objectif atteint")
            self._log.info(f"TERMINÉ : objectif de {self._packs.objectif} ouverture(s) atteint.")
            self._envoyer_bilan("Objectif atteint")
            return None
        if snap.disponibles is None:
            return None
        ouvrir, evenement = self._cycle.faut_il_ouvrir(snap.disponibles)
        if evenement:
            self._log.info(evenement)
        if not ouvrir:
            self._journaliser_attente(snap)
        return OUVRIR if ouvrir else None

    def _journaliser_attente(self, snap: PageSnapshot) -> None:
        """Explique pourquoi aucun clic n'est fait (une ligne par changement de stock ou de seuil)."""
        cle = (snap.disponibles, self._cycle.seuil)
        if cle == self._dernier_etat_attente:
            return
        self._dernier_etat_attente = cle
        manquants = self._cycle.seuil - (snap.disponibles or 0)
        estimation = ""
        if snap.prochain_dans_s is not None and manquants > 0:
            secondes = snap.prochain_dans_s + (manquants - 1) * self._settings.delai_indicatif_s
            estimation = f", environ {secondes // 60} min {secondes % 60:02d} s"
        self._log.info(f"En attente du seuil aléatoire : {snap.disponibles} / {snap.capacite} disponibles, "
                       f"seuil tiré {self._cycle.seuil} → encore {manquants} pack(s){estimation}. "
                       "Aucun clic avant.")

    def _suivre_resultat(self, attempt: Attempt, snap: PageSnapshot) -> None:
        maintenant = self._clock()
        if self._resultat_constate(attempt, snap):
            self._packs.valider(attempt.id)
            if attempt.type == OUVRIR:
                restants = self._packs.restants
                suite = f", {restants} restant(s)" if restants is not None else ""
                self._log.info(f"Pack ouvert et vérifié (révélation affichée) — total : "
                               f"{self._packs.ouverts}{suite}.")
            elif attempt.type == CONTINUER:
                self._log.info("Toutes les cartes révélées, « Continuer » : retour à la page des paquets.")
            self._cle_stable, self._lectures_stables = None, 0
            return
        if maintenant - attempt.debut > self._settings.delai_resultat_s:
            self._packs.abandonner()
            quoi = {OUVRIR: "l'ouverture", SUIVANT: "la révélation de la carte suivante",
                    CONTINUER: "« Continuer »"}[attempt.type]
            self._pause_auto(BotState.PAUSE,
                             f"Résultat de {quoi} non constaté après {self._settings.delai_resultat_s:g} s. "
                             "Non compté, aucune nouvelle tentative. Vérifiez la page puis confirmez.")

    @staticmethod
    def _resultat_constate(attempt: Attempt, snap: PageSnapshot) -> bool:
        avant = attempt.avant
        if attempt.type == OUVRIR:
            return snap.vue is View.REVELATION
        if attempt.type == CONTINUER:
            return snap.vue is View.PAQUETS
        # SUIVANT : la carte suivante est affichée.
        return (snap.vue is View.REVELATION and avant.carte_index is not None
                and snap.carte_index is not None and snap.carte_index > avant.carte_index)

    def _traiter_en_pause(self, ev: Evaluation, snap: PageSnapshot) -> None:
        attente = self._packs.en_cours
        if attente is not None and ev.normale and self._resultat_constate(attente, snap):
            self._packs.valider(attente.id)
            if attente.type == OUVRIR:
                self._log.info(f"Ouverture constatée pendant la pause — total : {self._packs.ouverts}.")
        if self._state is BotState.VERIFICATION:
            presente = ev.statut is PageStatus.VERIFICATION
            self._verifier_action_humaine(presente)
            if presente != self._verification_presente:
                self._verification_presente = presente
                if presente:
                    self._log.warning("La vérification est réapparue. Clics toujours suspendus.")
                elif not self._confirmation_requise:
                    self._log.info("La vérification a disparu d'elle-même. Contrôle de la page avant la "
                                   "reprise automatique…")
                elif ev.normale:
                    self._log.info("La vérification a disparu et la page est revenue à la normale. "
                                   "En attente de votre confirmation pour reprendre.")
                else:
                    self._log.warning(f"La vérification a disparu mais la page n'est pas normale : {ev.raison}.")
            if not self._confirmation_requise:
                self._attente_passive_verification(ev)
                return
        if not self._confirmation_demandee:
            return
        self._confirmation_demandee = False
        if not ev.normale:
            self._log.warning(f"Reprise refusée : page « {ev.statut.value} » — {ev.raison}. Toujours en pause.")
            return
        abandon = self._packs.abandonner()
        if abandon is not None:
            self._log.warning(f"L'action « {abandon.type} » non vérifiée est abandonnée et non comptée.")
        self._monitor.oublier_reference()
        self._reset_compteurs_lecture()
        self._verification_presente = False
        self._set_state(BotState.EN_COURS, "")
        self._log.info("Reprise confirmée : la page est normale, le programme continue.")

    def _entrer_verification(self, ev: Evaluation) -> None:
        self._verification_presente = True
        self._verification_debut = self._clock()
        self._action_humaine_requise = False
        self._verifications += 1
        if self._sur_verification is not None:
            try:
                self._sur_verification()
            except Exception as exc:
                self._log.warning(f"Relevé de la vérification impossible : {exc}")
        self._lectures_normales_verif = 0
        self._lectures_incertaines = 0
        if not self._settings.reprise_auto_verification:
            self._pause_auto(BotState.VERIFICATION, ev.raison)
            return
        self._set_state(BotState.VERIFICATION, ev.raison, confirmation=False)
        self._log.warning(f"VÉRIFICATION détectée : clics suspendus, attente passive de sa disparition "
                          f"(pause manuelle si elle dure plus de {self._settings.verification_delai_max_s:g} s). "
                          f"{ev.raison}")

    def _verifier_action_humaine(self, presente: bool) -> None:
        """Vérification toujours là après quelques secondes : elle attend un humain (case Cloudflare)."""
        if not presente or self._action_humaine_requise or self._verification_debut is None:
            return
        if self._clock() - self._verification_debut < self._settings.alerte_verification_s:
            return
        self._action_humaine_requise = True
        self._log.warning(f"ACTION HUMAINE REQUISE : la vérification ne passe pas seule depuis "
                          f"{self._settings.alerte_verification_s:g} s. Cochez la case dans Chrome vous-même ; "
                          "le bot ne clique jamais dessus et reprendra automatiquement dès qu'elle aura disparu.")
        if self._alerte is not None:
            try:
                self._alerte()
            except Exception as exc:
                self._log.warning(f"Signal sonore impossible : {exc}")
        self._notifier(ALERTE, "⚠ Action humaine requise",
                       f"Une vérification est affichée depuis plus de {self._settings.alerte_verification_s:g} s. "
                       "Cochez la case dans la fenêtre Chrome du bot. Le bot attend sans cliquer et reprendra "
                       "seul dès qu'elle aura disparu.")

    def _attente_passive_verification(self, ev: Evaluation) -> None:
        """Vérification en cours, reprise automatique autorisée : on observe sans jamais cliquer."""
        duree = self._clock() - (self._verification_debut or self._clock())
        if duree > self._settings.verification_delai_max_s:
            self._pause_auto(BotState.VERIFICATION,
                             f"Vérification bloquée depuis plus de {self._settings.verification_delai_max_s:g} s. "
                             "Vérifiez la page dans Chrome puis confirmez la reprise.")
            return
        if ev.statut is PageStatus.VERIFICATION:
            self._lectures_normales_verif = 0
            return
        if ev.statut is PageStatus.ERREUR:
            self._pause_auto(BotState.ERREUR, f"Après la vérification : {ev.raison}")
            return
        if ev.statut is PageStatus.INCERTAIN:
            self._lectures_normales_verif = 0
            self._lectures_incertaines += 1
            if self._lectures_incertaines >= self._settings.lectures_incertaines_tolerees:
                self._pause_auto(BotState.PAUSE, f"Après la vérification, état de la page incertain : {ev.raison}")
            return
        self._lectures_incertaines = 0
        self._lectures_normales_verif += 1
        if self._lectures_normales_verif < self._settings.lectures_normales_reprise:
            return
        attente = self._packs.en_cours
        if attente is not None:
            self._pause_auto(BotState.PAUSE,
                             f"Le résultat de l'action « {attente.type} » envoyée avant la vérification n'est pas "
                             "constaté. Non compté, aucune nouvelle tentative. Vérifiez la page puis confirmez.")
            return
        self._monitor.oublier_reference()
        self._reset_compteurs_lecture()
        self._verification_presente = False
        self._action_humaine_requise = False
        self._set_state(BotState.EN_COURS, "")
        self._log.info(f"Reprise automatique : vérification disparue après {duree:.0f} s, page normale sur "
                       f"{self._settings.lectures_normales_reprise} lectures consécutives.")

    # --- clic ------------------------------------------------------------------------------------

    def _cliquer(self, action: str, epoch: int) -> None:
        with self._lock:
            if epoch != self._epoch or self._state is not BotState.EN_COURS:
                self._log.info("Clic annulé : le programme n'est plus en cours.")
                return
            if self.observation:
                cle = (action, self._cle_stable)
                if cle != self._derniere_observation:
                    self._derniere_observation = cle
                    self._log.info(f"[Observation] Le programme aurait cliqué sur « {action} » "
                                   "(aucun clic envoyé).")
                return
            snap = self._dernier_snap_normal
            if snap is None:
                self._log.warning(f"Clic « {action} » annulé : aucune lecture normale récente de la page.")
                return
            attempt = self._packs.commencer(action, snap, self._clock(),
                                            self._settings.intervalle_min_clics_s)
            if attempt is None:
                _, raison = self._packs.peut_cliquer(self._clock(), self._settings.intervalle_min_clics_s)
                self._clics_refuses += 1
                self._log.warning(f"Clic « {action} » refusé (anti-double-clic) : {raison}.")
                return
            self._clics_envoyes += 1
        try:
            if action == OUVRIR:
                self._driver.click_open()
            elif action == SUIVANT:
                self._driver.click_next_card()
            elif action == CONTINUER:
                self._driver.click_continue()
            else:
                raise ValueError(f"action inconnue : {action}")
        except Exception as exc:
            with self._lock:
                self._packs.abandonner()
                if self._state is BotState.EN_COURS:
                    self._pause_auto(BotState.PAUSE,
                                     f"Échec du clic « {action} » ({exc}). Résultat inconnu : non compté, "
                                     "aucune nouvelle tentative.")
            return
        with self._lock:
            if self._state is not BotState.EN_COURS:
                self._log.warning(f"Le clic « {action} » était déjà parti au moment de l'interruption : "
                                  "vérifiez la page avant de reprendre.")
            elif action == OUVRIR:
                self._log.info("Clic sur « Ouvrir » envoyé. Vérification du résultat…")

    # --- utilitaires -----------------------------------------------------------------------------

    def _erreur_lecture(self, exc: Exception) -> None:
        self._derniere_eval = Evaluation(PageStatus.ERREUR, f"Lecture de la page impossible : {exc}")
        self._journaliser_statut_page(self._derniere_eval)
        if self._state is BotState.EN_COURS:
            self._pause_auto(BotState.ERREUR, f"Lecture de la page impossible : {exc}")
        elif self._confirmation_demandee:
            self._confirmation_demandee = False
            self._log.warning("Reprise refusée : la page ne peut pas être lue.")

    def _pause_auto(self, etat: BotState, raison: str) -> None:
        self._set_state(etat, raison, confirmation=True)
        self._pauses_auto += 1
        self._log.log("ERREUR" if etat is BotState.ERREUR else "ATTENTION",
                      f"PAUSE AUTOMATIQUE ({etat.value}) : {raison}")
        self._notifier(PAUSE, f"⏸ Pause de sécurité — {etat.value}",
                       f"{raison}\n\nAucun clic jusqu'à « Confirmer la reprise » dans le bot. "
                       f"Packs ouverts : {self._packs.ouverts}.")

    def _notifier(self, niveau: str, titre: str, message: str) -> None:
        """Dépose une notification Discord si un webhook est configuré. Ne bloque pas, ne lève jamais."""
        url = self._settings.discord_webhook_url
        if self._notificateur is None or not url:
            return
        try:
            self._notificateur.notifier(url, niveau, titre, message)
        except Exception as exc:
            self._log.warning(f"Notification Discord impossible : {exc}")

    def _envoyer_bilan(self, fin: str) -> None:
        if self._bilan_envoye:
            return
        self._bilan_envoye = True
        if not self._settings.discord_bilan_session:
            return
        duree = int(self._clock() - self._debut_session) if self._debut_session is not None else 0
        heures, reste = divmod(duree, 3600)
        self._notifier(BILAN, f"📊 Bilan de session — {fin}",
                       f"Packs ouverts : {self._packs.ouverts}\n"
                       f"Durée : {heures} h {reste // 60:02d} min\n"
                       f"Clics envoyés : {self._clics_envoyes} (refusés : {self._clics_refuses})\n"
                       f"Vérifications rencontrées : {self._verifications}\n"
                       f"Pauses de sécurité : {self._pauses_auto}")

    def _set_state(self, etat: BotState, raison: str, confirmation: bool = False) -> None:
        self._state = etat
        self._raison = raison
        self._confirmation_requise = confirmation
        self._confirmation_demandee = False
        self._epoch += 1

    def _reset_compteurs_lecture(self) -> None:
        self._cle_stable, self._lectures_stables = None, 0
        self._lectures_incertaines = 0

    def _journaliser_statut_page(self, ev: Evaluation) -> None:
        cle = (ev.statut, ev.raison)
        if cle == self._dernier_statut_journalise:
            return
        precedent = self._dernier_statut_journalise
        self._dernier_statut_journalise = cle
        if ev.normale:
            if precedent is not None:
                self._log.info("Page : état normal.")
            return
        self._log.warning(f"Page : {ev.statut.value} — {ev.raison}")
