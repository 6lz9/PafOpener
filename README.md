# PafOpener

Application Windows (CustomTkinter, thème sombre) qui suit les packs gratuits de [Wiki Masters](https://www.wiki-masters.com/pulls),
les ouvre à un rythme aléatoire sans jamais laisser le stock atteindre le plafond de 10, et se met en pause
au moindre doute (vérification automatique, page inattendue, erreur).

## Rythme d'ouverture aléatoire

1. Le programme tire au sort un **seuil** entre `seuil_min` et `seuil_max` (par défaut entre 5 et 8).
2. **Accumulation** : il attend sans rien ouvrir tant que le site affiche moins de packs que ce seuil.
3. **Vidage** : quand le seuil est atteint, il ouvre les packs un par un jusqu'à ce que le site affiche 0.
   Les packs qui arrivent pendant le vidage sont ouverts aussi.
4. Il tire ensuite un nouveau seuil, par exemple 5, 6, 7 ou 8, et recommence.

Le seuil en cours et la phase (accumulation ou vidage) sont affichés dans la fenêtre. `seuil_max` doit rester
inférieur à la capacité (10) : le plafond n'est jamais atteint tant que le programme tourne. Pendant une pause,
le stock continue de monter, et le journal prévient quand il approche de 10.

## Fenêtre « Vérification rapide »

Quand la fenêtre « Vérification rapide — On vérifie que tu es bien humain » apparaît :

1. Tous les clics sont suspendus immédiatement. Le programme n'interagit jamais avec la fenêtre : il ne clique
   pas sur « Annuler » et n'essaie ni de la résoudre, ni de la contourner, ni de la masquer.
2. Il attend passivement qu'elle disparaisse d'elle-même.
3. Il reprend **automatiquement** quand la page est redevenue NORMALE sur 3 lectures consécutives
   (`lectures_normales_reprise`). Si la fenêtre réapparaît entre-temps, le décompte repart de zéro.
4. **Case à cocher Cloudflare (« Vérifiez que vous êtes humain »)** : si la fenêtre est encore là après 10 s
   (`alerte_verification_s`), le bot émet un bip Windows, ramène sa fenêtre au premier plan et affiche
   **« ⚠ Action humaine requise : cochez la case dans Chrome »** (et envoie une alerte Discord si un webhook est
   configuré, voir [Notifications Discord](#notifications-discord-facultatives)). **Le bot ne clique jamais sur cette case** :
   c'est à vous de la cocher. Il continue d'attendre et reprend tout seul dès que la vérification a disparu.
   À chaque apparition, la page est aussi relevée en lecture seule dans `inspection\verification_*`
   (HTML, JSON et capture ; le contenu de l'iframe Cloudflare n'est pas lu).
5. Une **confirmation manuelle** reste obligatoire dans ces cas :
   - la fenêtre reste affichée plus de 10 minutes (`verification_delai_max_s`, par exemple si personne ne
     coche la case) ;
   - la page est incertaine ou en erreur après sa disparition ;
   - un clic envoyé juste avant la vérification n'a pas de résultat visible.

Le bouton **Pause** reste utilisable pendant l'attente. Pour revenir à une confirmation manuelle après chaque
vérification, mettez `"reprise_auto_verification": false` dans `settings.json`.

## Ce que le programme peut cliquer (et rien d'autre)

Le pilote réel (`wikimaster/browser.py`, classe `RealPage`) ne sait envoyer que trois clics :

| Action | Élément exigé |
|---|---|
| Ouvrir | bouton de `<main>` dont le texte est exactement « Ouvrir », actif, hors du bloc « Pack PRO du jour » |
| Carte suivante | bouton **droit** de la rangée ‹ ●●●●● ›, sans texte, actif |
| Continuer | bouton de `<main>` dont le texte est exactement « Continuer », actif |

Avant chaque clic, l'élément est relu et passé dans une liste blanche (`cible_autorisee`) qui refuse tout libellé
contenant par exemple « Rechargez », « $ », « CAD », « Pack PRO », « Comment ça marche », « favoris » ou
« Annuler ». Elle refuse aussi tout bouton désactivé, invisible, hors de `<main>`, ou ambigu (deux candidats).
Le clic n'est jamais forcé : si une fenêtre recouvre le bouton, Playwright refuse de cliquer et le programme se
met en pause.

**Jamais cliqués :** « Pack PRO du jour », « Comment ça marche ? », « Rechargez 10 paquets — 1,99 $ CAD »,
la flèche ‹, les points de navigation, l'étoile « Ajouter aux favoris » et « Annuler » dans la vérification.

Avant chaque clic, le programme attend une durée tirée au hasard entre un minimum et un maximum (0,8 et 1,8 s par
défaut), pour ne pas enchaîner les clics instantanément, puis **relit la page**. Ces deux bornes se règlent avec
les curseurs de l'onglet **Paramètres → Clics** (de 0 à 10 s, par pas de 0,1 s) ou dans `settings.json`
(`delai_clic_min_s` / `delai_clic_max_s`). Quel que soit ce réglage, deux clics restent espacés d'au moins
`intervalle_min_clics_s` (2 s). Cette attente
n'est pas un moyen de se cacher : le programme ne masque pas l'automatisation et ne contourne aucune
vérification.

## Ouverture d'un pack (d'après le site)

« Ouvrir » → « Carte 1 / 5 ». Le bouton « Encore 4 cartes » est inactif : le programme clique sur la flèche
de droite (›) pour révéler chaque carte (« Encore 3 », « 2 », « 1 »). Une fois toutes les cartes révélées, le bouton
**Continuer** apparaît, et le programme clique dessus pour revenir à la page des paquets. Chaque clic est vérifié
avant le suivant.

## Lancer le bot en un double-clic

Double-cliquez sur **`Lancer_Bot.bat`** (à la racine du projet). Il :

1. ouvre le Chrome dédié sur https://www.wiki-masters.com/pulls s'il n'est pas déjà ouvert, ou ajoute un
   onglet `/pulls` s'il n'y a aucun onglet Wiki Masters ;
2. ouvre l'interface du bot, sans fenêtre de console.

Cliquez ensuite sur **Démarrer** : avant ce clic, le bot ne clique sur rien. Par défaut, il tourne **sans fin**,
cycle après cycle (objectif `0` = illimité, affiché « ∞ »). Le « 10 » affiché est la capacité du stock sur le
site, pas un nombre maximal d'ouvertures. Pour s'arrêter après N ouvertures, saisissez N dans « Objectif
d'ouvertures ».

**Raccourci sur le Bureau** : clic droit sur `Lancer_Bot.bat` → *Afficher d'autres options* → *Envoyer vers* →
*Bureau (créer un raccourci)*. Pour un raccourci en mode observation, ouvrez les propriétés du raccourci et
ajoutez ` --observation` à la fin du champ *Cible*.

## Lancer le bot depuis le code source

```powershell
cd C:\Users\Lee\Desktop\Bot\WikiMasterPackOpener
.\.venv\Scripts\python.exe main.py --observation   # 1er essai conseillé : lit la page, AUCUN clic
.\.venv\Scripts\python.exe main.py                 # clique sur Ouvrir, › et Continuer
```

1. Le programme ouvre (ou retrouve) la fenêtre **Chrome dédiée** (profil `chrome_profile\`).
2. Dans cette fenêtre, connectez-vous si nécessaire et allez sur https://www.wiki-masters.com/pulls
   (un seul onglet `/pulls`). Le programme ne navigue jamais tout seul.
3. Cliquez sur **Démarrer** dans la fenêtre du programme.

Laissez la fenêtre Chrome du bot visible et ne cliquez pas dans la page pendant que le programme tourne :
tout changement que le programme n'a pas provoqué le met en pause (par sécurité). Utilisez **Pause** avant
d'intervenir à la main, puis **Reprendre**.

## Installation (une seule fois)

Dans PowerShell :

```powershell
cd C:\Users\Lee\Desktop\Bot\WikiMasterPackOpener
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Python 3.11 ou plus récent est nécessaire (testé avec 3.11.9). Dépendances : Playwright, CustomTkinter 6 (interface) et Pytest (tests), toutes listées dans `requirements.txt`. L'environnement `.venv` est déjà créé sur ce PC.

## Lancer la simulation

```powershell
cd C:\Users\Lee\Desktop\Bot\WikiMasterPackOpener
.\.venv\Scripts\python.exe main.py --simulation
```

Options :

| Option | Effet | Défaut |
|---|---|---|
| `--vitesse 30` | accélère le temps simulé (30 = 180 s en 6 s) | 10 |
| `--disponibles 3` | packs disponibles au démarrage | 1 |
| `--alea 60` | variation aléatoire ± du délai entre deux packs, en secondes | 30 |

Exemple : `.\.venv\Scripts\python.exe main.py --simulation --vitesse 30 --disponibles 5`

La simulation reproduit la page `/pulls` d'après les captures : compteur « X / 10 paquets disponibles »,
« Prochain dans M:SS », bouton « Ouvrir », révélation « Carte 1 / 5 » → « Encore N cartes » → « Continuer ».
**Elle n'ouvre aucun navigateur et n'envoie rien au site.**

### Ce qu'on peut tester à la main

1. **Démarrer** : le programme attend le seuil aléatoire, puis vide le stock en révélant les 5 cartes de chaque
   pack. Pour voir une ouverture tout de suite : `--disponibles 8`.
2. **Pause** / **Reprendre** : pause manuelle, aucun clic pendant la pause.
3. Panneau de simulation → **Vérification (5 s)** : la fenêtre « Vérification rapide » est simulée. L'état passe
   à « Vérification détectée » (rouge), aucun clic n'est envoyé, puis le programme reprend seul quand la fenêtre
   a disparu. **Vérification (30 s)** à vitesse ×10 dépasse les 60 s simulées : le programme passe en pause
   manuelle. Ancien comportement, si `reprise_auto_verification` vaut false : quand elle
   disparaît, le journal l'indique, mais le programme **reste en pause** jusqu'à **Confirmer la reprise**.
   La confirmation est refusée si la page n'est pas redevenue normale.
4. **Perte de connexion**, **Session expirée**, **Interface modifiée**, **Minuteur illisible**, **Fenêtre inconnue**,
   **Erreur Playwright (lecture)** : pause automatique avec la raison affichée. Cliquez sur **Rétablir la page**,
   puis sur **Confirmer la reprise**.
5. **Échec prochaine ouverture** : le clic ne produit rien. Après 10 s simulées, le programme passe en pause
   « résultat non constaté ». L'ouverture n'est pas comptée et le clic n'est pas répété.
6. **Test double clic** : le programme envoie volontairement un second clic juste après le premier. Ce second clic
   est refusé : il apparaît dans le compteur « Clics refusés » et dans le journal.
7. **Ouverture manuelle** : simule votre propre clic dans le navigateur. Le programme détecte un changement qu'il
   n'a pas provoqué et se met en pause.
8. **ARRÊTER** : arrêt immédiat. Plus aucun clic n'est envoyé et le navigateur est laissé tel quel.

## Paramètres

Les paramètres sont modifiables dans l'interface (**Appliquer** pour la session en cours, **Enregistrer** pour les
écrire dans `settings.json`), ou directement dans `settings.json`. Dans l'interface, le panneau **Paramètres** a
trois onglets :

- **Cycle** : capacité, délai pour un nouveau pack, objectif d'ouvertures, seuils aléatoires ;
- **Clics** : deux curseurs pour la temporisation avant chaque clic (minimum, maximum). Si vous poussez le
  minimum au-delà du maximum, le maximum suit (et inversement) ;
- **Discord** : URL du webhook, bouton **Tester**, interrupteur du bilan de fin de session.

Les changements s'appliquent en cours de route, sans redémarrer le bot.

| Paramètre | Rôle | Défaut |
|---|---|---|
| `capacite_packs` | plafond affiché par le site (« / 10 ») ; un écart avec le site met en pause | 10 |
| `delai_indicatif_s` | « Délai pour un nouveau pack » : temps entre deux packs (affichage seulement si le minuteur du site est illisible) | 180 |
| `objectif_ouvertures` | arrêt automatique après N ouvertures (0 = illimité : le bot tourne sans fin) | 0 |
| `seuil_min` / `seuil_max` | bornes du seuil aléatoire tiré à chaque cycle (`seuil_max` < capacité) | 5 / 8 |
| `intervalle_lecture_s` | fréquence de lecture de la page | 1.0 |
| `delai_resultat_s` | délai maximum pour constater le résultat d'un clic | 10 |
| `intervalle_min_clics_s` | délai minimum entre deux clics | 2 |
| `lectures_stables_requises` | nombre de lectures normales identiques avant un clic | 2 |
| `lectures_incertaines_tolerees` | nombre de lectures incertaines avant la pause (1 = pause immédiate) | 1 |
| `reprise_auto_verification` | reprise automatique après une « Vérification rapide » disparue d'elle-même | true |
| `lectures_normales_reprise` | lectures normales consécutives exigées avant cette reprise | 3 |
| `alerte_verification_s` | après ce délai, bip et « Action humaine requise » | 10 |
| `verification_delai_max_s` | au-delà de cette durée, la vérification demande une confirmation manuelle | 600 |
| `delai_clic_min_s` / `delai_clic_max_s` | temporisation aléatoire avant chaque clic (0 ≤ min ≤ max ≤ 10 s) | 0.8 / 1.8 |
| `discord_webhook_url` | URL du webhook Discord ; vide = aucune notification | `""` |
| `discord_bilan_session` | envoie aussi un bilan à l'arrêt ou quand l'objectif est atteint | false |
| `vitesse_simulation` | accélération du temps en simulation | 10 |

## Notifications Discord (facultatives)

Par défaut, aucune notification n'est envoyée et le programme ne se connecte à aucun service autre que le site.
Pour recevoir les alertes sur Discord :

1. Dans Discord : *Paramètres du salon* → *Intégrations* → *Webhooks* → *Nouveau webhook* → *Copier l'URL du
   webhook*.
2. Dans le bot : onglet **Paramètres → Discord**, collez l'URL, cliquez sur **Tester** (un message de test doit
   arriver dans le salon), puis sur **Enregistrer**.

Messages envoyés :

| Moment | Message |
|---|---|
| Une vérification est toujours affichée après `alerte_verification_s` (10 s) : case Cloudflare à cocher | ⚠ Action humaine requise |
| Chaque pause de sécurité (erreur de lecture, session expirée, page incertaine, résultat de clic non constaté, vérification trop longue…) | ⏸ Pause de sécurité, avec la raison |
| Arrêt manuel ou objectif atteint, si `discord_bilan_session` est activé | 📊 Bilan : packs ouverts, durée, clics, vérifications, pauses |

Une vérification qui disparaît d'elle-même en quelques secondes ne déclenche aucun message. Les messages ne
mentionnent personne (pas de @everyone ni de @here) ; le pied de message indique le mode (réel, observation,
simulation).

L'envoi se fait dans un **thread séparé** : le bot dépose le message dans une file et continue immédiatement.
Un Discord lent ou injoignable ne retarde donc jamais les lectures ni les clics. Un envoi échoué est seulement
noté dans le journal, sans nouvelle tentative. Si plus de 20 messages sont en attente, les suivants sont
abandonnés (et notés dans le journal). À la fermeture de la fenêtre, le bot attend au plus 3 s que le bilan
parte.

**L'URL du webhook est un secret** : quiconque la connaît peut écrire dans votre salon. Elle est masquée dans
l'interface, n'apparaît jamais dans le journal, et `settings.json` est exclu de git (`.gitignore`). En cas de
fuite, supprimez le webhook dans Discord et créez-en un nouveau.

## Règles de sécurité appliquées

- Le programme ne clique que si la page est **NORMALE**, c'est-à-dire si tous les éléments attendus sont présents
  et cohérents, et que ce constat se répète sur 2 lectures identiques. La page est encore relue juste avant le clic.
- Un seul clic à la fois : tant que le résultat du clic précédent n'est pas constaté sur la page, aucun autre clic.
- Une ouverture n'est comptée que lorsque l'écran de révélation des cartes est réellement affiché.
- Si le résultat d'un clic n'est pas constaté, le programme passe en pause. L'action n'est **jamais répétée
  automatiquement**.
- Vérification automatique, erreur ou état incertain : pause immédiate, puis reprise uniquement par
  **Confirmer la reprise**, après une nouvelle lecture de la page.
- Le minuteur local ne déclenche jamais de clic : seul le compteur affiché par le site compte.
- Le programme n'a aucune fonction capable de cliquer sur le bouton d'achat « Rechargez 10 paquets »,
  sur « Annuler » dans la fenêtre de vérification, ni sur un élément d'une fenêtre qui recouvre la page.
- La fenêtre « Vérification rapide » est reconnue par son texte. Toute autre fenêtre inconnue met aussi en pause
  (état incertain).
- Le programme ne tente jamais de résoudre, contourner ou masquer une vérification anti-bot.

## Tests automatisés

```powershell
cd C:\Users\Lee\Desktop\Bot\WikiMasterPackOpener
.\.venv\Scripts\python.exe -m pytest
```

Les tests n'accèdent jamais au site ni à Discord (l'envoi HTTP est remplacé par une fonction de test). Ils utilisent :

- la page simulée et une horloge manuelle, pour la logique ;
- des copies locales de la vraie page (`tests\fixtures\`), ouvertes dans un Chrome sans fenêtre et coupé du
  réseau, pour le pilote réel. Chaque clic reçu par la page y est enregistré, ce qui prouve qu'aucun bouton
  interdit n'est cliqué ;
- une fenêtre Tkinter masquée, pour l'interface.

## Journal

Le journal d'activité est affiché dans la fenêtre et écrit dans `logs\simulation_AAAAMMJJ.log`.

## Structure

```
Lancer_Bot.bat             lancement en un double-clic (Chrome dédié + interface)
main.py                    point d'entrée (normal, --observation, --simulation)
assets/                    logo.png (logo d'origine), logo.ico (icône de l'exe), fabriquer_icone.py
tester_un_pack.py          test réel minimal : ouvre UN pack puis s'arrête
wikimaster/
  config.py                paramètres + settings.json
  logger.py                journal horodaté (fenêtre + fichier)
  page_model.py            description neutre de la page (PageSnapshot, PageDriver)
  page_monitor.py          classement NORMAL / VÉRIFICATION / INCERTAIN / ERREUR
  pack_manager.py          compteurs, minuteur, verrou anti-double-clic
  controller.py            machine à états et boucle de travail
  notifications.py         notifications Discord (webhook) envoyées dans un thread séparé
  simulation.py            page Wiki Masters simulée + horloges
  browser.py               Chrome dédié (chrome_profile\) + inspection en lecture seule
  ui.py                    interface CustomTkinter (thème sombre)
tests/                     tests pytest
```

## Version autonome pour les amis (PafOpener.exe)

```powershell
cd C:\Users\Lee\Desktop\Bot\WikiMasterPackOpener
.\.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name PafOpener --icon assets\logo.ico --add-data "assets\logo.ico;assets" --add-data "assets\logo.png;assets" --collect-data customtkinter --collect-all playwright main.py
```

Pour changer de logo : déposez-le dans `C:\Users\Lee\Desktop\Bot` sous le nom `logo.png`, `logo.ico`, `logo.jpg`…
(le plus récent est choisi, son vrai format est détecté), lancez `.\.venv\Scripts\python.exe assets\fabriquer_icone.py`,
puis recompilez. Le script met à jour `assets\logo.png` et `assets\logo.ico` (10 tailles, LANCZOS ; les tailles d'un .ico source sont reprises telles quelles).

Une fois compilé, l'exe range `settings.json`, `logs\`, `inspection\` et `chrome_profile\` **à côté de lui** (et pas dans le projet). Ne copiez jamais dans le dossier à distribuer votre `settings.json` (il contient votre webhook Discord), ni `chrome_profile\` (votre session), ni `logs\` / `inspection\`. Il faut recompiler après chaque modification du code.

## Version Mac (PafOpener.app)

PyInstaller ne compile pas pour Mac depuis Windows : l'app est construite sur les machines macOS de GitHub par
`.github/workflows/build-mac.yml`. Mettez le projet dans un dépôt GitHub **privé** (le `.gitignore` exclut déjà
`settings.json`, `chrome_profile/`, `logs/`, `inspection/`), puis onglet **Actions → Build Mac → Run workflow**.
À la fin, téléchargez `PafOpener-mac-apple-silicon` (Mac M1 à M4) ou `PafOpener-mac-intel` en bas de la page du run :
chacun contient `PafOpener.zip` et `LISEZ-MOI.txt` (le déblocage Gatekeeper à faire une fois, l'app n'étant pas signée).

Sur un Mac, la même construction se lance à la main :

```bash
python3 -m pip install -r requirements.txt certifi pyinstaller==6.22.3
python3 -m PyInstaller --noconfirm --windowed --name PafOpener --osx-bundle-identifier com.pafopener.app --icon assets/logo.png --add-data "assets/logo.png:assets" --collect-data customtkinter --collect-all playwright main.py
ditto -c -k --keepParent dist/PafOpener.app PafOpener.zip
```

Différences avec Windows : les données vont dans `~/Library/Application Support/PafOpener` (l'intérieur du `.app`
peut être en lecture seule), Chrome est cherché dans `/Applications`, le bip est le son « Glass », et `certifi`
fournit les certificats HTTPS du webhook Discord.

## Chrome dédié et inspection (lecture seule)

Le bot utilise un **profil Chrome dédié** (`chrome_profile\` dans ce dossier), séparé de votre Chrome
habituel. Vous vous y connectez une seule fois, à la main. Le programme ne demande, ne lit et ne copie jamais vos
identifiants, cookies ou jetons. Depuis la version 136, Chrome interdit le pilotage du profil par défaut, et cette
protection n'est pas contournée.

```powershell
cd C:\Users\Lee\Desktop\Bot\WikiMasterPackOpener
.\.venv\Scripts\python.exe -m wikimaster.browser ouvrir      # ouvre Chrome (profil dédié) sur /pulls
.\.venv\Scripts\python.exe -m wikimaster.browser etat        # vérifie que Chrome est joignable
.\.venv\Scripts\python.exe -m wikimaster.browser inspecter   # lit la page, sans aucun clic
```

`inspecter` enregistre dans `inspection\` la structure de la page (JSON), son HTML et une capture d'écran. Ces
fichiers peuvent contenir votre pseudo ou votre solde : ils restent sur ce PC. Pendant que cette fenêtre Chrome
est ouverte, le port de débogage 9222 n'est accessible que depuis ce PC. Fermez la fenêtre quand vous ne
l'utilisez pas.

`enregistrer` relève chaque nouvel écran pendant 10 minutes, sans cliquer. Après un changement du site,
relevez les écrans puis régénérez les pages de test avec `.\.venv\Scripts\python.exe tests\fabriquer_fixtures.py`.
