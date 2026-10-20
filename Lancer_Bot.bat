@echo off
rem ============================================================================
rem  PafOpener - lancement en un double-clic
rem  1. ouvre le Chrome dedie (profil chrome_profile) sur /pulls s'il n'est pas
rem     deja ouvert, ou ajoute un onglet /pulls s'il manque ;
rem  2. ouvre l'interface du bot (sans fenetre de console).
rem  Le bot ne clique sur rien tant que vous n'avez pas clique sur "Demarrer".
rem  Arguments optionnels transmis a main.py, par exemple : Lancer_Bot.bat --observation
rem ============================================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo L'environnement Python .venv est introuvable dans :
    echo   %~dp0
    echo Installez-le une fois avec :
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py" %*
exit /b 0
