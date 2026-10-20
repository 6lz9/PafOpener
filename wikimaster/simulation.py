"""Page Wiki Master simulée, calquée sur les captures de https://www.wiki-masters.com/pulls.

- Page des paquets : « X / 10 paquets disponibles », « Prochain dans M:SS », bouton « Ouvrir »
  (inactif à 0, « Ouverture... » pendant l'ouverture), bouton d'achat « Rechargez 10 paquets » visible à 0 (jamais cliquable ici).
- Révélation : « Carte N / 5 ». Le bouton « Encore N cartes » est INACTIF : il faut cliquer sur la
  flèche pour révéler chaque carte. N diminue (4, 3, 2, 1) à chaque carte révélée, puis le bouton
  devient « Continuer », qui ramène à la page des paquets.
- Vérification : fenêtre « Vérification rapide » par-dessus la page floutée, qui disparaît seule.
- Un pack est généré toutes les `delai_s` secondes (± `alea_s`) tant que le stock est sous le plafond.

Aucune connexion réseau : rien n'est envoyé au site réel.
"""
from __future__ import annotations

import math
import random
import threading
import time

from .page_model import PageSnapshot, View

URL_SIMULEE = "https://www.wiki-masters.com/pulls"
TEXTE_VERIFICATION = ("Vérification rapide\nOn vérifie que tu es bien humain. Ça ne prend qu'une seconde.\n"
                      "Vérification...\nAnnuler")
TEXTE_VERIFICATION_CASE = ("Vérification rapide\nOn vérifie que tu es bien humain. Ça ne prend qu'une seconde.\n"
                           "[Cloudflare Turnstile] Vérifiez que vous êtes humain\nAnnuler")
TEXTE_FENETRE_INCONNUE = "Nouveau succès débloqué !\nFermer"


class ManualClock:
    """Horloge manuelle pour les tests : le temps n'avance que par `advance()`."""

    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, secondes: float) -> None:
        self.t += secondes


class AcceleratedClock:
    """Horloge accélérée pour la simulation interactive (vitesse modifiable à chaud, sans saut)."""

    def __init__(self, vitesse: float = 1.0):
        self._lock = threading.Lock()
        self._base_reel = time.monotonic()
        self._base_sim = 0.0
        self._vitesse = vitesse

    def __call__(self) -> float:
        with self._lock:
            return self._base_sim + (time.monotonic() - self._base_reel) * self._vitesse

    @property
    def vitesse(self) -> float:
        return self._vitesse

    def set_vitesse(self, vitesse: float) -> None:
        with self._lock:
            maintenant = time.monotonic()
            self._base_sim += (maintenant - self._base_reel) * self._vitesse
            self._base_reel = maintenant
            self._vitesse = vitesse


class SimulatedPage:
    """Implémente `PageDriver`. Les méthodes `declencher_*` et les attributs d'incident injectent des pannes."""

    def __init__(self, clock, capacite: int = 10, delai_s: float = 180.0, alea_s: float = 0.0,
                 disponibles: int = 1, cartes_par_pack: int = 5, latence_ouverture_s: float = 0.0,
                 seed: int | None = None):
        self._clock = clock
        self._lock = threading.RLock()
        self._rng = random.Random(seed)
        self.capacite = capacite
        self.delai_s = delai_s
        self.alea_s = alea_s
        self.cartes_par_pack = cartes_par_pack
        self.latence_ouverture_s = latence_ouverture_s

        self.disponibles = disponibles
        self.vue = View.PAQUETS
        self.carte_index = 0
        self.cartes_revelees = 0
        self._prochain_at: float | None = None
        self._ouverture_prevue_at: float | None = None
        self._planifier_prochain(self._clock())
        self.verification_jusqua: float | None = None
        self.verification_case = False   # case Cloudflare : ne disparaît que si « l'humain » la coche

        # Incidents injectables
        self.erreur_reseau = False
        self.session_expiree = False
        self.interface_modifiee = False
        self.minuteur_illisible = False
        self.fenetre_inconnue = False
        self.echec_prochaine_ouverture = False
        self.exception_prochaine_lecture: Exception | None = None
        self.exception_prochain_clic: Exception | None = None

        # Compteurs d'observation (pour les tests)
        self.clics_ouvrir = 0
        self.clics_fleche = 0
        self.clics_continuer = 0
        self.clics_ignores = 0            # clics qui n'avaient aucun effet possible
        self.clics_pendant_modale = 0     # clics envoyés alors qu'une fenêtre recouvrait la page
        self.packs_ouverts = 0
        self.achats = 0                   # aucune méthode ne permet d'acheter : doit rester à 0
        self.max_disponibles = disponibles
        self.historique_ouvertures: list[tuple[float, int]] = []  # (instant, stock juste avant)

    # --- génération des packs ---------------------------------------------------------------------

    def _planifier_prochain(self, depuis: float) -> None:
        if self.disponibles >= self.capacite:
            self._prochain_at = None
            return
        alea = self._rng.uniform(-self.alea_s, self.alea_s) if self.alea_s else 0.0
        self._prochain_at = depuis + max(1.0, self.delai_s + alea)

    def _avancer(self) -> None:
        maintenant = self._clock()
        while self._prochain_at is not None and maintenant >= self._prochain_at:
            self.disponibles += 1
            self.max_disponibles = max(self.max_disponibles, self.disponibles)
            self._planifier_prochain(self._prochain_at)
        if self._ouverture_prevue_at is not None and maintenant >= self._ouverture_prevue_at:
            self._ouverture_prevue_at = None
            self._effectuer_ouverture(maintenant)

    def _effectuer_ouverture(self, maintenant: float) -> None:
        etait_plein = self.disponibles >= self.capacite
        self.historique_ouvertures.append((maintenant, self.disponibles))
        self.disponibles -= 1
        self.packs_ouverts += 1
        if etait_plein:
            self._planifier_prochain(maintenant)
        self.vue = View.REVELATION
        self.carte_index = 1
        self.cartes_revelees = 1

    def verification_visible(self) -> bool:
        return self.verification_jusqua is not None and self._clock() < self.verification_jusqua

    def _texte_modale(self) -> str | None:
        if self.verification_case:
            return TEXTE_VERIFICATION_CASE
        if self.verification_visible():
            return TEXTE_VERIFICATION
        if self.fenetre_inconnue:
            return TEXTE_FENETRE_INCONNUE
        return None

    # --- PageDriver -------------------------------------------------------------------------------

    def read_snapshot(self) -> PageSnapshot:
        with self._lock:
            if self.exception_prochaine_lecture is not None:
                exc, self.exception_prochaine_lecture = self.exception_prochaine_lecture, None
                raise exc
            self._avancer()
            maintenant = self._clock()
            if self.erreur_reseau:
                return PageSnapshot(maintenant, None, View.INCONNUE,
                                    erreur="Page inaccessible : perte de connexion (simulée)")
            if self.session_expiree:
                return PageSnapshot(maintenant, "https://www.wiki-masters.com/login", View.INCONNUE,
                                    session_expiree=True)
            modale = self._texte_modale()
            if self.interface_modifiee:
                return PageSnapshot(maintenant, URL_SIMULEE, View.INCONNUE, modale_texte=modale)
            if self.vue is View.REVELATION:
                tout_revele = self.cartes_revelees >= self.cartes_par_pack
                return PageSnapshot(
                    maintenant, URL_SIMULEE, View.REVELATION,
                    carte_index=self.carte_index, carte_total=self.cartes_par_pack,
                    fleche_suivante_active=self.carte_index < self.cartes_par_pack,
                    encore_n=None if tout_revele else self.cartes_par_pack - self.cartes_revelees,
                    bouton_continuer_present=tout_revele,
                    modale_texte=modale)
            prochain = None
            if self._prochain_at is not None and not self.minuteur_illisible:
                prochain = max(0, math.ceil(self._prochain_at - maintenant))
            ouverture = self._ouverture_prevue_at is not None   # bouton « Ouverture... » inactif
            return PageSnapshot(
                maintenant, URL_SIMULEE, View.PAQUETS,
                disponibles=self.disponibles, capacite=self.capacite, prochain_dans_s=prochain,
                bouton_ouvrir_present=not ouverture, bouton_ouvrir_actif=self.disponibles > 0 and not ouverture,
                bouton_achat_visible=self.disponibles == 0,
                ouverture_en_cours=ouverture,
                modale_texte=modale)

    def click_open(self) -> None:
        with self._lock:
            self.clics_ouvrir += 1
            self._lever_exception_clic()
            self._avancer()
            if not self._clic_possible() or self.vue is not View.PAQUETS or self.disponibles <= 0 \
                    or self._ouverture_prevue_at is not None:
                self.clics_ignores += 1
                return
            if self.echec_prochaine_ouverture:
                self.echec_prochaine_ouverture = False
                return  # le clic part mais le site ne réagit pas
            if self.latence_ouverture_s > 0:
                self._ouverture_prevue_at = self._clock() + self.latence_ouverture_s
            else:
                self._effectuer_ouverture(self._clock())

    def click_next_card(self) -> None:
        with self._lock:
            self.clics_fleche += 1
            self._lever_exception_clic()
            if not self._clic_possible() or self.vue is not View.REVELATION \
                    or self.carte_index >= self.cartes_par_pack:
                self.clics_ignores += 1
                return
            self.carte_index += 1
            self.cartes_revelees = max(self.cartes_revelees, self.carte_index)

    def click_continue(self) -> None:
        with self._lock:
            self.clics_continuer += 1
            self._lever_exception_clic()
            if not self._clic_possible() or self.vue is not View.REVELATION \
                    or self.cartes_revelees < self.cartes_par_pack:
                self.clics_ignores += 1
                return
            self.vue = View.PAQUETS
            self.carte_index = 0
            self.cartes_revelees = 0

    def _clic_possible(self) -> bool:
        if self._texte_modale() is not None:
            self.clics_pendant_modale += 1   # la fenêtre intercepte le clic
            return False
        return not (self.erreur_reseau or self.session_expiree or self.interface_modifiee)

    def _lever_exception_clic(self) -> None:
        if self.exception_prochain_clic is not None:
            exc, self.exception_prochain_clic = self.exception_prochain_clic, None
            raise exc

    # --- incidents (panneau de simulation et tests) -------------------------------------------------

    @property
    def clics_total(self) -> int:
        return self.clics_ouvrir + self.clics_fleche + self.clics_continuer

    def declencher_verification(self, duree_s: float) -> None:
        with self._lock:
            self.verification_jusqua = self._clock() + duree_s

    def terminer_verification(self) -> None:
        with self._lock:
            self.verification_jusqua = None

    def declencher_case_cloudflare(self) -> None:
        """Vérification qui attend qu'un humain coche la case (ne disparaît jamais seule)."""
        with self._lock:
            self.verification_case = True

    def cocher_case_humain(self) -> None:
        """Simule VOTRE clic sur la case (le bot, lui, ne peut pas le faire)."""
        with self._lock:
            self.verification_case = False

    def ajouter_pack(self) -> None:
        with self._lock:
            self._avancer()
            if self.disponibles < self.capacite:
                self.disponibles += 1
                self.max_disponibles = max(self.max_disponibles, self.disponibles)
                if self.disponibles >= self.capacite:
                    self._prochain_at = None

    def ouverture_manuelle(self) -> None:
        """Simule l'utilisateur qui ouvre un pack lui-même dans le navigateur."""
        with self._lock:
            self._avancer()
            if self.vue is View.PAQUETS and self.disponibles > 0:
                self._effectuer_ouverture(self._clock())

    def retablir(self) -> None:
        with self._lock:
            self.erreur_reseau = False
            self.session_expiree = False
            self.interface_modifiee = False
            self.minuteur_illisible = False
            self.fenetre_inconnue = False
            self.echec_prochaine_ouverture = False
            self.verification_jusqua = None
            self.verification_case = False
