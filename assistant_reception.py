"""Réception privée, quotas partagés, précisions et traitements idempotents."""
import hashlib
import re
import uuid

from flask import url_for
from werkzeug.utils import secure_filename

from assistant_documents_analyse import CHAMPS, TYPES, analyser, date_iso
from assistant_documents_metier import preparer, appliquer
from assistant_fournisseurs import cle_pour
from assistant_pdf import (extraire_pdf, enregistrer_pdf, chemin_document,
                           nettoyer_creations, MAX_PDF)
from assistant_stockage import (AssistantErreur, compte, transaction, encoder, decoder,
                               instant, perimetre, preparer as preparer_compte, MAX_TOURS_JOUR)
from fiches_versions import FicheVerrouillee


def _document(conn, user, identifiant):
    row = conn.execute('SELECT * FROM assistant_documents WHERE id=? AND user_id=?',
                       (str(identifiant), user['id'])).fetchone()
    if row is None:
        raise AssistantErreur('Document introuvable.', 404)
    return dict(row), decoder(row['contenu'])


def _sauver(conn, doc, data, statut=None):
    conn.execute('''UPDATE assistant_documents SET contenu=?,statut=?,revision=revision+1,
        actualise_le=? WHERE id=?''',
        (encoder(data), statut or doc['statut'], instant(), doc['id']))


def _public(conn, user, doc, data):
    resultat = dict(data.get('resultat') or {})
    if resultat.get('facture_id') and user['profil'] not in ('directeur', 'comptable'):
        resultat.pop('lien', None)
    if resultat.get('subvention_id'):
        from blueprints.subventions import _refus_acces_subvention
        if _refus_acces_subvention(conn, resultat['subvention_id']):
            resultat.pop('lien', None)
    if resultat.get('contrat_id'):
        from blueprints.infos_salaries import _est_salarie_visible
        row = conn.execute('SELECT user_id FROM contrats WHERE id=?', (resultat['contrat_id'],)).fetchone()
        if not row or not _est_salarie_visible(conn, row['user_id']):
            resultat.pop('lien', None)
    plan, erreur = None, data.get('erreur', '')
    if data.get('analyse') and doc['statut'] != 'traite':
        try:
            plan = preparer(conn, user, data)
        except AssistantErreur as exc:
            # Une extraction incohérente ou une cible devenue inaccessible ne
            # doit pas masquer les autres PDF, ni empêcher un réexamen.
            erreur = exc.message
    commentaire = '\n'.join([data['commentaire'], *data.get('complements', [])]).strip()
    return {'id': doc['id'], 'nom': data['nom'], 'commentaire': commentaire,
            'statut': doc['statut'], 'revision': doc['revision'],
            'en_cours': bool(doc['en_cours'] and doc['verrou_jusqua'] > instant()),
            'pdf': url_for('assistant_bp.document_pdf', identifiant=doc['id']),
            'type': data.get('analyse', {}).get('type'), 'analyse': data.get('analyse'),
            'resultat': resultat, 'erreur': erreur,
            'questions': plan['questions'] if plan else [], 'choix': plan['choix'] if plan else {},
            'champs': plan['champs'] if plan else {}, 'autorise': plan['autorise'] if plan else False,
            'cree_le': doc['cree_le']}


def lire(identifiant):
    with transaction() as conn:
        user = compte(conn)
        doc, data = _document(conn, user, identifiant)
        return _public(conn, user, doc, data)


def lister():
    with transaction() as conn:
        user = compte(conn)
        rows = conn.execute('''SELECT * FROM assistant_documents WHERE user_id=?
            ORDER BY cree_le DESC,rowid DESC LIMIT 50''', (user['id'],)).fetchall()
        return [_public(conn, user, dict(r), decoder(r['contenu'])) for r in rows]


def recevoir(fichier, commentaire, model):
    if not isinstance(commentaire, str) or len(commentaire) > 2000:
        raise AssistantErreur('Le commentaire doit contenir au maximum 2 000 caractères.')
    if not fichier or not fichier.filename or not fichier.filename.lower().endswith('.pdf'):
        raise AssistantErreur('Déposez un fichier PDF numérique original, et non un scan.')
    if not isinstance(model, str) or len(model) > 100:
        raise AssistantErreur('Modèle invalide.')
    if model:
        cle_pour(model)
    contenu = fichier.read(MAX_PDF + 1)
    pages = extraire_pdf(contenu)
    empreinte = hashlib.sha256(contenu).hexdigest()
    cree = None
    try:
        with transaction() as conn:
            user = compte(conn)
            ancien = conn.execute('SELECT id FROM assistant_documents WHERE user_id=? AND empreinte=?',
                                  (user['id'], empreinte)).fetchone()
            if ancien:
                identifiant = ancien['id']
            else:
                identifiant = str(uuid.uuid4())
                nom = secure_filename(fichier.filename)[:200] or 'document.pdf'
                path = enregistrer_pdf(contenu, identifiant)
                cree = chemin_document(path)
                data = {'nom': nom, 'commentaire': commentaire.strip(), 'pages': pages}
                conn.execute('''INSERT INTO assistant_documents
                    (id,user_id,empreinte,fichier_path,contenu,cree_le,actualise_le)
                    VALUES (?,?,?,?,?,?,?)''',
                    (identifiant, user['id'], empreinte, path, encoder(data), instant(), instant()))
    except Exception:
        if cree:
            nettoyer_creations([cree])
        raise
    if model:
        return analyser_document(identifiant, model)
    return lire(identifiant)


def analyser_document(identifiant, model, commentaire=None, type_document=None):
    cle_pour(model)
    correction = commentaire is not None or type_document is not None
    if commentaire is not None and (not isinstance(commentaire, str) or len(commentaire) > 2000):
        raise AssistantErreur('La précision doit contenir au maximum 2 000 caractères.')
    if type_document is not None and (not isinstance(type_document, str) or type_document not in TYPES):
        raise AssistantErreur('Type de document invalide.')
    with transaction() as conn:
        user = compte(conn)
        doc, data = _document(conn, user, identifiant)
        if data.get('analyse') and not correction:
            return _public(conn, user, doc, data)
        if correction and any(k in data.get('resultat', {}) for k in ('facture_id', 'subvention_id', 'contrat_id')):
            raise AssistantErreur('Un dossier métier est déjà rattaché. Les corrections se font dans son module.', 409)
        if doc['en_cours'] and doc['verrou_jusqua'] > instant():
            raise AssistantErreur('L’analyse de ce document est déjà en cours.', 409)
        _, quota, _ = preparer_compte(conn)
        if quota['tours'] >= MAX_TOURS_JOUR:
            raise AssistantErreur('La limite de 30 demandes par jour est atteinte. Réessayez demain.', 429)
        if correction:
            complements = data.setdefault('complements', [])
            if len(complements) >= 10:
                raise AssistantErreur('Ce document a déjà reçu dix réexamens. Poursuivez dans le module concerné.', 409)
            note = (commentaire or '').strip()
            if type_document:
                note += '\nType de document précisé par l’utilisateur : ' + type_document
            complements.append(note.strip())
            _sauver(conn, doc, data)
            doc['revision'] += 1
        conn.execute('UPDATE assistant_etats SET tours=tours+1 WHERE user_id=?', (user['id'],))
        token, scope = str(uuid.uuid4()), perimetre(conn, user)
        conn.execute('UPDATE assistant_documents SET en_cours=?,verrou_jusqua=? WHERE id=?',
                     (token, instant() + 180, doc['id']))
    try:
        commentaire_effectif = '\n'.join([data['commentaire'], *data.get('complements', [])])
        analyse = analyser(data['pages'], commentaire_effectif, model)
        if type_document:
            if analyse['type'] != type_document:
                raise AssistantErreur('L’analyse ne correspond pas au type précisé. Vérifiez le PDF ou complétez le commentaire.', 502)
            analyse['confiance'] = 1
        with transaction() as conn:
            user = compte(conn)
            actuel, data = _document(conn, user, identifiant)
            if (actuel['revision'] != doc['revision'] or actuel['en_cours'] != token
                    or actuel['verrou_jusqua'] <= instant() or perimetre(conn, user) != scope):
                raise AssistantErreur('Vos droits ou le document ont changé. Rechargez avant de réessayer.', 409)
            if data.get('analyse'):
                data.setdefault('analyses_precedentes', []).append(data['analyse'])
            data.update(analyse=analyse, reponses={}, resultat={}, erreur='')
            _sauver(conn, actuel, data, 'analyse')
            conn.execute('UPDATE assistant_documents SET en_cours=NULL,verrou_jusqua=0 WHERE id=?', (doc['id'],))
        return traiter(identifiant)
    except Exception as exc:
        with transaction() as conn:
            conn.execute('''UPDATE assistant_documents SET en_cours=NULL,verrou_jusqua=0
                WHERE id=? AND en_cours=?''', (doc['id'], token))
        if isinstance(exc, AssistantErreur):
            raise
        raise AssistantErreur('L’analyse n’a pas abouti. Le PDF reste disponible dans la boîte de réception.', 503) from None


def valider_reponses(typ, reponses):
    ids = {'facture': {'affectation'}, 'convention': {'subvention_id', 'assignees', 'etapes'},
           'notification': {'subvention_id', 'assignees', 'etapes'}, 'contrat': {'salarie_id'}}
    if (not isinstance(reponses, dict) or set(reponses) - (set(CHAMPS[typ]) | ids.get(typ, set()) | {'confirmer_type'})):
        raise AssistantErreur('Précisions documentaires invalides.')
    for cle, v in reponses.items():
        if cle == 'confirmer_type':
            if not isinstance(v, bool):
                raise AssistantErreur('Confirmation invalide.')
        elif cle in ('subvention_id', 'salarie_id'):
            if cle == 'subvention_id' and v == 'nouvelle':
                continue
            if type(v) is not int or v < 1:
                raise AssistantErreur('Identifiant invalide.')
        elif cle == 'assignees':
            if (not isinstance(v, list) or len(v) > 2 or any(type(i) is not int or i < 1 for i in v)
                    or len(set(v)) != len(v)):
                raise AssistantErreur('Choisissez au maximum deux salariés distincts.')
        elif cle == 'etapes':
            if not isinstance(v, list) or len(v) > 30:
                raise AssistantErreur('La liste des échéances est invalide.')
            for e in v:
                if (not isinstance(e, dict) or set(e) != {'nom', 'date_echeance'}
                        or not isinstance(e['nom'], str) or not 1 <= len(e['nom'].strip()) <= 200
                        or not date_iso(e['date_echeance'])):
                    raise AssistantErreur('Chaque échéance doit avoir un libellé et une date.')
        elif v is not None and (not isinstance(v, (str, float, int)) or isinstance(v, bool) or len(str(v)) > 500):
            raise AssistantErreur('Valeur de précision invalide.')


def traiter(identifiant, revision=None, reponses=None):
    copies = []
    try:
        with transaction() as conn:
            user = compte(conn)
            doc, data = _document(conn, user, identifiant)
            if doc['statut'] == 'traite':
                if reponses:
                    valider_reponses(data['analyse']['type'], reponses)
                    if any(data.get('reponses', {}).get(k) != v for k, v in reponses.items()):
                        raise AssistantErreur('Ce document est déjà traité. Les corrections se font dans le module concerné.', 409)
                return _public(conn, user, doc, data)
            if revision is not None and (type(revision) is not int or doc['revision'] != revision):
                raise AssistantErreur('Cette analyse a changé. Rechargez le document.', 409)
            if not data.get('analyse'):
                raise AssistantErreur('Analysez d’abord le PDF.', 409)
            typ = data['analyse']['type']
            if reponses is not None:
                valider_reponses(typ, reponses)
                data.setdefault('reponses', {}).update(reponses)
            plan = preparer(conn, user, data)
            statut = 'precision'
            if typ in ('autre', 'arret_maladie'):
                data['resultat'] = {'message': data['analyse']['resume']}
                if typ == 'arret_maladie':
                    data['resultat']['lien'] = url_for('absences_bp.absences')
                statut = 'traite'
            elif not plan['autorise']:
                data['resultat'] = {'message': 'Analyse disponible. Votre profil ne permet pas cette création ; transmettez le document à un gestionnaire autorisé.'}
                statut = 'analyse'
            elif not plan['questions']:
                data['resultat'] = appliquer(conn, user, doc, data, plan, copies)
                statut = 'traite'
            data['erreur'] = ''
            _sauver(conn, doc, data, statut)
    except FicheVerrouillee:
        nettoyer_creations(copies)
        raise AssistantErreur('Le contrat modifierait une fiche mensuelle verrouillée. Vérifiez le dossier salarié avant de poursuivre.', 409) from None
    except Exception:
        nettoyer_creations(copies)
        raise
    return lire(identifiant)


def texte_pour_question(conn, user, identifiant, question):
    doc, data = _document(conn, user, identifiant)
    mots = set(re.findall(r'\w{3,}', question.casefold()))
    pages = sorted(data['pages'], key=lambda p: len(mots & set(re.findall(r'\w{3,}', p['texte'].casefold()))), reverse=True)[:3]
    return [{'titre': f"{data['nom']} · page {p['page']}", 'texte': p['texte'][:6000],
             'lien': url_for('assistant_bp.document_pdf', identifiant=doc['id']) + f"#page={p['page']}"}
            for p in pages if p['texte'].strip()]
