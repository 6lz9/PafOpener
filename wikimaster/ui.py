"""Interface CustomTkinter (thème sombre). Elle ne touche jamais la page : elle envoie des commandes au
contrôleur et affiche son état toutes les 250 ms."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from .config import DEFAULT_SETTINGS_PATH, ICONE_PATH, LOGO_PATH, Settings
from .controller import ETATS_INACTIFS, BotState, Controller, StatusView
from .logger import ATTENTION, ERREUR, ActivityLog
from .pack_manager import VIDAGE
from .page_monitor import PageStatus

RAFRAICHISSEMENT_MS = 250
DELAI_CLIC_BORNES = (0.0, 10.0)   # plage des curseurs de temporisation (= bornes acceptées par Settings)
# Segoe UI et Consolas n'existent pas sur Mac : polices système équivalentes.
POLICE, POLICE_MONO = ("Helvetica Neue", "Menlo") if sys.platform == "darwin" else ("Segoe UI", "Consolas")

# --- palette ----------------------------------------------------------------------------------------
FOND = "#0d1117"
CARTE = "#161b22"
CARTE_CLAIRE = "#1f2633"
BORD = "#2a3140"
TEXTE = "#e6edf3"
TEXTE_DOUX = "#8b949e"
ACCENT = "#82C8E5"          # couleur principale de PafOpener (boutons actifs, onglets, « En cours »…)
ACCENT_SURVOL = "#6AB4D3"   # même bleu, un peu plus foncé, au survol
TEXTE_SUR_ACCENT = FOND     # texte foncé : le blanc est peu lisible sur ce bleu clair

COULEURS_ETAT = {
    BotState.ATTENTE: "#4b5563",
    BotState.EN_COURS: ACCENT,
    BotState.PAUSE: "#d97706",
    BotState.VERIFICATION: "#dc2626",
    BotState.ERREUR: "#b91c1c",
    BotState.TERMINE: "#2563eb",
    BotState.ARRETE: "#374151",
}
# Bandeau en haut à droite (aucun en mode normal).
BANDEAUX_MODE = {
    "simulation": ("SIMULATION · aucune connexion au site réel", "#b45309"),
    "observation": ("OBSERVATION · lecture seule, aucun clic", "#1d4ed8"),
}
# (texte, fond, survol) des boutons de commande
STYLE_BOUTONS = {
    "demarrer": ("▶  Démarrer", ACCENT, ACCENT_SURVOL),
    "pause": ("❚❚  Pause", "#d97706", "#b45309"),
    "reprendre": ("↻  Reprendre", "#2563eb", "#1d4ed8"),
    "confirmer": ("✔  Confirmer la reprise", "#7c3aed", "#6d28d9"),
    "arreter": ("■  ARRÊTER", "#dc2626", "#b91c1c"),
}


def tailles_icone() -> list[int]:
    """Tailles d'icône à fournir, de la plus grande à la plus petite : tailles usuelles (100 % à 200 %) plus
    les tailles exactes demandées par Windows à l'échelle d'affichage actuelle (barre de titre, barre des tâches)."""
    tailles = {16, 20, 24, 32, 40, 48, 64}
    try:
        import ctypes
        metrique = ctypes.windll.user32.GetSystemMetrics
        tailles |= {t for t in (metrique(49), metrique(11)) if 8 <= t <= 256}   # SM_CXSMICON, SM_CXICON
    except (AttributeError, OSError):
        pass
    return sorted(tailles, reverse=True)


def appliquer_icone(fenetre) -> None:
    """Icône de la barre de titre et de la barre des tâches (logo de PafOpener).

    Le .ico multi-tailles sert de secours (et empêche CustomTkinter de remettre son icône par défaut). Puis le
    logo d'origine est réduit en LANCZOS aux tailles exactes voulues par Windows : sans cela, Windows
    agrandit ou réduit lui-même l'icône la plus proche, ce qui la rend floue. Sans effet si les fichiers manquent.
    """
    try:
        if ICONE_PATH.exists():
            fenetre.iconbitmap(str(ICONE_PATH))
    except tk.TclError:
        pass
    try:
        from PIL import ImageTk

        from .logo import images_logo
        if not LOGO_PATH.exists():
            return
        photos = [ImageTk.PhotoImage(image, master=fenetre) for image in images_logo(LOGO_PATH, tailles_icone())]
        fenetre.iconphoto(False, *photos)
        fenetre._photos_icone = photos   # garder une référence : sinon Tk perd les images
    except (ImportError, OSError, tk.TclError):
        pass


def texte_segment_choisi(segments, valeur) -> None:
    """Texte foncé sur le segment choisi (fond bleu clair), texte clair sur les autres.

    CustomTkinter n'offre qu'une couleur de texte pour tous les segments : on la règle bouton par bouton.
    """
    for cle, bouton in getattr(segments, "_buttons_dict", {}).items():
        bouton.configure(text_color=TEXTE_SUR_ACCENT if cle == valeur else TEXTE)


def barre_titre_sombre(fenetre) -> None:
    """Barre de titre Windows en mode sombre (Windows 10 20H1+ / 11). Sans effet ailleurs."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(fenetre.winfo_id())
        valeur = ctypes.c_int(1)
        for attribut in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (et ancienne valeur)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribut, ctypes.byref(valeur),
                                                          ctypes.sizeof(valeur)) == 0:
                break
        # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED : redessine la barre
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
    except Exception:
        pass


def format_secondes(secondes: float) -> str:
    return f"{secondes:.1f} s".replace(".", ",")


def format_duree(secondes: float | None) -> str:
    if secondes is None:
        return "--:--"
    s = int(round(secondes))
    return f"{s // 60}:{s % 60:02d}"


class App:
    def __init__(self, root: tk.Misc, controller: Controller, log: ActivityLog,
                 simulation=None, clock=None, settings_path=DEFAULT_SETTINGS_PATH,
                 mode: str | None = None, a_la_fermeture=None):
        ctk.set_appearance_mode("dark")
        self.root = root
        self.controller = controller
        self.log = log
        self.simulation = simulation        # SimulatedPage ou None
        self.clock = clock                  # AcceleratedClock en simulation
        self.settings_path = settings_path
        self._after_id: str | None = None
        self._a_la_fermeture = a_la_fermeture
        self._derniers: dict[tuple[int, str], object] = {}   # anti-scintillement : valeurs déjà affichées
        mode = mode or ("simulation" if simulation is not None else "reel")

        titre = "PafOpener" + {"simulation": " — SIMULATION", "observation": " — OBSERVATION"}.get(mode, "")
        root.title(titre)
        appliquer_icone(root)
        hauteur = max(780, min(960, root.winfo_screenheight() - 130))  # au-dessus de la barre des tâches
        root.minsize(980, 780)
        root.geometry(f"1100x{hauteur}+40+10")
        root.protocol("WM_DELETE_WINDOW", self.fermer)
        root.after(50, lambda: barre_titre_sombre(root))
        if isinstance(root, (ctk.CTk, ctk.CTkToplevel)):
            root.configure(fg_color=FOND)
        else:
            root.configure(bg=FOND)

        self.f_titre = ctk.CTkFont(family=POLICE, size=22, weight="bold")
        self.f_etat = ctk.CTkFont(family=POLICE, size=17, weight="bold")
        self.f_valeur = ctk.CTkFont(family=POLICE, size=26, weight="bold")
        self.f_normal = ctk.CTkFont(family=POLICE, size=13)
        self.f_gras = ctk.CTkFont(family=POLICE, size=13, weight="bold")
        self.f_petit = ctk.CTkFont(family=POLICE, size=11)
        self.f_bouton = ctk.CTkFont(family=POLICE, size=14, weight="bold")
        self.f_journal = ctk.CTkFont(family=POLICE_MONO, size=12)

        principal = ctk.CTkFrame(root, fg_color=FOND, corner_radius=0)
        principal.pack(fill="both", expand=True, padx=18, pady=(10, 12))

        self._construire_entete(principal, mode)
        self._construire_etat(principal)
        self._construire_compteurs(principal)
        self._construire_seuil(principal)
        self._construire_boutons(principal)
        bas = ctk.CTkFrame(principal, fg_color="transparent")
        bas.pack(fill="x", pady=(0, 8))
        # Largeurs fixes (paramètres 4/9, simulation 5/9) : elles ne changent pas d'un onglet à l'autre.
        bas.columnconfigure(0, weight=4, uniform="bas")
        if simulation is not None:
            bas.columnconfigure(1, weight=5, uniform="bas")
        self._construire_parametres(bas)
        if simulation is not None:
            self._construire_simulation(bas)
        self._construire_journal(principal)
        self.rafraichir()

    # --- construction -------------------------------------------------------------------------------

    def _carte(self, parent, **pack) -> ctk.CTkFrame:
        cadre = ctk.CTkFrame(parent, fg_color=CARTE, corner_radius=14, border_width=1, border_color=BORD)
        cadre.pack(**({"fill": "x", "pady": (0, 8)} | pack))
        return cadre

    def _titre_carte(self, parent, texte: str):
        ctk.CTkLabel(parent, text=texte.upper(), font=self.f_petit, text_color=TEXTE_DOUX,
                     anchor="w").pack(fill="x", padx=16, pady=(8, 0))

    def _construire_entete(self, parent, mode: str):
        entete = ctk.CTkFrame(parent, fg_color="transparent")
        entete.pack(fill="x", pady=(0, 8))
        nom = ctk.CTkFrame(entete, fg_color="transparent")
        nom.pack(side="left")
        ctk.CTkLabel(nom, text="Paf", font=self.f_titre, text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(nom, text="Opener", font=self.f_titre, text_color=TEXTE).pack(side="left")
        if mode in BANDEAUX_MODE:
            texte, couleur = BANDEAUX_MODE[mode]
            ctk.CTkLabel(entete, text=texte, font=self.f_gras, fg_color=couleur, text_color="white",
                         corner_radius=12, height=30).pack(side="right", ipadx=12)

    def _construire_etat(self, parent):
        cadre = self._carte(parent)
        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=16, pady=(12, 4))
        self.lbl_etat = ctk.CTkLabel(ligne, text="", font=self.f_etat, text_color="white",
                                     fg_color=COULEURS_ETAT[BotState.ATTENTE], corner_radius=12,
                                     width=260, height=42)
        self.lbl_etat.pack(side="left")
        self.lbl_page = ctk.CTkLabel(ligne, text="", font=self.f_gras, corner_radius=12, height=34,
                                     fg_color=CARTE_CLAIRE, text_color=TEXTE)
        self.lbl_page.pack(side="left", padx=(12, 0), ipadx=12)
        self.lbl_raison = ctk.CTkLabel(cadre, text="", font=self.f_normal, text_color="#fbbf24",
                                       anchor="w", justify="left", wraplength=980)
        self.lbl_raison.pack(fill="x", padx=18, pady=(0, 10))
        # Bandeau affiché seulement quand une vérification attend une action humaine (case Cloudflare).
        self.lbl_action_humaine = ctk.CTkLabel(cadre, text="", font=self.f_etat, fg_color="#facc15",
                                               text_color="#450a0a", corner_radius=12, justify="center",
                                               height=64)
        self._action_humaine_affichee = False

    def _construire_compteurs(self, parent):
        rangee = ctk.CTkFrame(parent, fg_color="transparent")
        rangee.pack(fill="x", pady=(0, 4))
        self.compteurs = {}
        for col, (cle, titre) in enumerate([("ouverts", "Packs ouverts"), ("disponibles", "Disponibles"),
                                            ("restants", "Restants"), ("minuteur", "Prochain pack")]):
            rangee.columnconfigure(col, weight=1, uniform="stats")
            carte = ctk.CTkFrame(rangee, fg_color=CARTE, corner_radius=14, border_width=1, border_color=BORD)
            carte.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 5, 0 if col == 3 else 5))
            ctk.CTkLabel(carte, text=titre.upper(), font=self.f_petit, text_color=TEXTE_DOUX).pack(pady=(8, 0))
            valeur = ctk.CTkLabel(carte, text="-", font=self.f_valeur, text_color=TEXTE)
            valeur.pack(pady=(0, 2))
            self.compteurs[cle] = valeur
            if cle == "disponibles":
                self.barre_stock = ctk.CTkProgressBar(carte, height=8, corner_radius=4,
                                                      progress_color=ACCENT, fg_color=CARTE_CLAIRE)
                self.barre_stock.set(0)
                self.barre_stock.pack(fill="x", padx=18, pady=(2, 12))
            elif cle == "minuteur":
                self.lbl_source_minuteur = ctk.CTkLabel(carte, text="", font=self.f_petit, text_color=TEXTE_DOUX)
                self.lbl_source_minuteur.pack(pady=(0, 6))
            else:
                ctk.CTkLabel(carte, text="", height=8).pack(pady=(0, 6))
        self.lbl_details = ctk.CTkLabel(parent, text="", font=self.f_petit, text_color=TEXTE_DOUX, anchor="w")
        self.lbl_details.pack(fill="x", padx=4, pady=(0, 6))

    def _construire_seuil(self, parent):
        cadre = self._carte(parent)
        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=16, pady=(10, 2))
        self.lbl_phase = ctk.CTkLabel(ligne, text="", font=self.f_gras, corner_radius=10, height=28,
                                      fg_color="#312e81", text_color="#c7d2fe")
        self.lbl_phase.pack(side="left", ipadx=10)
        self.lbl_seuil = ctk.CTkLabel(ligne, text="", font=self.f_gras, text_color=TEXTE, anchor="w")
        self.lbl_seuil.pack(side="left", padx=(12, 0), fill="x", expand=True)
        self.barre_seuil = ctk.CTkProgressBar(cadre, height=10, corner_radius=5,
                                              progress_color="#818cf8", fg_color=CARTE_CLAIRE)
        self.barre_seuil.set(0)
        self.barre_seuil.pack(fill="x", padx=16, pady=(4, 12))

    def _construire_boutons(self, parent):
        cadre = ctk.CTkFrame(parent, fg_color="transparent")
        cadre.pack(fill="x", pady=(2, 10))
        commandes = {"demarrer": self.controller.start, "pause": self.controller.pause,
                     "reprendre": self.controller.resume, "confirmer": self.controller.confirm_resume,
                     "arreter": self.controller.stop}
        boutons = {}
        for cle, commande in commandes.items():
            texte, fond, survol = STYLE_BOUTONS[cle]
            boutons[cle] = ctk.CTkButton(cadre, text=texte, command=commande, font=self.f_bouton,
                                         fg_color=fond, hover_color=survol,
                                         text_color=TEXTE_SUR_ACCENT if fond == ACCENT else "white",
                                         text_color_disabled="#6b7280", corner_radius=12, height=42,
                                         width=150 if cle != "confirmer" else 210)
        self.btn_demarrer = boutons["demarrer"]
        self.btn_pause = boutons["pause"]
        self.btn_reprendre = boutons["reprendre"]
        self.btn_confirmer = boutons["confirmer"]
        self.btn_arreter = boutons["arreter"]
        self._fonds_boutons = {b: STYLE_BOUTONS[c][1] for c, b in boutons.items()}
        for b in (self.btn_demarrer, self.btn_pause, self.btn_reprendre, self.btn_confirmer):
            b.pack(side="left", padx=(0, 10))
        self.btn_arreter.pack(side="right")

    def _construire_parametres(self, parent):
        cadre = ctk.CTkFrame(parent, fg_color=CARTE, corner_radius=14, border_width=1, border_color=BORD)
        cadre.grid(row=0, column=0, sticky="nsew", padx=(0, 5 if self.simulation is not None else 0))
        self._titre_carte(cadre, "Paramètres")
        s = self.controller.settings
        self.var_capacite = tk.StringVar(value=str(s.capacite_packs))
        self.var_delai = tk.StringVar(value=str(s.delai_indicatif_s))
        self.var_objectif = tk.StringVar(value=str(s.objectif_ouvertures))
        self.var_seuil_min = tk.StringVar(value=str(s.seuil_min))
        self.var_seuil_max = tk.StringVar(value=str(s.seuil_max))
        onglets = ctk.CTkTabview(cadre, height=222, corner_radius=10, fg_color=CARTE_CLAIRE, border_width=0,
                                 segmented_button_selected_color=ACCENT,
                                 segmented_button_selected_hover_color=ACCENT_SURVOL,
                                 segmented_button_font=self.f_petit, anchor="w",
                                 command=lambda: texte_segment_choisi(onglets._segmented_button, onglets.get()))
        onglets.pack(fill="x", padx=12, pady=(0, 2))
        self.onglets_parametres = onglets
        grille = onglets.add("Cycle")
        champs = [("Packs à gérer (capacité)", self.var_capacite),
                  ("Délai pour un nouveau pack (s)", self.var_delai),
                  ("Objectif d'ouvertures (0 = illimité)", self.var_objectif),
                  ("Seuil aléatoire minimum", self.var_seuil_min),
                  ("Seuil aléatoire maximum", self.var_seuil_max)]
        for i, (titre, var) in enumerate(champs):
            ctk.CTkLabel(grille, text=titre, font=self.f_normal, text_color=TEXTE, anchor="w").grid(
                row=i, column=0, sticky="w", pady=2)
            ctk.CTkEntry(grille, textvariable=var, width=80, height=28, corner_radius=8, font=self.f_normal,
                         fg_color=CARTE_CLAIRE, border_color=BORD, text_color=TEXTE, justify="center").grid(
                row=i, column=1, sticky="e", padx=(12, 0), pady=2)
        grille.columnconfigure(0, weight=1)
        self._construire_onglet_clics(onglets.add("Clics"))
        self._construire_onglet_discord(onglets.add("Discord"))
        texte_segment_choisi(onglets._segmented_button, onglets.get())
        actions = ctk.CTkFrame(cadre, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkButton(actions, text="Appliquer", command=self.appliquer_parametres, font=self.f_gras,
                      fg_color=ACCENT, hover_color=ACCENT_SURVOL, text_color=TEXTE_SUR_ACCENT,
                      corner_radius=10, height=34,
                      width=120).pack(side="left")
        ctk.CTkButton(actions, text="Enregistrer", command=self.enregistrer_parametres, font=self.f_gras,
                      fg_color=CARTE_CLAIRE, hover_color=BORD, border_width=1, border_color=BORD,
                      corner_radius=10, height=34, width=120).pack(side="left", padx=(10, 0))

    def _construire_onglet_clics(self, onglet):
        """Temporisation aléatoire avant chaque clic : deux curseurs (minimum, maximum), pas de 0,1 s."""
        s = self.controller.settings
        self.var_clic_min = tk.DoubleVar(value=s.delai_clic_min_s)
        self.var_clic_max = tk.DoubleVar(value=s.delai_clic_max_s)
        ctk.CTkLabel(onglet, text="Attente tirée au hasard avant chaque clic (Ouvrir, ›, Continuer)",
                     font=self.f_petit, text_color=TEXTE_DOUX, anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.lbl_clic_valeurs = {}
        for i, (titre, var) in enumerate([("Minimum", self.var_clic_min), ("Maximum", self.var_clic_max)],
                                         start=1):
            ctk.CTkLabel(onglet, text=titre, font=self.f_normal, text_color=TEXTE, anchor="w").grid(
                row=i, column=0, sticky="w", pady=4)
            ctk.CTkSlider(onglet, from_=DELAI_CLIC_BORNES[0], to=DELAI_CLIC_BORNES[1],
                          number_of_steps=round((DELAI_CLIC_BORNES[1] - DELAI_CLIC_BORNES[0]) * 10),
                          variable=var, command=lambda _v, m=(titre == "Minimum"): self._curseur_clic(m),
                          progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_SURVOL).grid(
                row=i, column=1, sticky="ew", padx=10, pady=4)
            valeur = ctk.CTkLabel(onglet, text="", font=self.f_gras, text_color=TEXTE, width=60, anchor="e")
            valeur.grid(row=i, column=2, sticky="e", pady=4)
            self.lbl_clic_valeurs[titre] = valeur
        self.lbl_clic_resume = ctk.CTkLabel(onglet, text="", font=self.f_petit, text_color=TEXTE_DOUX, anchor="w")
        self.lbl_clic_resume.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        onglet.columnconfigure(1, weight=1)
        self._curseur_clic(True)

    def _curseur_clic(self, minimum_bouge: bool) -> None:
        """Garde minimum ≤ maximum (le curseur qu'on ne touche pas suit) et met à jour les libellés."""
        mini, maxi = round(self.var_clic_min.get(), 1), round(self.var_clic_max.get(), 1)
        if mini > maxi:
            if minimum_bouge:
                maxi = mini
            else:
                mini = maxi
        self.var_clic_min.set(mini)
        self.var_clic_max.set(maxi)
        self.lbl_clic_valeurs["Minimum"].configure(text=format_secondes(mini))
        self.lbl_clic_valeurs["Maximum"].configure(text=format_secondes(maxi))
        self.lbl_clic_resume.configure(text=f"Chaque clic attend entre {format_secondes(mini)} et "
                                            f"{format_secondes(maxi)} (la page est relue après l'attente).")

    def _construire_onglet_discord(self, onglet):
        s = self.controller.settings
        self.var_webhook = tk.StringVar(value=s.discord_webhook_url)
        self.var_bilan = tk.BooleanVar(value=s.discord_bilan_session)
        ctk.CTkLabel(onglet, text="Facultatif : laissez vide pour désactiver. Alertes envoyées : action humaine "
                                  "requise, pause de sécurité.", font=self.f_petit, text_color=TEXTE_DOUX,
                     anchor="w", justify="left", wraplength=400).grid(row=0, column=0, columnspan=2, sticky="w")
        ctk.CTkLabel(onglet, text="URL du webhook", font=self.f_normal, text_color=TEXTE, anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.champ_webhook = ctk.CTkEntry(onglet, textvariable=self.var_webhook, height=28, corner_radius=8,
                                          font=self.f_petit, fg_color=CARTE, border_color=BORD, text_color=TEXTE,
                                          show="•")
        self.champ_webhook.grid(row=2, column=0, sticky="ew")
        ctk.CTkButton(onglet, text="Tester", command=self.tester_webhook, font=self.f_gras, width=80, height=28,
                      fg_color=CARTE, hover_color=BORD, border_width=1, border_color=BORD,
                      corner_radius=8).grid(row=2, column=1, sticky="e", padx=(8, 0))
        ctk.CTkSwitch(onglet, text="Bilan de fin de session (arrêt ou objectif atteint)", variable=self.var_bilan,
                      onvalue=True, offvalue=False, font=self.f_normal, text_color=TEXTE,
                      progress_color=ACCENT).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        onglet.columnconfigure(0, weight=1)

    def _construire_simulation(self, parent):
        cadre = ctk.CTkFrame(parent, fg_color=CARTE, corner_radius=14, border_width=1, border_color=BORD)
        cadre.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self._titre_carte(cadre, "Simulation · incidents")
        sim = self.simulation
        actions = [
            ("Vérification (5 s)", lambda: sim.declencher_verification(5 * self._vitesse())),
            ("Vérification (30 s)", lambda: sim.declencher_verification(30 * self._vitesse())),
            ("Case Cloudflare (attend l'humain)", sim.declencher_case_cloudflare),
            ("Vous cochez la case", sim.cocher_case_humain),
            ("Perte de connexion", lambda: setattr(sim, "erreur_reseau", True)),
            ("Session expirée", lambda: setattr(sim, "session_expiree", True)),
            ("Interface modifiée", lambda: setattr(sim, "interface_modifiee", True)),
            ("Minuteur illisible", lambda: setattr(sim, "minuteur_illisible", True)),
            ("Fenêtre inconnue", lambda: setattr(sim, "fenetre_inconnue", True)),
            ("Échec prochaine ouverture", lambda: setattr(sim, "echec_prochaine_ouverture", True)),
            ("Erreur Playwright (lecture)",
             lambda: setattr(sim, "exception_prochaine_lecture", RuntimeError("Erreur Playwright simulée"))),
            ("Test double clic", self.controller.request_double_click_test),
            ("Ajouter un pack", sim.ajouter_pack),
            ("Ouverture manuelle", sim.ouverture_manuelle),
            ("Rétablir la page", sim.retablir),
        ]
        grille = ctk.CTkFrame(cadre, fg_color="transparent")
        grille.pack(fill="x", padx=12, pady=(2, 2))
        for i, (texte, cmd) in enumerate(actions):
            accent = texte == "Rétablir la page"
            ctk.CTkButton(grille, text=texte, command=self._incident(texte, cmd), font=self.f_petit,
                          fg_color=ACCENT if accent else CARTE_CLAIRE,
                          hover_color=ACCENT_SURVOL if accent else BORD,
                          text_color=TEXTE_SUR_ACCENT if accent else TEXTE, corner_radius=8, height=26,
                          width=60).grid(row=i // 3, column=i % 3, sticky="ew", padx=3, pady=2)
        for col in range(3):
            grille.columnconfigure(col, weight=1, uniform="sim")
        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkLabel(ligne, text="Vitesse du temps simulé", font=self.f_normal, text_color=TEXTE).pack(side="left")
        self.var_vitesse = tk.StringVar(value=f"{self.clock.vitesse:g}" if self.clock else "1")
        vitesses = ctk.CTkSegmentedButton(ligne, values=["1", "5", "10", "30", "60"], variable=self.var_vitesse,
                                          command=lambda v: (texte_segment_choisi(vitesses, v),
                                                             self._changer_vitesse()),
                                          font=self.f_petit, selected_color=ACCENT,
                                          selected_hover_color=ACCENT_SURVOL, corner_radius=8)
        vitesses.pack(side="left", padx=10)
        texte_segment_choisi(vitesses, self.var_vitesse.get())
        ctk.CTkLabel(ligne, text="× (1 = temps réel)", font=self.f_petit, text_color=TEXTE_DOUX).pack(side="left")

    def _construire_journal(self, parent):
        cadre = self._carte(parent, fill="both", expand=True, pady=(0, 0))
        self._titre_carte(cadre, "Journal d'activité")
        self.journal = ctk.CTkTextbox(cadre, font=self.f_journal, fg_color="#0b0f14", text_color="#c9d1d9",
                                      corner_radius=10, border_width=0, wrap="word", height=180)
        self.journal.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        self.journal.tag_config(ATTENTION, foreground="#fbbf24")
        self.journal.tag_config(ERREUR, foreground="#f87171")
        self.journal.configure(state="disabled")

    # --- actions ------------------------------------------------------------------------------------

    def _vitesse(self) -> float:
        return self.clock.vitesse if self.clock is not None else 1.0

    def _incident(self, texte, cmd):
        def run():
            self.log.info(f"[Simulation] {texte}")
            cmd()
        return run

    def _changer_vitesse(self):
        if self.clock is not None:
            self.clock.set_vitesse(float(self.var_vitesse.get()))
            self.log.info(f"[Simulation] Vitesse du temps : ×{self.var_vitesse.get()}")

    def _lire_parametres(self) -> Settings | None:
        try:
            nouveaux = self.controller.settings.with_changes(
                capacite_packs=int(self.var_capacite.get()),
                delai_indicatif_s=int(self.var_delai.get()),
                objectif_ouvertures=int(self.var_objectif.get()),
                seuil_min=int(self.var_seuil_min.get()),
                seuil_max=int(self.var_seuil_max.get()),
                delai_clic_min_s=round(float(self.var_clic_min.get()), 1),
                delai_clic_max_s=round(float(self.var_clic_max.get()), 1),
                discord_webhook_url=self.var_webhook.get().strip(),
                discord_bilan_session=bool(self.var_bilan.get()),
            )
        except (ValueError, tk.TclError):
            messagebox.showerror("Paramètres", "Veuillez saisir des nombres entiers.")
            return None
        erreurs = nouveaux.validate()
        if erreurs:
            messagebox.showerror("Paramètres", "\n".join(erreurs))
            return None
        return nouveaux

    def appliquer_parametres(self) -> bool:
        nouveaux = self._lire_parametres()
        if nouveaux is None:
            return False
        if self.simulation is not None:
            self.simulation.capacite = nouveaux.capacite_packs
            self.simulation.delai_s = nouveaux.delai_indicatif_s
        return not self.controller.apply_settings(nouveaux)

    def tester_webhook(self) -> bool:
        """Envoie un message de test à l'URL saisie (même si elle n'est pas encore appliquée)."""
        url = self.var_webhook.get().strip()
        erreurs = self.controller.settings.with_changes(discord_webhook_url=url).validate()
        if not url or erreurs:
            messagebox.showerror("Discord", "\n".join(erreurs) or "Saisissez d'abord l'URL du webhook Discord.")
            return False
        return self.controller.tester_notification(url)

    def enregistrer_parametres(self) -> None:
        if self.appliquer_parametres():
            self.controller.settings.save(self.settings_path)
            self.log.info(f"Paramètres enregistrés dans {self.settings_path.name}.")

    def fermer(self) -> None:
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.controller.stop()
        self.controller.join(timeout=3)
        self.controller.attendre_notifications(timeout=3)   # laisse partir le bilan de session, s'il y en a un
        if self._a_la_fermeture is not None:
            try:
                self._a_la_fermeture()
            except Exception:
                pass
        self.root.destroy()

    # --- rafraîchissement ---------------------------------------------------------------------------

    def rafraichir(self) -> None:
        self._afficher(self.controller.status())
        self._vider_journal()
        self._after_id = self.root.after(RAFRAICHISSEMENT_MS, self.rafraichir)

    def _maj(self, widget, **options) -> None:
        """Ne reconfigure un widget que si l'une de ses valeurs a changé (évite de redessiner pour rien)."""
        changes = {k: v for k, v in options.items() if self._derniers.get((id(widget), k)) != v}
        if changes:
            widget.configure(**changes)
            for k, v in changes.items():
                self._derniers[(id(widget), k)] = v

    def _barre(self, barre, valeur: float, couleur: str) -> None:
        valeur = max(0.0, min(1.0, valeur))
        if self._derniers.get((id(barre), "valeur")) != valeur:
            barre.set(valeur)
            self._derniers[(id(barre), "valeur")] = valeur
        self._maj(barre, progress_color=couleur)

    def _afficher(self, st: StatusView) -> None:
        self._maj(self.lbl_etat, text=st.etat.value, fg_color=COULEURS_ETAT[st.etat],
                  text_color=TEXTE_SUR_ACCENT if COULEURS_ETAT[st.etat] == ACCENT else "white")

        if st.page_statut is None:
            self._maj(self.lbl_page, text="Page : pas encore lue", fg_color=CARTE_CLAIRE, text_color=TEXTE_DOUX)
        elif st.page_statut is PageStatus.NORMAL:
            self._maj(self.lbl_page, text="●  Page : normale", fg_color=ACCENT, text_color=TEXTE_SUR_ACCENT)
        else:
            self._maj(self.lbl_page, text=f"⚠ Page {st.page_statut.value.lower()}", fg_color="#7f1d1d",
                      text_color="#fecaca")

        lignes = []
        if st.raison:
            lignes.append(f"Raison : {st.raison}")
        if st.page_incertaine and st.page_raison and st.page_raison != st.raison:
            lignes.append(f"Page : {st.page_raison}")
        if st.etat is BotState.VERIFICATION and not st.confirmation_requise:
            depuis = f" depuis {st.verification_depuis_s:.0f} s" if st.verification_depuis_s is not None else ""
            if st.verification_presente:
                lignes.append(f"Vérification affichée{depuis} : clics suspendus, attente passive. Reprise "
                              "automatique dès qu'elle aura disparu (pause manuelle si elle dure trop longtemps).")
            else:
                lignes.append(f"Vérification disparue : contrôle de la page avant reprise automatique "
                              f"({st.lectures_normales_reprise} lecture(s) normale(s)).")
        elif st.etat is BotState.VERIFICATION:
            lignes.append("Vérification toujours affichée : ne rien faire, attendre qu'elle disparaisse."
                          if st.verification_presente else
                          "Vérification disparue. Vérifiez la page puis cliquez « Confirmer la reprise ».")
        if st.confirmation_demandee:
            lignes.append("Confirmation en cours de traitement…")
        self._maj(self.lbl_raison, text="\n".join(lignes) or "Aucune anomalie.",
                  text_color="#fbbf24" if lignes else TEXTE_DOUX)
        self._afficher_action_humaine(st.action_humaine_requise)

        # compteurs
        self._maj(self.compteurs["ouverts"], text=str(st.ouverts))
        dispo = st.disponibles
        self._maj(self.compteurs["disponibles"], text=f"{dispo if dispo is not None else '?'} / {st.capacite}")
        ratio = (dispo or 0) / st.capacite if st.capacite else 0
        self._barre(self.barre_stock, ratio,
                    "#ef4444" if dispo is not None and dispo >= st.capacite - 1 else ACCENT)
        self._maj(self.compteurs["restants"], text="∞" if st.restants is None else str(st.restants))
        self._maj(self.compteurs["minuteur"], text=format_duree(st.temps_restant_s))
        self._maj(self.lbl_source_minuteur, text=f"({st.source_minuteur})")
        details = f"Échecs non comptés : {st.echecs}   ·   Clics envoyés : {st.clics_envoyes}"
        if st.clics_refuses:
            details += f"   ·   Clics refusés : {st.clics_refuses}"
        if st.action_en_attente:
            details += f"   ·   En attente du résultat : {st.action_en_attente}"
        self._maj(self.lbl_details, text=details)

        # seuil aléatoire
        if st.phase == VIDAGE:
            texte = (f"Seuil aléatoire actuel : {st.seuil_actuel} / {st.capacite} — "
                     "VIDAGE : ouverture des packs jusqu'à 0")
            self._maj(self.lbl_phase, text="VIDAGE", fg_color=ACCENT, text_color=TEXTE_SUR_ACCENT)
            self._barre(self.barre_seuil, 1.0, ACCENT)
        else:
            manquants = (st.seuil_actuel - dispo) if dispo is not None else None
            texte = f"Seuil aléatoire actuel : {st.seuil_actuel} / {st.capacite} — accumulation"
            if manquants is not None and manquants > 0:
                texte += f" (encore {manquants} pack(s), ~{format_duree(st.attente_seuil_s)})"
            self._maj(self.lbl_phase, text="ACCUMULATION", fg_color="#312e81", text_color="#c7d2fe")
            self._barre(self.barre_seuil, (dispo or 0) / st.seuil_actuel if st.seuil_actuel else 0, "#818cf8")
        self._maj(self.lbl_seuil, text=texte)

        # boutons
        inactif = st.etat in ETATS_INACTIFS
        self._activer(self.btn_demarrer, inactif)
        self._activer(self.btn_pause, st.etat is BotState.EN_COURS
                      or (st.etat is BotState.VERIFICATION and not st.confirmation_requise))
        self._activer(self.btn_reprendre, st.etat is BotState.PAUSE and not st.confirmation_requise)
        self._activer(self.btn_confirmer, st.confirmation_requise and not st.confirmation_demandee
                      and st.etat not in ETATS_INACTIFS)
        self._activer(self.btn_arreter, st.etat not in (BotState.ATTENTE, BotState.ARRETE))

    def _afficher_action_humaine(self, requise: bool) -> None:
        if requise == self._action_humaine_affichee:
            return
        self._action_humaine_affichee = requise
        if requise:
            self.lbl_action_humaine.configure(
                text="⚠ Action humaine requise : cochez la case dans Chrome\n"
                     "(le bot attend sans cliquer et reprendra seul dès que la vérification aura disparu)")
            self.lbl_action_humaine.pack(fill="x", padx=16, pady=(0, 14), after=self.lbl_raison)
            try:  # ramène la fenêtre du bot au premier plan pour que le message soit vu
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", True)
                self.root.after(1500, lambda: self.root.attributes("-topmost", False))
            except tk.TclError:
                pass
        else:
            self.lbl_action_humaine.pack_forget()

    def _activer(self, bouton, actif: bool) -> None:
        etat = "normal" if actif else "disabled"
        self._maj(bouton, state=etat, fg_color=self._fonds_boutons[bouton] if actif else CARTE_CLAIRE)

    def _vider_journal(self) -> None:
        entrees = self.log.drain()
        if not entrees:
            return
        self.journal.configure(state="normal")
        for e in entrees:
            self.journal.insert("end", e.format() + "\n", e.niveau)
        self.journal.see("end")
        self.journal.configure(state="disabled")
