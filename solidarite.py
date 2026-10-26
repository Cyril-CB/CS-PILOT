"""Exception CP/CC au calendrier férié, sans modifier les jours ouvrés généraux."""
from datetime import date, timedelta
from absences_coherence import ConflitAbsence

CONGES_SOLIDARITE = ('Congé payé', 'Congé conventionnel')
MESSAGE_RECUP = ('La journée de solidarité ne peut pas être prise en récupération. '
                 'Posez un congé payé ou conventionnel sur cette date, '
                 'et séparez les éventuelles récupérations autour de cette journée.')


def dates_solidarite(conn, debut, fin):
    return {r['date'] for r in conn.execute(
        'SELECT date FROM jours_feries WHERE solidarite = 1 AND date BETWEEN ? AND ?',
        (debut, fin))}


def jours_absence(conn, debut, fin, motif):
    """Dates imputables, lun-ven : les fériés restent exclus sauf solidarité CP/CC.

    Une période englobante inclut la solidarité une seule fois. Comme les
    congés existants, le décompte est en jours entiers, sans prorata de planning.
    """
    feries = {r['date']: r['solidarite'] for r in conn.execute(
        'SELECT date, solidarite FROM jours_feries WHERE date BETWEEN ? AND ?', (debut, fin))}
    jour, dernier = date.fromisoformat(debut), date.fromisoformat(fin)
    resultat = []
    while jour <= dernier:
        iso = jour.isoformat()
        if jour.weekday() < 5 and (iso not in feries or
                (feries[iso] and motif in CONGES_SOLIDARITE)):
            resultat.append(iso)
        jour += timedelta(days=1)
    return resultat


def verifier_recuperation(conn, debut, fin):
    if dates_solidarite(conn, debut, fin):
        raise ConflitAbsence(MESSAGE_RECUP)


def verifier_date_solidarite_libre(conn, jour):
    # Une reconfiguration ne doit pas rendre caducs des nombres de jours
    # déjà enregistrés ni une récupération active. Aucun recalcul silencieux.
    for table in ('absences', 'demandes_conges', 'demandes_recup'):
        condition = " AND statut != 'refusee'" if table != 'absences' else ''
        if conn.execute(f'SELECT 1 FROM {table} WHERE date_debut <= ? AND date_fin >= ?{condition} LIMIT 1',
                        (jour, jour)).fetchone():
            raise ValueError('Une absence ou une demande couvre cette date. Corrigez-la avant de changer la journée de solidarité ; aucun décompte existant n’a été modifié.')
    if conn.execute("SELECT 1 FROM heures_reelles WHERE date = ? AND type_saisie IN ('recup_journee', 'recup_partielle') LIMIT 1", (jour,)).fetchone():
        raise ValueError('Une récupération figure déjà à cette date. Corrigez-la avant de désigner la journée de solidarité.')
    if conn.execute("SELECT 1 FROM presence_forfait_jour WHERE date = ? AND type_journee != 'travaille' LIMIT 1", (jour,)).fetchone():
        raise ValueError('Une saisie forfait jours existe à cette date. Corrigez-la avant de changer la journée de solidarité.')


def designer_solidarite(conn, ferie_id):
    """Bascule la désignation, ou remplace celle de l'année, sous verrou appelant."""
    ferie = conn.execute('SELECT * FROM jours_feries WHERE id = ?', (ferie_id,)).fetchone()
    if not ferie:
        raise ValueError('Jour férié introuvable.')
    if date.fromisoformat(ferie['date']).weekday() >= 5:
        raise ValueError('Choisissez un jour férié du lundi au vendredi pour la journée de solidarité.')
    ancien = conn.execute('SELECT * FROM jours_feries WHERE annee = ? AND solidarite = 1',
                           (ferie['annee'],)).fetchone()
    verifier_date_solidarite_libre(conn, ferie['date'])
    if ancien and ancien['id'] != ferie_id:
        verifier_date_solidarite_libre(conn, ancien['date'])
    conn.execute('UPDATE jours_feries SET solidarite = 0 WHERE annee = ?', (ferie['annee'],))
    if not ferie['solidarite']:
        conn.execute('UPDATE jours_feries SET solidarite = 1 WHERE id = ?', (ferie_id,))
    return not ferie['solidarite']
