"""
Blueprint import_bi_bp - Page dédiée à l'importation et la suppression des fichiers BI.

Fonctionnalités :
- Affichage des années déjà importées avec le premier et dernier mois,
  ou « Complet » quand il y a des écritures du 1er janvier au 31 décembre.
- Import d'un nouveau fichier BI (réutilise /api/bilan/import-bi).
- Suppression d'une année importée (réutilise /api/bilan/annee/<annee>).
- Accessible aux profils directeur et comptable.
"""
from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, flash, jsonify)
from database import get_db
from utils import login_required

import_bi_bp = Blueprint('import_bi_bp', __name__)

NOMS_MOIS = {
    1: 'janvier', 2: 'février', 3: 'mars', 4: 'avril',
    5: 'mai', 6: 'juin', 7: 'juillet', 8: 'août',
    9: 'septembre', 10: 'octobre', 11: 'novembre', 12: 'décembre',
}


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


def _get_annees_importees(conn):
    """Retourne la liste des années importées avec infos premier/dernier mois."""
    annees = conn.execute(
        'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee DESC'
    ).fetchall()

    result = []
    for row in annees:
        annee = row['annee']

        # Premier et dernier mois ayant des écritures pour cette année
        mois_row = conn.execute(
            '''SELECT MIN(mois) as premier_mois, MAX(mois) as dernier_mois,
                      COUNT(DISTINCT mois) as nb_mois
               FROM bilan_fec_donnees
               WHERE annee = ?''',
            (annee,)
        ).fetchone()

        premier_mois = mois_row['premier_mois'] if mois_row else None
        dernier_mois = mois_row['dernier_mois'] if mois_row else None
        nb_mois = mois_row['nb_mois'] if mois_row else 0

        # "Complet" si écritures du 1er janvier (mois 1) au 31 décembre (mois 12)
        if premier_mois == 1 and dernier_mois == 12:
            periode = 'Complet'
        elif premier_mois and dernier_mois:
            p = NOMS_MOIS.get(premier_mois, str(premier_mois))
            d = NOMS_MOIS.get(dernier_mois, str(dernier_mois))
            if premier_mois == dernier_mois:
                periode = p.capitalize()
            else:
                periode = f'{p.capitalize()} → {d}'
        else:
            periode = 'Aucune écriture'

        # Nombre total d'écritures pour l'année
        nb_ecritures_row = conn.execute(
            'SELECT SUM(nb_ecritures) as total FROM bilan_fec_imports WHERE annee = ?',
            (annee,)
        ).fetchone()
        nb_ecritures = nb_ecritures_row['total'] if nb_ecritures_row else 0

        # Date du dernier import
        dernier_import = conn.execute(
            '''SELECT created_at FROM bilan_fec_imports
               WHERE annee = ? ORDER BY created_at DESC LIMIT 1''',
            (annee,)
        ).fetchone()
        date_import = dernier_import['created_at'] if dernier_import else None

        result.append({
            'annee': annee,
            'periode': periode,
            'premier_mois': premier_mois,
            'dernier_mois': dernier_mois,
            'nb_mois': nb_mois,
            'nb_ecritures': nb_ecritures,
            'date_import': date_import,
        })

    return result


# ── Page principale ──────────────────────────────────────────────────────────

@import_bi_bp.route('/import-bi')
@login_required
def import_bi():
    """Affiche la page de gestion des imports BI."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        annees = _get_annees_importees(conn)
        return render_template('import_bi.html', annees_importees=annees)
    finally:
        conn.close()
