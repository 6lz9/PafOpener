"""Point d'entrée de PafOpener.

    .venv\\Scripts\\python.exe main.py                 # Chrome dédié, clics Ouvrir / › / Continuer
    .venv\\Scripts\\python.exe main.py --observation   # lecture seule : aucun clic
    .venv\\Scripts\\python.exe main.py --simulation    # page simulée, aucune connexion au site
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from wikimaster.config import DEFAULT_SETTINGS_PATH, PROJECT_DIR, Settings


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="PafOpener")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--simulation", action="store_true",
                      help="utiliser une page simulée (aucune connexion au site)")
    mode.add_argument("--observation", action="store_true",
                      help="lecture seule : lit la vraie page mais n'envoie aucun clic")
    parser.add_argument("--port", type=int, default=9222, help="port de débogage du Chrome dédié (défaut : 9222)")
    parser.add_argument("--vitesse", type=float, default=None,
                        help="simulation : accélération du temps (défaut : valeur de settings.json)")
    parser.add_argument("--disponibles", type=int, default=1,
                        help="simulation : packs disponibles au démarrage (défaut : 1)")
    parser.add_argument("--alea", type=float, default=30.0,
                        help="simulation : variation aléatoire ± en secondes du délai entre packs (défaut : 30)")
    return parser.parse_args(argv)


def lancer_simulation(args, settings: Settings) -> int:
    import customtkinter as ctk

    from wikimaster.controller import Controller
    from wikimaster.logger import ActivityLog
    from wikimaster.notifications import NotificateurDiscord
    from wikimaster.simulation import URL_SIMULEE, AcceleratedClock, SimulatedPage
    from wikimaster.ui import App

    vitesse = args.vitesse if args.vitesse is not None else settings.vitesse_simulation
    clock = AcceleratedClock(vitesse)
    page = SimulatedPage(clock, capacite=settings.capacite_packs, delai_s=settings.delai_indicatif_s,
                         alea_s=args.alea, disponibles=args.disponibles)
    log = ActivityLog(PROJECT_DIR / "logs" / f"simulation_{datetime.now():%Y%m%d}.log")
    # En simulation, les délais du contrôleur sont exprimés en temps simulé : on garde
    # des intervalles de lecture courts en temps réel.
    controller = Controller(page, settings.with_changes(
        intervalle_lecture_s=max(0.1, settings.intervalle_lecture_s / vitesse * 2)),
        log, clock=clock, prefixe_url=URL_SIMULEE, alerte=bip_alerte,
        notificateur=NotificateurDiscord(log, mode="Simulation (page simulée)"))
    log.info(f"Mode simulation — temps ×{vitesse:g}, délai {settings.delai_indicatif_s} s ± {args.alea:g} s, "
             f"{args.disponibles} pack(s) au départ.")
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    App(root, controller, log, simulation=page, clock=clock, mode="simulation")
    root.mainloop()
    return 0


def signaler_erreur(message: str) -> None:
    """Console si elle existe ; sinon (lancement par Lancer_Bot.bat, sans console) boîte de dialogue."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox
        racine = tk.Tk()
        racine.withdraw()
        messagebox.showerror("PafOpener", message)
        racine.destroy()
    except Exception:
        pass


def bip_alerte() -> None:
    """Petit signal sonore : « exclamation » Windows, ou son système « Glass » sur Mac. Sans effet ailleurs."""
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except ImportError:
        if sys.platform == "darwin":
            import subprocess
            try:
                subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass


def lancer_reel(args, settings: Settings) -> int:
    import customtkinter as ctk

    from wikimaster.browser import (PROFIL_DIR, URL_PULLS, FournisseurCDP, RealPage, assurer_onglet_pulls,
                                    lancer_chrome)
    from wikimaster.controller import Controller
    from wikimaster.logger import ActivityLog
    from wikimaster.notifications import NotificateurDiscord
    from wikimaster.ui import App

    mode = "observation" if args.observation else "reel"
    log = ActivityLog(PROJECT_DIR / "logs" / f"{mode}_{datetime.now():%Y%m%d}.log")
    try:
        info = lancer_chrome(args.port)
        onglet = assurer_onglet_pulls(args.port)
    except Exception as exc:
        signaler_erreur(f"Impossible de lancer ou de joindre le Chrome dédié : {exc}")
        return 3
    log.info(f"Chrome dédié joignable ({info.get('Browser', '?')}), profil : {PROFIL_DIR}")
    log.info(onglet)
    if settings.discord_webhook_url:
        log.info("Notifications Discord activées.")
    log.info(f"Ouvrez {URL_PULLS} dans CETTE fenêtre Chrome (connexion manuelle si besoin), puis « Démarrer ».")
    if mode == "observation":
        log.info("MODE OBSERVATION : la page est lue, les clics prévus sont seulement journalisés.")
    else:
        log.info("Seuls « Ouvrir », la flèche › et « Continuer » peuvent être cliqués.")

    driver = RealPage(fournisseur=lambda: FournisseurCDP(args.port))

    def relever_verification():
        base = driver.capturer("verification")
        log.info(f"Vérification relevée (lecture seule) : inspection\{base.name}.html / .json / .png")

    controller = Controller(driver, settings, log, prefixe_url=URL_PULLS, observation=args.observation,
                            alerte=bip_alerte, sur_verification=relever_verification,
                            notificateur=NotificateurDiscord(
                                log, mode="Mode observation" if args.observation else ""))
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    App(root, controller, log, mode=mode, a_la_fermeture=driver.fermer)
    root.mainloop()
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        settings = Settings.load(DEFAULT_SETTINGS_PATH)
    except ValueError as exc:
        signaler_erreur(f"Erreur dans {DEFAULT_SETTINGS_PATH.name} : {exc}")
        return 2
    if args.simulation:
        return lancer_simulation(args, settings)
    return lancer_reel(args, settings)


if __name__ == "__main__":
    sys.exit(main())
