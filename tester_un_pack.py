"""Test réel minimal : ouvre UN SEUL pack sur wiki-masters.com avec toutes les sécurités du bot, puis s'arrête.

    .venv\\Scripts\\python.exe tester_un_pack.py

Prérequis : le Chrome dédié est ouvert sur https://www.wiki-masters.com/pulls (un seul onglet /pulls),
au moins un pack est disponible, et l'interface du bot est arrêtée. Ne touchez pas à la page pendant le test.
Le journal complet est écrit dans logs\\test_un_pack_AAAAMMJJ.log.
"""
import sys
import time
from datetime import datetime

from wikimaster.browser import URL_PULLS, RealPage
from wikimaster.config import PROJECT_DIR, Settings
from wikimaster.controller import BotState, Controller
from wikimaster.logger import ActivityLog

DUREE_MAX_S = 120


def main() -> int:
    log = ActivityLog(PROJECT_DIR / "logs" / f"test_un_pack_{datetime.now():%Y%m%d}.log")
    pilote = RealPage()
    # Objectif 1 ouverture, seuil fixe 1 : ouvre dès qu'un pack est disponible, puis « Terminé ».
    ctrl = Controller(pilote, Settings(objectif_ouvertures=1, seuil_min=1, seuil_max=1), log,
                      use_thread=False, prefixe_url=URL_PULLS)
    debut = time.monotonic()
    affiches = 0
    try:
        ctrl.start()
        while time.monotonic() - debut < DUREE_MAX_S:
            ctrl.tick()
            for e in log.entries[affiches:]:
                print(e.format(), flush=True)
            affiches = len(log.entries)
            if ctrl.state is not BotState.EN_COURS:
                break
            time.sleep(1)
        st = ctrl.status()
    finally:
        ctrl.stop()
        pilote.fermer()
    for e in log.entries[affiches:]:
        print(e.format())
    print(f"\nRÉSULTAT : {st.etat.value} — ouverts : {st.ouverts}, clics envoyés : {st.clics_envoyes}, "
          f"durée : {time.monotonic() - debut:.0f} s" + (f"\nRaison : {st.raison}" if st.raison else ""))
    return 0 if st.etat is BotState.TERMINE and st.ouverts == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
