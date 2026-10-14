"""Besoins d'entretien par lieu, achat externe et notification à la réception."""
from contextlib import closing
import hashlib
import json
import re
import secrets
import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from database import get_db
from entretien import initialiser_catalogue
from sessions_securite import verifier_action
from sites_acces import (a_acces_entretien, compte_interne, entier_id, est_administrateur,
                         gere_site, lieux_entretien, peut_demander_entretien,
                         peut_lire_entretien, sites_geres, texte, utilisateurs_internes)
from utils import login_required

entretien_bp = Blueprint('entretien_bp', __name__)
STATUTS = {'en_cours': 'Demande transmise', 'commandee': 'Commandée',
           'recue': 'Produits disponibles', 'annulee': 'Annulée'}


def _transaction(conn):
    conn.execute('BEGIN IMMEDIATE')
    return verifier_action(conn)


def _note(raw):
    value = (raw or '').strip()
    if len(value) > 1000:
        raise ValueError('Le commentaire est limité à 1 000 caractères.')
    return value


@entretien_bp.route('/produits-entretien', methods=['GET', 'POST'])
@login_required
def liste():
    uid = session['user_id']
    with closing(get_db()) as conn:
        if request.method == 'POST':
            refus = _transaction(conn)
            if refus is not None:
                return refus
        if not a_acces_entretien(conn, uid):
            abort(403)

        if request.method == 'POST':
            try:
                lieu_id = entier_id(request.form.get('lieu_id'))
                if not peut_demander_entretien(conn, uid, lieu_id):
                    abort(403)
                lieu = conn.execute('SELECT * FROM entretien_lieux WHERE id = ?', (lieu_id,)).fetchone()
                if entier_id(request.form.get('lieu_revision')) != lieu['revision']:
                    raise ValueError('Ce lieu a changé. Rechargez son catalogue avant de transmettre vos besoins.')
                cle = request.form.get('cle_envoi', '')
                if not re.fullmatch(r'[a-f0-9]{32}', cle):
                    raise ValueError('Le formulaire a expiré. Rechargez la page.')
                note = _note(request.form.get('commentaire'))
                produits = {p['id']: p for p in conn.execute(
                    'SELECT * FROM entretien_produits WHERE site_id = ? AND actif = 1', (lieu['site_id'],))}
                lignes = []
                for key in request.form:
                    if not key.startswith('quantite_'):
                        continue
                    produit_id = entier_id(key[len('quantite_'):])
                    raw = request.form.get(key, '').strip()
                    if not raw or raw == '0':
                        continue
                    if len(request.form.getlist(key)) != 1 or not re.fullmatch(r'[0-9]{1,4}', raw) or int(raw) < 1:
                        raise ValueError('Chaque quantité doit être un entier compris entre 1 et 9 999.')
                    if produit_id not in produits:
                        raise ValueError('Un produit ne fait plus partie du catalogue de ce site. Rechargez la page.')
                    produit = produits[produit_id]
                    if entier_id(request.form.get(f'revision_produit_{produit_id}')) != produit['revision']:
                        raise ValueError('Le nom ou le conditionnement d’un produit a changé. Rechargez le catalogue avant de transmettre vos besoins.')
                    lignes.append((produit_id, produit['nom'], produit['unite'], int(raw)))
                if not lignes:
                    raise ValueError('Indiquez une quantité pour au moins un produit.')
                empreinte = hashlib.sha256(json.dumps([lieu_id, note, sorted(lignes)], ensure_ascii=False).encode()).hexdigest()
                existante = conn.execute('SELECT * FROM entretien_demandes WHERE cle_envoi = ?', (cle,)).fetchone()
                if existante:
                    if existante['user_id'] != uid or existante['empreinte'] != empreinte:
                        raise ValueError('Ce formulaire a déjà été transmis. Rechargez la page pour une nouvelle demande.')
                else:
                    demande_id = conn.execute('''INSERT INTO entretien_demandes
                        (site_id, lieu_id, lieu_nom, user_id, cle_envoi, empreinte, commentaire)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (lieu['site_id'], lieu_id, lieu['nom'], uid, cle, empreinte, note)).lastrowid
                    conn.executemany('''INSERT INTO entretien_lignes
                        (demande_id, site_id, produit_id, produit_nom, unite, quantite) VALUES (?, ?, ?, ?, ?, ?)''',
                        [(demande_id, lieu['site_id'], *ligne) for ligne in lignes])
                conn.commit()
                flash('Votre demande a été transmise à la personne chargée des commandes.', 'success')
            except (ValueError, sqlite3.IntegrityError) as exc:
                conn.rollback()
                flash(str(exc) if isinstance(exc, ValueError) else 'La demande n’a pas pu être enregistrée. Rechargez la page.', 'error')
            return redirect(url_for('entretien_bp.liste'), code=303)

        lieux = lieux_entretien(conn, uid)
        lieux_demande = [l for l in lieux if peut_demander_entretien(conn, uid, l['id'])]
        raw_lieu = request.args.get('lieu_id')
        selection = None
        if raw_lieu:
            try:
                cible = entier_id(raw_lieu)
            except ValueError:
                abort(400)
            selection = next((l for l in lieux_demande if l['id'] == cible), None)
            if not selection:
                abort(403)
        elif lieux_demande:
            selection = lieux_demande[0]
        produits = conn.execute('SELECT * FROM entretien_produits WHERE site_id = ? AND actif = 1 ORDER BY nom',
                                (selection['site_id'],)).fetchall() if selection else []
        # Filtrage SQL préalable : aucune demande d'un autre périmètre n'est
        # chargée dans le template, ni dans les totaux de préparation.
        demandes = conn.execute('''SELECT d.*, s.nom AS site_nom, s.actif AS site_actif,
                u.prenom, u.nom FROM entretien_demandes d
            JOIN sites s ON s.id = d.site_id JOIN users u ON u.id = d.user_id
            JOIN entretien_lieux l ON l.id = d.lieu_id
            WHERE (? = 1 OR (s.actif = 1 AND EXISTS (
                SELECT 1 FROM sites_responsables_modules r WHERE r.site_id = d.site_id
                AND r.module = 'entretien' AND r.user_id = ?))
                OR (s.actif = 1 AND l.actif = 1 AND l.demandeur_id = ?))
            ORDER BY d.id DESC''', (int(est_administrateur(conn, uid)), uid, uid)).fetchall()
        demandes_data = []
        for demande in demandes:
            item = dict(demande)
            item['peut_gerer'] = gere_site(conn, uid, 'entretien', item['site_id'])
            item['lignes'] = conn.execute('SELECT * FROM entretien_lignes WHERE demande_id = ? ORDER BY produit_nom', (item['id'],)).fetchall()
            demandes_data.append(item)
        regroupements = []
        for site in sites_geres(conn, uid, 'entretien'):
            besoins = [d for d in demandes_data if d['site_id'] == site['id'] and d['statut'] == 'en_cours']
            totaux = {}
            for besoin in besoins:
                for ligne in besoin['lignes']:
                    key = (ligne['produit_id'], ligne['produit_nom'], ligne['unite'])
                    totaux[key] = totaux.get(key, 0) + ligne['quantite']
            if besoins:
                regroupements.append({'site': site, 'besoins': besoins,
                    'lignes': [{'nom': k[1], 'unite': k[2], 'quantite': v} for k, v in sorted(totaux.items(), key=lambda x: x[0][1])]})
        return render_template('entretien.html', lieux_demande=lieux_demande, selection=selection,
            produits=produits, demandes=demandes_data, regroupements=regroupements, statuts=STATUTS,
            cle_envoi=secrets.token_hex(16), peut_configurer=bool(sites_geres(conn, uid, 'entretien')),
            est_admin=est_administrateur(conn, uid))


@entretien_bp.route('/produits-entretien/<int:demande_id>/statut', methods=['POST'])
@login_required
def statut(demande_id):
    with closing(get_db()) as conn:
        refus = _transaction(conn)
        if refus is not None:
            return refus
        demande = conn.execute('SELECT * FROM entretien_demandes WHERE id = ?', (demande_id,)).fetchone()
        if not demande or not gere_site(conn, session['user_id'], 'entretien', demande['site_id']):
            abort(403)
        try:
            cible = request.form.get('statut')
            revision = entier_id(request.form.get('revision'))
            if cible not in ('commandee', 'recue', 'annulee'):
                raise ValueError('Action invalide.')
            # Un double clic/rejeu d'une même transition n'écrit rien et ne
            # renvoie pas une notification déjà marquée lue.
            if demande['statut'] == cible and demande['revision'] == revision + 1:
                return redirect(url_for('entretien_bp.liste'), code=303)
            if demande['revision'] != revision:
                raise ValueError('Cette demande a changé. Rechargez la page.')
            transitions = {'en_cours': ('commandee', 'annulee'), 'commandee': ('recue', 'annulee')}
            if cible not in transitions.get(demande['statut'], ()):
                raise ValueError('Ce changement de statut n’est plus possible.')
            note = _note(request.form.get('reception_note')) if cible == 'recue' else ''
            notifie = False
            conn.execute('''UPDATE entretien_demandes SET statut = ?, revision = revision + 1,
                traite_par = ?, reception_note = ?,
                commandee_at = CASE WHEN ? = 'commandee' THEN CURRENT_TIMESTAMP ELSE commandee_at END,
                recue_at = CASE WHEN ? = 'recue' THEN CURRENT_TIMESTAMP ELSE recue_at END WHERE id = ?''',
                (cible, session['user_id'], note, cible, cible, demande_id))
            if cible == 'recue':
                lieu = conn.execute('SELECT demandeur_id FROM entretien_lieux WHERE id = ?', (demande['lieu_id'],)).fetchone()
                # Le titulaire courant reçoit l'avis, même si la demande avait
                # été saisie par un remplaçant ou avant son attribution.
                destinataire = lieu['demandeur_id']
                if peut_lire_entretien(conn, destinataire, demande):
                    conn.execute('INSERT OR IGNORE INTO entretien_notifications (demande_id, user_id) VALUES (?, ?)',
                                 (demande_id, destinataire))
                    notifie = True
            conn.commit()
            if cible == 'recue':
                flash('Produits disponibles : le responsable du lieu a été notifié.' if notifie else
                      'Produits disponibles. Aucun avis envoyé : vérifiez le lieu et son responsable actif dans les paramètres.',
                      'success' if notifie else 'warning')
            else:
                flash('Le statut de la demande a été mis à jour.', 'success')
        except ValueError as exc:
            conn.rollback()
            flash(str(exc), 'error')
    return redirect(url_for('entretien_bp.liste'), code=303)


@entretien_bp.route('/produits-entretien/commander', methods=['POST'])
@login_required
def commander():
    """Regrouper exactement les demandes affichées, sans absorber une nouvelle saisie."""
    with closing(get_db()) as conn:
        refus = _transaction(conn)
        if refus is not None:
            return refus
        try:
            site_id = entier_id(request.form.get('site_id'))
            if not gere_site(conn, session['user_id'], 'entretien', site_id):
                abort(403)
            ids = {entier_id(v) for v in request.form.getlist('demandes')}
            if not ids or len(ids) > 1000:
                raise ValueError('Sélectionnez entre 1 et 1 000 demandes.')
            demandes = [conn.execute('SELECT * FROM entretien_demandes WHERE id = ?', (did,)).fetchone() for did in ids]
            if any(not d or d['site_id'] != site_id for d in demandes):
                abort(403)
            if all(d['statut'] == 'commandee' for d in demandes):
                return redirect(url_for('entretien_bp.liste'), code=303)
            if any(d['statut'] != 'en_cours' for d in demandes):
                raise ValueError('Une demande a déjà été traitée. Rechargez la liste avant de commander.')
            conn.executemany('''UPDATE entretien_demandes SET statut = 'commandee', commandee_at = CURRENT_TIMESTAMP,
                revision = revision + 1, traite_par = ? WHERE id = ?''', [(session['user_id'], did) for did in ids])
            conn.commit()
            flash('Les demandes regroupées ont été marquées commandées.', 'success')
        except ValueError as exc:
            conn.rollback()
            flash(str(exc), 'error')
    return redirect(url_for('entretien_bp.liste'), code=303)


@entretien_bp.route('/produits-entretien/<int:demande_id>/lu', methods=['POST'])
@login_required
def lire_notification(demande_id):
    with closing(get_db()) as conn:
        refus = _transaction(conn)
        if refus is not None:
            return refus
        demande = conn.execute('SELECT * FROM entretien_demandes WHERE id = ?', (demande_id,)).fetchone()
        if not demande or not peut_lire_entretien(conn, session['user_id'], demande):
            abort(403)
        conn.execute('''UPDATE entretien_notifications SET lu_le = CURRENT_TIMESTAMP
            WHERE demande_id = ? AND user_id = ? AND lu_le IS NULL''', (demande_id, session['user_id']))
        conn.commit()
    return redirect(url_for('entretien_bp.liste'), code=303)


@entretien_bp.route('/produits-entretien/parametres', methods=['GET', 'POST'])
@login_required
def parametres():
    uid = session['user_id']
    with closing(get_db()) as conn:
        if request.method == 'POST':
            refus = _transaction(conn)
            if refus is not None:
                return refus
        sites = sites_geres(conn, uid, 'entretien')
        if not sites:
            abort(403)
        try:
            raw_site = request.form.get('site_id') if request.method == 'POST' else request.args.get('site_id')
            site_id = entier_id(raw_site) if raw_site else sites[0]['id']
        except ValueError:
            abort(400)
        if not gere_site(conn, uid, 'entretien', site_id):
            abort(403)
        if request.method == 'POST':
            try:
                action = request.form.get('action')
                if action == 'catalogue_initial':
                    initialiser_catalogue(conn, site_id)
                elif action in ('lieu', 'produit'):
                    nom = texte(request.form.get('nom'), 100 if action == 'lieu' else 150, 'Le nom')
                    table = 'entretien_lieux' if action == 'lieu' else 'entretien_produits'
                    element_id = entier_id(request.form['id']) if request.form.get('id') else None
                    if element_id:
                        element = conn.execute(f'SELECT * FROM {table} WHERE id = ? AND site_id = ?', (element_id, site_id)).fetchone()
                        if not element:
                            abort(403)
                        if element['revision'] != entier_id(request.form.get('revision')):
                            raise ValueError('Cet élément a changé. Rechargez la page.')
                    actif = int(not element_id or request.form.get('actif') == '1')
                    if action == 'lieu':
                        demandeur_id = entier_id(request.form.get('demandeur_id'))
                        if not compte_interne(conn, demandeur_id):
                            raise ValueError('Le demandeur doit être un compte interne actif.')
                        if element_id:
                            conn.execute('UPDATE entretien_lieux SET nom = ?, demandeur_id = ?, actif = ?, revision = revision + 1 WHERE id = ?',
                                         (nom, demandeur_id, actif, element_id))
                        else:
                            conn.execute('INSERT INTO entretien_lieux (site_id, nom, demandeur_id) VALUES (?, ?, ?)', (site_id, nom, demandeur_id))
                    else:
                        unite = texte(request.form.get('unite'), 40, 'L’unité')
                        if element_id:
                            conn.execute('UPDATE entretien_produits SET nom = ?, unite = ?, actif = ?, revision = revision + 1 WHERE id = ?',
                                         (nom, unite, actif, element_id))
                        else:
                            conn.execute('INSERT INTO entretien_produits (site_id, nom, unite) VALUES (?, ?, ?)', (site_id, nom, unite))
                else:
                    raise ValueError('Action inconnue.')
                conn.commit()
                flash('Les paramètres des produits d’entretien ont été enregistrés.', 'success')
            except (ValueError, sqlite3.IntegrityError) as exc:
                conn.rollback()
                flash(str(exc) if isinstance(exc, ValueError) else 'Ce nom est déjà utilisé sur ce site.', 'error')
            return redirect(url_for('entretien_bp.parametres', site_id=site_id), code=303)
        return render_template('entretien_parametres.html', sites=sites, site_id=site_id,
            lieux=conn.execute('SELECT * FROM entretien_lieux WHERE site_id = ? ORDER BY nom', (site_id,)).fetchall(),
            produits=conn.execute('SELECT * FROM entretien_produits WHERE site_id = ? ORDER BY nom', (site_id,)).fetchall(),
            utilisateurs=utilisateurs_internes(conn))
