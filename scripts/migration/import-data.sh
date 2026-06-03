#!/bin/bash
#
# CS-PILOT - Import des donnees pour migration VPS -> VPS
# ========================================================
#
# A lancer sur le VPS CIBLE (le nouveau serveur), APRES avoir clone le depot
# et installe les dependances (ex. via ./lancer.sh une premiere fois).
#
# Restaure depuis l'archive produite par export-data.sh :
#   - la base de donnees,
#   - les dossiers de donnees (documents, factures, modeles_contrats,
#     contrats_generes, exports).
# Un .env neuf (nouveau SECRET_KEY) est genere s'il n'existe pas, puis tous les
# parametres chiffres de app_settings (SMTP, cles API, tarifs ALSH...) sont
# RE-CHIFFRES avec cette nouvelle cle a partir de la cle d'origine transmise
# dans l'archive : rien a reconfigurer manuellement.
# Toute donnee existante est sauvegardee avant ecrasement.
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
DATA_FOLDERS=(documents factures modeles_contrats contrats_generes exports)

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
for folder in "${DATA_FOLDERS[@]}"; do
    if [ -d "$DATA_DIR/$folder" ] && [ -n "$(ls -A "$DATA_DIR/$folder" 2>/dev/null)" ]; then
        warn "Dossier '$folder' existant : archivage avant ecrasement."
        tar -czf "$BACKUP_DIR/$folder-pre-import-$TS.tar.gz" -C "$DATA_DIR" "$folder"
    fi
done

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

# --- Mise en place des dossiers de donnees ---
for folder in "${DATA_FOLDERS[@]}"; do
    if [ -d "$TMP_DIR/$folder" ]; then
        rm -rf "$DATA_DIR/$folder"
        cp -a "$TMP_DIR/$folder" "$DATA_DIR/$folder"
        n="$(find "$DATA_DIR/$folder" -type f | wc -l | tr -d ' ')"
        info "Dossier '$folder' restaure ($n fichiers)."
    fi
done

# --- .env / SECRET_KEY (genere si absent) + recuperation de la NOUVELLE cle ---
ENV_FILE="$DATA_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    info ".env deja present : SECRET_KEY existant conserve."
else
    warn "Generation d'un nouveau .env avec SECRET_KEY aleatoire..."
    GEN_KEY="$("$PY" -c "import secrets; print(secrets.token_hex(32))")"
    cat > "$ENV_FILE" <<EOF
# Genere automatiquement lors de la migration ($TS)
# Pour regenerer une cle : python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=$GEN_KEY

# Decommentez si l'application est derriere un reverse proxy / HTTPS (Nginx, Cloudflare...)
# BEHIND_PROXY=true
EOF
    chmod 600 "$ENV_FILE"
    info ".env cree avec un nouveau SECRET_KEY."
fi
NEW_KEY="$(grep -E '^[[:space:]]*SECRET_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d ' \r\"')"

# --- Re-chiffrement des parametres avec la nouvelle cle ---
OLD_KEY_FILE="$TMP_DIR/_migration/old_secret_key"
if [ -f "$OLD_KEY_FILE" ]; then
    OLD_KEY="$(cat "$OLD_KEY_FILE")"
    warn "Re-chiffrement des parametres (SMTP, cles API, tarifs ALSH...) avec la nouvelle cle..."
    "$PY" "$SCRIPT_DIR/reencrypt_settings.py" "$OLD_KEY" "$NEW_KEY" "$DATA_DIR/cspilot.db"
else
    warn "Cle d'origine absente de l'archive : pas de re-chiffrement automatique."
    warn "Les parametres chiffres (SMTP, cles API...) devront etre reconfigures via l'UI."
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
echo "  - Se connecter et verifier : donnees, documents, parametres (SMTP, cles API)."
echo "  - Supprimer l'archive de migration (contient la cle d'origine) :"
echo "       rm -f \"$ARCHIVE\""
echo ""
echo "Note : le SECRET_KEY ayant change, les sessions de l'ancien serveur sont"
echo "       invalidees. Les utilisateurs devront se reconnecter (normal)."
echo ""
