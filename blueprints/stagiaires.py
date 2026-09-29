"""Suivi des stagiaires : fiche, tuteur et emploi du temps par demi-journée.

Direction, comptabilité et responsables consultent et tiennent les fiches de
tous les stagiaires : un stagiaire passe d'un secteur à l'autre pendant son
stage, son emploi du temps se construit donc à plusieurs. Les autres profils
n'y ont pas accès, même par URL directe.

Chaque demi-journée est rattachée au secteur qui accueille le stagiaire ; le
responsable de ce secteur en est averti dans son fil d'actions
(`dashboard_actions._stagiaires_attendus`).
"""
from contextlib import closing
import logging
import sqlite3

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, session, url_for)

from database import get_db
from sessions_securite import verifier_action
import stagiaires as service
from utils import aujourd_hui, login_required, maintenant

stagiaires_bp = Blueprint('stagiaires_bp', __name__)
logger = logging.getLogger(__name__)

_ERREUR_TECHNIQUE = 'Enregistrement impossible. Réessayez dans un instant.'


def _autoriser():
    if session.get('profil') not in service.GESTIONNAIRES:
        abort(403)


def _horodatage():
    return maintenant().strftime('%Y-%m-%d %H:%M:%S')


def _stagiaire(conn, stagiaire_id):
    stagiaire = conn.execute('SELECT * FROM stagiaires WHERE id = ?',
                             (stagiaire_id,)).fetchone()
    if stagiaire is None:
        abort(404)
    return stagiaire


def _tuteurs(conn, tuteur_actuel=None):
    """Comptes proposés comme tuteur : les comptes actifs du centre.

    Le tuteur déjà désigné reste proposé si son compte a été désactivé depuis,
    pour que la fiche puisse être corrigée sans changer de tuteur.
    """
    return conn.execute(
        '''SELECT u.id, u.nom, u.prenom, u.actif, se.nom AS secteur
           FROM users u LEFT JOIN secteurs se ON se.id = u.secteur_id
           WHERE (u.actif = 1 AND u.profil != 'prestataire') OR u.id = ?
           ORDER BY u.nom COLLATE NOCASE, u.prenom COLLATE NOCASE''',
        (tuteur_actuel,)
    ).fetchall()


def _secteurs(conn):
    return conn.execute('SELECT id, nom FROM secteurs ORDER BY nom COLLATE NOCASE').fetchall()


def _page_fiche(conn, stagiaire=None, valeurs=None, erreur=None, statut=200,
                grille_saisie=None):
    """Formulaire de création, ou fiche complète avec l'emploi du temps.

    `grille_saisie` : formulaire d'emploi du temps refusé, réaffiché tel que
    saisi pour que la correction ne fasse pas tout reprendre.
    """
    jours, creneaux, nb_renseignes = [], {}, 0
    if stagiaire is not None:
        jours = [{'date': j, 'libelle': service.libelle_jour(j),
                  'week_end': j.weekday() >= 5,
                  'champs': {cle: service.nom_champ(j, cle)
                             for cle, _ in service.DEMI_JOURNEES}}
                 for j in service.jours_du_stage(stagiaire['date_debut'],
                                                 stagiaire['date_fin'])]
        for r in conn.execute(
                '''SELECT c.date, c.demi_journee, c.secteur_id
                   FROM stagiaires_creneaux c
                   JOIN secteurs se ON se.id = c.secteur_id
                   WHERE c.stagiaire_id = ?''', (stagiaire['id'],)):
            creneaux[(r['date'], r['demi_journee'])] = r['secteur_id']
        nb_renseignes = len(creneaux)
        if grille_saisie is not None:
            creneaux = {}
            for jour in jours:
                for cle, champ in jour['champs'].items():
                    secteur_id = service.lire_identifiant(grille_saisie.get(champ))
                    if secteur_id is not None:
                        creneaux[(jour['date'].isoformat(), cle)] = secteur_id
    return render_template(
        'stagiaire_fiche.html',
        stagiaire=stagiaire,
        valeurs=valeurs if valeurs is not None else (stagiaire or {}),
        erreur=erreur,
        tuteurs=_tuteurs(conn, stagiaire['tuteur_id'] if stagiaire else None),
        secteurs=_secteurs(conn),
        jours=jours,
        creneaux=creneaux,
        nb_renseignes=nb_renseignes,
        demi_journees=service.DEMI_JOURNEES,
        suggestions_etudes=service.SUGGESTIONS_ETUDES,
        max_jours=service.MAX_JOURS_STAGE,
        limites={'nom': service.MAX_NOM, 'etudes': service.MAX_ETUDES,
                 'etablissement': service.MAX_ETABLISSEMENT},
    ), statut


def _ouvrir_ecriture(conn):
    """Verrou d'écriture, puis session et profil revérifiés sous ce verrou.

    Renvoie la réponse à retourner telle quelle si la session n'est plus
    valable ; lève 403 si le profil ne l'autorise plus.
    """
    conn.execute('BEGIN IMMEDIATE')
    erreur = verifier_action(conn)
    if erreur is not None:
        conn.rollback()
        return erreur
    if session.get('profil') not in service.GESTIONNAIRES:
        conn.rollback()
        abort(403)
    return None


@stagiaires_bp.route('/stagiaires')
@login_required
def liste():
    """Stagiaires en cours, à venir et terminés."""
    _autoriser()
    today = aujourd_hui().isoformat()
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''SELECT s.id, s.nom, s.prenom, s.etudes, s.etablissement,
                      s.date_debut, s.date_fin,
                      t.prenom AS tuteur_prenom, t.nom AS tuteur_nom
               FROM stagiaires s LEFT JOIN users t ON t.id = s.tuteur_id'''
        ).fetchall()
        secteurs = {}
        for r in conn.execute(
                '''SELECT DISTINCT c.stagiaire_id, se.nom
                   FROM stagiaires_creneaux c JOIN secteurs se ON se.id = c.secteur_id
                   ORDER BY se.nom COLLATE NOCASE'''):
            secteurs.setdefault(r['stagiaire_id'], []).append(r['nom'])

    en_cours = sorted((r for r in rows if r['date_debut'] <= today <= r['date_fin']),
                      key=lambda r: (r['date_fin'], r['nom'], r['prenom']))
    a_venir = sorted((r for r in rows if r['date_debut'] > today),
                     key=lambda r: (r['date_debut'], r['nom'], r['prenom']))
    termines = sorted((r for r in rows if r['date_fin'] < today),
                      key=lambda r: (r['date_fin'], r['nom'], r['prenom']), reverse=True)
    return render_template('stagiaires_liste.html',
                           groupes=[('En cours', en_cours), ('À venir', a_venir)],
                           termines=termines, secteurs=secteurs,
                           aucun=not rows)


@stagiaires_bp.route('/stagiaires/nouveau', methods=['GET', 'POST'])
@login_required
def nouveau():
    """Création de la fiche ; l'emploi du temps se remplit ensuite sur la fiche."""
    _autoriser()
    with closing(get_db()) as conn:
        if request.method == 'GET':
            return _page_fiche(conn, valeurs={})
        try:
            refus = _ouvrir_ecriture(conn)
            if refus is not None:
                return refus
            v = service.valider_fiche(request.form, conn)
            curseur = conn.execute(
                '''INSERT INTO stagiaires (nom, prenom, etudes, etablissement, tuteur_id,
                                           date_debut, date_fin, cree_par, cree_le)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (v['nom'], v['prenom'], v['etudes'], v['etablissement'], v['tuteur_id'],
                 v['date_debut'], v['date_fin'], session['user_id'], _horodatage()))
            stagiaire_id = curseur.lastrowid
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            return _page_fiche(conn, valeurs=request.form, erreur=str(exc), statut=400)
        except sqlite3.Error:
            conn.rollback()
            logger.error('Création de la fiche stagiaire impossible', exc_info=True)
            return _page_fiche(conn, valeurs=request.form, erreur=_ERREUR_TECHNIQUE, statut=503)
    flash('Stagiaire enregistré. Indiquez maintenant les secteurs qui l’accueillent, '
          'demi-journée par demi-journée.', 'success')
    return redirect(url_for('stagiaires_bp.fiche', stagiaire_id=stagiaire_id,
                            _anchor='emploi-du-temps'))


@stagiaires_bp.route('/stagiaires/<int:stagiaire_id>')
@login_required
def fiche(stagiaire_id):
    _autoriser()
    with closing(get_db()) as conn:
        return _page_fiche(conn, _stagiaire(conn, stagiaire_id))


@stagiaires_bp.route('/stagiaires/<int:stagiaire_id>/informations', methods=['POST'])
@login_required
def modifier(stagiaire_id):
    """Modifie la fiche. Les demi-journées sorties de la période sont retirées."""
    _autoriser()
    with closing(get_db()) as conn:
        try:
            refus = _ouvrir_ecriture(conn)
            if refus is not None:
                return refus
            stagiaire = _stagiaire(conn, stagiaire_id)
            v = service.valider_fiche(request.form, conn, tuteur_actuel=stagiaire['tuteur_id'])
            conn.execute(
                '''UPDATE stagiaires SET nom = ?, prenom = ?, etudes = ?, etablissement = ?,
                          tuteur_id = ?, date_debut = ?, date_fin = ?,
                          modifie_par = ?, modifie_le = ?
                   WHERE id = ?''',
                (v['nom'], v['prenom'], v['etudes'], v['etablissement'], v['tuteur_id'],
                 v['date_debut'], v['date_fin'], session['user_id'], _horodatage(),
                 stagiaire_id))
            retires = conn.execute(
                '''DELETE FROM stagiaires_creneaux
                   WHERE stagiaire_id = ? AND (date < ? OR date > ?)''',
                (stagiaire_id, v['date_debut'], v['date_fin'])).rowcount
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            return _page_fiche(conn, _stagiaire(conn, stagiaire_id), valeurs=request.form,
                               erreur=str(exc), statut=400)
        except sqlite3.Error:
            conn.rollback()
            logger.error('Modification de la fiche stagiaire impossible', exc_info=True)
            return _page_fiche(conn, _stagiaire(conn, stagiaire_id), valeurs=request.form,
                               erreur=_ERREUR_TECHNIQUE, statut=503)
    message = 'Fiche du stagiaire enregistrée.'
    if retires:
        message += (f" {retires} demi-journée{'s' if retires > 1 else ''} hors de la "
                    f"nouvelle période {'ont été retirées' if retires > 1 else 'a été retirée'}"
                    " de l’emploi du temps.")
    flash(message, 'success')
    return redirect(url_for('stagiaires_bp.fiche', stagiaire_id=stagiaire_id))


@stagiaires_bp.route('/stagiaires/<int:stagiaire_id>/emploi-du-temps', methods=['POST'])
@login_required
def emploi_du_temps(stagiaire_id):
    """Remplace l'emploi du temps par les demi-journées envoyées."""
    _autoriser()
    with closing(get_db()) as conn:
        try:
            refus = _ouvrir_ecriture(conn)
            if refus is not None:
                return refus
            stagiaire = _stagiaire(conn, stagiaire_id)
            jours = service.jours_du_stage(stagiaire['date_debut'], stagiaire['date_fin'])
            secteurs_ids = {r['id'] for r in _secteurs(conn)}
            creneaux = service.lire_emploi_du_temps(request.form, jours, secteurs_ids)
            conn.execute('DELETE FROM stagiaires_creneaux WHERE stagiaire_id = ?',
                         (stagiaire_id,))
            conn.executemany(
                '''INSERT INTO stagiaires_creneaux (stagiaire_id, date, demi_journee, secteur_id)
                   VALUES (?, ?, ?, ?)''',
                [(stagiaire_id, jour, demi, secteur) for jour, demi, secteur in creneaux])
            conn.execute('UPDATE stagiaires SET modifie_par = ?, modifie_le = ? WHERE id = ?',
                         (session['user_id'], _horodatage(), stagiaire_id))
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            return _page_fiche(conn, _stagiaire(conn, stagiaire_id), erreur=str(exc),
                               statut=400, grille_saisie=request.form)
        except sqlite3.Error:
            conn.rollback()
            logger.error('Enregistrement de l’emploi du temps impossible', exc_info=True)
            return _page_fiche(conn, _stagiaire(conn, stagiaire_id),
                               erreur=_ERREUR_TECHNIQUE, statut=503)
    nb = len(creneaux)
    flash(f"Emploi du temps enregistré : {nb} demi-journée{'s' if nb > 1 else ''} "
          f"au centre.", 'success')
    return redirect(url_for('stagiaires_bp.fiche', stagiaire_id=stagiaire_id,
                            _anchor='emploi-du-temps'))


@stagiaires_bp.route('/stagiaires/<int:stagiaire_id>/supprimer', methods=['POST'])
@login_required
def supprimer(stagiaire_id):
    """Supprime la fiche et son emploi du temps."""
    _autoriser()
    with closing(get_db()) as conn:
        try:
            refus = _ouvrir_ecriture(conn)
            if refus is not None:
                return refus
            _stagiaire(conn, stagiaire_id)
            conn.execute('DELETE FROM stagiaires_creneaux WHERE stagiaire_id = ?',
                         (stagiaire_id,))
            conn.execute('DELETE FROM stagiaires WHERE id = ?', (stagiaire_id,))
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            logger.error('Suppression de la fiche stagiaire impossible', exc_info=True)
            flash(_ERREUR_TECHNIQUE, 'error')
            return redirect(url_for('stagiaires_bp.fiche', stagiaire_id=stagiaire_id))
    flash('Fiche du stagiaire supprimée, emploi du temps compris.', 'success')
    return redirect(url_for('stagiaires_bp.liste'))
