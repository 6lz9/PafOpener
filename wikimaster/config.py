"""Paramètres de l'application, stockés dans settings.json (modifiable à la main ou via l'interface)."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path


def dossier_application() -> Path:
    """Dossier des données (settings.json, logs/, chrome_profile/, inspection/).

    Exécutable PyInstaller : le dossier qui contient le .exe (le code, lui, est décompressé dans un dossier
    temporaire effacé à la fermeture). Application Mac (PafOpener.app) : ~/Library/Application Support/PafOpener,
    car l'intérieur du .app peut être en lecture seule (et serait effacé en remplaçant l'app). Sinon : la racine
    du projet.
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            dossier = Path.home() / "Library" / "Application Support" / "PafOpener"
            dossier.mkdir(parents=True, exist_ok=True)
            return dossier
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def chemin_ressource(relatif: str) -> Path:
    """Fichier fourni avec le programme (icône…) : dans l'exécutable PyInstaller, il est décompressé dans
    `sys._MEIPASS` ; sinon il est à la racine du projet."""
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if getattr(sys, "frozen", False) and base else Path(__file__).resolve().parent.parent) / relatif


PROJECT_DIR = dossier_application()
DEFAULT_SETTINGS_PATH = PROJECT_DIR / "settings.json"
ICONE_PATH = chemin_ressource("assets/logo.ico")   # icône multi-tailles (secours, et icône du .exe)
LOGO_PATH = chemin_ressource("assets/logo.png")    # logo d'origine (fond transparent), pleine résolution


@dataclass(frozen=True)
class Settings:
    # Plafond de packs stockables, tel qu'affiché par le site (« 1 / 10 »).
    capacite_packs: int = 10
    # Délai pour un nouveau pack (temps entre deux nouveaux packs). Sert uniquement à l'affichage
    # quand le minuteur du site est illisible : jamais pour décider d'un clic.
    delai_indicatif_s: int = 180
    # Nombre d'ouvertures avant arrêt automatique. 0 = pas de limite.
    objectif_ouvertures: int = 0
    # Seuil aléatoire : à chaque cycle, un seuil est tiré au sort entre ces deux bornes (incluses).
    # Le programme attend que le stock l'atteigne, puis ouvre jusqu'à 0, puis tire un nouveau seuil.
    # seuil_max doit rester sous la capacité pour ne jamais atteindre le plafond.
    seuil_min: int = 5
    seuil_max: int = 8
    # Fréquence de lecture de la page.
    intervalle_lecture_s: float = 1.0
    # Temps maximum pour constater le résultat d'un clic avant de passer en état incertain.
    delai_resultat_s: float = 10.0
    # Délai minimum entre deux clics, quels qu'ils soient.
    intervalle_min_clics_s: float = 2.0
    # Temporisation avant chaque clic (« Ouvrir », flèche, « Continuer ») : durée tirée au hasard dans cet
    # intervalle, pour ne pas enchaîner les clics instantanément. La page est relue APRÈS cette attente.
    delai_clic_min_s: float = 0.8
    delai_clic_max_s: float = 1.8
    # Nombre de lectures normales et identiques consécutives exigées avant un clic.
    lectures_stables_requises: int = 2
    # Nombre de lectures incertaines consécutives avant la pause automatique.
    # 1 = pause dès la première lecture incertaine (le plus prudent).
    # Aucun clic n'est jamais fait pendant une lecture incertaine, quelle que soit cette valeur.
    lectures_incertaines_tolerees: int = 1
    # Fenêtre « Vérification rapide » : attente passive, puis reprise automatique quand elle a disparu
    # d'elle-même et que la page est NORMALE sur `lectures_normales_reprise` lectures consécutives.
    # Si elle reste affichée plus de `verification_delai_max_s` secondes : pause avec confirmation manuelle.
    # false = confirmation manuelle après chaque vérification.
    reprise_auto_verification: bool = True
    lectures_normales_reprise: int = 3
    # Si la vérification est toujours affichée après ce délai (case à cocher Cloudflare qui attend un humain) :
    # bip Windows + « Action humaine requise » dans l'interface. Le bot continue d'attendre sans cliquer.
    alerte_verification_s: float = 10.0
    # Filet de sécurité si personne ne coche la case : au-delà, pause avec confirmation manuelle.
    verification_delai_max_s: float = 600.0
    # Accélération du temps en mode simulation (10 = 180 s simulées en 18 s réelles).
    vitesse_simulation: float = 10.0
    # Notifications Discord (facultatives) : URL du webhook, vide = aucune notification.
    # Envoyées quand une action humaine est requise et à chaque pause de sécurité.
    discord_webhook_url: str = ""
    # Envoie aussi un bilan (packs ouverts, durée, pauses) à l'arrêt ou quand l'objectif est atteint.
    discord_bilan_session: bool = False

    def validate(self) -> list[str]:
        """Retourne la liste des erreurs (vide si les paramètres sont valides)."""
        errors: list[str] = []
        if not 1 <= self.capacite_packs <= 100:
            errors.append("La capacité doit être comprise entre 1 et 100 packs.")
        if not 1 <= self.delai_indicatif_s <= 86400:
            errors.append("Le délai pour un nouveau pack doit être compris entre 1 et 86400 secondes.")
        if self.objectif_ouvertures < 0:
            errors.append("L'objectif d'ouvertures ne peut pas être négatif (0 = illimité).")
        if not 1 <= self.seuil_min <= self.seuil_max:
            errors.append("Le seuil minimum doit être au moins 1 et ne pas dépasser le seuil maximum.")
        if self.seuil_max >= self.capacite_packs:
            errors.append(f"Le seuil maximum doit être inférieur à la capacité ({self.capacite_packs}) "
                          "pour ne jamais atteindre le plafond.")
        if not 0.1 <= self.intervalle_lecture_s <= 60:
            errors.append("L'intervalle de lecture doit être compris entre 0,1 et 60 secondes.")
        if self.delai_resultat_s < 1:
            errors.append("Le délai de vérification du résultat doit être d'au moins 1 seconde.")
        if self.intervalle_min_clics_s < 0.5:
            errors.append("L'intervalle minimum entre deux clics doit être d'au moins 0,5 seconde.")
        if not 0 <= self.delai_clic_min_s <= self.delai_clic_max_s <= 10:
            errors.append("La temporisation avant clic doit vérifier 0 ≤ minimum ≤ maximum ≤ 10 secondes.")
        if self.lectures_stables_requises < 1:
            errors.append("Il faut au moins 1 lecture stable avant un clic.")
        if self.lectures_incertaines_tolerees < 1:
            errors.append("Le nombre de lectures incertaines tolérées doit être d'au moins 1.")
        if self.lectures_normales_reprise < 2:
            errors.append("Il faut au moins 2 lectures normales consécutives avant une reprise automatique.")
        if not 1 <= self.alerte_verification_s < self.verification_delai_max_s:
            errors.append("Le délai avant l'alerte « action humaine requise » doit être d'au moins 1 s et "
                          "inférieur à la durée maximale de vérification.")
        if not 5 <= self.verification_delai_max_s <= 3600:
            errors.append("La durée maximale d'une vérification doit être comprise entre 5 et 3600 secondes.")
        if not 1 <= self.vitesse_simulation <= 1000:
            errors.append("La vitesse de simulation doit être comprise entre 1 et 1000.")
        url = self.discord_webhook_url
        if url and (not url.startswith("https://") or len(url) > 500 or any(c.isspace() for c in url)):
            errors.append("L'URL du webhook Discord doit commencer par https:// et ne contenir aucun espace "
                          "(laisser vide pour désactiver les notifications).")
        return errors

    def with_changes(self, **changes) -> "Settings":
        return replace(self, **changes)

    @classmethod
    def load(cls, path: Path = DEFAULT_SETTINGS_PATH) -> "Settings":
        """Charge les paramètres. Fichier absent = valeurs par défaut. Fichier invalide = ValueError."""
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} n'est pas un JSON valide : {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{path.name} doit contenir un objet JSON.")
        known = {f.name: f for f in fields(cls)}
        values = {}
        for key, value in raw.items():
            if key not in known:
                continue  # clé inconnue : ignorée
            type_champ = known[key].type
            if type_champ in ("bool", bool):
                if not isinstance(value, bool):
                    raise ValueError(f"Paramètre « {key} » : true ou false attendu, reçu {value!r}.")
                values[key] = value
                continue
            if type_champ in ("str", str):
                if not isinstance(value, str):
                    raise ValueError(f"Paramètre « {key} » : texte attendu, reçu {value!r}.")
                values[key] = value.strip()
                continue
            expected = int if type_champ in ("int", int) else float
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Paramètre « {key} » : nombre attendu, reçu {value!r}.")
            if expected is int and value != int(value):
                raise ValueError(f"Paramètre « {key} » : nombre entier attendu, reçu {value!r}.")
            values[key] = expected(value)
        settings = cls(**values)
        errors = settings.validate()
        if errors:
            raise ValueError(" ".join(errors))
        return settings

    def save(self, path: Path = DEFAULT_SETTINGS_PATH) -> None:
        errors = self.validate()
        if errors:
            raise ValueError(" ".join(errors))
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
