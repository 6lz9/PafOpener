"""browser.py : vérifications sans réseau ni navigateur."""
import re
import sys
from pathlib import Path

from wikimaster import browser

SOURCE = Path(browser.__file__).read_text(encoding="utf-8")


def test_aucune_action_interdite_dans_le_code():
    interdits = [r"\.dblclick\(", r"\.fill\(", r"\.type\(", r"\.press\(", r"\.tap\(", r"\.check\(",
                 r"dispatch_event", r"\.cookies\(", r"storage_state", r"localStorage", r"sessionStorage",
                 r"document\.cookie", r"\.close\(\)", r"\.goto\(", r"\.reload\(", r"force\s*=",
                 r"\.mouse\.", r"\.keyboard\.", r"\.click\(\)\s*;", r"el\.click\(", r"(?<!_executeur)\.submit\("]
    trouves = [motif for motif in interdits if re.search(motif, SOURCE)]
    assert trouves == [], f"appels interdits dans browser.py : {trouves}"


def test_un_seul_clic_dans_tout_le_module_et_apres_la_liste_blanche():
    clics = [m.start() for m in re.finditer(r"\.click\(", SOURCE)]
    assert len(clics) == 1, "un seul point d'envoi de clic est autorisé"
    avant = SOURCE[:clics[0]]
    fonction = avant[avant.rindex("def "):]
    assert fonction.startswith("def _cliquer(")
    assert "cible_autorisee(action" in fonction and "raise CibleInterdite" in fonction
    assert fonction.index("cible_autorisee(action") < len(fonction)


def test_profil_dedie_dans_le_projet():
    assert browser.PROFIL_DIR.name == "chrome_profile"
    assert browser.PROFIL_DIR.parent == Path(browser.__file__).resolve().parent.parent
    assert "--user-data-dir=" in SOURCE


def test_port_de_debogage_local_uniquement():
    assert "http://127.0.0.1:" in SOURCE
    assert "0.0.0.0" not in SOURCE and "remote-debugging-address" not in SOURCE


def test_aucun_chrome_sur_un_port_libre():
    assert browser.version_debogage(port=1) is None
    assert browser.onglets(port=1) == []


def test_chrome_installe():
    attendu = "Google Chrome" if sys.platform == "darwin" else "chrome.exe"
    assert browser.trouver_chrome().name == attendu


def test_chemins_chrome_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    chemins = browser.chemins_chrome()
    assert Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") in chemins
    assert all(c.name == "Google Chrome" for c in chemins)


def test_chemins_chrome_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert all(c.name == "chrome.exe" for c in browser.chemins_chrome())


def test_onglet_pulls_ouvert_seulement_si_absent(monkeypatch):
    requetes = []

    class Reponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(browser.urllib.request, "urlopen",
                        lambda req, timeout=0: requetes.append((req.get_method(), req.full_url)) or Reponse())
    monkeypatch.setattr(browser, "onglets", lambda port=0: [{"url": "https://www.wiki-masters.com/pulls"}])
    assert "déjà ouvert" in browser.assurer_onglet_pulls()
    monkeypatch.setattr(browser, "onglets", lambda port=0: [{"url": "https://www.wiki-masters.com/collection"}])
    assert "pas sur /pulls" in browser.assurer_onglet_pulls()
    assert requetes == []                                   # jamais de navigation imposée
    monkeypatch.setattr(browser, "onglets", lambda port=0: [{"url": "chrome://newtab/"}])
    assert "Nouvel onglet" in browser.assurer_onglet_pulls()
    assert requetes == [("PUT", "http://127.0.0.1:9222/json/new?https://www.wiki-masters.com/pulls")]
