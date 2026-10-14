"""Administration des sites physiques et des responsables par module."""
from contextlib import closing
import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from database import get_db
from sessions_securite import verifier_action
from sites_acces import MODULES, entier_id, est_administrateur, texte, utilisateurs_internes
from utils import login_required

sites_bp = Blueprint('sites_bp', __name__)


@sites_bp.route('/sites', methods=['GET', 'POST'])
@login_required
def gestion():
    with closing(get_db()) as conn:
        if request.method == 'POST':
            conn.execute('BEGIN IMMEDIATE')
            refus = verifier_action(conn)
            if refus is not None:
                return refus
        if not est_administrateur(conn, session['user_id']):
            abort(403)

        if request.method == 'POST':
            try:
                action = request.form.get('action')
                nom = texte(request.form.get('nom'), 100, 'Le nom du site')
                if action == 'creer':
                    conn.execute('INSERT INTO sites (nom) VALUES (?)', (nom,))
                elif action == 'modifier':
                    site_id = entier_id(request.form.get('site_id'))
                    revision = entier_id(request.form.get('revision'))
                    site = conn.execute('SELECT * FROM sites WHERE id = ?', (site_id,)).fetchone()
                    if not site or site['revision'] != revision:
                        raise ValueError('Ce site a changé. Rechargez la page avant de réessayer.')
                    membres = {entier_id(v) for v in request.form.getlist('membres')}
                    responsables = {}
                    for module in MODULES:
                        raw = request.form.get('responsable_' + module)
                        responsables[module] = entier_id(raw) if raw else None
                    internes = {u['id'] for u in utilisateurs_internes(conn)}
                    if not (membres | {u for u in responsables.values() if u}) <= internes:
                        raise ValueError('Sélectionnez uniquement des comptes internes actifs.')
                    conn.execute('UPDATE sites SET nom = ?, actif = ?, revision = revision + 1 WHERE id = ?',
                                 (nom, int(request.form.get('actif') == '1'), site_id))
                    conn.execute('DELETE FROM sites_utilisateurs WHERE site_id = ?', (site_id,))
                    conn.executemany('INSERT INTO sites_utilisateurs (site_id, user_id) VALUES (?, ?)',
                                     [(site_id, uid) for uid in sorted(membres)])
                    conn.execute('DELETE FROM sites_responsables_modules WHERE site_id = ?', (site_id,))
                    conn.executemany('INSERT INTO sites_responsables_modules (site_id, module, user_id) VALUES (?, ?, ?)',
                                     [(site_id, module, uid) for module, uid in responsables.items() if uid])
                else:
                    raise ValueError('Action inconnue.')
                conn.commit()
                flash('Le site et ses accès ont été enregistrés.', 'success')
            except (ValueError, sqlite3.IntegrityError) as exc:
                conn.rollback()
                flash(str(exc) if isinstance(exc, ValueError) else 'Ce nom de site est déjà utilisé.', 'error')
            return redirect(url_for('sites_bp.gestion'), code=303)

        sites = [dict(s) for s in conn.execute('SELECT * FROM sites ORDER BY actif DESC, nom')]
        for site in sites:
            site['membres'] = [r['user_id'] for r in conn.execute('SELECT user_id FROM sites_utilisateurs WHERE site_id = ?', (site['id'],))]
            site['responsables'] = {r['module']: r['user_id'] for r in conn.execute('SELECT module, user_id FROM sites_responsables_modules WHERE site_id = ?', (site['id'],))}
        return render_template('sites.html', sites=sites, utilisateurs=utilisateurs_internes(conn), modules=MODULES)
