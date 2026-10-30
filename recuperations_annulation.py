"""Retrait daté des récupérations, sans commit ni saisie de travail fictif."""
import json
from datetime import date, timedelta

from absences_coherence import ConflitAbsence, _contenu
from fiches_versions import FicheVerrouillee
from utils import maintenant


def creer_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS recup_annulations (
        demande_recup_id INTEGER NOT NULL REFERENCES demandes_recup(id),
        date TEXT NOT NULL, nb_heures REAL NOT NULL,
        auteur_id INTEGER NOT NULL REFERENCES users(id),
        date_annulation TEXT NOT NULL, motif TEXT NOT NULL, absence_id INTEGER,
        PRIMARY KEY(demande_recup_id,date))''')


def jours_recuperation(demande):
    debut, fin = date.fromisoformat(demande['date_debut']), date.fromisoformat(demande['date_fin'])
    if debut > fin:
        raise ConflitAbsence('Période de récupération invalide.')
    jours = []
    while debut <= fin:
        # Même périmètre que le report historique des récupérations complètes.
        if debut.weekday() < 5:
            jours.append(debut.isoformat())
        debut += timedelta(days=1)
    return jours


def annuler_recuperation(conn, demande, debut, fin, auteur_id, motif, absence_id=None):
    """Retire seulement les projections identifiées ; transaction de l'appelant."""
    from utils import get_type_periode, get_planning_valide_a_date, get_heures_theoriques_jour

    if demande['statut'] not in ('validee', 'annulee'):
        raise ConflitAbsence('Seule une récupération validée peut être annulée.')
    if not motif or not motif.strip() or len(motif.strip()) > 1000:
        raise ConflitAbsence('Un motif de 1 à 1 000 caractères est obligatoire.')
    try:
        if date.fromisoformat(debut).isoformat()!=debut or date.fromisoformat(fin).isoformat()!=fin or debut>fin:
            raise ValueError
    except (TypeError,ValueError):
        raise ConflitAbsence('Période d’annulation invalide.') from None
    if debut<demande['date_debut'] or fin>demande['date_fin']:
        raise ConflitAbsence('La période à annuler doit être comprise dans la récupération.')
    did, uid = demande['id'], demande['user_id']
    annules = {r[0] for r in conn.execute('SELECT date FROM recup_annulations WHERE demande_recup_id=?',(did,))}
    jours = jours_recuperation(demande)
    cibles = [j for j in jours if debut<=j<=fin and j not in annules]
    if demande['statut']=='annulee' or not cibles:
        return []
    now = maintenant().strftime('%Y-%m-%d %H:%M:%S')
    details = []
    for jour in cibles:
        v = conn.execute('SELECT bloque FROM validations WHERE user_id=? AND annee=? AND mois=?',
                         (uid,int(jour[:4]),int(jour[5:7]))).fetchone()
        if v and v['bloque']:
            raise FicheVerrouillee('Un mois concerné est verrouillé. La direction doit le réouvrir avec un motif avant cette correction.')
        concurrente = conn.execute('''SELECT 1 FROM demandes_recup d WHERE d.user_id=?
            AND d.id!=? AND d.statut='validee' AND d.date_debut<=? AND d.date_fin>=?
            AND NOT EXISTS (SELECT 1 FROM recup_annulations a WHERE a.demande_recup_id=d.id AND a.date=?)''',
            (uid,did,jour,jour,jour)).fetchone()
        if concurrente:
            raise ConflitAbsence('Plusieurs récupérations historiques couvrent cette journée ; une revue est nécessaire.')
        p = conn.execute("SELECT * FROM rh_projections WHERE user_id=? AND date=? AND calendrier='heures_reelles'",(uid,jour)).fetchone()
        row = conn.execute('SELECT * FROM heures_reelles WHERE user_id=? AND date=?',(uid,jour)).fetchone()
        if p:
            if p['demande_recup_id']!=did or not row or p['contenu']!=_contenu(row):
                raise ConflitAbsence('La journée ne correspond plus à cette récupération ; aucune donnée n’a été écrasée.')
        elif row:
            partielle = demande['type_demande']=='partielle'
            attendu = (f"Récup. partielle {demande['heure_debut']}-{demande['heure_fin']} "
                       f"({demande['nb_heures']:.2f}h) - Demande #{did} validée") if partielle else f'Récupération - Demande #{did} validée'
            if row['type_saisie']!=('recup_partielle' if partielle else 'recup_journee') or row['commentaire']!=attendu:
                raise ConflitAbsence('Origine historique ambiguë : aucune donnée n’a été écrasée. Une revue est nécessaire.')
        # Une absence encore active n'est jamais retirée par cette opération.
        if conn.execute('SELECT 1 FROM absences WHERE user_id=? AND date_debut<=? AND date_fin>=?',(uid,jour,jour)).fetchone():
            raise ConflitAbsence('Une absence couvre déjà la journée ; aucune annulation de récupération n’a été appliquée.')
        if demande['type_demande']=='partielle':
            heures = demande['nb_heures']
        else:
            planning = get_planning_valide_a_date(uid,get_type_periode(jour,conn=conn),jour,conn=conn)
            if not planning:
                raise ConflitAbsence('Planning manquant : impossible de tracer les heures restituées.')
            heures = get_heures_theoriques_jour(planning,date.fromisoformat(jour).weekday())
        conn.execute('DELETE FROM rh_projections WHERE user_id=? AND date=? AND demande_recup_id=?',(uid,jour,did))
        if row:
            conn.execute('DELETE FROM heures_reelles WHERE user_id=? AND date=?',(uid,jour))
        conn.execute('''INSERT INTO recup_annulations
            (demande_recup_id,date,nb_heures,auteur_id,date_annulation,motif,absence_id) VALUES(?,?,?,?,?,?,?)''',
            (did,jour,heures,auteur_id,now,motif.strip(),absence_id))
        details.append({'date':jour,'nb_heures':heures,'ancienne_saisie':dict(row) if row else None})
    statut = 'annulee' if set(jours)<=annules|set(cibles) else 'validee'
    conn.execute('UPDATE demandes_recup SET statut=? WHERE id=?',(statut,did))
    conn.execute('''INSERT INTO historique_modifications
        (user_id_modifie,date_concernee,modifie_par,action,anciennes_valeurs,nouvelles_valeurs,date_modification)
        VALUES (?,?,?,'annulation_recup',?,?,?)''',
        (uid,cibles[0],auteur_id,json.dumps(dict(demande),ensure_ascii=False),
         json.dumps({'demande_id':did,'motif':motif.strip(),'absence_id':absence_id,'statut':statut,'jours':details},ensure_ascii=False),now))
    return cibles


def enrichir_annulations(conn, demandes):
    """Présentation des dates retirées sans réécrire la demande d'origine."""
    result = []
    for demande in demandes:
        d = dict(demande)
        annulations = [dict(r) for r in conn.execute('''SELECT a.*, u.prenom || ' ' || u.nom AS auteur_nom
            FROM recup_annulations a JOIN users u ON u.id=a.auteur_id
            WHERE demande_recup_id=? ORDER BY date''',(d['id'],))]
        d['annulations'] = annulations
        d['heures_annulees'] = sum(a['nb_heures'] for a in annulations)
        d['heures_maintenues'] = max(0,(d.get('nb_heures') or 0)-d['heures_annulees'])
        d['jours_maintenus'] = 0 if d['statut']=='annulee' else max(0,d['nb_jours']-len(annulations)) if d.get('type_demande')!='partielle' else d['nb_jours']
        result.append(d)
    return result
