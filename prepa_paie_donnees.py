"""Données réellement présentées à la préparation de paie et preuve de vérification."""
import hashlib
import json
from calendar import monthrange
from flask import current_app
from itsdangerous import URLSafeSerializer

MOTIFS_ABSENCE_PAIE = [
    'Arrêt maladie', 'Congé payé', 'Congé conventionnel', 'Congé parental',
    'Jour enfant malade', 'Accident du travail', 'Evènement familial', 'Sans solde',
    'Mi-temps thérapeutique', 'Forfait jour', 'Autre',
]


def donnees_salarie(conn, uid, mois, annee):
    debut = f'{annee:04d}-{mois:02d}-01'
    fin = f'{annee:04d}-{mois:02d}-{monthrange(annee, mois)[1]:02d}'
    sal = conn.execute('''SELECT u.nom,u.prenom,COALESCE(s.nom,'') secteur FROM users u
        LEFT JOIN secteurs s ON s.id=u.secteur_id WHERE u.id=?''', (uid,)).fetchone()
    contrats = conn.execute('''SELECT id,type_contrat,date_debut,date_fin,forfait,nbr_jours,
        temps_hebdo,fichier_path,fichier_nom FROM contrats WHERE user_id=? AND date_debut<=?
        AND (date_fin IS NULL OR date_fin>=?) ORDER BY date_debut DESC,id''', (uid, fin, debut)).fetchall()
    placeholders = ','.join('?' for _ in MOTIFS_ABSENCE_PAIE)
    absences = conn.execute(f'''SELECT id,motif,date_debut,date_fin,date_reprise,commentaire,
        jours_ouvres,justificatif_path FROM absences WHERE user_id=? AND motif IN ({placeholders})
        AND date_debut<=? AND date_fin>=? ORDER BY date_debut,id''', (uid, *MOTIFS_ABSENCE_PAIE, fin, debut)).fetchall()
    row = conn.execute('SELECT * FROM variables_paie WHERE user_id=? AND mois=? AND annee=?', (uid, mois, annee)).fetchone()
    vp = dict(row) if row else {}
    d = dict(sal) if sal else {'nom': '', 'prenom': '', 'secteur': ''}
    d.update(user_id=uid, contrats=[dict(c) for c in contrats], absences=[dict(a) for a in absences],
             mutuelle=int(vp.get('mutuelle') or 0), nb_enfants=vp.get('nb_enfants') or 0,
             heures_reelles=vp.get('heures_reelles'), heures_supps=vp.get('heures_supps'),
             commentaire=vp.get('commentaire') or '')
    for k in ('transport', 'acompte', 'saisie_salaire', 'pret_avance', 'autres_regularisation'):
        d[k] = float(vp.get(k) or 0)
    return d


def empreinte(donnees):
    return hashlib.sha256(json.dumps(donnees, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def reference(donnees, mois, annee, statut):
    return URLSafeSerializer(current_app.secret_key, salt='verification-paie-v1').dumps(
        [donnees['user_id'], mois, annee, empreinte(donnees), statut.get('revision', 0)])


def creer_schema(conn):
    colonnes = {r[1] for r in conn.execute('PRAGMA table_info(prepa_paie_statut)')}
    premiere = 'empreinte_verifiee' not in colonnes
    for nom, type_sql in (('empreinte_verifiee','TEXT'), ('verifie_le','TEXT'), ('modifie_le','TEXT'), ('revision','INTEGER NOT NULL DEFAULT 0')):
        if nom not in colonnes:
            conn.execute(f'ALTER TABLE prepa_paie_statut ADD COLUMN {nom} {type_sql}')
    if premiere:
        # La dernière vérification est connue, les données alors vues ne le sont pas.
        conn.execute('''UPDATE prepa_paie_statut SET verifie_le=updated_at, traite=0
            WHERE traite=1''')
    conn.execute("""CREATE TABLE IF NOT EXISTS paie_a_recalculer (
        user_id INTEGER NOT NULL,mois INTEGER NOT NULL,annee INTEGER NOT NULL,
        PRIMARY KEY(user_id,mois,annee))""")
    for table in ('users', 'secteurs', 'contrats', 'absences', 'variables_paie'):
        for op in ('INSERT', 'UPDATE', 'DELETE'):
            refs = ('OLD', 'NEW') if op == 'UPDATE' else (('OLD',) if op == 'DELETE' else ('NEW',))
            requetes = []
            for ref in refs:
                if table == 'secteurs':
                    condition = f'p.user_id IN (SELECT id FROM users WHERE secteur_id={ref}.id)'
                else:
                    champ = 'id' if table == 'users' else 'user_id'
                    condition = f'p.user_id={ref}.{champ}'
                if table in ('absences', 'contrats'):
                    condition += f" AND {ref}.date_debut<=date(printf('%04d-%02d-01',p.annee,p.mois),'+1 month','-1 day') AND ({ref}.date_fin IS NULL OR {ref}.date_fin>=printf('%04d-%02d-01',p.annee,p.mois))"
                elif table == 'variables_paie':
                    condition += f' AND p.mois={ref}.mois AND p.annee={ref}.annee'
                requetes.append(f'INSERT OR IGNORE INTO paie_a_recalculer SELECT p.user_id,p.mois,p.annee FROM prepa_paie_statut p WHERE {condition};')
            corps = ''.join(requetes)
            conn.execute(f'CREATE TRIGGER IF NOT EXISTS paie_{table}_{op.lower()} AFTER {op} ON {table} BEGIN {corps} END')


def actualiser_statuts(conn):
    rows = conn.execute('''SELECT p.* FROM paie_a_recalculer q JOIN prepa_paie_statut p USING(user_id,mois,annee)
        WHERE p.traite=1 AND p.empreinte_verifiee IS NOT NULL''').fetchall()
    for row in rows:
        d = donnees_salarie(conn, row['user_id'], row['mois'], row['annee'])
        if empreinte(d) != row['empreinte_verifiee']:
            from access_log import journaliser_action, ACTION_PREPA_PAIE_OBSOLETE
            journaliser_action(conn, ACTION_PREPA_PAIE_OBSOLETE, cible_type='user',
                cible_id=row['user_id'], details=f"mois={row['mois']}/{row['annee']} ; vérification antérieure conservée")
            conn.execute('''UPDATE prepa_paie_statut SET traite=0,modifie_le=CURRENT_TIMESTAMP,
                revision=revision+1 WHERE id=?''', (row['id'],))
    conn.execute('DELETE FROM paie_a_recalculer')
