"""Fabrique tests/fixtures/*.html à partir des écrans relevés dans inspection/ (à relancer si le site change).

    .venv\\Scripts\\python.exe tests\\fabriquer_fixtures.py

Seule la zone <main> est conservée (ni pseudo, ni solde, ni barre latérale), sans images externes.
Les pages marquées SYNTHÉTIQUE sont construites à la main (états jamais capturés ou pièges).
"""
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE = Path(__file__).resolve().parent / "fixtures"

ENREGISTREUR = """<script>
window.__clics = [];
document.addEventListener('click', (e) => {
  const b = e.target.closest('button');
  const tous = [...document.querySelectorAll('main button')];
  window.__clics.push(b ? {index: tous.indexOf(b), texte: (b.innerText || '').trim(),
                          aria: b.getAttribute('aria-label')} : {index: -1, tag: e.target.tagName});
}, true);
</script>"""


def extraire_main(html: str) -> str:
    m = html[html.index("<main"):html.index("</main>") + len("</main>")]
    m = re.sub(r"<img[^>]*>", '<img alt="">', m)
    return m


def page(main: str, origine: str, extra: str = "") -> str:
    return (f"<!doctype html>\n<!-- {origine} -->\n<html lang=\"fr\"><head><meta charset=\"utf-8\">"
            "<title>WikiMasters</title><style>.flex,.inline-flex{display:flex}.flex-col{flex-direction:column}.items-center{align-items:center}</style></head>\n<body style=\"margin:0\"><div style=\"display:flex\">"
            f"{main}</div>{extra}\n{ENREGISTREUR}</body></html>\n")


def main() -> int:
    ecrans = sorted((RACINE / "inspection").glob("ecran_*.html"))
    if len(ecrans) < 9:
        print("Il faut les 9 écrans de l'enregistrement du 14/10/2026 dans inspection/.")
        return 1
    SORTIE.mkdir(exist_ok=True)
    reels = {"paquets_6.html": 0, "paquets_pret.html": 1, "paquets_ouverture.html": 2,
             "carte_1.html": 3, "carte_4.html": 6, "carte_5.html": 7}
    mains = {}
    for nom, i in reels.items():
        mains[nom] = extraire_main(ecrans[i].read_text(encoding="utf-8"))
        (SORTIE / nom).write_text(page(mains[nom], f"RÉEL : relevé {ecrans[i].stem}"), encoding="utf-8")

    base = mains["paquets_6.html"]
    # Stock à 0 : « Ouvrir » désactivé + bouton d'achat (capture « attente d'un pack.png »).
    zero = base.replace('<span class="text-[var(--color-accent)]">6</span>',
                        '<span class="text-[var(--color-accent)]">0</span>')
    zero = zero.replace('<button class="\n          relative', '<button disabled="" class="\n          relative', 1)
    zero = zero.replace('<div class="w-full max-w-sm',
                        '<button class="px-6 py-3 rounded-xl">Rechargez 10 paquets — 1,99 $ CAD</button>'
                        '<div class="w-full max-w-sm', 1)
    (SORTIE / "synth_paquets_0_achat.html").write_text(
        page(zero, "SYNTHÉTIQUE : stock à 0 avec bouton d'achat"), encoding="utf-8")

    # Fenêtre « Vérification rapide » par-dessus la page (capture verification.png).
    modale = ('<div style="position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.6);'
              'backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center">'
              '<div style="background:#111;color:#fff;padding:24px;border-radius:12px;width:380px">'
              '<h2>Vérification rapide</h2><p>On vérifie que tu es bien humain. Ça ne prend qu\'une seconde.</p>'
              '<p>Vérification...</p><button>Annuler</button></div></div>')
    (SORTIE / "synth_verification.html").write_text(
        page(base, "SYNTHÉTIQUE : fenêtre Vérification rapide (d'après la capture)", modale), encoding="utf-8")

    # Piège : un bouton « Ouvrir » dans le bloc « Pack PRO du jour ».
    pro = base.replace('<p class="text-xs font-medium text-violet-200/90">Pack PRO du jour</p>',
                       '<p class="text-xs font-medium text-violet-200/90">Pack PRO du jour</p>'
                       '<button class="pro">Ouvrir</button>', 1)
    (SORTIE / "synth_pack_pro_ouvrir.html").write_text(
        page(pro, "SYNTHÉTIQUE : piège, bouton Ouvrir dans le bloc Pack PRO"), encoding="utf-8")

    # Piège : deux boutons « Ouvrir » ambigus.
    deux = base.replace(">Comment ça marche ?</button>", ">Ouvrir</button>", 1)
    (SORTIE / "synth_deux_ouvrir.html").write_text(
        page(deux, "SYNTHÉTIQUE : piège, deux boutons Ouvrir"), encoding="utf-8")
    print(f"{len(list(SORTIE.glob('*.html')))} fixtures écrites dans {SORTIE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
