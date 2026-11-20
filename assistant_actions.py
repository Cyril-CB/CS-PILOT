"""Propositions relues et confirmées : créations personnelles, exécution unique."""
from datetime import date, datetime, time
import hashlib
import json
import random
import uuid

from flask import url_for

from assistant_stockage import (AssistantErreur, compte, transaction, encoder, decoder,
                               instant, perimetre)
from planificateur_creation import creer_element, placer_nouvelle_tache, CreationErreur
from utils import maintenant

COMMUNS = {'type', 'titre', 'description'}
CHAMPS = {'evenement': COMMUNS | {'date_fixe', 'heure_debut', 'heure_fin'},
          'tache': COMMUNS | {'duree_min', 'deadline', 'preference', 'secable', 'duree_min_bloc'}}
DUREE = 7 * 86400


def normaliser(champs):
    if (not isinstance(champs, dict) or not isinstance(champs.get('type'), str)
            or champs['type'] not in CHAMPS or set(champs) - CHAMPS[champs['type']]):
        raise AssistantErreur('Proposition invalide : seuls les rendez-vous et tâches personnels sont proposés.')
    c = {'type': champs['type']}
    for k, maxi in (('titre', 200), ('description', 2000)):
        v = champs.get(k) or ''
        if not isinstance(v, str) or len(v) > maxi:
            raise AssistantErreur('Titre ou description de proposition invalide.')
        c[k] = v.strip()
    dates = ('date_fixe',) if c['type'] == 'evenement' else ('deadline',)
    for k in dates:
        v = champs.get(k) or None
        if v is not None:
            try:
                if not isinstance(v, str) or date.fromisoformat(v).isoformat() != v:
                    raise ValueError()
            except (TypeError, ValueError):
                raise AssistantErreur('Date invalide : utilisez AAAA-MM-JJ.') from None
        c[k] = v
    if c['type'] == 'evenement':
        for k in ('heure_debut', 'heure_fin'):
            v = champs.get(k) or None
            if v is not None:
                try:
                    if not isinstance(v, str) or len(v) != 5 or time.fromisoformat(v).strftime('%H:%M') != v:
                        raise ValueError()
                except (TypeError, ValueError):
                    raise AssistantErreur('Heure invalide : utilisez HH:MM.') from None
            c[k] = v
    else:
        for k, defaut in (('duree_min', None), ('duree_min_bloc', min(30, champs.get('duree_min') or 30)
                          if type(champs.get('duree_min')) is int else 30)):
            v = champs.get(k, defaut)
            if v is not None and (type(v) is not int or not 5 <= v <= 1440):
                raise AssistantErreur('La durée doit être comprise entre 5 et 1 440 minutes.')
            c[k] = v
        c['preference'] = champs.get('preference') or 'aucune'
        c['secable'] = champs.get('secable', False)
        if c['preference'] not in ('aucune', 'matin', 'apres_midi') or type(c['secable']) is not bool:
            raise AssistantErreur('Préférence de placement invalide.')
        if c['duree_min'] and c['duree_min_bloc'] and c['duree_min_bloc'] > c['duree_min']:
            raise AssistantErreur('La durée minimale d’un bloc dépasse la durée de la tâche.')
        if c['duree_min_bloc'] is None:
            c['duree_min_bloc'] = min(30, c['duree_min'] or 30)
    return c


def verifier_complet(c):
    if not c['titre']:
        raise AssistantErreur('Complétez le titre avant de confirmer.')
    if c['type'] == 'evenement':
        if not all(c.get(k) for k in ('date_fixe', 'heure_debut', 'heure_fin')):
            raise AssistantErreur('Complétez la date et les deux horaires du rendez-vous.')
        if c['heure_fin'] <= c['heure_debut']:
            raise AssistantErreur('La fin du rendez-vous doit suivre son début.')
        if datetime.fromisoformat(c['date_fixe'] + 'T' + c['heure_debut']) < maintenant():
            raise AssistantErreur('Le rendez-vous est passé. Vérifiez sa date et son heure.')
    else:
        if c['duree_min'] is None:
            raise AssistantErreur('Précisez la durée estimée de la tâche.')
        if c['deadline'] and c['deadline'] < maintenant().date().isoformat():
            raise AssistantErreur('L’échéance est passée. Vérifiez la date de la tâche.')


def _contexte(conn, user, c):
    from blueprints.planificateur import _candidats_comparaison
    refs = [dict(r) for r in _candidats_comparaison(conn, user['id'])] if c['type'] == 'tache' else []
    similaires = []
    for r in conn.execute('SELECT * FROM planif_taches WHERE user_id=? AND type=? ORDER BY id DESC',
                          (user['id'], c['type'])):
        if r['titre'].strip().casefold() != c['titre'].casefold():
            continue
        cles = ('date_fixe', 'heure_debut', 'heure_fin') if c['type'] == 'evenement' else ('duree_min', 'deadline')
        if all((r[k] or None) == (c[k] or None) for k in cles):
            similaires.append({'id': r['id'], 'titre': r['titre']})
    agenda = [dict(r) for r in conn.execute('''SELECT id,tache_id,date,heure_debut,heure_fin,statut,verrouille
        FROM planif_blocs WHERE user_id=? AND date>=? ORDER BY id''',
        (user['id'], maintenant().date().isoformat()))]
    conflits = []
    if c['type'] == 'evenement' and all(c.get(k) for k in ('date_fixe','heure_debut','heure_fin')):
        conflits = [{'date': b['date'], 'debut': b['heure_debut'], 'fin': b['heure_fin']} for b in agenda
                    if b['date'] == c['date_fixe'] and b['heure_debut'] < c['heure_fin'] and b['heure_fin'] > c['heure_debut']]
    empreinte = hashlib.sha256(json.dumps([maintenant().date().isoformat(), refs, similaires, agenda],
                                         sort_keys=True).encode()).hexdigest()
    return empreinte, [{'id':r['id'], 'titre':r['titre']} for r in refs], similaires[:5], conflits[:10]


def _charger(conn, user, identifiant):
    r = conn.execute('SELECT * FROM assistant_actions WHERE id=? AND user_id=?',
                     (str(identifiant), user['id'])).fetchone()
    if not r:
        raise AssistantErreur('Proposition introuvable.', 404)
    return dict(r), decoder(r['contenu'])


def _sauver(conn, r, data, statut=None):
    r['revision'] += 1
    r['statut'] = statut or r['statut']
    conn.execute('UPDATE assistant_actions SET contenu=?,revision=?,statut=? WHERE id=?',
                 (encoder(data), r['revision'], r['statut'], r['id']))


def _actualiser(conn, user, r, data):
    if r['statut'] != 'attente':
        return
    if r['expire_le'] <= instant() or r['perimetre'] != perimetre(conn, user):
        _sauver(conn, r, data, 'expiree')
        return
    empreinte, refs, similaires, conflits = _contexte(conn, user, data['champs'])
    if data.get('contexte') != empreinte:
        random.shuffle(refs)
        data.update(contexte=empreinte, references=refs, similaires=similaires, conflits=conflits)
        _sauver(conn, r, data)


def _public(conn, user, r, data):
    erreur = ''
    try:
        verifier_complet(data['champs'])
    except AssistantErreur as exc:
        erreur = exc.message
    resultat = dict(data.get('resultat') or {})
    if resultat:
        resultat['existe'] = bool(conn.execute('SELECT 1 FROM planif_taches WHERE id=? AND user_id=?',
                                              (resultat['id'], user['id'])).fetchone())
        resultat['lien'] = url_for('planificateur_bp.planificateur')
    return {'id':r['id'], 'revision':r['revision'], 'statut':r['statut'], 'champs':data['champs'],
            'references':data.get('references', []), 'similaires':data.get('similaires', []),
            'conflits':data.get('conflits', []), 'resultat':resultat, 'precision':erreur,
            'cree_le':r['cree_le'], 'expire_le':r['expire_le']}


def ajouter(conn, user, tour, champs):
    """Appelée dans la transaction du dialogue, jamais une création métier."""
    c = normaliser(champs)
    ancien = conn.execute('SELECT * FROM assistant_actions WHERE user_id=? AND demande_id=?',
                          (user['id'], tour['request_id'])).fetchone()
    if ancien:
        if ancien['signature'] != tour['signature']:
            raise AssistantErreur('Cette demande a déjà servi à une autre proposition.', 409)
        return ancien['id']
    if conn.execute('''SELECT COUNT(*) FROM assistant_actions
            WHERE user_id=? AND statut='attente' AND expire_le>? AND perimetre=?''',
            (user['id'], instant(), tour['scope'])).fetchone()[0] >= 10:
        raise AssistantErreur('Dix propositions attendent déjà. Confirmez-en ou abandonnez-en une.', 409)
    identifiant = str(uuid.uuid4())
    conn.execute('''INSERT INTO assistant_actions
        (id,user_id,demande_id,signature,perimetre,contenu,cree_le,expire_le)
        VALUES (?,?,?,?,?,?,?,?)''', (identifiant, user['id'], tour['request_id'], tour['signature'],
        tour['scope'], encoder({'champs':c}), instant(), instant()+DUREE))
    r, data = _charger(conn, user, identifiant)
    _actualiser(conn, user, r, data)
    return identifiant


def lister(identifiant=None):
    with transaction() as conn:
        user = compte(conn)
        ids = [str(identifiant)] if identifiant else [r[0] for r in conn.execute('''SELECT id FROM assistant_actions
            WHERE user_id=? ORDER BY (statut='attente') DESC,cree_le DESC,rowid DESC LIMIT 20''', (user['id'],))]
        resultat = []
        for ident in ids:
            r, data = _charger(conn, user, ident)
            _actualiser(conn, user, r, data)
            resultat.append(_public(conn, user, r, data))
        return resultat[0] if identifiant else resultat


def modifier(identifiant, revision, champs=None, abandonner=False):
    with transaction() as conn:
        user = compte(conn)
        r, data = _charger(conn, user, identifiant)
        if type(revision) is not int or revision != r['revision']:
            raise AssistantErreur('La proposition a changé. Rechargez-la.', 409)
        if r['statut'] != 'attente' or r['expire_le'] <= instant() or r['perimetre'] != perimetre(conn, user):
            raise AssistantErreur('Cette proposition ne peut plus être modifiée. Préparez-en une nouvelle.', 409)
        if not abandonner:
            data = {'champs':normaliser(champs)}
        _sauver(conn, r, data, 'abandonnee' if abandonner else None)
        _actualiser(conn, user, r, data)
        return _public(conn, user, r, data)


def confirmer(identifiant, revision, comparaisons, accepter_doublon):
    with transaction() as conn:
        user = compte(conn)
        r, data = _charger(conn, user, identifiant)
        if r['statut'] == 'executee':
            return _public(conn, user, r, data)
        if (type(revision) is not int or revision != r['revision'] or r['statut'] != 'attente'
                or r['expire_le'] <= instant() or r['perimetre'] != perimetre(conn, user)):
            raise AssistantErreur('La proposition a changé ou expiré. Rechargez-la avant de confirmer.', 409)
        c = data['champs']
        verifier_complet(c)
        if _contexte(conn, user, c)[0] != data['contexte']:
            raise AssistantErreur('Le planificateur a changé. Relisez la proposition et les comparaisons actualisées.', 409)
        if type(accepter_doublon) is not bool or (data['similaires'] and not accepter_doublon):
            raise AssistantErreur('Un élément correspondant existe déjà. Ouvrez-le ou confirmez une création distincte.', 409)
        if (not isinstance(comparaisons, list) or len(comparaisons) != len(data['references'])
                or any(not isinstance(p, dict) or set(p) != {'tache_id','reponse'}
                    or type(p['tache_id']) is not int or p['reponse'] not in ('superieur','egal','inferieur') for p in comparaisons)
                or {p['tache_id'] for p in comparaisons} != {p['id'] for p in data['references']}):
            raise AssistantErreur('Répondez à chaque comparaison de priorité affichée.')
        try:
            tid = creer_element(conn, user['id'], {**c, 'comparaisons':comparaisons}, sans_reevaluation=True)
        except CreationErreur as exc:
            raise AssistantErreur(str(exc)) from None
        non_placees = placer_nouvelle_tache(conn, user['id'], tid) if c['type'] == 'tache' else []
        data['resultat'] = {'id':tid, 'non_placee':bool(non_placees)}
        _sauver(conn, r, data, 'executee')
        return _public(conn, user, r, data)
