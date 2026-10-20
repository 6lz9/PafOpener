"""Suivi des packs : compteurs, minuteur et verrou anti-double-clic.

Règle centrale : une seule tentative d'action à la fois. Tant que le résultat d'un clic n'a pas
été constaté sur la page (succès) ou abandonné (échec / incertitude), tout nouveau clic est refusé.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass

from .page_model import PageSnapshot

OUVRIR = "ouvrir"
SUIVANT = "suivant"      # flèche qui révèle la carte suivante
CONTINUER = "continuer"  # « Continuer » une fois toutes les cartes révélées

ACCUMULATION = "accumulation"
VIDAGE = "vidage"


class CycleAleatoire:
    """Rythme d'ouverture aléatoire.

    Accumulation : on attend sans ouvrir que le stock atteigne un seuil tiré au sort entre
    seuil_min et seuil_max (bornes incluses).
    Vidage : on ouvre les packs un par un jusqu'à ce que le site affiche 0, puis on tire un nouveau seuil.
    """

    def __init__(self, seuil_min: int, seuil_max: int, rng: random.Random | None = None):
        self.seuil_min = seuil_min
        self.seuil_max = seuil_max
        self._rng = rng or random.Random()
        self.seuil = 0
        self.phase = ACCUMULATION
        self.cycles_termines = 0
        self.tirer()

    def tirer(self) -> int:
        self.seuil = self._rng.randint(self.seuil_min, self.seuil_max)
        self.phase = ACCUMULATION
        return self.seuil

    def faut_il_ouvrir(self, disponibles: int) -> tuple[bool, str]:
        """Décision pour une lecture normale et stable. Retourne (ouvrir ?, événement à journaliser)."""
        evenement = ""
        if self.phase == ACCUMULATION and disponibles >= self.seuil:
            self.phase = VIDAGE
            evenement = (f"Seuil aléatoire atteint ({disponibles} ≥ {self.seuil}) : ouverture des packs "
                         "jusqu'à revenir à 0.")
        if self.phase == VIDAGE and disponibles == 0:
            self.cycles_termines += 1
            ancien = self.seuil
            self.tirer()
            return False, f"Stock vidé (cycle à {ancien}). Nouveau seuil aléatoire : {self.seuil}."
        return self.phase == VIDAGE, evenement


@dataclass(frozen=True)
class Attempt:
    id: int
    type: str                 # OUVRIR ou SUIVANT
    debut: float
    avant: PageSnapshot       # lecture juste avant le clic


class PackManager:
    def __init__(self, capacite: int, objectif: int, delai_indicatif_s: float):
        self.capacite = capacite
        self.objectif = objectif
        self.delai_indicatif_s = delai_indicatif_s
        self._ids = itertools.count(1)
        self.reinitialiser_session()

    def reinitialiser_session(self) -> None:
        self.ouverts = 0
        self.echecs = 0
        self.disponibles: int | None = None
        self.max_disponibles_vu = 0
        self.en_cours: Attempt | None = None
        self.dernier_clic: float | None = None
        self._minuteur_site: tuple[float, int] | None = None  # (pris_a, secondes)
        self._echeance_locale: float | None = None

    # --- compteurs -------------------------------------------------------------------------------

    @property
    def restants(self) -> int | None:
        """Ouvertures restantes avant l'objectif (None = pas d'objectif)."""
        if self.objectif <= 0:
            return None
        return max(0, self.objectif - self.ouverts)

    @property
    def objectif_atteint(self) -> bool:
        return self.objectif > 0 and self.ouverts >= self.objectif

    def observer(self, snap: PageSnapshot) -> bool:
        """Met à jour les compteurs avec une lecture valide de la page des paquets.

        Retourne True si un nouveau pack est apparu depuis la lecture précédente.
        """
        if snap.disponibles is None:
            return False
        nouveau = self.disponibles is not None and snap.disponibles > self.disponibles
        if self.disponibles is None or nouveau:
            self._echeance_locale = snap.pris_a + self.delai_indicatif_s
        if snap.disponibles >= self.capacite:
            self._echeance_locale = None
        self.disponibles = snap.disponibles
        self.max_disponibles_vu = max(self.max_disponibles_vu, snap.disponibles)
        self._minuteur_site = (snap.pris_a, snap.prochain_dans_s) if snap.prochain_dans_s is not None else None
        return nouveau

    def temps_restant(self, maintenant: float) -> tuple[float | None, str]:
        """Temps avant le prochain pack : minuteur du site si lisible, sinon estimation locale."""
        if self.disponibles is not None and self.disponibles >= self.capacite:
            return None, "plafond atteint"
        if self._minuteur_site is not None:
            pris_a, secondes = self._minuteur_site
            return max(0.0, secondes - (maintenant - pris_a)), "site"
        if self._echeance_locale is not None:
            return max(0.0, self._echeance_locale - maintenant), "estimation locale"
        return None, "inconnu"

    # --- verrou anti-double-clic -----------------------------------------------------------------

    def peut_cliquer(self, maintenant: float, intervalle_min_s: float) -> tuple[bool, str]:
        if self.en_cours is not None:
            return False, f"une action « {self.en_cours.type} » attend encore son résultat"
        if self.dernier_clic is not None and maintenant - self.dernier_clic < intervalle_min_s:
            return False, f"moins de {intervalle_min_s:g} s depuis le clic précédent"
        return True, ""

    def commencer(self, type_action: str, avant: PageSnapshot, maintenant: float,
                  intervalle_min_s: float) -> Attempt | None:
        """Réserve le droit de cliquer. Retourne None si un clic est déjà en cours ou trop récent."""
        ok, _ = self.peut_cliquer(maintenant, intervalle_min_s)
        if not ok:
            return None
        self.en_cours = Attempt(next(self._ids), type_action, maintenant, avant)
        self.dernier_clic = maintenant
        return self.en_cours

    def valider(self, attempt_id: int) -> bool:
        """Résultat constaté sur la page. Compte l'ouverture une seule fois par tentative."""
        if self.en_cours is None or self.en_cours.id != attempt_id:
            return False
        if self.en_cours.type == OUVRIR:
            self.ouverts += 1
        self.en_cours = None
        return True

    def abandonner(self) -> Attempt | None:
        """Résultat non constaté : la tentative n'est PAS comptée et ne sera PAS répétée."""
        attempt, self.en_cours = self.en_cours, None
        if attempt is not None and attempt.type == OUVRIR:
            self.echecs += 1
        return attempt
