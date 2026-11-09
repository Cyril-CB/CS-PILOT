"""
Blueprint planning_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file
from datetime import datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from database import get_db
from utils import login_required, calculer_heures, get_semaine_alternance, est_dans_equipe_responsable

planning_bp = Blueprint('planning_bp', __name__)


def _peut_gerer_plannings():
    """Profils autorisés à saisir le planning d'autres salariés."""
    return session.get('profil') in ('comptable', 'directeur', 'responsable')


def _salarie_accessible(conn, user_id):
    """Indique si l'utilisateur connecté peut saisir le planning de user_id.

    - Chacun peut gérer son propre planning.
    - Direction et comptable : tous les salariés actifs (hors prestataire).
    - Responsable : uniquement les salariés de son secteur.
    """
    if user_id == session.get('user_id'):
        return True

    profil = session.get('profil')
    if profil in ('comptable', 'directeur'):
        return conn.execute(
            "SELECT 1 FROM users WHERE id = ? AND actif = 1 AND profil != 'prestataire'",
            (user_id,)
        ).fetchone() is not None

    if profil == 'responsable':
        # Équipe : secteur commun OU rattachement direct (responsable_id).
        actif = conn.execute(
            "SELECT 1 FROM users WHERE id = ? AND actif = 1 AND profil != 'prestataire'",
            (user_id,)
        ).fetchone() is not None
        return actif and est_dans_equipe_responsable(conn, session['user_id'], user_id)

    return False


def _liste_salaries(conn):
    """Liste des salariés dont l'utilisateur peut gérer le planning (sélecteur)."""
    profil = session.get('profil')
    if profil in ('comptable', 'directeur'):
        return conn.execute('''
            SELECT u.id, u.nom, u.prenom, COALESCE(s.nom, '') AS secteur_nom
            FROM users u
            LEFT JOIN secteurs s ON u.secteur_id = s.id
            WHERE u.actif = 1 AND u.profil != 'prestataire'
            ORDER BY u.nom, u.prenom
        ''').fetchall()

    if profil == 'responsable':
        resp = conn.execute(
            'SELECT secteur_id FROM users WHERE id = ?', (session['user_id'],)
        ).fetchone()
        secteur_id = resp['secteur_id'] if resp else None
        # Secteur + rattachés directs + lui-même (un secteur NULL ne matche
        # jamais : seuls les rattachés et lui-même restent alors listés).
        return conn.execute('''
            SELECT u.id, u.nom, u.prenom, COALESCE(s.nom, '') AS secteur_nom
            FROM users u
            LEFT JOIN secteurs s ON u.secteur_id = s.id
            WHERE u.actif = 1 AND u.profil != 'prestataire'
              AND (u.secteur_id = ? OR u.responsable_id = ? OR u.id = ?)
            ORDER BY u.nom, u.prenom
        ''', (secteur_id, session['user_id'], session['user_id'])).fetchall()

    return []


def _redirect_planning(user_id_cible):
    """Redirige vers le planning en conservant le salarié cible (si ce n'est pas soi-même)."""
    if user_id_cible and user_id_cible != session['user_id']:
        return redirect(url_for('planning_bp.planning_theorique', user_id=user_id_cible))
    return redirect(url_for('planning_bp.planning_theorique'))



@planning_bp.route('/planning_theorique/pdf')
@login_required
def exporter_plannings_actifs_pdf():
    """PDF des seuls plannings en vigueur a la date d'impression.

    Les versions futures et les versions historiques sont exclues.
    L'alternance en cours conserve ses deux semaines lorsque configuree.
    """
    uid = request.args.get('user_id', default=session['user_id'], type=int)
    conn = get_db()
    try:
        if not _salarie_accessible(conn, uid):
            return ('Acces refuse', 403)
        user = conn.execute('SELECT nom, prenom FROM users WHERE id=?', (uid,)).fetchone()
        if not user:
            return ('Salarie introuvable', 404)
        aujourdhui = datetime.now().date()
        date_str = aujourdhui.isoformat()
        # Alternance en cours : les deux semaines sont actives, mais ne pas
        # charger un planning dont la validite ne demarre que dans le futur.
        semaine_courante = get_semaine_alternance(uid, date_str, conn=conn)
        types = ('periode_scolaire', 'vacances')
        alternances = ('fixe',) if semaine_courante == 'fixe' else ('semaine_1','semaine_2')
        actifs = []
        for periode in types:
            for alternance in alternances:
                if alternance == 'fixe':
                    row = conn.execute("""
                        SELECT * FROM planning_theorique WHERE user_id=? AND type_periode=?
                        AND (type_alternance IS NULL OR type_alternance='fixe')
                        AND date_debut_validite<=?
                        ORDER BY date_debut_validite DESC,id DESC LIMIT 1
                    """, (uid,periode,date_str)).fetchone()
                else:
                    row = conn.execute("""
                        SELECT * FROM planning_theorique WHERE user_id=? AND type_periode=?
                        AND type_alternance=? AND date_debut_validite<=?
                        ORDER BY date_debut_validite DESC,id DESC LIMIT 1
                    """, (uid,periode,alternance,date_str)).fetchone()
                    if not row:
                        row = conn.execute("""
                            SELECT * FROM planning_theorique WHERE user_id=? AND type_periode=?
                            AND (type_alternance IS NULL OR type_alternance='fixe')
                            AND date_debut_validite<=?
                            ORDER BY date_debut_validite DESC,id DESC LIMIT 1
                        """, (uid,periode,date_str)).fetchone()
                if row and row['id'] not in {p['id'] for p in actifs}:
                    actifs.append(dict(row))
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=30,
                                leftMargin=30, topMargin=30, bottomMargin=30)
        styles = getSampleStyleSheet()
        elements = [
            Paragraph('Plannings theoriques en vigueur', styles['Title']),
            Paragraph(escape(f"{user['prenom']} {user['nom']} - situation au {aujourdhui.strftime('%d/%m/%Y')}"), styles['Normal']),
            Spacer(1, 12)
        ]
        jours = [('lundi','Lundi'),('mardi','Mardi'),('mercredi','Mercredi'),
                 ('jeudi','Jeudi'),('vendredi','Vendredi')]
        for p in actifs:
            libelle = 'Periode scolaire' if p['type_periode']=='periode_scolaire' else 'Vacances'
            alternance = p['type_alternance'] or 'fixe'
            elements.append(Paragraph(escape(f"{libelle} - {alternance} (depuis le {p['date_debut_validite']})"), styles['Heading2']))
            lignes = [['Jour','Matin','Apres-midi','Troisieme creneau']]
            for day,label in jours:
                slots = []
                for prefix in ('matin','aprem','soir'):
                    deb = p[f'{day}_{prefix}_debut'] or ''
                    fin = p[f'{day}_{prefix}_fin'] or ''
                    slots.append(f"{deb} - {fin}" if deb or fin else '-')
                lignes.append([label,*slots])
            tableau = Table(lignes, colWidths=[125,190,190,190],repeatRows=1)
            tableau.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8eef5')),
                ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#cbd5e1')),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                ('BOTTOMPADDING',(0,0),(-1,-1),8),
                ('TOPPADDING',(0,0),(-1,-1),8)
            ]))
            elements.extend([tableau,Spacer(1,16)])
        if not actifs:
            elements.append(Paragraph('Aucun planning actuellement en vigueur.', styles['Normal']))
        doc.build(elements)
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True,
                         download_name=f'plannings_actifs_{uid}_{date_str}.pdf')
    finally:
        conn.close()


@planning_bp.route('/planning_theorique', methods=['GET', 'POST'])
@login_required
def planning_theorique():
    """Gestion du planning théorique avec historisation et alternance.

    Par défaut, on saisit son propre planning. La direction, le comptable et
    les responsables (pour leur équipe uniquement) peuvent saisir le planning
    d'un autre salarié via le paramètre ``user_id``.
    """
    user_id_param = (request.args.get('user_id', type=int) if request.method == 'GET'
                     else request.form.get('user_id', type=int))
    user_id_cible = user_id_param if user_id_param else session['user_id']

    # Contrôle d'accès au salarié cible
    conn = get_db()
    autorise = _salarie_accessible(conn, user_id_cible)
    conn.close()
    if not autorise:
        flash("Vous n'avez pas le droit de saisir ce planning", 'error')
        return redirect(url_for('planning_bp.planning_theorique'))

    if request.method == 'POST':
        type_periode = request.form.get('type_periode')
        date_debut_validite = request.form.get('date_debut_validite')
        type_alternance = request.form.get('type_alternance', 'fixe')
        date_reference = request.form.get('date_reference')

        if not date_debut_validite:
            flash('Vous devez spécifier une date de début de validité', 'error')
            return _redirect_planning(user_id_cible)

        # Vérifier la cohérence alternance
        if type_alternance in ['semaine_1', 'semaine_2'] and not date_reference:
            flash('Vous devez spécifier une date de référence pour l\'alternance', 'error')
            return _redirect_planning(user_id_cible)

        # Vérifier que la date de référence est un lundi
        if date_reference:
            date_ref_obj = datetime.strptime(date_reference, '%Y-%m-%d')
            if date_ref_obj.weekday() != 0:  # 0 = lundi
                flash('⚠️ La date de référence doit être un lundi', 'error')
                return _redirect_planning(user_id_cible)

        # Vérifier si date dans le passé → warning
        date_validite_obj = datetime.strptime(date_debut_validite, '%Y-%m-%d')
        aujourdhui = datetime.now().date()

        if date_validite_obj.date() < aujourdhui:
            # Vérifier s'il y a des heures saisies après cette date
            conn = get_db()
            heures_apres = conn.execute('''
                SELECT COUNT(*) as nb FROM heures_reelles
                WHERE user_id = ? AND date >= ?
            ''', (user_id_cible, date_debut_validite)).fetchone()

            if heures_apres and heures_apres['nb'] > 0:
                flash(f'⚠️ ATTENTION : {heures_apres["nb"]} jour(s) avec des heures saisies après le {date_debut_validite}. Les calculs de solde seront recalculés avec ce nouveau planning !', 'warning')
            conn.close()

        # Récupérer tous les horaires des 5 jours
        jours = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi']
        horaires = {}
        total_hebdo = 0

        # Créneaux d'une journée : matin + après-midi + soir (3e optionnel).
        creneaux = ('matin_debut', 'matin_fin', 'aprem_debut', 'aprem_fin',
                    'soir_debut', 'soir_fin')
        for jour in jours:
            for suffixe in creneaux:
                horaires[f'{jour}_{suffixe}'] = request.form.get(f'{jour}_{suffixe}') or None
            # Calculer les heures du jour (3 créneaux)
            for slot in ('matin', 'aprem', 'soir'):
                total_hebdo += calculer_heures(horaires[f'{jour}_{slot}_debut'],
                                               horaires[f'{jour}_{slot}_fin'])

        conn = get_db()
        try:
            # CRÉER un nouveau planning (historisation). Les colonnes de créneaux
            # sont générées depuis les constantes (jours × créneaux) : aucune
            # donnée utilisateur n'entre dans le SQL, seulement des valeurs liées.
            slot_cols, slot_vals = [], []
            for jour in jours:
                for suffixe in creneaux:
                    slot_cols.append(f'{jour}_{suffixe}')
                    slot_vals.append(horaires[f'{jour}_{suffixe}'])
            colonnes = ('user_id, type_periode, date_debut_validite, type_alternance, '
                        + ', '.join(slot_cols) + ', total_hebdo')
            placeholders = ', '.join(['?'] * (4 + len(slot_cols) + 1))
            conn.execute(
                f'INSERT INTO planning_theorique ({colonnes}) VALUES ({placeholders})',
                [user_id_cible, type_periode, date_debut_validite, type_alternance]
                + slot_vals + [total_hebdo]
            )

            # Si alternance, enregistrer la date de référence
            if type_alternance in ['semaine_1', 'semaine_2'] and date_reference:
                # Vérifier si on a déjà une référence pour cette date
                ref_existante = conn.execute('''
                    SELECT id FROM alternance_reference
                    WHERE user_id = ? AND date_debut_validite = ?
                ''', (user_id_cible, date_debut_validite)).fetchone()

                if not ref_existante:
                    conn.execute('''
                        INSERT INTO alternance_reference (user_id, date_reference, date_debut_validite)
                        VALUES (?, ?, ?)
                    ''', (user_id_cible, date_reference, date_debut_validite))

            conn.commit()

            if type_alternance == 'fixe':
                flash(f'✅ Nouveau planning {type_periode} créé ({total_hebdo:.2f}h/semaine), valable à partir du {date_debut_validite}', 'success')
            else:
                flash(f'✅ Planning {type_alternance} - {type_periode} créé ({total_hebdo:.2f}h/semaine), valable à partir du {date_debut_validite}', 'success')
        except Exception as e:
            flash(f'Erreur: {str(e)}', 'error')
        finally:
            conn.close()

        return _redirect_planning(user_id_cible)

    # GET: afficher tous les plannings (historique complet) + infos alternance
    conn = get_db()
    plannings = conn.execute('''
        SELECT * FROM planning_theorique
        WHERE user_id = ?
        ORDER BY type_alternance, type_periode, date_debut_validite DESC
    ''', (user_id_cible,)).fetchall()

    # Récupérer les dates de référence alternance
    references = conn.execute('''
        SELECT * FROM alternance_reference
        WHERE user_id = ?
        ORDER BY date_debut_validite DESC
    ''', (user_id_cible,)).fetchall()

    # Calculer la semaine actuelle si alternance configurée
    semaine_actuelle = None
    if references:
        semaine_actuelle = get_semaine_alternance(user_id_cible, datetime.now().strftime('%Y-%m-%d'))

    # Salarié cible + liste des salariés gérables (pour le sélecteur)
    user_cible = conn.execute(
        'SELECT id, nom, prenom FROM users WHERE id = ?', (user_id_cible,)
    ).fetchone()
    peut_gerer = _peut_gerer_plannings()
    salaries = _liste_salaries(conn) if peut_gerer else []

    conn.close()

    return render_template('planning_theorique.html',
                         plannings=plannings,
                         references=references,
                         semaine_actuelle=semaine_actuelle,
                         date_actuelle=datetime.now().strftime('%Y-%m-%d'),
                         user_cible=dict(user_cible) if user_cible else None,
                         user_id_cible=user_id_cible,
                         salaries=salaries,
                         peut_gerer=peut_gerer)


@planning_bp.route('/planning_theorique/supprimer/<int:planning_id>', methods=['POST'])
@login_required
def supprimer_planning(planning_id):
    """Suppression d'un planning - uniquement en cas d'erreur de saisie"""
    conn = get_db()
    redirect_user = session['user_id']
    try:
        planning = conn.execute(
            'SELECT id, user_id, date_debut_validite FROM planning_theorique WHERE id = ?',
            (planning_id,)
        ).fetchone()

        if not planning or not _salarie_accessible(conn, planning['user_id']):
            flash('Planning introuvable ou accès refusé', 'error')
            return redirect(url_for('planning_bp.planning_theorique'))

        redirect_user = planning['user_id']
        conn.execute('DELETE FROM planning_theorique WHERE id = ?', (planning_id,))

        # Nettoyer alternance_reference si plus aucun planning alterné ne reste
        restants = conn.execute(
            "SELECT COUNT(*) as nb FROM planning_theorique "
            "WHERE user_id = ? AND type_alternance IN ('semaine_1', 'semaine_2')",
            (redirect_user,)
        ).fetchone()
        if restants['nb'] == 0:
            conn.execute('DELETE FROM alternance_reference WHERE user_id = ?', (redirect_user,))

        conn.commit()
        flash(f'Planning du {planning["date_debut_validite"]} supprimé.', 'success')
    except Exception as e:
        flash(f'Erreur lors de la suppression : {str(e)}', 'error')
    finally:
        conn.close()

    return _redirect_planning(redirect_user)
