"""Connexion à Chrome avec un profil dédié (`chrome_profile/`), sans jamais toucher à vos identifiants.

Deux usages :
  - inspection en lecture seule (commandes ci-dessous) pour relever les éléments HTML de la page ;
  - `RealPage`, le pilote de la vraie page, qui ne sait cliquer que sur « Ouvrir », la flèche › et
    « Continuer », après un contrôle de liste blanche (`cible_autorisee`).
Aucune saisie, aucune navigation, aucune lecture de cookies ni de jetons.

    .venv\\Scripts\\python.exe -m wikimaster.browser ouvrir      # lance Chrome (profil dédié) sur /pulls
    .venv\\Scripts\\python.exe -m wikimaster.browser etat        # Chrome est-il joignable ? quel onglet ?
    .venv\\Scripts\\python.exe -m wikimaster.browser inspecter   # lit la page et écrit le résultat dans inspection\\

Fonctionnement : Chrome est lancé normalement, avec un dossier de profil séparé et le port de débogage
9222 ouvert sur 127.0.0.1 (uniquement accessible depuis ce PC). Vous vous connectez à la main dans
cette fenêtre. Les scripts d'inspection s'y rattachent avec Playwright (`connect_over_cdp`) et ne font
que lire. Depuis Chrome 136, ce mode est refusé sur le profil Chrome habituel : c'est pour cela qu'un
profil dédié est utilisé (protection de Chrome respectée, pas contournée).

Tant que cette fenêtre Chrome est ouverte, un programme local pourrait piloter CE profil via le port 9222.
Fermez-la quand vous ne l'utilisez pas.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import PROJECT_DIR
from .page_model import PageSnapshot, View

URL_PULLS = "https://www.wiki-masters.com/pulls"
DOMAINE = "wiki-masters.com"
PROFIL_DIR = PROJECT_DIR / "chrome_profile"
INSPECTION_DIR = PROJECT_DIR / "inspection"
PORT = 9222

CHROME_MAC = "Google Chrome.app/Contents/MacOS/Google Chrome"


def chemins_chrome() -> list[Path]:
    """Emplacements habituels de Chrome sur le système en cours (Windows ou Mac)."""
    if sys.platform == "darwin":
        return [Path("/Applications") / CHROME_MAC, Path.home() / "Applications" / CHROME_MAC]
    return [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]


class ChromeIntrouvable(RuntimeError):
    pass


def trouver_chrome() -> Path:
    for chemin in chemins_chrome():
        if chemin.is_file():
            return chemin
    raise ChromeIntrouvable("Google Chrome introuvable dans les emplacements habituels.")


def version_debogage(port: int = PORT) -> dict | None:
    """Infos du Chrome joignable sur le port de débogage local, ou None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as rep:
            return json.loads(rep.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def onglets(port: int = PORT) -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as rep:
            return [o for o in json.loads(rep.read().decode("utf-8")) if o.get("type") == "page"]
    except (urllib.error.URLError, OSError, ValueError):
        return []


def lancer_chrome(port: int = PORT, url: str = URL_PULLS, attente_s: float = 20.0) -> dict:
    """Lance Chrome avec le profil dédié. Ne fait rien si un Chrome de débogage tourne déjà sur ce port."""
    deja = version_debogage(port)
    if deja is not None:
        return deja
    PROFIL_DIR.mkdir(exist_ok=True)
    args = [
        str(trouver_chrome()),
        f"--user-data-dir={PROFIL_DIR}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]
    drapeaux = 0
    if sys.platform == "win32":
        drapeaux = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, creationflags=drapeaux, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fin = time.monotonic() + attente_s
    while time.monotonic() < fin:
        info = version_debogage(port)
        if info is not None:
            return info
        time.sleep(0.5)
    raise RuntimeError(f"Chrome ne répond pas sur le port {port} après {attente_s:g} s.")


def assurer_onglet_pulls(port: int = PORT) -> str:
    """Ouvre un onglet /pulls dans le Chrome dédié s'il n'y a aucun onglet Wiki Masters.

    N'ouvre qu'une page (comme taper l'adresse) : aucun clic. Retourne un message pour le journal.
    """
    pages = onglets(port)
    if any((o.get("url") or "").startswith(URL_PULLS) for o in pages):
        return "Onglet /pulls déjà ouvert."
    if any(DOMAINE in (o.get("url") or "") for o in pages):
        return f"Un onglet Wiki Masters est ouvert mais pas sur /pulls : allez sur {URL_PULLS}."
    requete = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{URL_PULLS}", method="PUT")
    with urllib.request.urlopen(requete, timeout=5):
        pass
    return f"Nouvel onglet ouvert sur {URL_PULLS}."


@contextmanager
def connexion(port: int = PORT):
    """Se rattache au Chrome dédié. À la sortie, se déconnecte SANS fermer Chrome ni ses onglets."""
    from playwright.sync_api import sync_playwright

    if version_debogage(port) is None:
        raise RuntimeError("Aucun Chrome dédié joignable. Lancez d'abord : "
                           ".venv\\Scripts\\python.exe -m wikimaster.browser ouvrir")
    pw = sync_playwright().start()
    try:
        navigateur = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        yield navigateur
    finally:
        pw.stop()  # déconnexion uniquement : la fermeture du navigateur n'est volontairement jamais demandée


def onglet_wiki_masters(navigateur):
    for contexte in navigateur.contexts:
        for page in contexte.pages:
            if DOMAINE in (page.url or ""):
                return page
    return None


# Script exécuté dans la page : LECTURE SEULE (aucun clic, aucune modification du DOM,
# aucune lecture de cookies ni du stockage local du site).
JS_INSPECTION = r"""
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
           && parseFloat(s.opacity || '1') > 0;
  };
  const chemin = (el) => {
    const parts = [];
    while (el && el.nodeType === 1 && parts.length < 8) {
      let p = el.tagName.toLowerCase();
      if (el.id) { p += '#' + el.id; parts.unshift(p); break; }
      const cls = [...el.classList].slice(0, 3).join('.');
      if (cls) p += '.' + cls;
      const parent = el.parentElement;
      if (parent) {
        const memes = [...parent.children].filter(c => c.tagName === el.tagName);
        if (memes.length > 1) p += `:nth-of-type(${memes.indexOf(el) + 1})`;
      }
      parts.unshift(p);
      el = el.parentElement;
    }
    return parts.join(' > ');
  };
  const decrire = (el) => {
    const r = el.getBoundingClientRect();
    const attrs = {};
    for (const a of el.attributes) {
      if (a.name === 'style' || a.name.startsWith('on')) continue;
      attrs[a.name] = a.value.slice(0, 200);
    }
    return {
      tag: el.tagName.toLowerCase(),
      texte: (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 200),
      attributs: attrs,
      desactive: !!(el.disabled || el.getAttribute('aria-disabled') === 'true'),
      visible: visible(el),
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      css: chemin(el),
      html: el.outerHTML.slice(0, 600),
    };
  };
  const cles = ['paquets disponibles', 'Prochain dans', 'Ouvrir', 'Rechargez', 'Carte', 'Encore',
                'Continuer', 'Vérification', 'humain', 'Annuler', 'Pack PRO'];
  const parTexte = {};
  for (const cle of cles) {
    const trouves = [];
    for (const el of document.querySelectorAll('body *')) {
      const propre = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ');
      if (propre.includes(cle)) trouves.push(decrire(el));
      if (trouves.length >= 6) break;
    }
    parTexte[cle] = trouves;
  }
  const boutons = [...document.querySelectorAll('button, a[href], [role=button], input[type=button], input[type=submit]')]
    .filter(visible).slice(0, 80).map(decrire);
  const fenetres = [...document.querySelectorAll('[role=dialog], [role=alertdialog], [aria-modal=true], dialog[open]')]
    .map(decrire);
  const superpositions = [...document.querySelectorAll('body *')].filter(el => {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' || !visible(el)) return false;
    const r = el.getBoundingClientRect();
    return r.width * r.height > 0.25 * innerWidth * innerHeight;
  }).slice(0, 10).map(decrire);
  const iframes = [...document.querySelectorAll('iframe')].map(f => ({src: (f.src || '').slice(0, 200), ...decrire(f)}));
  return {
    url: location.href, titre: document.title, etat: document.readyState,
    fenetre: [innerWidth, innerHeight],
    texte_visible: (document.body.innerText || '').slice(0, 4000),
    par_texte: parTexte, boutons, fenetres, superpositions, iframes,
  };
}
"""


def inspecter(port: int = PORT, capture: bool = True) -> Path:
    """Lit l'onglet Wiki Masters (sans aucun clic) et enregistre JSON + HTML + capture dans inspection/."""
    INSPECTION_DIR.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    with connexion(port) as navigateur:
        page = onglet_wiki_masters(navigateur)
        if page is None:
            raise RuntimeError(f"Aucun onglet {DOMAINE} ouvert dans le Chrome dédié.")
        donnees = page.evaluate(JS_INSPECTION)
        base = INSPECTION_DIR / f"pulls_{horodatage}"
        base.with_suffix(".json").write_text(json.dumps(donnees, indent=2, ensure_ascii=False), encoding="utf-8")
        base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
        if capture:
            page.screenshot(path=str(base.with_suffix(".png")))
    return base.with_suffix(".json")


# Signature de l'écran (lecture seule) : texte visible de <main> + fenêtres éventuelles, minuteur masqué.
JS_SIGNATURE = r"""
() => {
  const main = document.querySelector('main');
  const texte = ((main && main.innerText) || '').replace(/\d+:\d\d/g, '#:##');
  const fenetres = [...document.querySelectorAll('[role=dialog], [role=alertdialog], [aria-modal=true], dialog[open]')]
    .map(e => (e.innerText || '').trim()).join(' | ');
  const boutons = [...document.querySelectorAll('main button')]
    .map(b => (b.disabled ? '[x]' : '') + (b.innerText || b.getAttribute('aria-label') || '').trim()).join(' | ');
  return texte + ' ## ' + fenetres + ' ## ' + boutons;
}
"""


def enregistrer(duree_s: float = 600, port: int = PORT, max_captures: int = 80) -> list[Path]:
    """Relit la page toutes les 0,5 s (sans aucun clic) et enregistre chaque nouvel écran dans inspection/."""
    INSPECTION_DIR.mkdir(exist_ok=True)
    captures: list[Path] = []
    with connexion(port) as navigateur:
        page = onglet_wiki_masters(navigateur)
        if page is None:
            raise RuntimeError(f"Aucun onglet {DOMAINE} ouvert dans le Chrome dédié.")
        print(f"Enregistrement en lecture seule pendant {duree_s:g} s (Ctrl+C pour arrêter)…", flush=True)
        precedente = None
        fin = time.monotonic() + duree_s
        while time.monotonic() < fin and len(captures) < max_captures:
            try:
                signature = page.evaluate(JS_SIGNATURE)
            except Exception as exc:  # navigation en cours, onglet fermé…
                print(f"  lecture impossible : {exc}", flush=True)
                time.sleep(1)
                page = onglet_wiki_masters(navigateur) or page
                continue
            if signature != precedente:
                precedente = signature
                base = INSPECTION_DIR / f"ecran_{datetime.now():%Y%m%d_%H%M%S_%f}"[:-3]
                try:
                    donnees = page.evaluate(JS_INSPECTION)
                    base.with_suffix(".json").write_text(json.dumps(donnees, indent=2, ensure_ascii=False),
                                                         encoding="utf-8")
                    base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
                    page.screenshot(path=str(base.with_suffix(".png")))
                except Exception as exc:
                    print(f"  capture incomplète : {exc}", flush=True)
                captures.append(base)
                resume = " ".join(signature.split())[:140]
                print(f"[{datetime.now():%H:%M:%S}] nouvel écran n°{len(captures)} : {resume}", flush=True)
            time.sleep(0.5)
    return captures


# ==================================================================================================
# Vraie page : lecture de la page et clics strictement limités à « Ouvrir », flèche › et « Continuer »
# ==================================================================================================
#
# Éléments relevés sur la vraie page (inspection du 14/10/2026, aucun id ni data-testid sur le site) :
#   Page des paquets
#     - <main> > … > <button> contenant l'image du pack et <span>Ouvrir</span>
#       (texte « Ouverture... » + attribut disabled pendant l'ouverture)
#     - .card-frame : <span>6</span><span> / 10</span>, puis « paquets disponibles »,
#       puis « Prochain dans <span class="font-mono">2:03</span> » (ou « Prêt ! » à l'arrivée d'un pack)
#     - à NE JAMAIS cliquer : « Comment ça marche ? », bloc « Pack PRO du jour », bouton d'achat « Rechargez… »
#   Révélation
#     - « <span>Carte</span><span>1</span><span>/ 5</span> »
#     - rangée : [bouton ‹ (disabled sur la carte 1)] [div de 5 boutons-points] [bouton › (disabled sur 5/5)]
#     - juste après la rangée : <button disabled>Encore 4 cartes</button> (… « Encore 1 carte »),
#       remplacé par <button>Continuer</button> une fois toutes les cartes révélées
#     - à NE JAMAIS cliquer : ‹, les points, l'étoile « Ajouter aux favoris (verrouille la carte…) »

# Fonctions de repérage partagées par la lecture et les clics (exécutées dans la page, lecture seule).
JS_REPERAGE = r"""
const norm = (t) => (t || '').replace(/\s+/g, ' ').trim();
const visible = (el) => {
  if (!el) return false;
  const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
};
const racine = () => document.querySelector('main');
const texteDirect = (el) => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ');
const parTexteDirect = (base, test) => base ? [...base.querySelectorAll('*')].filter(el => test(norm(texteDirect(el)))) : [];
const blocPackPro = () => { const p = parTexteDirect(racine(), t => /^Pack PRO/i.test(t))[0]; return p ? p.parentElement : null; };
const horsPackPro = (el) => { const b = blocPackPro(); return !(b && b.contains(el)); };
const boutons = () => racine() ? [...racine().querySelectorAll('button')].filter(visible) : [];
const unique = (liste) => liste.length === 1 ? liste[0] : null;
const btnOuvrir = () => unique(boutons().filter(b => norm(b.innerText) === 'Ouvrir' && horsPackPro(b)));
const btnOuverture = () => boutons().find(b => /^Ouverture/.test(norm(b.innerText))) || null;
const btnEncore = () => unique(boutons().filter(b => /^Encore \d+ cartes?$/.test(norm(b.innerText))));
const btnContinuer = () => unique(boutons().filter(b => norm(b.innerText) === 'Continuer' && horsPackPro(b)));
const btnAchat = () => boutons().find(b => /rechargez|\$|\bCAD\b|€/i.test(norm(b.innerText))) || null;
const rangeeNavigation = () => {
  const bas = btnEncore() || btnContinuer();
  const rangee = bas && bas.previousElementSibling;
  if (!rangee) return null;
  const enfants = [...rangee.children];
  if (enfants.length !== 3) return null;
  const [g, points, d] = enfants;
  if (g.tagName !== 'BUTTON' || d.tagName !== 'BUTTON' || points.tagName !== 'DIV') return null;
  if (norm(g.innerText) || norm(d.innerText) || g.getAttribute('aria-label') || d.getAttribute('aria-label')) return null;
  const p = [...points.children];
  if (!p.length || !p.every(x => x.tagName === 'BUTTON' && !norm(x.innerText))) return null;
  if (d.getBoundingClientRect().left <= g.getBoundingClientRect().left) return null;
  return {gauche: g, points: p, droite: d};
};
const flecheDroite = () => { const r = rangeeNavigation(); return r ? r.droite : null; };
const texteCarte = () => { const s = parTexteDirect(racine(), t => t === 'Carte')[0]; return s ? norm(s.parentElement.innerText) : null; };
const texteCompteur = () => {
  const l = parTexteDirect(racine(), t => /^paquets? disponibles?$/i.test(t))[0];
  if (!l) return null;
  const m = norm(l.parentElement.innerText).match(/(\d+)\s*\/\s*(\d+)/);
  return m ? m[0] : null;
};
const texteMinuteur = () => {
  const l = parTexteDirect(racine(), t => t.startsWith('Prochain dans'))[0];
  return l ? norm(l.innerText).replace(/^Prochain dans/, '').trim() : null;
};
const texteModale = () => {
  const vus = new Set();
  document.querySelectorAll('[role=dialog],[role=alertdialog],[aria-modal=true],dialog[open]')
    .forEach(e => { if (visible(e)) vus.add(e); });
  for (const el of document.body.querySelectorAll('*')) {
    if (getComputedStyle(el).position !== 'fixed' || !visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height > 0.25 * innerWidth * innerHeight) vus.add(el);
  }
  for (const el of parTexteDirect(document.body, t => /v[ée]rification rapide|bien humain/i.test(t)))
    if (visible(el)) vus.add(el);
  if (!vus.size) return null;
  return [...vus].map(e => norm(e.innerText)).filter(Boolean).join(' | ');
};
const cible = (action) => action === 'ouvrir' ? btnOuvrir()
  : action === 'suivant' ? flecheDroite()
  : action === 'continuer' ? btnContinuer() : null;
const decrire = (el) => {
  const bloc = blocPackPro();
  return {
    tag: el.tagName.toLowerCase(),
    texte: norm(el.innerText),
    aria: norm(el.getAttribute('aria-label')),
    titre: norm(el.getAttribute('title')),
    desactive: !!(el.disabled || el.getAttribute('aria-disabled') === 'true'),
    dans_main: !!(racine() && racine().contains(el)),
    dans_pack_pro: !!(bloc && bloc.contains(el)),
    est_fleche_droite: el === flecheDroite(),
    visible: visible(el),
  };
};
"""

JS_LECTURE = "() => {" + JS_REPERAGE + r"""
  const ouvrir = btnOuvrir(), fleche = flecheDroite(), continuer = btnContinuer();
  return {
    url: location.href,
    en_ligne: navigator.onLine,
    modale: texteModale(),
    carte: texteCarte(),
    compteur: texteCompteur(),
    minuteur: texteMinuteur(),
    ouvrir_present: !!ouvrir,
    ouvrir_desactive: !!(ouvrir && ouvrir.disabled),
    ouverture: !!btnOuverture(),
    achat: !!btnAchat(),
    fleche_present: !!fleche,
    fleche_desactive: !!(fleche && fleche.disabled),
    encore: btnEncore() ? norm(btnEncore().innerText) : null,
    continuer_present: !!(continuer && !continuer.disabled),
  };
}"""

JS_CIBLE = "(action) => {" + JS_REPERAGE + " return cible(action); }"
JS_DECRIRE = "(el) => {" + JS_REPERAGE + " return decrire(el); }"

# Liste blanche : texte exact attendu pour chaque action. Tout le reste est refusé.
TEXTE_AUTORISE = {"ouvrir": "Ouvrir", "continuer": "Continuer", "suivant": ""}
MOTS_INTERDITS = re.compile(
    r"recharg|achat|achet|paiement|payer|\$|\bcad\b|€|prix|pack pro|réclam|reclam|comment ça marche|"
    r"favori|verrouill|défauss|defauss|vente|vendre|échange|echange|annuler|supprimer|abonnement|premium",
    re.IGNORECASE)


class CibleInterdite(RuntimeError):
    """Le programme a refusé de cliquer : l'élément trouvé n'est pas exactement celui attendu."""


def cible_autorisee(action: str, d: dict) -> tuple[bool, str]:
    """Dernier contrôle avant TOUT clic réel. Retourne (autorisé ?, raison du refus)."""
    if action not in TEXTE_AUTORISE:
        return False, f"action inconnue « {action} »"
    if d.get("tag") != "button":
        return False, f"élément <{d.get('tag')}> au lieu d'un bouton"
    if not d.get("dans_main"):
        return False, "bouton hors de la zone principale de la page"
    if d.get("dans_pack_pro"):
        return False, "bouton situé dans le bloc « Pack PRO du jour »"
    if d.get("desactive"):
        return False, "bouton désactivé"
    if not d.get("visible"):
        return False, "bouton invisible"
    libelles = " ".join(filter(None, (d.get("texte"), d.get("aria"), d.get("titre"))))
    if MOTS_INTERDITS.search(libelles):
        return False, f"libellé interdit : « {libelles[:80]} »"
    if d.get("texte", "") != TEXTE_AUTORISE[action]:
        return False, f"texte « {d.get('texte', '')[:40]} » au lieu de « {TEXTE_AUTORISE[action]} »"
    if action == "suivant":
        if d.get("aria") or d.get("titre"):
            return False, "la flèche › attendue n'a ni aria-label ni title"
        if not d.get("est_fleche_droite"):
            return False, "ce bouton n'est pas la flèche droite de la rangée de navigation"
    return True, ""


def _secondes(minuteur: str | None) -> int | None:
    if minuteur is None:
        return None
    m = re.fullmatch(r"(\d+):(\d{2})", minuteur.strip())
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    if re.fullmatch(r"pr[êe]t\s*!?", minuteur.strip(), re.IGNORECASE):
        return 0
    return None


def snapshot_depuis_donnees(d: dict, pris_a: float) -> PageSnapshot:
    """Convertit le résultat brut de JS_LECTURE en PageSnapshot (fonction pure, testée)."""
    url = d.get("url")
    if not d.get("en_ligne", True):
        return PageSnapshot(pris_a, url, View.INCONNUE, erreur="Perte de connexion : le navigateur est hors ligne")
    if url and urllib.parse.urlparse(url).path.rstrip("/") in ("/login", "/connexion", "/signin"):
        return PageSnapshot(pris_a, url, View.INCONNUE, session_expiree=True)
    modale = d.get("modale")
    carte = re.fullmatch(r"Carte\s*(\d+)\s*/\s*(\d+)", d.get("carte") or "")
    if carte:
        encore = re.fullmatch(r"Encore (\d+) cartes?", d.get("encore") or "")
        return PageSnapshot(
            pris_a, url, View.REVELATION,
            carte_index=int(carte.group(1)), carte_total=int(carte.group(2)),
            fleche_suivante_active=bool(d.get("fleche_present")) and not d.get("fleche_desactive"),
            encore_n=int(encore.group(1)) if encore else None,
            bouton_continuer_present=bool(d.get("continuer_present")),
            modale_texte=modale)
    compteur = re.fullmatch(r"(\d+)\s*/\s*(\d+)", d.get("compteur") or "")
    if compteur and (d.get("ouvrir_present") or d.get("ouverture")):
        return PageSnapshot(
            pris_a, url, View.PAQUETS,
            disponibles=int(compteur.group(1)), capacite=int(compteur.group(2)),
            prochain_dans_s=_secondes(d.get("minuteur")),
            bouton_ouvrir_present=bool(d.get("ouvrir_present")),
            bouton_ouvrir_actif=bool(d.get("ouvrir_present")) and not d.get("ouvrir_desactive"),
            bouton_achat_visible=bool(d.get("achat")),
            ouverture_en_cours=bool(d.get("ouverture")),
            modale_texte=modale)
    return PageSnapshot(pris_a, url, View.INCONNUE, modale_texte=modale)


class FournisseurCDP:
    """Onglet /pulls du Chrome dédié, via le port de débogage local. Utilisé dans UN seul thread."""

    def __init__(self, port: int = PORT):
        self.port = port
        self._pw = None
        self._navigateur = None

    def page(self):
        if self._navigateur is None or not self._navigateur.is_connected():
            self.fermer()
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._navigateur = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        pages = [p for ctx in self._navigateur.contexts for p in ctx.pages]
        pulls = [p for p in pages if (p.url or "").startswith(URL_PULLS)]
        if len(pulls) > 1:
            raise RuntimeError("Plusieurs onglets /pulls sont ouverts : gardez-en un seul.")
        if pulls:
            return pulls[0]
        autres = [p for p in pages if DOMAINE in (p.url or "")]
        return autres[0] if len(autres) == 1 else None

    def fermer(self) -> None:
        if self._pw is not None:
            try:
                self._pw.stop()   # déconnexion uniquement : Chrome et ses onglets restent ouverts
            except Exception:
                pass
        self._pw = None
        self._navigateur = None


class RealPage:
    """Implémente `PageDriver` sur la vraie page. Playwright tourne dans un thread qui lui est réservé.

    Ne sait faire que trois clics, chacun vérifié par `cible_autorisee` juste avant l'envoi :
    « Ouvrir », la flèche › et « Continuer ». Jamais de clic forcé : Playwright vérifie
    que le bouton est visible, stable, actif et qu'aucune fenêtre ne le recouvre, sinon il échoue.
    """

    def __init__(self, clock=time.monotonic, fournisseur=None, timeout_clic_ms: int = 3000,
                 timeout_operation_s: float = 20.0):
        self._clock = clock
        self._fournisseur_usine = fournisseur or (lambda: FournisseurCDP())
        self._fournisseur = None
        self._timeout_clic_ms = timeout_clic_ms
        self._timeout_operation_s = timeout_operation_s
        self._executeur = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")

    def _executer(self, fn):
        return self._executeur.submit(fn).result(timeout=self._timeout_operation_s)

    def _page(self):
        if self._fournisseur is None:
            self._fournisseur = self._fournisseur_usine()
        return self._fournisseur.page()

    # --- PageDriver --------------------------------------------------------------------------------

    def read_snapshot(self) -> PageSnapshot:
        return self._executer(self._lire)

    def _lire(self) -> PageSnapshot:
        pris_a = self._clock()
        page = self._page()
        if page is None:
            return PageSnapshot(pris_a, None, View.INCONNUE,
                                erreur=f"Aucun onglet {URL_PULLS} ouvert dans le Chrome dédié")
        if (page.url or "").startswith("chrome-error://"):
            return PageSnapshot(pris_a, page.url, View.INCONNUE, erreur="Page inaccessible (erreur de chargement)")
        return snapshot_depuis_donnees(page.evaluate(JS_LECTURE), pris_a)

    def click_open(self) -> None:
        self._executer(lambda: self._cliquer("ouvrir"))

    def click_next_card(self) -> None:
        self._executer(lambda: self._cliquer("suivant"))

    def click_continue(self) -> None:
        self._executer(lambda: self._cliquer("continuer"))

    def _cliquer(self, action: str) -> None:
        page = self._page()
        if page is None:
            raise RuntimeError("onglet /pulls introuvable")
        element = page.evaluate_handle(JS_CIBLE, action).as_element()
        if element is None:
            raise CibleInterdite(f"élément « {action} » introuvable ou ambigu : aucun clic envoyé")
        ok, raison = cible_autorisee(action, element.evaluate(JS_DECRIRE))
        if not ok:
            raise CibleInterdite(f"clic « {action} » refusé : {raison}")
        element.click(timeout=self._timeout_clic_ms)

    def capturer(self, prefixe: str = "verification") -> Path:
        """Relevé en lecture seule de la page actuelle (JSON, HTML, capture) dans inspection/.

        Le contenu de l'iframe Cloudflare n'est pas lu : seuls ses attributs (src, taille) le sont.
        """
        def _capturer() -> Path:
            page = self._page()
            if page is None:
                raise RuntimeError("onglet /pulls introuvable")
            INSPECTION_DIR.mkdir(exist_ok=True)
            base = INSPECTION_DIR / f"{prefixe}_{datetime.now():%Y%m%d_%H%M%S}"
            base.with_suffix(".json").write_text(
                json.dumps(page.evaluate(JS_INSPECTION), indent=2, ensure_ascii=False), encoding="utf-8")
            base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(base.with_suffix(".png")))
            return base
        return self._executer(_capturer)

    def fermer(self) -> None:
        def _fermer():
            if self._fournisseur is not None:
                self._fournisseur.fermer()
        try:
            self._executer(_fermer)
        finally:
            self._executeur.shutdown(wait=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Chrome dédié pour PafOpener (lecture seule)")
    parser.add_argument("commande", choices=["ouvrir", "etat", "inspecter", "enregistrer"])
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--duree", type=float, default=600, help="durée de l'enregistrement en secondes")
    args = parser.parse_args(argv)

    if args.commande == "ouvrir":
        info = lancer_chrome(args.port)
        print(f"Chrome dédié prêt ({info.get('Browser', '?')}), profil : {PROFIL_DIR}")
        print("Connectez-vous manuellement à Wiki Masters dans cette fenêtre, puis allez sur /pulls.")
        return 0
    if args.commande == "etat":
        info = version_debogage(args.port)
        if info is None:
            print("Aucun Chrome dédié joignable.")
            return 1
        print(f"Chrome dédié joignable : {info.get('Browser', '?')}")
        for o in onglets(args.port):
            print(f"  - {o.get('title', '')[:60]!r} {o.get('url', '')}")
        return 0
    if args.commande == "enregistrer":
        captures = enregistrer(args.duree, args.port)
        print(f"{len(captures)} écran(s) enregistré(s) dans {INSPECTION_DIR}")
        return 0
    chemin = inspecter(args.port)
    print(f"Inspection enregistrée : {chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
