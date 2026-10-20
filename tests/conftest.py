import random

import pytest

from wikimaster.config import Settings
from wikimaster.controller import Controller
from wikimaster.logger import ActivityLog
from wikimaster.simulation import URL_SIMULEE, ManualClock, SimulatedPage

# Par défaut, les tests de sécurité utilisent un seuil fixe de 1 (ouvrir dès qu'un pack est là)
# pour aller droit au but ; le seuil aléatoire est testé explicitement dans test_cycle.py.
REGLAGES_TEST = {"seuil_min": 1, "seuil_max": 1}


class Banc:
    """Banc d'essai : contrôleur + page simulée + horloge manuelle, sans thread."""

    def __init__(self, reglages: dict | None = None, graine: int = 0, observation: bool = False,
                 **page_kwargs):
        self.clock = ManualClock()
        self.attentes: list[float] = []   # temporisations demandées avant les clics (instantanées ici)
        page_kwargs.setdefault("disponibles", 1)
        self.page = SimulatedPage(self.clock, **page_kwargs)
        self.log = ActivityLog()
        settings = Settings(**{**REGLAGES_TEST, **(reglages or {})})
        self.ctrl = Controller(self.page, settings, self.log, clock=self.clock, use_thread=False,
                               prefixe_url=URL_SIMULEE, rng=random.Random(graine),
                               attente=self.attentes.append, observation=observation)

    def run(self, ticks: int, dt: float = 1.0) -> None:
        for _ in range(ticks):
            self.ctrl.tick()
            self.clock.advance(dt)

    def run_until(self, condition, max_ticks: int = 2000, dt: float = 1.0) -> bool:
        for _ in range(max_ticks):
            if condition():
                return True
            self.ctrl.tick()
            self.clock.advance(dt)
        return condition()

    @property
    def status(self):
        return self.ctrl.status()

    def clics(self) -> int:
        return self.page.clics_total

    def journal(self) -> str:
        return "\n".join(self.log.messages())


@pytest.fixture
def banc():
    return Banc()


@pytest.fixture
def make_banc():
    return Banc
