#!/bin/bash
echo "============================================================"
echo "   GESTION DU TEMPS DE TRAVAIL - DEMARRAGE"
echo "============================================================"
echo ""
echo "Verification de l'installation..."
echo ""

# Se placer dans le repertoire du script
cd "$(dirname "$0")"

# Verifier si Python est installe
if ! command -v python3 &> /dev/null; then
    echo "[ERREUR] Python3 n'est pas installe"
    echo ""
    echo "  Installer avec : sudo apt install python3 python3-pip python3-venv"
    echo ""
    exit 1
fi

echo "[OK] Python detecte ($(python3 --version))"
echo ""

# Creer un environnement virtuel si absent
if [ ! -d "venv" ]; then
    echo "[INFO] Creation de l'environnement virtuel..."
    python3 -m venv venv
fi

# Activer l'environnement virtuel
source venv/bin/activate

# Verifier les dependances
if ! python3 -c "import flask" &> /dev/null; then
    echo "[INFO] Installation des dependances..."
    pip install -r requirements.txt
    echo ""
fi

echo "[OK] Dependances installees"
echo ""

# Charger le .env si present
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "[OK] Variables d'environnement chargees (.env)"
    echo ""
fi

echo "============================================================"
echo "   LANCEMENT DE L'APPLICATION"
echo "============================================================"
echo ""
echo "Pour arreter l'application : Ctrl+C"
echo ""

python3 app.py
