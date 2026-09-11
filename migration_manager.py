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
from database import get_db
from contextlib import closing
import time

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
    from schema_resilience import creer_journal_migrations
    creer_journal_migrations(conn)
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
    appliquees = {m['version'] for m in get_migrations_appliquees() if m['statut'] == 'ok'}
    fichiers = lister_fichiers_migrations()

    en_attente = []
    for f in fichiers:
        if f['version'] not in appliquees:
            try:
                module = _load_migration_module(f['chemin'])
                nom = getattr(module, 'NOM', f['fichier'])
                description = getattr(module, 'DESCRIPTION', '')
            except Exception:
                nom = f['fichier']
                description = 'Fichier de migration illisible : vérifier le code avant application.'
            en_attente.append({
                'version': f['version'],
                'fichier': f['fichier'],
                'nom': nom,
                'description': description,
            })
    return en_attente


def appliquer_migration(version, appliquee_par=None, *, reprise_historique=False):
    """DDL + données + succès dans une seule transaction SQLite.

    Une erreur de l'ancien gestionnaire peut avoir été partiellement commitée :
    sa reprise exige un diagnostic isolé et l'option CLI explicite. Les erreurs
    rollbackées par ce gestionnaire sont directement relançables.
    """
    try:
        _ensure_migration_table()
    except sqlite3.Error:
        return False, 'Journal indisponible ou autre opération en cours : diagnostic nécessaire.'
    fichiers = lister_fichiers_migrations()
    fichier = next((f for f in fichiers if f['version'] == version), None)
    if fichier is None:
        return False, 'Fichier de migration introuvable.'
    debut = time.monotonic()
    nom = fichier['fichier']
    acteur = appliquee_par or 'systeme'
    try:
        with closing(get_db()) as conn, conn.migration_atomique():
            lignes = {r['version']: dict(r) for r in conn.execute('SELECT * FROM schema_migrations')}
            if set(lignes) - {f['version'] for f in fichiers}:
                return False, ('Migrations inconnues de ce code : installez la version compatible '
                               'avant toute migration ; voir docs/resilience.md.')
            existante = lignes.get(version)
            if existante and existante['statut'] == 'ok':
                return False, f'La migration {version} est déjà appliquée.'
            precedentes = [f['version'] for f in fichiers if f['version'] < version]
            if any(lignes.get(v, {}).get('statut') != 'ok' for v in precedentes) or any(
                    v < version and r['statut'] != 'ok' for v, r in lignes.items()):
                return False, 'Appliquez ou réparez les migrations précédentes dans l’ordre.'
            derniere = conn.execute(
                'SELECT transaction_annulee FROM schema_migrations_tentatives '
                'WHERE version=? ORDER BY id DESC LIMIT 1', (version,)).fetchone()
            if existante and existante['statut'] != 'ok' and not reprise_historique and (
                    not derniere or not derniere['transaction_annulee']):
                return False, (f'Migration {version} : ancien échec potentiellement partiel. '
                               'Diagnostic sur une copie isolée ou restauration avant reprise ; voir docs/resilience.md.')
            module = _load_migration_module(fichier['chemin'])
            nom = getattr(module, 'NOM', nom)
            module.upgrade(conn)
            duree = int((time.monotonic() - debut) * 1000)
            conn.execute(
                "INSERT INTO schema_migrations(version, nom, description, appliquee_par, duree_ms, statut) "
                "VALUES (?, ?, ?, ?, ?, 'ok') ON CONFLICT(version) DO UPDATE SET "
                "nom=excluded.nom, description=excluded.description, appliquee_le=CURRENT_TIMESTAMP, "
                "appliquee_par=excluded.appliquee_par, duree_ms=excluded.duree_ms, statut='ok'",
                (version, nom, getattr(module, 'DESCRIPTION', ''), acteur, duree))
            conn.execute(
                "INSERT INTO schema_migrations_tentatives(version, statut, detail, appliquee_par, duree_ms) "
                "VALUES (?, 'ok', 'Schéma, données et succès commités ensemble', ?, ?)",
                (version, acteur, duree))
        return True, f'Migration {version} appliquée avec succès ({duree} ms).'
    except Exception as erreur:
        # Ne pas exposer str(erreur) : une exception peut contenir une valeur
        # chiffrée, une clé ou une donnée métier. Le type suffit au diagnostic.
        detail = f'{type(erreur).__name__} : transaction annulée intégralement'
        duree = int((time.monotonic() - debut) * 1000)
        try:
            with closing(get_db()) as conn, conn.migration_atomique():
                # Un autre processus peut avoir réussi après notre rollback.
                conn.execute(
                    "INSERT INTO schema_migrations(version, nom, description, appliquee_par, duree_ms, statut) "
                    "VALUES (?, ?, ?, ?, ?, 'erreur') ON CONFLICT(version) DO UPDATE SET "
                    "description=excluded.description, appliquee_le=CURRENT_TIMESTAMP, "
                    "appliquee_par=excluded.appliquee_par, duree_ms=excluded.duree_ms, statut='erreur' "
                    "WHERE schema_migrations.statut != 'ok'",
                    (version, nom, detail, acteur, duree))
                conn.execute(
                    "INSERT INTO schema_migrations_tentatives(version, statut, detail, appliquee_par, duree_ms, transaction_annulee) "
                    "VALUES (?, 'erreur', ?, ?, ?, 1)", (version, detail, acteur, duree))
        except sqlite3.Error:
            return False, f'Migration {version} : échec, journal indisponible. Arrêtez et diagnostiquez la base.'
        return False, f'Migration {version} : échec ({detail}). Corrigez la cause avant de relancer.'


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
    connues = {f['version'] for f in lister_fichiers_migrations()}
    inconnues = [m for m in appliquees if m['version'] not in connues]
    en_attente = get_migrations_en_attente()
    version = get_version_actuelle()
    with closing(get_db()) as conn:
        tentatives = [dict(r) for r in conn.execute(
            'SELECT * FROM schema_migrations_tentatives ORDER BY id DESC LIMIT 100')]

    return {
        'version_actuelle': version,
        'nb_appliquees': sum(m['statut'] == 'ok' for m in appliquees),
        'erreurs': [m for m in appliquees if m['statut'] != 'ok'],
        'inconnues': inconnues,
        'nb_en_attente': len(en_attente),
        'appliquees': appliquees,
        'tentatives': tentatives,
        'en_attente': en_attente,
        'a_jour': not en_attente and not inconnues and all(m['statut'] == 'ok' for m in appliquees),
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
