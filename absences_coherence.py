"""Provenance et intégrité des projections d'absences/récupérations.

Pas de commit ici : décision, compteurs, projection et preuve sont atomiques.
Les anciennes ambiguïtés sont signalées, jamais arbitrées à la migration.
"""
import json
from datetime import date


class ConflitAbsence(ValueError):
    """Une opération détruirait une autre absence ou une récupération appliquée."""


CALENDRIERS = ('heures_reelles', 'presence_forfait_jour')


def creer_schema(conn):
    colonnes = {r[1] for r in conn.execute('PRAGMA table_info(absences)')}
    if 'demande_conge_id' not in colonnes:
        conn.execute('ALTER TABLE absences ADD COLUMN demande_conge_id INTEGER REFERENCES demandes_conges(id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_absences_periode ON absences(user_id, date_debut, date_fin)')
    conn.execute('''CREATE TABLE IF NOT EXISTS rh_projections (
        user_id INTEGER NOT NULL, date TEXT NOT NULL, calendrier TEXT NOT NULL,
        absence_id INTEGER, demande_recup_id INTEGER, contenu TEXT NOT NULL,
        PRIMARY KEY(user_id, date, calendrier),
        CHECK ((absence_id IS NULL) != (demande_recup_id IS NULL)))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS rh_projections_a_verifier (
        user_id INTEGER NOT NULL, date TEXT NOT NULL, calendrier TEXT NOT NULL,
        PRIMARY KEY(user_id, date, calendrier))''')
    for table in CALENDRIERS:
        for op in ('INSERT', 'UPDATE', 'DELETE'):
            refs = ('OLD', 'NEW') if op == 'UPDATE' else (('OLD',) if op == 'DELETE' else ('NEW',))
            corps = ''.join(f"INSERT OR IGNORE INTO rh_projections_a_verifier VALUES ({ref}.user_id, {ref}.date, '{table}');" for ref in refs)
            conn.execute(f'CREATE TRIGGER IF NOT EXISTS coherence_{table}_{op.lower()} AFTER {op} ON {table} BEGIN {corps} END')


def _contenu(row):
    # L'identifiant technique change avec INSERT OR REPLACE, pas le contenu.
    return json.dumps({k: row[k] for k in row.keys() if k != 'id'}, sort_keys=True, ensure_ascii=False)


def memoriser_projection(conn, calendrier, uid, jour, absence_id=None, demande_recup_id=None):
    assert calendrier in CALENDRIERS
    row = conn.execute(f'SELECT * FROM {calendrier} WHERE user_id=? AND date=?', (uid, jour)).fetchone()
    conn.execute('''INSERT OR REPLACE INTO rh_projections
        (user_id,date,calendrier,absence_id,demande_recup_id,contenu) VALUES (?,?,?,?,?,?)''',
        (uid, jour, calendrier, absence_id, demande_recup_id, _contenu(row)))


def verifier_projections(conn):
    for p in conn.execute('''SELECT p.* FROM rh_projections_a_verifier q
            JOIN rh_projections p USING(user_id,date,calendrier)''').fetchall():
        table = p['calendrier']
        if table not in CALENDRIERS:
            raise ConflitAbsence('Origine de calendrier invalide ; une revue est nécessaire.')
        row = conn.execute(f'SELECT * FROM {table} WHERE user_id=? AND date=?', (p['user_id'], p['date'])).fetchone()
        if not row or _contenu(row) != p['contenu']:
            raise ConflitAbsence("Cette journée provient d'une absence ou d'une récupération validée. Corrigez son origine avant de modifier le calendrier.")
    # Une ancienne projection n'a pas de preuve structurée. Si une route
    # touche cette journée, elle ne peut effacer l'absence encore active.
    anciennes = conn.execute("""SELECT DISTINCT q.user_id,q.date,q.calendrier
        FROM rh_projections_a_verifier q JOIN absences a ON a.user_id=q.user_id
        AND a.date_debut<=q.date AND a.date_fin>=q.date
        LEFT JOIN rh_projections p USING(user_id,date,calendrier)
        WHERE p.user_id IS NULL""").fetchall()
    for q in anciennes:
        table = q['calendrier']
        if table not in CALENDRIERS:
            raise ConflitAbsence('Origine de calendrier invalide.')
        row = conn.execute(f'SELECT * FROM {table} WHERE user_id=? AND date=?', (q['user_id'], q['date'])).fetchone()
        motifs = conn.execute('SELECT id,motif FROM absences WHERE user_id=? AND date_debut<=? AND date_fin>=?', (q['user_id'], q['date'], q['date'])).fetchall()
        commentaires = {f"Absence #{a['id']} - {a['motif']}" for a in motifs}
        # Les week-ends/fériés ne portent pas de projection d'absence.
        if date.fromisoformat(q['date']).weekday() >= 5 or conn.execute('SELECT 1 FROM jours_feries WHERE date=?', (q['date'],)).fetchone():
            continue
        if not row or row['commentaire'] not in commentaires:
            raise ConflitAbsence("Une absence historique couvre encore cette journée. Corrigez son origine avant de modifier le calendrier.")
    conn.execute('DELETE FROM rh_projections_a_verifier')


def verifier_disponibilite(conn, uid, debut, fin):
    try:
        normalisees = (date.fromisoformat(debut).isoformat(), date.fromisoformat(fin).isoformat())
    except (TypeError, ValueError):
        raise ConflitAbsence('Dates de la demande invalides. Corrigez la demande avant validation.') from None
    if normalisees != (debut, fin) or debut > fin:
        raise ConflitAbsence('Dates de la demande non normalisées. Corrigez la demande avant validation.')
    absence = conn.execute('''SELECT id,motif,date_debut,date_fin FROM absences
        WHERE user_id=? AND date_debut<=? AND date_fin>=?
        ORDER BY date_debut,id LIMIT 1''', (uid, fin, debut)).fetchone()
    if absence:
        raise ConflitAbsence(f"Conflit avec l'absence n°{absence['id']} ({absence['motif']}, du {absence['date_debut']} au {absence['date_fin']}). Corrigez d'abord l'absence existante ; aucun remplacement automatique n'est effectué.")
    # Inclut les récupérations historiques, même sans provenance structurée.
    recup = conn.execute('''SELECT id FROM demandes_recup WHERE user_id=?
        AND statut='validee' AND date_debut<=? AND date_fin>=? LIMIT 1''', (uid, fin, debut)).fetchone()
    if recup:
        raise ConflitAbsence("Une récupération validée couvre déjà cette période. Aucun cumul ni remplacement automatique n'est possible.")
    ligne = conn.execute('''SELECT 1 FROM heures_reelles WHERE user_id=? AND date BETWEEN ? AND ?
        AND type_saisie IN ('recup_journee','recup_partielle') LIMIT 1''', (uid, debut, fin)).fetchone()
    if ligne:
        raise ConflitAbsence("Une récupération figure déjà au calendrier sur cette période.")


def conflits_historiques(conn, uid=None):
    """Détection bornée par salarié sur la page Absences, sans réparation."""
    return conn.execute('''SELECT a.id AS premiere, b.id AS seconde, a.user_id,
        a.date_debut, a.date_fin FROM absences a JOIN absences b
        ON a.user_id=b.user_id AND a.id<b.id
        AND a.date_debut<=b.date_fin AND b.date_debut<=a.date_fin
        WHERE (? IS NULL OR a.user_id=?) ORDER BY a.user_id,a.id LIMIT 100''', (uid, uid)).fetchall()


def retirer_projection(conn, absence_id, uid, debut, fin):
    """Retire uniquement la source visée et restaure une source restante unique.

    Sur les données antérieures, l'égalité du commentaire COMPLET évite la
    confusion #1/#10. Plusieurs sources restantes : refus et revue explicite.
    """
    from blueprints.absences import _reporter_absence_sur_calendrier
    absence = conn.execute('SELECT motif FROM absences WHERE id=?', (absence_id,)).fetchone()
    commentaire = f"Absence #{absence_id} - {absence['motif']}"
    restaurations = []
    for table in CALENDRIERS:
        rows = conn.execute(f'''SELECT c.date FROM {table} c LEFT JOIN rh_projections p
            ON p.user_id=c.user_id AND p.date=c.date AND p.calendrier=?
            WHERE c.user_id=? AND c.date BETWEEN ? AND ?
              AND (p.absence_id=? OR (p.user_id IS NULL AND c.commentaire=?))''',
            (table, uid, debut, fin, absence_id, commentaire)).fetchall()
        for row in rows:
            jour = row['date']
            restantes = conn.execute('''SELECT * FROM absences WHERE user_id=? AND id!=?
                AND date_debut<=? AND date_fin>=? ORDER BY id''', (uid, absence_id, jour, jour)).fetchall()
            if len(restantes) > 1:
                raise ConflitAbsence("Plusieurs absences historiques resteraient sur cette journée. Une revue des origines est nécessaire avant suppression.")
            conn.execute('DELETE FROM rh_projections WHERE user_id=? AND date=? AND calendrier=?', (uid, jour, table))
            if restantes:
                r = restantes[0]
                _reporter_absence_sur_calendrier(conn, r['id'], uid, jour, jour, r['motif'])
                restaurations.append({'date': jour, 'absence_id': r['id'], 'calendrier': table})
            elif table == 'heures_reelles':
                conn.execute('DELETE FROM heures_reelles WHERE user_id=? AND date=?', (uid, jour))
            else:
                conn.execute('''UPDATE presence_forfait_jour SET type_journee='travaille', commentaire=NULL,
                    matin_debut=NULL,matin_fin=NULL,aprem_debut=NULL,aprem_fin=NULL WHERE user_id=? AND date=?''', (uid, jour))
    return restaurations
