"""État privé, contrôle du périmètre et concurrence de l'assistant.

Les appels réseau ne se font jamais sous un verrou SQLite. Une révision et un
bail empêchent une réponse tardive de réintroduire une conversation effacée.
"""
from contextlib import contextmanager
import hashlib
import json
import uuid

from flask import session

from database import get_db
from sessions_securite import verifier_session
from utils import maintenant, encrypt_value, decrypt_value

PROFILS = ('directeur', 'comptable', 'responsable')
MAX_MEMOIRES = 30
MAX_MEMOIRE = 400
MAX_TOURS_JOUR = 30
DUREE_CONVERSATION = 30 * 86400


class AssistantErreur(Exception):
    def __init__(self, message, statut=400):
        super().__init__(message)
        self.message, self.statut = message, statut


def encoder(value):
    return encrypt_value(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


def decoder(value):
    try:
        return json.loads(decrypt_value(value))
    except Exception:
        raise AssistantErreur('La mémoire personnelle ne peut pas être relue. Contactez la direction.', 503) from None


def instant():
    return int(maintenant().timestamp())


def compte(conn):
    if not verifier_session(conn) or session.get('force_password_change'):
        raise AssistantErreur('Votre session a changé. Reconnectez-vous.', 403)
    user = conn.execute('SELECT id, profil, secteur_id, session_version FROM users WHERE id=?',
                        (session['user_id'],)).fetchone()
    if not acces_autorise(conn, user):
        raise AssistantErreur('Accès réservé aux profils de gestion et aux salariés du secteur Pilotage.', 403)
    return dict(user)


def acces_autorise(conn, user):
    if user['profil'] in PROFILS:
        return True
    if user['profil'] != 'salarie':
        return False
    secteur = conn.execute('SELECT nom FROM secteurs WHERE id=?', (user['secteur_id'],)).fetchone()
    return bool(secteur and secteur['nom'].strip().casefold() == 'pilotage')


def perimetre(conn, user):
    from interface_flux import carte_pour_utilisateur
    carte = carte_pour_utilisateur(user['profil'], user['id'])
    droits = {'compte': user, 'navigation': carte}
    # Un changement de nom du secteur doit aussi révoquer l'accès Pilotage.
    secteur = conn.execute('SELECT nom FROM secteurs WHERE id=?', (user['secteur_id'],)).fetchone()
    droits['secteur'] = secteur['nom'] if secteur else None
    if user['profil'] not in ('directeur', 'comptable'):
        # Les changements de rattachement, d'affectation ou de délégation ne
        # doivent pas laisser d'anciennes données dans les échanges suivants.
        droits['equipe'] = [tuple(r) for r in conn.execute(
            'SELECT id, profil, actif FROM users WHERE secteur_id=? OR responsable_id=? ORDER BY id',
            (user['secteur_id'], user['id']))]
        droits['factures'] = [r[0] for r in conn.execute(
            'SELECT id FROM factures WHERE secteur_id=? ORDER BY id', (user['secteur_id'],))]
        droits['subventions'] = [tuple(r) for r in conn.execute(
            '''SELECT s.id, se.id FROM subventions s
               LEFT JOIN subventions_sous_elements se ON se.subvention_id=s.id
               WHERE s.assignee_1_id=? OR s.assignee_2_id=? OR se.assignee_id=?
               ORDER BY s.id, se.id''', (user['id'],) * 3)]
    return hashlib.sha256(json.dumps(droits, sort_keys=True, default=str).encode()).hexdigest()


@contextmanager
def transaction():
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def preparer(conn):
    user = compte(conn)
    scope = perimetre(conn, user)
    now, jour = instant(), maintenant().date().isoformat()
    row = conn.execute('SELECT * FROM assistant_etats WHERE user_id=?', (user['id'],)).fetchone()
    notice = ''
    if row is None:
        conn.execute('''INSERT INTO assistant_etats
            (user_id,perimetre,contenu,jour,actualise_le) VALUES (?,?,?,?,?)''',
            (user['id'], scope, encoder({'messages': [], 'resume': ''}), jour, now))
    elif row['perimetre'] != scope:
        conn.execute('DELETE FROM assistant_memoires WHERE user_id=?', (user['id'],))
        vider_conversation(conn, user['id'])
        conn.execute('UPDATE assistant_etats SET perimetre=? WHERE user_id=?', (scope, user['id']))
        notice = 'Vos droits ont changé : la conversation et les souvenirs précédents ont été effacés.'
    elif row['actualise_le'] < now - DUREE_CONVERSATION:
        vider_conversation(conn, user['id'])
        notice = 'La conversation précédente a expiré après 30 jours.'
    expired = conn.execute('DELETE FROM assistant_memoires WHERE user_id=? AND expire_le<=?',
                           (user['id'], now)).rowcount
    if expired:
        vider_conversation(conn, user['id'])
        notice = 'Un souvenir a expiré : le contexte de conversation a été réinitialisé.'
    row = dict(conn.execute('SELECT * FROM assistant_etats WHERE user_id=?', (user['id'],)).fetchone())
    if row['jour'] != jour:
        conn.execute('UPDATE assistant_etats SET jour=?,tours=0 WHERE user_id=?', (jour, user['id']))
        row.update(jour=jour, tours=0)
    return user, row, notice


def vider_conversation(conn, uid):
    conn.execute('''UPDATE assistant_etats SET contenu=?,revision=revision+1,
        en_cours=NULL,verrou_jusqua=0,actualise_le=? WHERE user_id=?''',
        (encoder({'messages': [], 'resume': ''}), instant(), uid))


def memoires(conn, uid):
    return [dict(id=r['id'], categorie=r['categorie'], texte=decoder(r['contenu']),
                 expire_le=r['expire_le']) for r in conn.execute(
        'SELECT * FROM assistant_memoires WHERE user_id=? ORDER BY cree_le,id', (uid,))]


def etat_public(conn, user, row, notice=''):
    data = decoder(row['contenu'])
    return {'messages': data['messages'], 'resume': data['resume'],
            'memoires': memoires(conn, user['id']), 'notice': notice,
            'restant': max(0, MAX_TOURS_JOUR - row['tours']),
            'en_cours': bool(row['en_cours'] and row['verrou_jusqua'] > instant())}


def lire_etat():
    with transaction() as conn:
        user, row, notice = preparer(conn)
        return etat_public(conn, user, row, notice)


def reserver(message, model, request_id, document_id=None):
    with transaction() as conn:
        user, row, notice = preparer(conn)
        data = decoder(row['contenu'])
        if document_id is not None:
            from assistant_reception import _document
            _document(conn, user, document_id)
        signature = hashlib.sha256((model + '\n' + message + '\n' + (document_id or '')).encode()).hexdigest()
        action = conn.execute('SELECT signature FROM assistant_actions WHERE user_id=? AND demande_id=?',
                              (user['id'], request_id)).fetchone()
        if action:
            if action['signature'] != signature:
                raise AssistantErreur('Cette demande a déjà servi à une autre proposition.', 409)
            return {'reponse_existante': etat_public(conn, user, row, notice)}
        dernier = data.get('dernier', {})
        if dernier.get('id') == request_id:
            if dernier['signature'] != signature:
                raise AssistantErreur('Cette demande a déjà été utilisée avec un autre contenu.', 409)
            return {'reponse_existante': etat_public(conn, user, row, notice)}
        if row['en_cours'] and row['verrou_jusqua'] > instant():
            raise AssistantErreur('Une réponse est déjà en préparation. Patientez quelques instants.', 409)
        if row['tours'] >= MAX_TOURS_JOUR:
            raise AssistantErreur('La limite de 30 demandes par jour est atteinte. Réessayez demain.', 429)
        token = str(uuid.uuid4())
        conn.execute('''UPDATE assistant_etats SET en_cours=?,verrou_jusqua=?,tours=tours+1
            WHERE user_id=?''', (token, instant() + 180, user['id']))
        return {'user': user, 'scope': row['perimetre'], 'revision': row['revision'],
                'token': token, 'data': data, 'memoires': memoires(conn, user['id']),
                'request_id': request_id, 'signature': signature, 'notice': notice}


def verifier_tour(conn, tour):
    user, row, _ = preparer(conn)
    if (user['id'] != tour['user']['id'] or row['perimetre'] != tour['scope']
            or row['revision'] != tour['revision'] or row['en_cours'] != tour['token']
            or row['verrou_jusqua'] <= instant()):
        raise AssistantErreur('Le contexte a changé. Rechargez la conversation avant de réessayer.', 409)
    return user, row


def terminer(tour, question, reponse, sources, resume, proposition=None):
    with transaction() as conn:
        user, row = verifier_tour(conn, tour)
        if proposition is not None:
            from assistant_actions import ajouter
            ajouter(conn, user, tour, proposition)
        data = tour['data']
        data['messages'] = (data['messages'] + [
            {'role': 'user', 'texte': question, 'sources': []},
            {'role': 'assistant', 'texte': reponse, 'sources': sources},
        ])[-20:]
        data['resume'] = resume
        data['dernier'] = {'id': tour['request_id'], 'signature': tour['signature']}
        conn.execute('''UPDATE assistant_etats SET contenu=?,revision=revision+1,
            en_cours=NULL,verrou_jusqua=0,actualise_le=? WHERE user_id=?''',
            (encoder(data), instant(), user['id']))
        row = dict(conn.execute('SELECT * FROM assistant_etats WHERE user_id=?', (user['id'],)).fetchone())
        return etat_public(conn, user, row, tour['notice'])


def liberer(tour):
    with transaction() as conn:
        conn.execute('''UPDATE assistant_etats SET en_cours=NULL,verrou_jusqua=0
            WHERE user_id=? AND en_cours=?''', (tour['user']['id'], tour['token']))


def sauver_memoire(texte, categorie, identifiant=None):
    if not isinstance(texte, str) or not 1 <= len(texte.strip()) <= MAX_MEMOIRE:
        raise AssistantErreur('Un souvenir doit contenir entre 1 et 400 caractères.')
    if categorie not in ('preference', 'suivi'):
        raise AssistantErreur('Catégorie de souvenir invalide.')
    with transaction() as conn:
        user, row, _ = preparer(conn)
        uid = user['id']
        if identifiant:
            if not conn.execute('SELECT 1 FROM assistant_memoires WHERE id=? AND user_id=?',
                                (identifiant, uid)).fetchone():
                raise AssistantErreur('Souvenir introuvable.', 404)
        elif conn.execute('SELECT COUNT(*) FROM assistant_memoires WHERE user_id=?', (uid,)).fetchone()[0] >= MAX_MEMOIRES:
            raise AssistantErreur('La mémoire est limitée à 30 éléments. Supprimez-en un pour continuer.', 409)
        if any(n['id'] != identifiant and n['texte'].casefold() == texte.strip().casefold()
               for n in memoires(conn, uid)):
            raise AssistantErreur('Ce souvenir figure déjà dans votre mémoire.', 409)
        expires = instant() + 30 * 86400 if categorie == 'suivi' else None
        if identifiant:
            conn.execute('''UPDATE assistant_memoires SET categorie=?,contenu=?,expire_le=?
                WHERE id=? AND user_id=?''', (categorie, encoder(texte.strip()), expires, identifiant, uid))
        else:
            conn.execute('''INSERT INTO assistant_memoires
                (id,user_id,categorie,contenu,cree_le,expire_le) VALUES (?,?,?,?,?,?)''',
                (str(uuid.uuid4()), uid, categorie, encoder(texte.strip()), instant(), expires))
        # Retirer un ancien souvenir du contexte implique aussi d'effacer les
        # résumés susceptibles de le répéter. Annule une réponse en cours.
        vider_conversation(conn, uid)


def oublier(identifiant=None, tout=False):
    with transaction() as conn:
        user, _, _ = preparer(conn)
        if identifiant:
            if not conn.execute('DELETE FROM assistant_memoires WHERE id=? AND user_id=?',
                                (identifiant, user['id'])).rowcount:
                raise AssistantErreur('Souvenir introuvable.', 404)
        if tout:
            conn.execute('DELETE FROM assistant_memoires WHERE user_id=?', (user['id'],))
        vider_conversation(conn, user['id'])
