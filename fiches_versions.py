"""Versions et invariants des fiches mensuelles, dans la transaction de l'appelant."""
import hashlib
import json
from datetime import datetime

from fiches_contenu import calculer_contenu
from utils import maintenant

ROLES = ('salarie', 'responsable', 'directeur')


class FicheVerrouillee(ValueError):
    """Une transaction entière doit être annulée avant toute réponse utilisateur."""


def creer_schema(conn):
    """Schéma final commun à init_db et à la migration 0065 ; sans commit."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fiches_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, annee INTEGER NOT NULL, mois INTEGER NOT NULL,
            numero INTEGER NOT NULL, empreinte TEXT NOT NULL, contenu TEXT NOT NULL,
            origine TEXT NOT NULL, cree_le TEXT NOT NULL,
            UNIQUE(user_id, annee, mois, numero)
        )
    """)
    colonnes = {r[1] for r in conn.execute('PRAGMA table_info(validations)')}
    for colonne in ('version_courante_id', *(f'version_{r}_id' for r in ROLES)):
        if colonne not in colonnes:
            conn.execute(f'ALTER TABLE validations ADD COLUMN {colonne} INTEGER REFERENCES fiches_versions(id)')
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fiches_evenements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, annee INTEGER NOT NULL, mois INTEGER NOT NULL,
            version_id INTEGER, evenement TEXT NOT NULL, role TEXT,
            auteur_id INTEGER, auteur_nom TEXT, date_evenement TEXT NOT NULL,
            details TEXT,
            FOREIGN KEY(version_id) REFERENCES fiches_versions(id)
        )
    """)
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_fiches_evenements_mois
                    ON fiches_evenements(user_id, annee, mois, id)""")
    _installer_suivi_sources(conn)
    actualiser_versions(conn)


def _installer_suivi_sources(conn):
    """SQLite repère les salariés affectés, même via un nouveau producteur SQL.

    La file fait partie de la transaction : un rollback retire aussi ses entrées.
    Les changements de calendrier collectif concernent toutes les fiches signées.
    """
    conn.execute('CREATE TABLE IF NOT EXISTS fiches_a_recalculer (user_id INTEGER PRIMARY KEY)')
    tables = ('heures_reelles', 'planning_theorique', 'alternance_reference',
              'contrats', 'absences', 'variables_paie', 'users', 'validations',
              'periodes_vacances', 'jours_feries')
    for table in tables:
        for operation in ('INSERT', 'UPDATE', 'DELETE'):
            if table in ('periodes_vacances', 'jours_feries'):
                requetes = ['INSERT OR IGNORE INTO fiches_a_recalculer SELECT DISTINCT user_id FROM validations;']
            else:
                champ = 'id' if table == 'users' else 'user_id'
                lignes = ('NEW',) if operation == 'INSERT' else ('OLD',) if operation == 'DELETE' else ('OLD', 'NEW')
                requetes = [f'INSERT OR IGNORE INTO fiches_a_recalculer VALUES ({ligne}.{champ});'
                            for ligne in lignes]
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS fiche_source_{table}_{operation.lower()}
                AFTER {operation} ON {table} BEGIN {' '.join(requetes)} END""")


def serialiser(contenu):
    return json.dumps(contenu, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False,
                      default=lambda value: value.isoformat())


def empreinte(contenu):
    return hashlib.sha256(serialiser(contenu).encode('utf-8')).hexdigest()


def contenu_version(conn, version_id):
    row = conn.execute('SELECT contenu FROM fiches_versions WHERE id=?', (version_id,)).fetchone()
    if row is None:
        raise ValueError('La référence de la fiche est introuvable.')
    contenu = json.loads(row['contenu'])
    for jour in contenu['journees']:
        jour['date_obj'] = datetime.fromisoformat(jour['date_obj'])
    return contenu


def evenement(conn, user_id, annee, mois, type_evenement, version_id=None,
              role=None, auteur_id=None, auteur_nom=None, details=None):
    # Hors requête (migration/tests/CLI), l'auteur reste explicitement inconnu.
    from flask import has_request_context, session
    if auteur_id is None and has_request_context():
        auteur_id = session.get('user_id')
    if auteur_nom is None and auteur_id is not None:
        user = conn.execute('SELECT prenom, nom FROM users WHERE id=?', (auteur_id,)).fetchone()
        if user:
            auteur_nom = f"{user['prenom']} {user['nom']}"
    conn.execute("""
        INSERT INTO fiches_evenements
        (user_id, annee, mois, version_id, evenement, role, auteur_id, auteur_nom,
         date_evenement, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, annee, mois, version_id, type_evenement, role, auteur_id,
          auteur_nom, maintenant().isoformat(timespec='microseconds'),
          json.dumps(details, ensure_ascii=False) if details is not None else None))


def enregistrer_version(conn, contenu, origine):
    user_id, annee, mois = (contenu[k] for k in ('user_id', 'annee', 'mois'))
    derniere = conn.execute("""
        SELECT id, numero, empreinte FROM fiches_versions
        WHERE user_id=? AND annee=? AND mois=? ORDER BY numero DESC LIMIT 1
    """, (user_id, annee, mois)).fetchone()
    digest = empreinte(contenu)
    if derniere and derniere['empreinte'] == digest:
        return derniere['id']
    numero = derniere['numero'] + 1 if derniere else 1
    cur = conn.execute("""
        INSERT INTO fiches_versions
        (user_id, annee, mois, numero, empreinte, contenu, origine, cree_le)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, annee, mois, numero, digest, serialiser(contenu), origine,
          maintenant().isoformat(timespec='microseconds')))
    return cur.lastrowid


def actualiser_versions(conn, user_ids=None):
    """Contrôle final AVANT commit, avec toutes les écritures déjà visibles.

    Le verrou d'écriture SQLite reste détenu jusqu'au commit : une autre
    signature ou modification ne peut s'intercaler. Seules les fiches ayant
    déjà une validation nécessitent ce contrôle ; le contenu non signé n'est
    pas historisé à chaque frappe.
    """
    sql, params = 'SELECT * FROM validations', ()
    if user_ids is not None:
        if not user_ids:
            return
        sql += ' WHERE user_id IN (' + ','.join('?' for _ in user_ids) + ')'
        params = tuple(user_ids)
    rows = conn.execute(sql + ' ORDER BY user_id, annee, mois', params).fetchall()
    for row in rows:
        v = dict(row)
        contenu = calculer_contenu(conn, v['user_id'], v['mois'], v['annee'])
        precedente = conn.execute(
            'SELECT empreinte FROM fiches_versions WHERE id=?',
            (v['version_courante_id'],),
        ).fetchone()
        if precedente and precedente['empreinte'] == empreinte(contenu):
            continue
        if precedente and v['bloque']:
            nom = f"{contenu['identite']['prenom']} {contenu['identite']['nom']}"
            raise FicheVerrouillee(
                f"La fiche de {nom} ({v['mois']:02d}/{v['annee']}) est verrouillée. "
                "Aucune modification n'a été enregistrée. La direction doit "
                "d'abord la réouvrir avec un motif, puis la faire signer à nouveau."
            )
        if v['version_courante_id'] and not precedente:
            raise ValueError('Référence de fiche manquante : opération annulée.')
        origine = 'modification' if precedente else 'reprise_historique'
        version_id = enregistrer_version(conn, contenu, origine)
        conn.execute('UPDATE validations SET version_courante_id=? WHERE id=?',
                     (version_id, v['id']))
        details = {'version_precedente_id': v['version_courante_id']}
        if not precedente:
            details['limite'] = "État constaté à la reprise ; contenu anciennement signé non vérifiable."
            details['signatures_anterieures'] = [
                {'role': role, 'nom': v[f'validation_{role}'], 'date': v[f'date_{role}']}
                for role in ROLES if v[f'validation_{role}']
            ]
        evenement(conn, v['user_id'], v['annee'], v['mois'], origine,
                  version_id=version_id, details=details)


def lire_contenu(conn, user_id, mois, annee, aujourdhui=None):
    v = conn.execute(
        'SELECT bloque, version_courante_id FROM validations WHERE user_id=? AND mois=? AND annee=?',
        (user_id, mois, annee),
    ).fetchone()
    if v and v['bloque'] and v['version_courante_id']:
        return contenu_version(conn, v['version_courante_id'])
    kwargs = {'aujourdhui': aujourdhui} if aujourdhui is not None else {}
    return calculer_contenu(conn, user_id, mois, annee, **kwargs)


def presenter_validation(row):
    """Les anciens noms restent en base ; seuls les accords actuels sont cochés."""
    if row is None:
        return None
    v = dict(row)
    v['signatures_obsoletes'] = []
    v['historique_non_versionne'] = False
    verrou_historique = (v['bloque'] and v.get('version_directeur_id') is None
                        and v.get('version_responsable_id') is None)
    for role in ROLES:
        nom = v[f'validation_{role}']
        version = v.get(f'version_{role}_id')
        actuelle = bool(version and version == v.get('version_courante_id'))
        if nom and not actuelle:
            if verrou_historique and version is None:
                v['historique_non_versionne'] = True
            else:
                v['signatures_obsoletes'].append(
                    {'role': role, 'nom': nom, 'date': v[f'date_{role}']})
                v[f'validation_{role}'] = None
                v[f'date_{role}'] = None
    return v
