"""Création commune au planificateur et à l'assistant, sans commit implicite."""


class CreationErreur(ValueError):
    pass


def creer_element(conn, user_id, data, sans_reevaluation=False):
    # Import local : le blueprint appelle ce service et porte les règles existantes.
    from blueprints.planificateur import (
        _valide_date, _valide_heure, _parse_int, _parser_reponses,
        _candidats_comparaison, _calculer_priorite_num, _priorite_de,
        _sync_bloc_evenement, moteur, PRIORITES_VALIDES, PREFERENCES_VALIDES,
    )
    titre = data.get('titre') or ''
    description = data.get('description') or ''
    if not isinstance(titre, str) or not titre.strip():
        raise CreationErreur('Le titre est obligatoire.')
    if not isinstance(description, str):
        raise CreationErreur('Description invalide.')
    titre, description = titre.strip(), description.strip()
    if data.get('type', 'tache') == 'evenement':
        jour = _valide_date(data.get('date_fixe'))
        debut, fin = _valide_heure(data.get('heure_debut')), _valide_heure(data.get('heure_fin'))
        if not (jour and debut and fin):
            raise CreationErreur("Date et horaires de l'evenement requis.")
        if moteur._to_min(fin) <= moteur._to_min(debut):
            raise CreationErreur("L'heure de fin doit suivre l'heure de debut.")
        identifiant = conn.execute('''INSERT INTO planif_taches
            (user_id,type,titre,description,date_fixe,heure_debut,heure_fin,duree_min,statut)
            VALUES (?,'evenement',?,?,?,?,?,?,'a_faire')''',
            (user_id, titre, description, jour, debut, fin, moteur._to_min(fin)-moteur._to_min(debut))).lastrowid
        tache = conn.execute('SELECT * FROM planif_taches WHERE id=?', (identifiant,)).fetchone()
        _sync_bloc_evenement(conn, tache)
        return identifiant
    duree = _parse_int(data.get('duree_min'), 60, mini=5, maxi=24*60)
    refs = _candidats_comparaison(conn, user_id)
    reponses = _parser_reponses(data.get('comparaisons'))
    if not reponses and refs:
        raise CreationErreur('Situez la priorité de la tâche par rapport aux tâches présentées.')
    if sans_reevaluation and len(refs) == 2:
        haute, basse = sorted(refs, key=_priorite_de, reverse=True)
        if reponses.get(haute['id']) == 'superieur' and reponses.get(basse['id']) == 'inferieur':
            raise CreationErreur('Ces comparaisons sont contradictoires. Revoyez vos réponses ; aucune tâche existante ne sera réévaluée.')
    priorite_num, reevaluee = _calculer_priorite_num(conn, user_id, data.get('comparaisons'))
    if sans_reevaluation and reevaluee is not None:
        # Le calcul peut ordonner autrement deux références de même priorité.
        # L'appelant annule toute la transaction, y compris cette réévaluation.
        raise CreationErreur('Ces comparaisons sont contradictoires. Revoyez vos réponses ; aucune tâche existante ne sera réévaluée.')
    return conn.execute('''INSERT INTO planif_taches
        (user_id,type,titre,description,duree_min,deadline,priorite,priorite_num,
         preference,secable,duree_min_bloc,statut)
        VALUES (?,'tache',?,?,?,?,?,?,?,?,?,'a_faire')''',
        (user_id, titre, description, duree, _valide_date(data.get('deadline')),
         data.get('priorite') if data.get('priorite') in PRIORITES_VALIDES else 'normale', priorite_num,
         data.get('preference') if data.get('preference') in PREFERENCES_VALIDES else 'aucune',
         int(str(data.get('secable')) in ('1','true','on','True')),
         _parse_int(data.get('duree_min_bloc'), 30, mini=5, maxi=duree))).lastrowid


def placer_nouvelle_tache(conn, user_id, identifiant):
    """Moteur habituel, autour de tous les blocs existants, sans les déplacer."""
    from datetime import timedelta
    # Import local pour réutiliser les horaires, absences et jours fériés du blueprint.
    from blueprints.planificateur import (
        _horaires_par_date, _jours_feries_set, _jours_absences_set, HORIZON_JOURS, moteur,
    )
    from utils import maintenant
    now = maintenant()
    debut, fin = now.date(), now.date() + timedelta(days=HORIZON_JOURS)
    horaires = _horaires_par_date(conn, user_id, debut, fin)
    absences = _jours_absences_set(conn, user_id, debut, fin)
    horaires = {d:h for d,h in horaires.items() if d not in absences}
    occupes = {}
    for b in conn.execute('''SELECT date,heure_debut,heure_fin FROM planif_blocs
            WHERE user_id=? AND date BETWEEN ? AND ?''', (user_id, debut.isoformat(), fin.isoformat())):
        occupes.setdefault(b['date'], []).append((moteur._to_min(b['heure_debut']), moteur._to_min(b['heure_fin'])))
    tache = dict(conn.execute('SELECT * FROM planif_taches WHERE id=? AND user_id=?', (identifiant, user_id)).fetchone())
    resultat = moteur.planifier([tache], occupes, horaires, debut, fin,
        _jours_feries_set(conn, debut, fin), minute_courante=now.hour*60 + now.minute)
    for b in resultat['blocs']:
        conn.execute('''INSERT INTO planif_blocs
            (tache_id,user_id,date,heure_debut,heure_fin,duree_min,statut,verrouille)
            VALUES (?,?,?,?,?,?,'planifie',0)''',
            (identifiant, user_id, b['date'], b['heure_debut'], b['heure_fin'], b['duree_min']))
    return resultat['non_planifie']
