@echo off
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
pip show Flask >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installation des dependances...
    pip install -r requirements.txt
    echo.
)

REM Vérifier si psycopg2 est installé (requis pour PostgreSQL)
pip show psycopg2-binary >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installation des dependances PostgreSQL...
    pip install -r requirements.txt
    echo.
)

echo [OK] Dependances installees
echo.

REM Charger les variables d'environnement depuis .env
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
)

REM Vérifier si DATABASE_URL est configuré
if "%DATABASE_URL%"=="" (
    echo ============================================================
    echo    CONFIGURATION BASE DE DONNEES REQUISE
    echo ============================================================
    echo.
    echo La variable DATABASE_URL n'est pas definie dans le fichier .env
    echo.
    echo Cette application necessite PostgreSQL.
    echo.
    echo Etapes de configuration :
    echo.
    echo 1. Installez PostgreSQL : https://www.postgresql.org/download/windows/
    echo.
    echo 2. Creez la base de donnees ^(dans psql ou pgAdmin^) :
    echo       CREATE DATABASE cspilot;
    echo.
    echo 3. Creez ou modifiez le fichier .env dans ce dossier :
    echo       DATABASE_URL=postgresql://postgres:VotreMotDePasse@localhost:5432/cspilot
    echo       SECRET_KEY=VotreCleSecrete
    echo.
    echo    ^(Copiez le fichier .env.example comme point de depart^)
    echo.
    echo ============================================================
    pause
    exit /b 1
)

echo [OK] DATABASE_URL configuree
echo.
echo ============================================================
echo    LANCEMENT DE L'APPLICATION
echo ============================================================
echo.
echo Pour arreter l'application : appuyez sur Ctrl+C
echo.
echo L'application va demarrer dans quelques secondes...
echo.

REM Lancer l'application
python app.py

echo.
echo ============================================================
echo    APPLICATION ARRETEE
echo ============================================================
echo.
pause
