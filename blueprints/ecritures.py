"""
Blueprint ecritures_bp - Generation et gestion des ecritures comptables.

L'IA genere les ecritures a partir des factures "a_traiter" en utilisant
les regles comptables et les informations fournisseurs.
Circuit : Brouillon -> Validee -> Exportee
Acces : directeur, comptable.
"""
import json
from datetime import datetime
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from database import get_db
from utils import login_required
from blueprints.pesee_alisfa import call_ai, _extract_json_from_response
from blueprints.api_keys import get_available_models

ecritures_bp = Blueprint('ecritures_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']


GENERATE_SYSTEM_PROMPT = """Tu es un assistant comptable expert. Tu génères des écritures comptables pour une association
qui n'est PAS assujettie à la TVA (donc montant TTC = montant comptable).

Pour chaque facture, tu dois générer les lignes d'écriture comptable suivantes :
1. Une ligne de DÉBIT sur le compte de charge approprié (montant TTC)
2. Une ligne de CRÉDIT sur le compte fournisseur (montant TTC)

Tu DOIS répondre STRICTEMENT au format JSON suivant (un tableau d'écritures) :
[
  {
    "facture_id": 123,
    "lignes": [
      {
        "compte": "606100",
        "libelle": "FOURNISSEUR FACTURE 2024-001 01/2025",
        "debit": 1234.56,
        "credit": 0,
        "code_analytique": "ANA01",
        "type": "charge"
      },
      {
        "compte": "FOURN",
        "libelle": "FOURNISSEUR FACTURE 2024-001 01/2025",
        "debit": 0,
        "credit": 1234.56,
        "code_analytique": null,
        "type": "fournisseur"
      }
    ]
  }
]

Règles IMPÉRATIVES :
- Le libellé est TOUJOURS EN MAJUSCULES.
- Pour le compte fournisseur, utilise le code_comptable du fournisseur (lettres majuscules).
- Si un fournisseur n'a pas de code_comptable, utilise "FOURNISSEUR".
- Utilise les règles comptables fournies pour déterminer le compte de charge et le code analytique.
- Si une règle a deux codes analytiques avec des pourcentages, génère deux lignes de débit (une par analytique, avec le montant réparti selon les pourcentages).
- Le libellé suit le modèle fourni dans la règle, avec les variables remplacées.
- S'il n'y a pas de règle applicable, utilise le compte 607000 par défaut.
- L'échéance est au format JJMMAAAA si elle est connue, sinon null.
"""


@ecritures_bp.route('/ecritures')
@login_required
def liste_ecritures():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    ecritures_rows = conn.execute('''
        SELECT e.*, f.fournisseur_id, fr.nom as fournisseur_nom
        FROM ecritures_comptables e
        LEFT JOIN factures f ON e.facture_id = f.id
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        ORDER BY e.date_ecriture DESC, e.id
    ''').fetchall()

    # Compter les factures "a_traiter"
    nb_a_traiter = conn.execute(
        "SELECT COUNT(*) as nb FROM factures WHERE statut = 'a_traiter'"
    ).fetchone()['nb']

    conn.close()

    # Convertir les Row en dicts pour que tojson fonctionne dans le template
    ecritures = [dict(e) for e in ecritures_rows]

    models = get_available_models()
    has_key = len(models) > 0

    return render_template('ecritures.html', ecritures=ecritures, nb_a_traiter=nb_a_traiter,
                           available_models=models, has_api_key=has_key)


@ecritures_bp.route('/ecritures/generer', methods=['POST'])
@login_required
def generer_ecritures():
    """Génère les écritures comptables via l'IA pour les factures 'a_traiter'."""
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    model = request.form.get('model', '')
    if not model:
        flash('Veuillez sélectionner un modèle IA.', 'error')
        return redirect(url_for('ecritures_bp.liste_ecritures'))

    conn = get_db()

    # Récupérer les factures à traiter
    factures = conn.execute('''
        SELECT f.*, fr.nom as fournisseur_nom, fr.code_comptable as fournisseur_code,
               fr.alias1 as fournisseur_alias1
        FROM factures f
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        WHERE f.statut = 'a_traiter'
    ''').fetchall()

    if not factures:
        conn.close()
        flash('Aucune facture à traiter.', 'info')
        return redirect(url_for('ecritures_bp.liste_ecritures'))

    # Récupérer les règles actives
    regles = conn.execute(
        "SELECT * FROM regles_comptables WHERE statut = 'active'"
    ).fetchall()

    # Construire le contexte pour l'IA
    factures_data = []
    for f in factures:
        factures_data.append({
            'facture_id': f['id'],
            'fournisseur': f['fournisseur_nom'] or 'Inconnu',
            'fournisseur_code_comptable': f['fournisseur_code'] or 'FOURNISSEUR',
            'numero_facture': f['numero_facture'] or '',
            'date_facture': f['date_facture'] or '',
            'date_echeance': f['date_echeance'],
            'montant_ttc': f['montant_ttc'] or 0,
            'description': f['description'] or ''
        })

    regles_data = []
    for r in regles:
        rd = {
            'nom': r['nom'],
            'type_regle': r['type_regle'],
            'cible': r['cible'],
            'compte_comptable': r['compte_comptable'],
            'code_analytique_1': r['code_analytique_1'],
            'pourcentage_analytique_1': r['pourcentage_analytique_1'],
            'modele_libelle': r['modele_libelle'] or '{supplier} {invoice_number}'
        }
        if r['code_analytique_2']:
            rd['code_analytique_2'] = r['code_analytique_2']
            rd['pourcentage_analytique_2'] = r['pourcentage_analytique_2']
        regles_data.append(rd)

    user_prompt = (
        f"Voici les factures à traiter :\n{json.dumps(factures_data, ensure_ascii=False, indent=2)}\n\n"
        f"Voici les règles comptables actives :\n{json.dumps(regles_data, ensure_ascii=False, indent=2)}\n\n"
        "Génère les écritures comptables pour chaque facture."
    )

    messages = [
        {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    try:
        raw = call_ai(messages, model)
        result = _extract_json_from_response(raw)

        if not isinstance(result, list):
            result = [result]

        nb_ecritures = 0
        for entry in result:
            facture_id = entry.get('facture_id')
            lignes = entry.get('lignes', [])

            if not facture_id or not lignes:
                continue

            # Récupérer la facture pour la date et l'échéance
            fac = conn.execute('SELECT date_facture, date_echeance, numero_facture FROM factures WHERE id=%s',
                               (facture_id,)).fetchone()
            if not fac:
                continue

            date_ecriture = fac['date_facture'] or datetime.now().strftime('%Y-%m-%d')

            for ligne in lignes:
                echeance = None
                if fac['date_echeance']:
                    # Convertir en JJMMAAAA
                    try:
                        dt = datetime.strptime(fac['date_echeance'], '%Y-%m-%d')
                        echeance = dt.strftime('%d%m%Y')
                    except ValueError:
                        echeance = fac['date_echeance']

                conn.execute(
                    '''INSERT INTO ecritures_comptables
                       (facture_id, date_ecriture, compte, libelle, numero_facture,
                        debit, credit, code_analytique, echeance)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                    (facture_id, date_ecriture, ligne.get('compte', ''),
                     (ligne.get('libelle', '') or '').upper(),
                     fac['numero_facture'] or '',
                     float(ligne.get('debit', 0) or 0),
                     float(ligne.get('credit', 0) or 0),
                     ligne.get('code_analytique'),
                     echeance if ligne.get('type') != 'fournisseur' else (echeance or None))
                )
                nb_ecritures += 1

            # Marquer la facture comme traitée
            conn.execute(
                "UPDATE factures SET statut='traitee', updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                (facture_id,)
            )
            # Historique
            from blueprints.factures import _add_historique
            _add_historique(conn, facture_id, 'Écritures générées',
                           f'{len(lignes)} ligne(s) d\'écriture générée(s)')

        conn.commit()
        conn.close()

        flash(f'{nb_ecritures} écriture(s) générée(s) avec succès.', 'success')

    except Exception as e:
        conn.close()
        flash(f'Erreur lors de la génération : {str(e)}', 'error')

    return redirect(url_for('ecritures_bp.liste_ecritures'))


@ecritures_bp.route('/ecritures/<int:ecriture_id>/modifier', methods=['POST'])
@login_required
def modifier_ecriture(ecriture_id):
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    compte = request.form.get('compte', '').strip()
    libelle = request.form.get('libelle', '').strip().upper()
    debit = request.form.get('debit', '0')
    credit = request.form.get('credit', '0')
    code_analytique = request.form.get('code_analytique', '').strip() or None

    try:
        debit = float(debit)
        credit = float(credit)
    except ValueError:
        debit, credit = 0, 0

    conn = get_db()
    conn.execute(
        '''UPDATE ecritures_comptables SET compte=%s, libelle=%s, debit=%s, credit=%s,
           code_analytique=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s''',
        (compte, libelle, debit, credit, code_analytique, ecriture_id)
    )
    conn.commit()
    conn.close()

    flash('Écriture modifiée.', 'success')
    return redirect(url_for('ecritures_bp.liste_ecritures'))


@ecritures_bp.route('/ecritures/valider', methods=['POST'])
@login_required
def valider_ecritures():
    """Valide les écritures sélectionnées (brouillon -> validée)."""
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    ids = request.form.getlist('ecriture_ids')
    if not ids:
        flash('Aucune écriture sélectionnée.', 'warning')
        return redirect(url_for('ecritures_bp.liste_ecritures'))

    conn = get_db()
    placeholders = ','.join('%s' * len(ids))
    conn.execute(
        f"UPDATE ecritures_comptables SET statut='validee', updated_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders}) AND statut='brouillon'",
        ids
    )
    conn.commit()
    conn.close()

    flash(f'{len(ids)} écriture(s) validée(s).', 'success')
    return redirect(url_for('ecritures_bp.liste_ecritures'))
