#!/bin/bash
#
# CS-PILOT - Import des donnees pour migration VPS -> VPS
# ========================================================
#
# A lancer sur le VPS CIBLE (le nouveau serveur), APRES avoir clone le depot
# et installe les dependances (ex. via ./lancer.sh une premiere fois).
#
# Restaure la base de donnees et les documents depuis l'archive produite par
# export-data.sh. Un .env neuf (avec un nouveau SECRET_KEY) est genere s'il
# n'existe pas encore. Toute donnee existante est sauvegardee avant ecrasement.
#
# Usage :
#   ./scripts/migration/import-data.sh cspilot-migration-AAAAMMJJ-HHMMSS.tar.gz
#
set -euo pipefail

# --- Couleurs ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[INFO]${NC} $*"; }
err()   { echo -e "${RED}[ERREUR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="$PROJECT_DIR"   # mode script : DATA_DIR == dossier du projet (cf. database.py)

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
    err "Archive manquante."
    echo "Usage : $0 cspilot-migration-AAAAMMJJ-HHMMSS.tar.gz"
    exit 1
fi
if [ ! -f "$ARCHIVE" ]; then
    err "Archive introuvable : $ARCHIVE"
    exit 1
fi

echo "============================================================"
echo "   CS-PILOT - IMPORT DES DONNEES (migration)"
echo "============================================================"
echo ""

# --- Verifier que le code et les dependances sont en place ---
PY="python3"
if [ -x "$PROJECT_DIR/venv/bin/python" ]; then
    PY="$PROJECT_DIR/venv/bin/python"
else
    warn "venv introuvable. Lancez d'abord ./lancer.sh pour creer l'environnement,"
    warn "ou installez les dependances avant de poursuivre."
fi
if ! "$PY" -c "import flask" &> /dev/null; then
    err "Flask n'est pas installe dans cet environnement."
    err "Executez ./lancer.sh une premiere fois, puis Ctrl+C, avant l'import."
    exit 1
fi
info "Environnement Python pret ($PY)."

# --- Arreter le service si actif ---
SERVICE_WAS_RUNNING=0
if systemctl is-active --quiet cspilot 2>/dev/null; then
    warn "Arret du service cspilot..."
    sudo systemctl stop cspilot
    SERVICE_WAS_RUNNING=1
    info "Service cspilot arrete."
fi

# --- Sauvegarde de securite de l'existant ---
BACKUP_DIR="$DATA_DIR/backups"
mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
if [ -f "$DATA_DIR/cspilot.db" ]; then
    warn "Base existante detectee : sauvegarde avant ecrasement."
    cp "$DATA_DIR/cspilot.db" "$BACKUP_DIR/cspilot-pre-import-$TS.db"
    info "Sauvegarde : backups/cspilot-pre-import-$TS.db"
fi
if [ -d "$DATA_DIR/documents" ] && [ -n "$(ls -A "$DATA_DIR/documents" 2>/dev/null)" ]; then
    warn "Documents existants detectes : archivage avant ecrasement."
    tar -czf "$BACKUP_DIR/documents-pre-import-$TS.tar.gz" -C "$DATA_DIR" documents
    info "Archive : backups/documents-pre-import-$TS.tar.gz"
fi

# --- Extraction de l'archive ---
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
warn "Extraction de l'archive..."
tar -xzf "$ARCHIVE" -C "$TMP_DIR"
[ -f "$TMP_DIR/cspilot.db" ] || { err "Archive invalide : cspilot.db absent."; exit 1; }

# --- Mise en place de la base ---
# On retire d'eventuels fichiers WAL/SHM orphelins avant de poser la nouvelle base.
rm -f "$DATA_DIR/cspilot.db-wal" "$DATA_DIR/cspilot.db-shm"
cp "$TMP_DIR/cspilot.db" "$DATA_DIR/cspilot.db"
info "Base de donnees restauree ($(du -h "$DATA_DIR/cspilot.db" | cut -f1))."

# --- Mise en place des documents ---
if [ -d "$TMP_DIR/documents" ]; then
    rm -rf "$DATA_DIR/documents"
    cp -a "$TMP_DIR/documents" "$DATA_DIR/documents"
    DOC_COUNT="$(find "$DATA_DIR/documents" -type f | wc -l | tr -d ' ')"
    info "Documents restaures ($DOC_COUNT fichiers)."
fi

# --- Generation d'un .env neuf (nouveau SECRET_KEY) ---
ENV_FILE="$DATA_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    info ".env deja present : SECRET_KEY existant conserve."
else
    warn "Generation d'un nouveau .env avec SECRET_KEY aleatoire..."
    NEW_KEY="$("$PY" -c "import secrets; print(secrets.token_hex(32))")"
    cat > "$ENV_FILE" <<EOF
# Genere automatiquement lors de la migration ($TS)
# Pour regenerer une cle : python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=$NEW_KEY

# Decommentez si l'application est derriere un reverse proxy / HTTPS (Nginx, Cloudflare...)
# BEHIND_PROXY=true
EOF
    info ".env cree avec un nouveau SECRET_KEY."
fi

# --- Application des migrations de schema en attente ---
warn "Application des migrations de schema en attente (si le code est plus recent)..."
( cd "$PROJECT_DIR" && "$PY" -c "
from migration_manager import appliquer_toutes_en_attente, get_version_actuelle
res = appliquer_toutes_en_attente(appliquee_par='migration')
print('Migrations appliquees :', res if res else 'aucune (schema deja a jour)')
print('Version du schema :', get_version_actuelle())
" )

echo ""
echo "============================================================"
info "Import termine."
echo "============================================================"
echo ""
echo "Etapes suivantes :"
if [ "$SERVICE_WAS_RUNNING" -eq 1 ]; then
    echo "  - Redemarrer le service :  sudo systemctl start cspilot"
else
    echo "  - Demarrer l'application :  sudo systemctl start cspilot"
    echo "    (ou ./lancer.sh pour un test manuel)"
fi
echo "  - Se connecter et verifier : donnees, documents, version du schema"
echo "    (panneau Administration)."
echo ""
echo "Note : le SECRET_KEY ayant change, les sessions de l'ancien serveur sont"
echo "       invalidees. Les utilisateurs devront se reconnecter (normal)."
echo ""
