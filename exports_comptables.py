"""Preuves des exports TXT : fichier et lignes conservés dans le même commit.

Les helpers ne commitent jamais. Les décisions HTTP prennent BEGIN IMMEDIATE
avant de relire droits, sélection et contenu. Aucun ancien export n'est reconstruit.
"""
import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import current_app, session
from itsdangerous import BadSignature, URLSafeSerializer


class ExportRefuse(ValueError):
    """Refus métier, sans modification de l'export ni des écritures."""


COLONNES_METIER = (
    'facture_id', 'date_ecriture', 'compte', 'libelle', 'numero_facture',
    'debit', 'credit', 'code_analytique', 'echeance',
)
COLONNES_TXT = ('Journal', 'Date', 'Compte / auxiliaire', 'Libellé',
                'Référence facture', 'Débit', 'Crédit', 'Analytique', 'Échéance')


def creer_schema(conn):
    """Migration 0069 et init_db ; les marqueurs historiques sont posés une fois."""
    ajouts = {
        'ecritures_comptables': {'revision': 'INTEGER NOT NULL DEFAULT 1',
                                'export_historique': 'INTEGER NOT NULL DEFAULT 0'},
        'factures': {'archivee': 'INTEGER NOT NULL DEFAULT 0'},
        'archives_export': {
            'preuve_version': 'INTEGER NOT NULL DEFAULT 0',
            'contenu': 'BLOB', 'empreinte': 'TEXT', 'format': 'TEXT',
            'total_debit_centimes': 'INTEGER', 'total_credit_centimes': 'INTEGER',
            'auteur_nom': 'TEXT',
        },
    }
    for table, colonnes in ajouts.items():
        presentes = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
        for colonne, definition in colonnes.items():
            if colonne not in presentes:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {colonne} {definition}')
                if colonne == 'export_historique':
                    conn.execute("UPDATE ecritures_comptables SET export_historique=1 WHERE statut='exportee'")
    conn.execute('''CREATE TABLE IF NOT EXISTS export_lignes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        archive_id INTEGER NOT NULL REFERENCES archives_export(id),
        ecriture_id INTEGER NOT NULL UNIQUE,
        facture_id INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        position INTEGER NOT NULL,
        contenu TEXT NOT NULL,
        UNIQUE(archive_id, position)
    )''')
    # Pas de cascade vers les sources : une preuve doit rester autonome.
    conn.execute('''CREATE TABLE IF NOT EXISTS comptabilite_evenements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        archive_id INTEGER,
        ecriture_id INTEGER,
        facture_id INTEGER,
        user_id INTEGER,
        auteur_nom TEXT NOT NULL,
        details TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_export_lignes_facture ON export_lignes(facture_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_ecritures_facture ON ecritures_comptables(facture_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_compta_evenements_archive ON comptabilite_evenements(archive_id, id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_compta_evenements_facture ON comptabilite_evenements(facture_id, id)')
    for table in ('archives_export', 'export_lignes', 'comptabilite_evenements'):
        for operation in ('UPDATE', 'DELETE'):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS preuve_{table}_{operation.lower()}
                BEFORE {operation} ON {table} BEGIN
                SELECT RAISE(ABORT, 'Preuve comptable immuable'); END''')
    changements = ' OR '.join(f'OLD.{c} IS NOT NEW.{c}' for c in COLONNES_METIER)
    for operation in ('UPDATE', 'DELETE'):
        condition = '' if operation == 'DELETE' else (
            f"AND (OLD.statut!='validee' OR NEW.statut!='exportee' OR "
            f"OLD.revision IS NOT NEW.revision OR {changements})")
        conn.execute(f'''CREATE TRIGGER IF NOT EXISTS ecriture_exportee_{operation.lower()}
            BEFORE {operation} ON ecritures_comptables
            WHEN OLD.statut='exportee' OR EXISTS (
                SELECT 1 FROM export_lignes WHERE ecriture_id=OLD.id)
            {condition}
            BEGIN SELECT RAISE(ABORT, 'Ecriture exportee immuable'); END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS ecriture_export_preuve
        BEFORE UPDATE OF statut ON ecritures_comptables
        WHEN NEW.statut='exportee' AND NOT EXISTS (
            SELECT 1 FROM export_lignes WHERE ecriture_id=NEW.id AND revision=NEW.revision)
        BEGIN SELECT RAISE(ABORT, 'Preuve export manquante'); END''')
    conn.execute(f'''CREATE TRIGGER IF NOT EXISTS ecriture_revision
        AFTER UPDATE ON ecritures_comptables WHEN {changements}
        BEGIN UPDATE ecritures_comptables
            SET revision=OLD.revision+1, statut='brouillon', updated_at=CURRENT_TIMESTAMP
            WHERE id=NEW.id; END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS facture_exportee_conserver
        BEFORE DELETE ON factures WHEN EXISTS (
            SELECT 1 FROM ecritures_comptables WHERE facture_id=OLD.id AND statut='exportee')
        OR EXISTS (SELECT 1 FROM export_lignes WHERE facture_id=OLD.id)
        BEGIN SELECT RAISE(ABORT, 'Facture exportee a archiver'); END''')
    for operation in ('UPDATE', 'DELETE'):
        conn.execute(f'''CREATE TRIGGER IF NOT EXISTS historique_facture_exportee_{operation.lower()}
            BEFORE {operation} ON facture_historique WHEN EXISTS (
                SELECT 1 FROM ecritures_comptables WHERE facture_id=OLD.facture_id AND statut='exportee')
            OR EXISTS (SELECT 1 FROM export_lignes WHERE facture_id=OLD.facture_id)
            BEGIN SELECT RAISE(ABORT, 'Historique comptable a conserver'); END''')


def canonique(data):
    # L'ancien éditeur acceptait float('inf'). Garder ces valeurs identifiables
    # dans une référence ou un événement, sans bloquer la page ni les confondre
    # avec zéro. colonnes_txt les refuse toujours avant tout nouvel export.
    def normaliser(value):
        if isinstance(value, float) and not math.isfinite(value):
            return {'nombre_non_fini': str(value)}
        if isinstance(value, dict):
            return {k: normaliser(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normaliser(v) for v in value]
        return value
    return json.dumps(normaliser(data), sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def empreinte(data):
    return hashlib.sha256(canonique(data).encode('utf-8')).hexdigest()


def source_facture(conn, facture_id):
    row = conn.execute('''SELECT f.id, f.fournisseur_id, f.numero_facture, f.date_facture,
        f.date_echeance, f.montant_ttc, f.description, f.statut, f.archivee,
        f.secteur_id, f.fichier_nom, fr.nom AS fournisseur_nom, fr.code_comptable
        FROM factures f LEFT JOIN fournisseurs fr ON fr.id=f.fournisseur_id
        WHERE f.id=?''', (facture_id,)).fetchone()
    if not row:
        raise ExportRefuse('Facture source introuvable. Rechargez la page.')
    return dict(row)


def contenu_ecriture(row, source):
    return {'ecriture': {c: row[c] for c in ('id', *COLONNES_METIER, 'revision', 'statut')},
            'source': source}


def reference(row, source):
    return URLSafeSerializer(current_app.secret_key, salt='ecriture-comptable-v1').dumps(
        [session['user_id'], row['id'], empreinte(contenu_ecriture(row, source))])


def verifier_reference(token, row, source):
    try:
        valeur = URLSafeSerializer(current_app.secret_key, salt='ecriture-comptable-v1').loads(token or '')
    except BadSignature:
        raise ExportRefuse('Référence de la page absente ou invalide. Rechargez la page.') from None
    if valeur != [session['user_id'], row['id'], empreinte(contenu_ecriture(row, source))]:
        raise ExportRefuse('Le contenu ou son état a changé. Rechargez la page avant de continuer.')


def identifiants(valeurs):
    if not valeurs or len(valeurs) > 5000:
        raise ExportRefuse('Sélectionnez entre 1 et 5 000 écritures.')
    try:
        ids = [int(v) for v in valeurs]
    except (ValueError, TypeError):
        raise ExportRefuse('Sélection invalide. Rechargez la page.') from None
    if len(set(ids)) != len(ids) or any(i <= 0 or i > 9223372036854775807 for i in ids):
        raise ExportRefuse('Sélection invalide ou contenant des doublons.')
    return ids


def montant_centimes(valeur):
    try:
        nombre = Decimal(str(valeur or 0))
        if not nombre.is_finite() or nombre < 0 or nombre > Decimal('999999999999.99'):
            raise ValueError
        if nombre != nombre.quantize(Decimal('0.01')):
            raise ValueError
        return int(nombre * 100)
    except (InvalidOperation, ValueError):
        raise ExportRefuse('Les montants doivent être positifs ou nuls, avec au plus deux décimales.') from None


def texte_champ(valeur):
    valeur = str(valeur or '')
    if any(ord(c) < 32 or ord(c) == 127 for c in valeur):
        raise ExportRefuse('Une colonne contient une tabulation ou un caractère de contrôle. Corrigez-la.')
    return valeur


def colonnes_txt(row):
    try:
        date = datetime.strptime(row['date_ecriture'], '%Y-%m-%d')
        if date.strftime('%Y-%m-%d') != row['date_ecriture']:
            raise ValueError
        echeance = row['echeance'] or ''
        if echeance and datetime.strptime(echeance, '%d%m%Y').strftime('%d%m%Y') != echeance:
            raise ValueError
    except (TypeError, ValueError):
        raise ExportRefuse('Date comptable ou échéance invalide. Corrigez l’écriture avant export.') from None
    debit, credit = montant_centimes(row['debit']), montant_centimes(row['credit'])
    if not (debit > 0) ^ (credit > 0):
        raise ExportRefuse('Chaque ligne doit comporter un débit ou un crédit, exclusivement.')
    if not row['compte'].strip() or not row['libelle'].strip():
        raise ExportRefuse('Compte et libellé sont obligatoires.')
    def montant(cents):
        return f'{cents // 100}.{cents % 100:02d}' if cents else ''
    return [texte_champ(v) for v in (
        'AC', date.strftime('%d%m%Y'), row['compte'], row['libelle'].upper(),
        row['numero_facture'], montant(debit), montant(credit), row['code_analytique'], echeance)]


def selection_export(conn, ids, formulaire):
    rows = []
    sources = {}
    for eid in ids:
        row = conn.execute('SELECT * FROM ecritures_comptables WHERE id=?', (eid,)).fetchone()
        if not row or row['statut'] != 'validee':
            raise ExportRefuse('Toutes les écritures sélectionnées doivent exister et être validées, sans export antérieur.')
        fid = row['facture_id']
        if fid not in sources:
            sources[fid] = source_facture(conn, fid)
        if sources[fid]['archivee']:
            raise ExportRefuse('Une facture archivée ne peut pas être exportée.')
        verifier_reference(formulaire.get(f'reference_{eid}'), row, sources[fid])
        rows.append(row)
    selection = set(ids)
    for fid in sources:
        toutes = conn.execute('SELECT id, statut FROM ecritures_comptables WHERE facture_id=?', (fid,)).fetchall()
        if {r['id'] for r in toutes} - selection:
            raise ExportRefuse('Sélectionnez la pièce complète : toutes les lignes de chaque facture doivent être validées et sélectionnées. Une pièce historiquement partielle nécessite une correction explicite.')
    rows.sort(key=lambda r: (r['date_ecriture'], r['id']))
    lignes, totaux = [], {}
    for row in rows:
        colonnes = colonnes_txt(row)
        debit, credit = montant_centimes(row['debit']), montant_centimes(row['credit'])
        balance = totaux.setdefault(row['facture_id'], [0, 0])
        balance[0] += debit
        balance[1] += credit
        lignes.append({**contenu_ecriture(row, sources[row['facture_id']]), 'colonnes': colonnes})
    if any(d != c for d, c in totaux.values()):
        raise ExportRefuse('Chaque pièce doit être équilibrée : le total débit doit égaler le total crédit.')
    return lignes, sum(d for d, _ in totaux.values()), sum(c for _, c in totaux.values())


def evenement(conn, action, details, *, archive_id=None, ecriture_id=None, facture_id=None):
    conn.execute('''INSERT INTO comptabilite_evenements
        (action, archive_id, ecriture_id, facture_id, user_id, auteur_nom, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (action, archive_id, ecriture_id, facture_id, session['user_id'],
         f"{session.get('prenom', '')} {session.get('nom', '')}".strip(), canonique(details)))


def presenter_evenements(rows):
    libelles = {
        'export': 'Export du fichier', 'retelechargement': 'Nouveau téléchargement du fichier déjà exporté',
        'modification_refusee': 'Modification après export refusée',
        'suppression_facture_refusee': 'Suppression de la source refusée',
        'suppression_archive_refusee': 'Suppression de l’archive refusée',
        'correction_signalee': 'Correction après export signalée',
        'archivage_facture': 'Facture archivée', 'validation': 'Validation de l’écriture',
        'modification': 'Modification et retour en brouillon', 'suppression_facture': 'Facture supprimée',
    }
    return [{**dict(r), 'libelle': libelles.get(r['action'], r['action']),
             'details': json.loads(r['details'])} for r in rows]


def facture_exportee(conn, facture_id):
    return bool(conn.execute('''SELECT 1 FROM ecritures_comptables
        WHERE facture_id=? AND statut='exportee' UNION ALL
        SELECT 1 FROM export_lignes WHERE facture_id=? LIMIT 1''', (facture_id, facture_id)).fetchone())
