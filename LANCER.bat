@echo off
cd /d "%~dp0"
cls
echo ============================================================
echo    GESTION DU TEMPS DE TRAVAIL - DEMARRAGE
echo ============================================================
echo.
echo Verification de l'installation...
echo.

REM Vérifier si Python est installé
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH
    echo.
    echo Telecharger Python sur : https://www.python.org/downloads/
    echo N'oubliez pas de cocher "Add Python to PATH" lors de l'installation
    echo.
    pause
    exit /b 1
)

echo [OK] Python detecte
echo.

REM Vérifier si les dépendances sont installées
python -c "import flask, waitress, requests, dotenv" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installation des dependances...
    python -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
    echo.
)

echo [OK] Dependances installees
echo.
echo ============================================================
echo    LANCEMENT DE L'APPLICATION
echo ============================================================
echo.
echo Pour arreter l'application : appuyez sur Ctrl+C
echo.
echo L'application va demarrer dans quelques secondes...
echo.

REM Le superviseur charge .env avec python-dotenv, sans execution shell.
python superviseur.py

echo.
echo ============================================================
echo    APPLICATION ARRETEE
echo ============================================================
echo.
pause
