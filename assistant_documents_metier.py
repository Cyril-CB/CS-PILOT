"""Actions documentaires fermées : créations uniquement, pièces existantes conservées."""
from datetime import date
from pathlib import Path
import hashlib

from flask import url_for

from access_log import journaliser_action, ACTION_AJOUT_CONTRAT
from assistant_documents_analyse import TYPES, date_iso, nombre, normaliser
from assistant_pdf import chemin_document, copier_piece
from assistant_stockage import AssistantErreur
from database import DATA_DIR
from factures_import import enregistrer_import
from stockage_restaure import resoudre_fichier


def _actifs(conn):
    return [dict(r) for r in conn.execute("SELECT id,nom,prenom FROM users WHERE actif=1 AND profil!='prestataire' ORDER BY nom,prenom")]


def _nom_personne(p):
    return normaliser(p['prenom'] + ' ' + p['nom'])


def _subventions(conn, user):
    if user['profil'] in ('directeur', 'comptable'):
        return conn.execute('SELECT * FROM subventions ORDER BY id').fetchall()
    return conn.execute('''SELECT * FROM subventions WHERE assignee_1_id=? OR assignee_2_id=?
        OR id IN (SELECT subvention_id FROM subventions_sous_elements WHERE assignee_id=?)
        ORDER BY id''', (user['id'],) * 3).fetchall()


def _champ(champs, questions, nom, label, genre='texte'):
    valeur = champs.get(nom)
    try:
        if genre == 'date':
            valeur = date_iso(valeur)
        elif genre == 'nombre':
            valeur = nombre(valeur)
        elif valeur is not None:
            if not isinstance(valeur, str) or not 1 <= len(valeur.strip()) <= 500:
                valeur = None
            else:
                valeur = valeur.strip()
    except AssistantErreur:
        valeur = None
    if valeur is None:
        questions.append({'champ': nom, 'label': label, 'type': genre, 'obligatoire': True})
    else:
        champs[nom] = valeur


def preparer(conn, user, contenu):
    """Recalcule choix et permissions live ; aucun identifiant proposé par le modèle."""
    a, reponses = contenu['analyse'], contenu.get('reponses', {})
    typ = a['type']
    champs = dict(a['champs'])
    autorises = set(champs) | {'fournisseur', 'numero_facture', 'date_facture', 'date_echeance',
        'montant_ttc', 'description', 'nom', 'annee_action', 'date_notification',
        'montant_demande', 'montant_accorde', 'nom_salarie', 'prenom_salarie', 'type_contrat',
        'date_debut', 'date_fin', 'temps_hebdo', 'forfait', 'nbr_jours'}
    champs.update({k: v for k, v in reponses.items() if k in autorises})
    droits = user['profil'] in ('directeur', 'comptable', 'responsable')
    if typ == 'facture':
        droits = user['profil'] in ('directeur', 'comptable')
    q, choix = [], {}
    plan = {'type': typ, 'champs': champs, 'questions': q, 'choix': choix, 'autorise': droits,
            'etapes': reponses.get('etapes', a['etapes']), 'cible': None}
    if typ in ('autre', 'arret_maladie') or not droits:
        return plan
    if a['confiance'] < 0.9 and not reponses.get('confirmer_type'):
        q.append({'champ': 'confirmer_type', 'type': 'confirmation', 'obligatoire': True,
                  'label': 'Confirmez que ce document est bien de type « ' + TYPES[typ] + ' ».'})
    if typ == 'facture':
        for cle, label, genre in [('fournisseur', 'Fournisseur', 'texte'),
                ('numero_facture', 'Numéro de facture', 'texte'),
                ('date_facture', 'Date de facture', 'date'), ('montant_ttc', 'Montant TTC', 'nombre')]:
            _champ(champs, q, cle, label, genre)
        for cle in ('date_echeance',):
            if champs.get(cle):
                champs[cle] = date_iso(champs[cle])
        secteurs = [dict(r) for r in conn.execute('SELECT id,nom FROM secteurs ORDER BY nom')]
        choix['affectations'] = [{'id': 'direction', 'nom': 'Direction'}] + [
            {'id': str(s['id']), 'nom': s['nom']} for s in secteurs]
        affectation = reponses.get('affectation', a['instructions'].get('affectation'))
        if affectation:
            matches = [s for s in choix['affectations'] if normaliser(s['nom']) == normaliser(affectation)
                       or ('affectation' in reponses and str(s['id']) == str(affectation))]
            if len(matches) == 1:
                plan['affectation'] = matches[0]['id']
            else:
                q.append({'champ': 'affectation', 'label': 'Quel secteur souhaitez-vous utiliser ?',
                          'type': 'affectation', 'obligatoire': True})
        return plan
    if typ in ('convention', 'notification'):
        _champ(champs, q, 'nom', 'Nom de la subvention')
        annee = str(champs.get('annee_action') or '')
        if not (len(annee) == 4 and annee.isdigit() and 1900 <= int(annee) <= 2200):
            q.append({'champ': 'annee_action', 'label': 'Quelle année est financée par ce document ?',
                      'type': 'annee', 'obligatoire': True})
        else:
            champs['annee_action'] = annee
        lignes = _subventions(conn, user)
        exacts = [s for s in lignes if normaliser(s['nom']) == normaliser(champs.get('nom'))
                  and str(s['annee_action'] or '') == annee]
        mots = set(normaliser(champs.get('nom')).split()) - {'de', 'la', 'le', 'les', 'des', 'du'}
        proches = [s for s in lignes if (set(normaliser(s['nom']).split()) & mots)
                   and (not annee or not s['annee_action'] or str(s['annee_action']) == annee)]
        choix['subventions'] = [{'id': s['id'], 'nom': s['nom'], 'annee': s['annee_action']} for s in proches[:20]]
        cible = reponses.get('subvention_id')
        if cible == 'nouvelle':
            plan['cible'] = None
        elif cible is not None:
            cible = next((s for s in lignes if s['id'] == cible), None)
            if cible is None:
                raise AssistantErreur('Subvention inaccessible.', 403)
            if annee and cible['annee_action'] and str(cible['annee_action']) != annee:
                raise AssistantErreur('L’année du dossier choisi ne correspond pas à l’année financée.')
            plan['cible'] = dict(cible)
        elif len(exacts) == 1:
            plan['cible'] = dict(exacts[0])
        elif proches or len(exacts) > 1:
            q.append({'champ': 'subvention_id', 'type': 'subvention', 'obligatoire': True,
                      'label': 'Ce document correspond-il à l’un de ces dossiers, ou faut-il en créer un ?'})
        if plan['cible'] is None:
            choix['salaries'] = _actifs(conn)
            assignees = reponses.get('assignees')
            if assignees is None and a['instructions']['salaries']:
                assignees = []
                for nom in a['instructions']['salaries']:
                    p = [p for p in choix['salaries'] if _nom_personne(p) == normaliser(nom)
                         or normaliser(p['nom'] + ' ' + p['prenom']) == normaliser(nom)]
                    if len(p) == 1:
                        assignees.append(p[0]['id'])
                if len(assignees) != len(a['instructions']['salaries']):
                    assignees = None
            if assignees is None and a['instructions']['sans_salarie']:
                assignees = []
            if assignees is None:
                q.append({'champ': 'assignees', 'label': 'À qui assigner la subvention ? Vous pouvez laisser vide.',
                          'type': 'salaries', 'obligatoire': False})
            else:
                if any(i not in {p['id'] for p in choix['salaries']} for i in assignees):
                    raise AssistantErreur('Salarié assigné introuvable.')
                plan['assignees'] = assignees
        if not plan['etapes'] and 'etapes' not in reponses and not a['instructions']['sans_echeance']:
            q.append({'champ': 'etapes', 'label': 'Y a-t-il des échéances à ajouter ? Vous pouvez laisser vide.',
                      'type': 'etapes', 'obligatoire': False})
        return plan
    from blueprints.infos_salaries import _est_salarie_visible, TYPES_CONTRAT
    choix['salaries'] = [p for p in _actifs(conn) if _est_salarie_visible(conn, p['id'])]
    cible = reponses.get('salarie_id')
    if cible is None:
        matches = [p for p in choix['salaries'] if normaliser(p['nom']) == normaliser(champs.get('nom_salarie'))
                   and normaliser(p['prenom']) == normaliser(champs.get('prenom_salarie'))]
        cible = matches[0]['id'] if len(matches) == 1 else None
    if cible is None:
        q.append({'champ': 'salarie_id', 'label': 'À quel salarié existant rattacher le contrat ?',
                  'type': 'salarie', 'obligatoire': True})
    elif cible not in {p['id'] for p in choix['salaries']}:
        raise AssistantErreur('Salarié inaccessible.', 403)
    plan['salarie_id'] = cible
    _champ(champs, q, 'date_debut', 'Date de début du contrat', 'date')
    if champs.get('type_contrat') not in TYPES_CONTRAT:
        q.append({'champ': 'type_contrat', 'label': 'Type de contrat', 'type': 'contrat', 'obligatoire': True})
    if champs.get('type_contrat') != 'CEE':
        _champ(champs, q, 'temps_hebdo', 'Temps hebdomadaire en heures', 'nombre')
        if champs.get('temps_hebdo') is not None and not 0 < nombre(champs['temps_hebdo']) <= 60:
            raise AssistantErreur('Le temps hebdomadaire doit être compris entre 0 et 60 heures.')
    if champs.get('date_fin'):
        champs['date_fin'] = date_iso(champs['date_fin'])
        if champs.get('date_debut') and champs['date_fin'] < champs['date_debut']:
            raise AssistantErreur('La fin du contrat ne peut pas précéder son début.')
    return plan


def _lien_subvention(sub):
    annee = str(sub.get('annee_action') or '')
    borne = date.today().year
    if not (annee.isdigit() and borne - 3 <= int(annee) <= borne + 2):
        annee = 'toutes'
    return url_for('subventions_bp.gestion_subventions', annee=annee)


def appliquer(conn, user, document, contenu, plan, fichiers_crees):
    """Aucun identifiant ni opération libre issus de l'IA ; transaction déjà verrouillée."""
    typ, c = plan['type'], plan['champs']
    source = chemin_document(document['fichier_path'])
    if typ == 'facture':
        from blueprints.factures import PROFILS_GESTION
        if user['profil'] not in PROFILS_GESTION:
            raise AssistantErreur('La création de factures est réservée à la direction et la comptabilité.', 403)
        c['montant_ttc'] = nombre(c['montant_ttc'])
        existante = conn.execute('''SELECT f.id FROM factures f JOIN fournisseurs p ON p.id=f.fournisseur_id
            WHERE (LOWER(p.nom)=LOWER(?) OR LOWER(p.alias1)=LOWER(?) OR LOWER(p.alias2)=LOWER(?))
            AND f.numero_facture=? AND f.date_facture=? AND f.montant_ttc=?''',
            (c['fournisseur'], c['fournisseur'], c['fournisseur'], c['numero_facture'],
             c['date_facture'], c['montant_ttc'])).fetchone()
        if existante:
            return {'message': 'Cette facture est déjà présente. Aucun doublon créé.',
                    'lien': url_for('factures_bp.liste_factures'), 'facture_id': existante['id']}
        affectation = plan.get('affectation')
        fid = enregistrer_import(conn, source, contenu['nom'], c, user['id'], fichiers_crees,
            secteur_id=int(affectation) if affectation and affectation != 'direction' else None,
            direction=affectation == 'direction')
        return {'message': 'Facture intégrée au circuit habituel. La suite du traitement se fait dans Factures.',
                'lien': url_for('factures_bp.liste_factures'), 'facture_id': fid}
    if typ in ('convention', 'notification'):
        from blueprints.subventions import _peut_modifier, _refus_acces_subvention, STATUT_DEFAUT
        if not _peut_modifier():
            raise AssistantErreur('Création de subvention non autorisée.', 403)
        sub = plan['cible']
        nouveau = sub is None
        if nouveau:
            cat = conn.execute("SELECT id FROM subventions_types WHERE nom=? COLLATE NOCASE", ('_A classer',)).fetchone()
            if not cat:
                type_id = conn.execute('''INSERT INTO subventions_types(nom,couleur,ordre)
                    SELECT ?,'#808080',COALESCE(MAX(ordre),-1)+1 FROM subventions_types''', ('_A classer',)).lastrowid
            else:
                type_id = cat['id']
            ids = (plan.get('assignees', []) + [None, None])[:2]
            sid = conn.execute('''INSERT INTO subventions(nom,groupe,type_id,annee_action,
                date_notification,montant_demande,montant_accorde,assignee_1_id,assignee_2_id)
                VALUES (?,?,?,?,?,?,?,?,?)''', (c['nom'], STATUT_DEFAUT, type_id, str(c['annee_action']),
                date_iso(c.get('date_notification')), nombre(c.get('montant_demande')) or 0,
                nombre(c.get('montant_accorde')) or 0, *ids)).lastrowid
            sub = dict(conn.execute('SELECT * FROM subventions WHERE id=?', (sid,)).fetchone())
        else:
            sid = sub['id']
            if _refus_acces_subvention(conn, sid):
                raise AssistantErreur('Subvention inaccessible.', 403)
        racine = Path(DATA_DIR) / 'documents' / 'subventions'
        chemins = [sub['justificatif_path']] + [r[0] for r in conn.execute(
            'SELECT document_path FROM subventions_sous_elements WHERE subvention_id=? AND document_path IS NOT NULL', (sid,))]
        deja_joint = False
        for chemin in filter(None, chemins):
            resolu = resoudre_fichier(chemin, 'documents/subventions')
            p = Path(resolu) if resolu else None
            if (p and p.resolve().is_relative_to(racine.resolve()) and p.is_file()
                    and p.stat().st_size == source.stat().st_size):
                with p.open('rb') as entree:
                    deja_joint = hashlib.file_digest(entree, 'sha256').hexdigest() == document['empreinte']
                if deja_joint:
                    break
        copie = None if deja_joint else copier_piece(source, racine, 'document.pdf', fichiers_crees)
        ordre = conn.execute('SELECT COALESCE(MAX(ordre),-1)+1 FROM subventions_sous_elements WHERE subvention_id=?', (sid,)).fetchone()[0]
        if copie and not sub['justificatif_path']:
            # Exception explicitement demandée : ajout d'une pièce vide, jamais remplacement.
            conn.execute('UPDATE subventions SET justificatif_path=?,justificatif_nom=? WHERE id=? AND COALESCE(justificatif_path,\'\')=\'\'',
                         (copie.name, contenu['nom'], sid))
        elif copie:
            conn.execute('''INSERT INTO subventions_sous_elements
                (subvention_id,nom,ordre,document_path,document_nom) VALUES (?,?,?,?,?)''',
                (sid, contenu['analyse']['titre'], ordre, copie.name, contenu['nom']))
            ordre += 1
        for etape in plan['etapes']:
            if conn.execute('''SELECT 1 FROM subventions_sous_elements
                    WHERE subvention_id=? AND nom=? AND date_echeance=?''',
                    (sid, etape['nom'], etape['date_echeance'])).fetchone():
                continue
            conn.execute('''INSERT INTO subventions_sous_elements(subvention_id,nom,date_echeance,ordre)
                VALUES (?,?,?,?)''', (sid, etape['nom'], etape['date_echeance'], ordre))
            ordre += 1
        journaliser_action(conn, 'assistant_creation_subvention' if nouveau else 'assistant_piece_subvention',
                           cible_type='subvention', cible_id=sid)
        return {'message': 'Subvention créée et document classé.' if nouveau else 'Document rattaché ; les données existantes sont conservées.',
                'lien': _lien_subvention(sub), 'subvention_id': sid}
    if typ == 'contrat':
        from blueprints.infos_salaries import (_peut_gerer, _est_salarie_visible,
                                               _construire_nom_contrat)
        uid = plan['salarie_id']
        if not _peut_gerer() or not _est_salarie_visible(conn, uid):
            raise AssistantErreur('Salarié inaccessible.', 403)
        lien = url_for('infos_salaries_bp.infos_salaries', user_id=uid)
        duplicate = conn.execute('''SELECT id FROM contrats WHERE user_id=? AND type_contrat=? AND date_debut=?
            AND COALESCE(date_fin,'')=COALESCE(?,'') AND COALESCE(temps_hebdo,0)=COALESCE(?,0)''',
            (uid, c['type_contrat'], c['date_debut'], c.get('date_fin'), nombre(c.get('temps_hebdo')))).fetchone()
        if duplicate:
            return {'message': 'Un contrat correspondant existe déjà. Vérifiez sa fiche ; aucun contrat existant modifié.',
                    'lien': lien, 'contrat_id': duplicate['id']}
        p = conn.execute('SELECT nom,prenom FROM users WHERE id=?', (uid,)).fetchone()
        nom = _construire_nom_contrat(c['date_debut'], p['nom'], p['prenom'], c['type_contrat'], '.pdf')
        copie = copier_piece(source, Path(DATA_DIR) / 'documents', nom, fichiers_crees)
        cid = conn.execute('''INSERT INTO contrats(user_id,type_contrat,date_debut,date_fin,
            temps_hebdo,forfait,nbr_jours,fichier_path,fichier_nom,saisi_par) VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (uid, c['type_contrat'], c['date_debut'], c.get('date_fin'), nombre(c.get('temps_hebdo')),
             c.get('forfait'), nombre(c.get('nbr_jours')), copie.name, contenu['nom'], user['id'])).lastrowid
        journaliser_action(conn, ACTION_AJOUT_CONTRAT, cible_type='user', cible_id=uid,
                           details='origine=assistant_reception')
        return {'message': 'Contrat ajouté au salarié. Contrôlez les informations dans sa fiche.',
                'lien': lien, 'contrat_id': cid}
    raise AssistantErreur('Ce type de document ne permet aucune création métier.')
