"""
Gestionnaire de migrations de base de donnees.

Systeme de versionnement du schema de la base SQLite.
Chaque migration est un fichier Python dans le dossier migrations/
avec un numero de version, un nom descriptif, et des fonctions upgrade/downgrade.

Conventions de nommage : XXXX_description.py (ex: 0001_initial_schema.py)
"""
import os
import importlib.util
import sqlite3
from datetime import datetime
from database import get_db, DATABASE

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')


def _ensure_migration_table():
    """Cree la table schema_migrations si elle n'existe pas."""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL UNIQUE,
            nom TEXT NOT NULL,
            description TEXT,
            appliquee_le TEXT DEFAULT CURRENT_TIMESTAMP,
            appliquee_par TEXT,
            duree_ms INTEGER,
            statut TEXT DEFAULT 'ok'
        )
    ''')
    conn.commit()
    conn.close()


def _load_migration_module(filepath):
    """Charge dynamiquement un fichier de migration Python."""
    module_name = os.path.splitext(os.path.basename(filepath))[0]
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lister_fichiers_migrations():
    """Liste tous les fichiers de migration disponibles, tries par version."""
    if not os.path.exists(MIGRATIONS_DIR):
        os.makedirs(MIGRATIONS_DIR, exist_ok=True)
        return []

    fichiers = []
    for f in sorted(os.listdir(MIGRATIONS_DIR)):
        if f.endswith('.py') and not f.startswith('__'):
            version = f.split('_')[0]
            fichiers.append({
                'version': version,
                'fichier': f,
                'chemin': os.path.join(MIGRATIONS_DIR, f)
            })
    return fichiers


def get_migrations_appliquees():
    """Retourne la liste des versions de migrations deja appliquees."""
    _ensure_migration_table()
    conn = get_db()
    rows = conn.execute(
        "SELECT version, nom, description, appliquee_le, appliquee_par, duree_ms, statut "
        "FROM schema_migrations ORDER BY version"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_version_actuelle():
    """Retourne la version actuelle du schema (derniere migration appliquee)."""
    _ensure_migration_table()
    conn = get_db()
    row = conn.execute(
        "SELECT version FROM schema_migrations WHERE statut = 'ok' ORDER BY version DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row['version'] if row else '0000'


def get_migrations_en_attente():
    """Retourne la liste des migrations pas encore appliquees."""
    appliquees = {m['version'] for m in get_migrations_appliquees()}
    fichiers = lister_fichiers_migrations()

    en_attente = []
    for f in fichiers:
        if f['version'] not in appliquees:
            module = _load_migration_module(f['chemin'])
            en_attente.append({
                'version': f['version'],
                'fichier': f['fichier'],
                'nom': getattr(module, 'NOM', f['fichier']),
                'description': getattr(module, 'DESCRIPTION', ''),
            })
    return en_attente


def appliquer_migration(version, appliquee_par=None):
    """Applique une migration specifique par son numero de version.

    Retourne (success: bool, message: str).
    """
    _ensure_migration_table()

    # Verifier que la migration n'est pas deja appliquee avec succes
    conn = get_db()
    existing = conn.execute(
        "SELECT id, statut FROM schema_migrations WHERE version = ?", (version,)
    ).fetchone()
    conn.close()
    if existing and existing['statut'] == 'ok':
        return False, f"La migration {version} est deja appliquee."

    # Trouver le fichier correspondant
    fichiers = lister_fichiers_migrations()
    fichier = None
    for f in fichiers:
        if f['version'] == version:
            fichier = f
            break

    if not fichier:
        return False, f"Fichier de migration introuvable pour la version {version}."

    module = _load_migration_module(fichier['chemin'])

    if not hasattr(module, 'upgrade'):
        return False, f"La migration {version} ne contient pas de fonction upgrade()."

    # Appliquer la migration
    start = datetime.now()
    try:
        conn = get_db()
        module.upgrade(conn)
        conn.commit()
        duree = int((datetime.now() - start).total_seconds() * 1000)

        conn.execute(
            "INSERT INTO schema_migrations (version, nom, description, appliquee_par, duree_ms, statut) "
            "VALUES (?, ?, ?, ?, ?, 'ok')",
            (
                version,
                getattr(module, 'NOM', fichier['fichier']),
                getattr(module, 'DESCRIPTION', ''),
                appliquee_par or 'systeme',
                duree
            )
        )
        conn.commit()
        conn.close()
        return True, f"Migration {version} appliquee avec succes ({duree} ms)."
    except Exception as e:
        duree = int((datetime.now() - start).total_seconds() * 1000)
        # Liberer le verrou en ecriture avant d'enregistrer l'echec
        try:
            conn.rollback()
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
        # Enregistrer l'echec
        try:
            conn2 = get_db()
            conn2.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, nom, description, appliquee_par, duree_ms, statut) "
                "VALUES (?, ?, ?, ?, ?, 'erreur')",
                (
                    version,
                    getattr(module, 'NOM', fichier['fichier']),
                    f"ERREUR: {str(e)}",
                    appliquee_par or 'systeme',
                    duree
                )
            )
            conn2.commit()
            conn2.close()
        except Exception:
            pass
        return False, f"Erreur lors de la migration {version}: {str(e)}"


def appliquer_toutes_en_attente(appliquee_par=None):
    """Applique toutes les migrations en attente dans l'ordre.

    Retourne une liste de (version, success, message).
    """
    en_attente = get_migrations_en_attente()
    resultats = []

    for m in en_attente:
        success, msg = appliquer_migration(m['version'], appliquee_par)
        resultats.append((m['version'], success, msg))
        if not success:
            break  # Arreter en cas d'erreur

    return resultats


def get_statut_complet():
    """Retourne un dictionnaire complet de l'etat du systeme de migrations."""
    appliquees = get_migrations_appliquees()
    en_attente = get_migrations_en_attente()
    version = get_version_actuelle()

    return {
        'version_actuelle': version,
        'nb_appliquees': len(appliquees),
        'nb_en_attente': len(en_attente),
        'appliquees': appliquees,
        'en_attente': en_attente,
        'a_jour': len(en_attente) == 0,
    }


def marquer_migration_existante(version, nom, description=''):
    """Marque une migration comme deja appliquee sans l'executer.

    Utile pour enregistrer les migrations qui correspondent au schema existant.
    """
    _ensure_migration_table()
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM schema_migrations WHERE version = ?", (version,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO schema_migrations (version, nom, description, appliquee_par, duree_ms, statut) "
            "VALUES (?, ?, ?, 'baseline', 0, 'ok')",
            (version, nom, description)
        )
        conn.commit()
    conn.close()
