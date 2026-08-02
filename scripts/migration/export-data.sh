#!/bin/bash
#
# CS-PILOT - Export des donnees pour migration VPS -> VPS
# ========================================================
#
# A lancer sur le VPS SOURCE (le serveur actuel).
# Produit une archive .tar.gz unique contenant :
#   - la base de donnees (copie coherente via l'API backup SQLite),
#   - les dossiers de donnees sur disque (documents, factures, modeles de
#     contrats, contrats generes, exports),
#   - le SECRET_KEY d'origine (de maniere TRANSITOIRE), uniquement pour
#     permettre le re-chiffrement des parametres (SMTP, cles API, tarifs ALSH,
#     etc.) sur la cible avec une nouvelle cle. Cette cle est jetee apres import.
#
# /!\ L'archive contient des donnees sensibles (base + cle d'origine).
#     Elle est creee avec des permissions restreintes (600). Transferez-la de
#     facon securisee (scp/ssh) et supprimez-la des deux cotes apres migration.
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
# Dossiers de donnees sur disque a transferer (cf. blueprints/*.py).
DATA_FOLDERS=(documents factures modeles_contrats contrats_generes exports)

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

# --- Recuperation du SECRET_KEY d'origine (pour re-chiffrement sur la cible) ---
OLD_KEY=""
if [ -f "$DATA_DIR/.env" ]; then
    OLD_KEY="$(grep -E '^[[:space:]]*SECRET_KEY=' "$DATA_DIR/.env" | head -1 | cut -d= -f2- | tr -d ' \r\"')"
fi
[ -z "$OLD_KEY" ] && OLD_KEY="${SECRET_KEY:-}"
if [ -z "$OLD_KEY" ]; then
    warn "SECRET_KEY d'origine introuvable (.env absent ?)."
    warn "Les parametres chiffres (SMTP, cles API...) devront etre reconfigures"
    warn "manuellement sur la cible. La migration des donnees se poursuit."
else
    info "SECRET_KEY d'origine recupere (pour re-chiffrement automatique)."
fi

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

# --- Copie des dossiers de donnees presents ---
TAR_ITEMS=(cspilot.db)
for folder in "${DATA_FOLDERS[@]}"; do
    src="$DATA_DIR/$folder"
    if [ -d "$src" ] && [ -n "$(ls -A "$src" 2>/dev/null)" ]; then
        n="$(find "$src" -type f | wc -l | tr -d ' ')"
        cp -a "$src" "$STAGE_DIR/$folder"
        TAR_ITEMS+=("$folder")
        info "Dossier '$folder' copie ($n fichiers)."
    fi
done

# --- Metadonnees de migration (SECRET_KEY d'origine) ---
if [ -n "$OLD_KEY" ]; then
    META_DIR="$STAGE_DIR/_migration"
    mkdir -p "$META_DIR"
    printf '%s' "$OLD_KEY" > "$META_DIR/old_secret_key"
    chmod 600 "$META_DIR/old_secret_key"
    TAR_ITEMS+=(_migration)
fi

# --- Creation de l'archive (permissions restreintes) ---
mkdir -p "$OUTPUT_DIR"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$OUTPUT_DIR/cspilot-migration-$TIMESTAMP.tar.gz"
warn "Creation de l'archive..."
( umask 077 && tar -czf "$ARCHIVE" -C "$STAGE_DIR" "${TAR_ITEMS[@]}" )
chmod 600 "$ARCHIVE"

echo ""
echo "============================================================"
info "Export termine."
echo "  Archive   : $ARCHIVE"
echo "  Taille    : $(du -h "$ARCHIVE" | cut -f1)"
echo "  SHA-256   : $(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
echo "============================================================"
echo ""
echo "/!\\ Archive sensible (donnees + cle d'origine). A transferer en SSH"
echo "    et a supprimer des deux cotes une fois la migration validee."
echo ""
echo "Etapes suivantes :"
echo "  1. Transferer l'archive vers le nouveau VPS :"
echo "       scp \"$ARCHIVE\" user@NOUVEAU_VPS:~/"
echo "  2. Verifier le SHA-256 apres transfert (doit etre identique)."
echo "  3. Sur le nouveau VPS, lancer :"
echo "       ./scripts/migration/import-data.sh ~/$(basename "$ARCHIVE")"
echo ""
