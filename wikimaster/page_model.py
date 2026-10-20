"""Description neutre de la page des packs, commune à la simulation et à la vraie page.

Le contrôleur ne voit la page qu'à travers `PageSnapshot` (lecture) et `PageDriver` (actions).
Il n'existe volontairement AUCUNE méthode pour cliquer sur :
  - le bouton d'achat « Rechargez 10 paquets — 1,99 $ CAD » ;
  - le bouton « Annuler » de la fenêtre « Vérification rapide » (ni aucun élément d'une fenêtre modale) ;
  - le bouton « Encore N cartes » (inactif tant que toutes les cartes ne sont pas révélées).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class View(Enum):
    PAQUETS = "page des paquets"          # « Ouvrir un paquet », compteur « X / 10 », bouton « Ouvrir »
    REVELATION = "révélation des cartes"  # « Carte N / 5 », flèche suivante, « Encore N cartes » / « Continuer »
    INCONNUE = "interface inconnue"


@dataclass(frozen=True)
class PageSnapshot:
    """Lecture instantanée de la page. `None` = élément absent ou illisible.

    Le pilote rapporte ce qu'il voit, sans l'interpréter : c'est `PageMonitor` qui décide
    si la page est normale, en vérification, incertaine ou en erreur.
    """

    pris_a: float                         # horloge du contrôleur au moment de la lecture
    url: str | None
    vue: View
    # --- page des paquets ---
    disponibles: int | None = None        # « 1 » dans « 1 / 10 »
    capacite: int | None = None           # « 10 » dans « 1 / 10 »
    prochain_dans_s: int | None = None    # « Prochain dans 2:09 »
    bouton_ouvrir_present: bool = False
    bouton_ouvrir_actif: bool = False
    bouton_achat_visible: bool = False    # information seulement : jamais cliqué
    ouverture_en_cours: bool = False      # le bouton affiche « Ouverture... » (transitoire, inactif)
    # --- révélation des cartes ---
    carte_index: int | None = None        # « Carte 1 / 5 »
    carte_total: int | None = None
    fleche_suivante_active: bool = False  # flèche qui révèle la carte suivante
    encore_n: int | None = None           # « Encore N cartes » (None = bouton absent)
    bouton_continuer_present: bool = False
    # --- superpositions et erreurs ---
    modale_texte: str | None = None       # texte de toute fenêtre/superposition visible (None = aucune)
    session_expiree: bool = False
    erreur: str | None = None             # page inaccessible, perte de connexion…


class PageDriver(Protocol):
    """Accès à la page. Toutes les méthodes sont appelées depuis un seul thread (celui du contrôleur)."""

    def read_snapshot(self) -> PageSnapshot: ...

    def click_open(self) -> None:
        """Un seul clic sur « Ouvrir ». Ne réessaie jamais."""

    def click_next_card(self) -> None:
        """Un seul clic sur la flèche qui révèle la carte suivante. Ne réessaie jamais."""

    def click_continue(self) -> None:
        """Un seul clic sur « Continuer » (toutes les cartes révélées). Ne réessaie jamais."""
