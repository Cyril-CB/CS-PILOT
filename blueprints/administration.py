"""
Blueprint administration_bp - Page d'administration systeme.
Gestion des migrations de base de donnees et informations systeme.
Accessible uniquement aux directeurs et comptables.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from utils import login_required
from database import get_db
import os

administration_bp = Blueprint('administration_bp', __name__)


def _check_admin():
    """Verifie que l'utilisateur est directeur ou comptable."""
    return session.get('profil') in ('directeur', 'comptable')


@administration_bp.route('/administration')
@login_required
def administration():
    """Page principale d'administration systeme."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    from migration_manager import get_statut_complet

    statut_migrations = get_statut_complet()
    version_db = statut_migrations.get('version_actuelle', '0000')
    version_app = f"1.0.{version_db}"

    # Informations sur la base de donnees
    db_info = _get_db_info()

    return render_template(
        'administration.html',
        statut=statut_migrations,
        db_info=db_info,
        version_app=version_app
    )


@administration_bp.route('/administration/appliquer_migration', methods=['POST'])
@login_required
def appliquer_migration():
    """Applique une migration specifique."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    version = request.form.get('version')
    if not version:
        flash('Version de migration non specifiee', 'error')
        return redirect(url_for('administration_bp.administration'))

    from migration_manager import appliquer_migration as run_migration
    from app import invalidate_version_cache

    user_name = f"{session.get('prenom', '')} {session.get('nom', '')}"
    success, message = run_migration(version, appliquee_par=user_name)

    if success:
        invalidate_version_cache()
        flash(message, 'success')
    else:
        flash(message, 'error')

    return redirect(url_for('administration_bp.administration'))


@administration_bp.route('/administration/appliquer_toutes', methods=['POST'])
@login_required
def appliquer_toutes():
    """Applique toutes les migrations en attente."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    from migration_manager import appliquer_toutes_en_attente
    from app import invalidate_version_cache

    user_name = f"{session.get('prenom', '')} {session.get('nom', '')}"
    resultats = appliquer_toutes_en_attente(appliquee_par=user_name)

    if not resultats:
        flash('Aucune migration en attente.', 'info')
    else:
        nb_ok = sum(1 for _, success, _ in resultats if success)
        nb_err = sum(1 for _, success, _ in resultats if not success)

        if nb_ok > 0:
            invalidate_version_cache()

        if nb_err == 0:
            flash(f'{nb_ok} migration(s) appliquee(s) avec succes.', 'success')
        else:
            flash(
                f'{nb_ok} migration(s) reussie(s), {nb_err} erreur(s). '
                'Consultez le detail ci-dessous.',
                'error'
            )

    return redirect(url_for('administration_bp.administration'))


@administration_bp.route('/administration/initialiser_baseline', methods=['POST'])
@login_required
def initialiser_baseline():
    """Marque le schema initial comme deja applique (pour bases existantes)."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    from migration_manager import marquer_migration_existante

    marquer_migration_existante(
        '0001',
        'Schema initial',
        'Schema de base marque comme applique (base existante)'
    )
    flash(
        'Schema initial marque comme applique. '
        'Les prochaines migrations pourront etre appliquees normalement.',
        'success'
    )

    return redirect(url_for('administration_bp.administration'))


@administration_bp.route('/administration/reinitialiser_bdd', methods=['POST'])
@login_required
def reinitialiser_bdd():
    """Reinitialise completement la base de donnees (supprime toutes les donnees)."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    # Verification du jeton de confirmation
    if request.form.get('confirmation') != 'REINITIALISER':
        flash('Confirmation invalide. La reinitialisation a ete annulee.', 'error')
        return redirect(url_for('administration_bp.administration'))

    import shutil
    from database import init_db

    # Pour PostgreSQL, supprimer toutes les tables et recréer le schema
    try:
        conn = get_db()
        # Drop all tables in public schema
        tables = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        ).fetchall()
        for row in tables:
            conn.execute(f"DROP TABLE IF EXISTS {row['tablename']} CASCADE")
        conn.commit()
        conn.close()
    except Exception as e:
        flash(f'Erreur lors de la suppression des tables : {e}', 'error')
        return redirect(url_for('administration_bp.administration'))

    # Recreer le schema vide
    init_db()

    # Vider la session (plus d'utilisateur en base)
    session.clear()

    flash('Base de donnees reinitialisee. Veuillez creer un nouveau compte administrateur.', 'success')
    return redirect(url_for('auth.setup'))


def _get_db_info():
    """Recupere les informations sur la base de donnees."""
    info = {
        'fichier': 'PostgreSQL',
        'taille': None,
        'nb_tables': 0,
        'tables': []
    }

    try:
        conn = get_db()
        tables = conn.execute(
            "SELECT table_name as name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
        ).fetchall()
        info['nb_tables'] = len(tables)

        for t in tables:
            count = conn.execute(f"SELECT COUNT(*) as nb FROM [{t['name']}]").fetchone()
            info['tables'].append({
                'nom': t['name'],
                'nb_lignes': count['nb'] if count else 0
            })

        conn.close()
    except Exception:
        pass

    return info
