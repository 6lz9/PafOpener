"""Classement de l'état de la page : NORMAL, VÉRIFICATION, INCERTAIN ou ERREUR.

Principe : la page n'est NORMALE que si tous les éléments attendus sont présents et cohérents
et qu'aucune fenêtre ne la recouvre. Tout le reste bloque les clics. Le moniteur ne fait que lire :
il n'interagit jamais avec une vérification (pas de résolution, pas de contournement, pas de masquage,
pas de clic sur « Annuler »).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum

from .page_model import PageSnapshot, View

# Textes de la fenêtre observée sur wiki-masters.com (capture verification.png) :
#   « Vérification rapide »
#   « On vérifie que tu es bien humain. Ça ne prend qu'une seconde. »
#   « Vérification... »   [Annuler]
# + formulations génériques de vérification anti-bot. Comparaison sans accents ni majuscules.
SIGNATURES_VERIFICATION = (
    "verification rapide",
    "tu es bien humain",
    "on verifie que",
    "verification...",
    "verification…",
    "etes-vous humain",
    "vous etes humain",          # case à cocher Cloudflare Turnstile « Vérifiez que vous êtes humain »
    "cloudflare",
    "captcha",
    "turnstile",
    "verify you are human",
    "are you human",
)


def normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    return " ".join(sans_accents.lower().split())


def est_verification(texte: str) -> bool:
    t = normaliser(texte)
    return any(sig in t for sig in SIGNATURES_VERIFICATION)


class PageStatus(Enum):
    NORMAL = "Normale"
    VERIFICATION = "Vérification détectée"
    INCERTAIN = "Incertaine"
    ERREUR = "Erreur"


@dataclass(frozen=True)
class Evaluation:
    statut: PageStatus
    raison: str = ""
    # True pour un changement inexpliqué de la page : pause immédiate, sans tolérance.
    suspect: bool = False

    @property
    def normale(self) -> bool:
        return self.statut is PageStatus.NORMAL


class PageMonitor:
    def __init__(self, capacite_attendue: int, prefixe_url: str | None = None):
        self.capacite_attendue = capacite_attendue
        self.prefixe_url = prefixe_url
        self._precedent: PageSnapshot | None = None

    def oublier_reference(self) -> None:
        """À appeler après une reprise confirmée : les changements faits pendant la pause ne sont pas suspects."""
        self._precedent = None

    def evaluer(self, snap: PageSnapshot, action_en_attente: str | None = None,
                comparer: bool = True) -> Evaluation:
        """Évalue une lecture.

        action_en_attente : type de la dernière action du programme dont le résultat n'est pas encore
        constaté (« ouvrir », « suivant », « continuer »), pour distinguer un changement attendu d'un
        changement suspect.
        comparer : False pendant une pause (l'utilisateur peut agir lui-même sur la page).
        """
        evaluation = self._evaluer(snap, action_en_attente, comparer)
        if snap.erreur is None and snap.modale_texte is None:
            self._precedent = snap
        return evaluation

    def _evaluer(self, snap: PageSnapshot, action: str | None, comparer: bool) -> Evaluation:
        if snap.erreur:
            return Evaluation(PageStatus.ERREUR, snap.erreur)
        if snap.session_expiree:
            return Evaluation(PageStatus.ERREUR, "Session expirée : reconnectez-vous manuellement dans le navigateur")
        if snap.modale_texte is not None:
            extrait = " ".join(snap.modale_texte.split())[:90]
            if est_verification(snap.modale_texte):
                return Evaluation(PageStatus.VERIFICATION, f"Vérification automatique affichée : « {extrait} »")
            return Evaluation(PageStatus.INCERTAIN, f"Fenêtre inattendue affichée : « {extrait} »")
        if self.prefixe_url and not (snap.url or "").startswith(self.prefixe_url):
            return Evaluation(PageStatus.INCERTAIN, f"Adresse inattendue : {snap.url!r}")

        if snap.vue is View.PAQUETS and snap.ouverture_en_cours:
            # « Ouverture... » : état transitoire normal juste après NOTRE clic sur « Ouvrir ».
            if snap.disponibles is None or snap.capacite is None:
                return Evaluation(PageStatus.INCERTAIN, "Compteur de packs disponibles absent ou illisible")
            if action != "ouvrir":
                return Evaluation(PageStatus.INCERTAIN, "Ouverture d'un pack en cours sans action du programme "
                                  "(ouverture faite à la main dans Chrome ?)",
                                  suspect=comparer)
            return Evaluation(PageStatus.NORMAL)
        if snap.vue is View.PAQUETS:
            raison = self._verifier_paquets(snap)
        elif snap.vue is View.REVELATION:
            raison = self._verifier_revelation(snap)
        else:
            raison = "Interface inattendue : ni la page des paquets ni la révélation des cartes"
        if raison:
            return Evaluation(PageStatus.INCERTAIN, raison)

        if comparer:
            raison = self._changement_suspect(snap, action)
            if raison:
                return Evaluation(PageStatus.INCERTAIN, raison, suspect=True)
        return Evaluation(PageStatus.NORMAL)

    def _verifier_paquets(self, snap: PageSnapshot) -> str:
        if snap.disponibles is None or snap.capacite is None:
            return "Compteur de packs disponibles absent ou illisible"
        if snap.capacite != self.capacite_attendue:
            return (f"Capacité affichée ({snap.capacite}) différente de la capacité configurée "
                    f"({self.capacite_attendue})")
        if not 0 <= snap.disponibles <= snap.capacite:
            return f"Compteur incohérent : {snap.disponibles} / {snap.capacite}"
        if not snap.bouton_ouvrir_present:
            return "Bouton « Ouvrir » absent"
        if snap.disponibles > 0 and not snap.bouton_ouvrir_actif:
            return "Bouton « Ouvrir » inactif alors que des packs sont disponibles"
        if snap.disponibles == 0 and snap.bouton_ouvrir_actif:
            return "Bouton « Ouvrir » actif alors qu'aucun pack n'est disponible"
        if snap.disponibles < snap.capacite and snap.prochain_dans_s is None:
            return "Minuteur « Prochain dans » absent ou illisible"
        return ""

    @staticmethod
    def _verifier_revelation(snap: PageSnapshot) -> str:
        if snap.carte_index is None or snap.carte_total is None:
            return "Numéro de carte « Carte N / 5 » absent ou illisible"
        if not 1 <= snap.carte_index <= snap.carte_total:
            return f"Numéro de carte incohérent : {snap.carte_index} / {snap.carte_total}"
        if snap.encore_n is not None and snap.bouton_continuer_present:
            return "« Encore N cartes » et « Continuer » affichés en même temps"
        if snap.encore_n is None and not snap.bouton_continuer_present:
            return "Ni « Encore N cartes » ni « Continuer » n'est affiché"
        if snap.encore_n is not None:
            if not 1 <= snap.encore_n < snap.carte_total:
                return f"« Encore {snap.encore_n} cartes » incohérent pour un paquet de {snap.carte_total}"
            if not snap.fleche_suivante_active:
                return "Cartes restant à révéler mais flèche suivante inactive"
        return ""

    def _changement_suspect(self, snap: PageSnapshot, action: str | None) -> str:
        prev = self._precedent
        if prev is None:
            return ""
        if prev.vue is View.PAQUETS and snap.vue is View.REVELATION and action != "ouvrir":
            return "Révélation de cartes apparue sans action du programme"
        if prev.vue is View.REVELATION and snap.vue is View.PAQUETS and action != "continuer":
            return "Retour à la page des paquets sans action du programme"
        if (prev.vue is View.REVELATION and snap.vue is View.REVELATION and action != "suivant"
                and prev.carte_index != snap.carte_index):
            return (f"Carte affichée modifiée ({prev.carte_index} → {snap.carte_index}) "
                    "sans action du programme")
        if (prev.vue is View.PAQUETS and snap.vue is View.PAQUETS and action != "ouvrir"
                and prev.disponibles is not None and snap.disponibles is not None
                and snap.disponibles < prev.disponibles):
            return (f"Packs disponibles en baisse ({prev.disponibles} → {snap.disponibles}) "
                    "sans action du programme")
        return ""
