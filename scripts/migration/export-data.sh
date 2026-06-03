#!/bin/bash
#
# CS-PILOT - Export des donnees pour migration VPS -> VPS
# ========================================================
#
# A lancer sur le VPS SOURCE (le serveur actuel).
# Produit une archive .tar.gz unique contenant la base de donnees (copie
# coherente) et tous les documents uploades, prete a etre transferee vers
# le nouveau VPS.
#
# Le fichier .env (donc le SECRET_KEY) n'est PAS inclus : une nouvelle cle
# sera generee sur le serveur cible lors de l'import.
#
# Usage :
#   ./scripts/migration/export-data.sh [--stop-service] [--output DOSSIER]
#
#   --stop-service   Arrete le service systemd "cspilot" pendant l'export
#                    pour un instantane parfaitement propre, puis le relance.
#                    (Optionnel : la copie via l'API backup SQLite est deja
#                    coherente meme si l'application tourne.)
#   --output DOSSIER Dossier ou ecrire l'archive (defaut : dossier courant).
#
set -euo pipefail

# --- Couleurs ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[INFO]${NC} $*"; }
err()   { echo -e "${RED}[ERREUR]${NC} $*" >&2; }

# --- Racine du projet (deux niveaux au-dessus de ce script) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="$PROJECT_DIR"   # mode script : DATA_DIR == dossier du projet (cf. database.py)

DB_FILE="$DATA_DIR/cspilot.db"
DOCS_DIR="$DATA_DIR/documents"

# --- Options ---
STOP_SERVICE=0
OUTPUT_DIR="$(pwd)"
while [ $# -gt 0 ]; do
    case "$1" in
        --stop-service) STOP_SERVICE=1; shift ;;
        --output) OUTPUT_DIR="$2"; shift 2 ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) err "Option inconnue : $1"; exit 1 ;;
    esac
done

echo "============================================================"
echo "   CS-PILOT - EXPORT DES DONNEES (migration)"
echo "============================================================"
echo ""

# --- Verifications ---
if [ ! -f "$DB_FILE" ]; then
    err "Base de donnees introuvable : $DB_FILE"
    err "Lancez ce script depuis le dossier du projet CS-PILOT."
    exit 1
fi
info "Base de donnees detectee : $DB_FILE ($(du -h "$DB_FILE" | cut -f1))"

# --- Arret optionnel du service ---
SERVICE_WAS_STOPPED=0
if [ "$STOP_SERVICE" -eq 1 ]; then
    if systemctl is-active --quiet cspilot 2>/dev/null; then
        warn "Arret du service cspilot pour un instantane propre..."
        sudo systemctl stop cspilot
        SERVICE_WAS_STOPPED=1
        info "Service cspilot arrete."
    else
        warn "Service cspilot non actif : rien a arreter."
    fi
fi

# --- Dossier temporaire ---
TMP_DIR="$(mktemp -d)"
STAGE_DIR="$TMP_DIR/cspilot-data"
mkdir -p "$STAGE_DIR"
cleanup() {
    rm -rf "$TMP_DIR"
    if [ "$SERVICE_WAS_STOPPED" -eq 1 ]; then
        warn "Redemarrage du service cspilot..."
        sudo systemctl start cspilot && info "Service cspilot redemarre."
    fi
}
trap cleanup EXIT

# --- Copie coherente de la base (SQLite est en mode WAL) ---
warn "Copie coherente de la base de donnees..."
if command -v sqlite3 &> /dev/null; then
    sqlite3 "$DB_FILE" ".backup '$STAGE_DIR/cspilot.db'"
    info "Base copiee via l'API backup SQLite (sqlite3)."
else
    warn "sqlite3 absent : utilisation de backup_db.py (API backup Python)."
    PY="python3"; [ -x "$PROJECT_DIR/venv/bin/python" ] && PY="$PROJECT_DIR/venv/bin/python"
    BK_PATH="$( cd "$PROJECT_DIR" && "$PY" -c "import backup_db; path,erreur=backup_db.creer_sauvegarde(label='migration'); import sys; sys.stderr.write((erreur or '')+'\n'); print(path or '')" )"
    [ -z "$BK_PATH" ] || [ ! -f "$BK_PATH" ] && { err "Echec de la sauvegarde de la base."; exit 1; }
    cp "$BK_PATH" "$STAGE_DIR/cspilot.db"
    info "Base copiee via backup_db.py."
fi

# --- Copie des documents ---
if [ -d "$DOCS_DIR" ]; then
    DOC_COUNT="$(find "$DOCS_DIR" -type f | wc -l | tr -d ' ')"
    warn "Copie des documents ($DOC_COUNT fichiers)..."
    cp -a "$DOCS_DIR" "$STAGE_DIR/documents"
    info "Documents copies."
else
    warn "Aucun dossier 'documents' : export de la base seule."
    mkdir -p "$STAGE_DIR/documents"
fi

# --- Creation de l'archive ---
mkdir -p "$OUTPUT_DIR"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$OUTPUT_DIR/cspilot-migration-$TIMESTAMP.tar.gz"
warn "Creation de l'archive..."
tar -czf "$ARCHIVE" -C "$STAGE_DIR" cspilot.db documents

echo ""
echo "============================================================"
info "Export termine."
echo "  Archive   : $ARCHIVE"
echo "  Taille    : $(du -h "$ARCHIVE" | cut -f1)"
echo "  SHA-256   : $(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
echo "============================================================"
echo ""
echo "Etapes suivantes :"
echo "  1. Transferer l'archive vers le nouveau VPS :"
echo "       scp \"$ARCHIVE\" user@NOUVEAU_VPS:~/"
echo "  2. Verifier le SHA-256 apres transfert (doit etre identique)."
echo "  3. Sur le nouveau VPS, lancer :"
echo "       ./scripts/migration/import-data.sh ~/$(basename "$ARCHIVE")"
echo ""
