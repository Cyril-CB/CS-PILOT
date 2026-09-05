"""
Blueprint variables_paie_bp.
Page mensuelle Variables Paie (comptable) : mutuelle, enfants,
transport, acompte, saisie sur salaire, pret/avance, regularisations.
Inclut la cloture mensuelle des conges.
"""
import json
import calendar
import logging
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash)
from datetime import datetime, date
from fiches_versions import FicheVerrouillee
from database import get_db
from utils import login_required, NOMS_MOIS, calculer_solde_recup
from access_log import (journaliser_action, ACTION_ENREG_VARIABLES_PAIE,
                        ACTION_CLOTURE_CONGES)

logger = logging.getLogger(__name__)

variables_paie_bp = Blueprint('variables_paie_bp', __name__)


def _peut_gerer_variables_paie():
    """Seuls le comptable et le directeur ont acces."""
    return session.get('profil') in ['comptable', 'directeur']


def _variables_modifiees(ancien, nouveau):
    """Indique si les variables de paie visibles en prepa paie ont change.

    `ancien` : ligne variables_paie existante (sqlite Row / dict) ou None
    lorsqu'aucune donnee n'a encore ete enregistree pour ce salarie ce mois-la.
    `nouveau` : dict des valeurs issues du formulaire.

    La comparaison porte sur les memes champs (et avec la meme tolerance
    "valeur vide = 0") que ceux repris dans la grille de preparation de paie :
    on ne retire la validation du prestataire que lorsqu'une donnee qu'il voit
    change reellement. En l'absence de ligne existante, la reference est l'etat
    "tout a zero" affiche en prepa paie tant que rien n'a ete saisi.
    """
    a = dict(ancien) if ancien else {}

    if int(a.get('mutuelle') or 0) != int(nouveau['mutuelle'] or 0):
        return True
    if int(a.get('nb_enfants') or 0) != int(nouveau['nb_enfants'] or 0):
        return True
    for champ in ('heures_reelles', 'heures_supps', 'transport', 'acompte',
                  'saisie_salaire', 'pret_avance', 'autres_regularisation'):
        if float(a.get(champ) or 0) != float(nouveau[champ] or 0):
            return True
    if (a.get('commentaire') or '') != (nouveau['commentaire'] or ''):
        return True
    return False


@variables_paie_bp.route('/variables_paie', methods=['GET'])
@login_required
def variables_paie():
    """Page principale : affiche la grille mensuelle de tous les salaries."""
    if not _peut_gerer_variables_paie():
        flash("Acces non autorise. Seuls le comptable et la direction peuvent acceder aux variables de paie.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    # Mois / annee courants ou passes en parametre
    now = datetime.now()
    mois = request.args.get('mois', now.month, type=int)
    annee = request.args.get('annee', now.year, type=int)

    if mois < 1:
        mois = 12
        annee -= 1
    elif mois > 12:
        mois = 1
        annee += 1

    conn = get_db()

    # Liste des salaries actifs avec leur secteur
    salaries = conn.execute('''
        SELECT u.id, u.nom, u.prenom, u.profil,
               COALESCE(s.nom, '') AS secteur_nom
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE u.actif = 1 AND u.profil != 'prestataire'
        ORDER BY u.nom, u.prenom
    ''').fetchall()

    # Donnees mensuelles existantes pour ce mois
    rows = conn.execute('''
        SELECT * FROM variables_paie
        WHERE mois = ? AND annee = ?
    ''', (mois, annee)).fetchall()
    donnees_mois = {r['user_id']: dict(r) for r in rows}

    # Valeurs par defaut persistantes
    defauts_rows = conn.execute('SELECT * FROM variables_paie_defauts').fetchall()
    defauts = {r['user_id']: dict(r) for r in defauts_rows}

    # Verifier si les conges ont deja ete clotures pour ce mois
    cloture_conges = conn.execute(
        'SELECT * FROM conges_cloture_mensuelle WHERE mois = ? AND annee = ?',
        (mois, annee)
    ).fetchone()
    conges_deja_clotures = dict(cloture_conges) if cloture_conges else None

    conn.close()

    # Construire la liste combinee : donnees du mois OU defauts
    grille = []
    for sal in salaries:
        uid = sal['id']
        if uid in donnees_mois:
            d = donnees_mois[uid]
        else:
            # Pre-remplir avec les valeurs persistantes
            df = defauts.get(uid, {})
            d = {
                'user_id': uid,
                'mutuelle': df.get('mutuelle', 0),
                'nb_enfants': df.get('nb_enfants', 0),
                'heures_reelles': None,
                'heures_supps': None,
                # Nouvelle saisie : les heures supp payees sont deduites du
                # compteur de recup par defaut (decochable au cas par cas).
                'hs_deduites_compteur': 1,
                'transport': 0,
                'acompte': 0,
                'saisie_salaire': df.get('saisie_salaire', 0),
                'pret_avance': df.get('pret_avance', 0),
                'autres_regularisation': 0,
                'commentaire': '',
            }
        # Normaliser en entier : sur les bases anterieures a la migration
        # 0038, la colonne TEXT renvoie '0'/'1' et '0' serait considere
        # comme coche par le template.
        d['mutuelle'] = int(d.get('mutuelle') or 0)
        # Lignes enregistrees avant la migration 0057 : NULL = non deduit.
        d['hs_deduites_compteur'] = int(d.get('hs_deduites_compteur') or 0)
        # Solde de recuperation actuel : aide a decider combien payer (et a
        # solder pile un CDD qui part). Sans objet pour le directeur (forfait
        # jours, pas de compteur d'heures).
        solde_recup = None
        if sal['profil'] != 'directeur':
            try:
                solde_recup = calculer_solde_recup(uid)
            except Exception:
                logger.exception("Solde recup indisponible pour user %s", uid)
        grille.append({
            'user_id': uid,
            'nom': sal['nom'],
            'prenom': sal['prenom'],
            'secteur': sal['secteur_nom'],
            'data': d,
            'solde_recup': solde_recup,
            'saved': uid in donnees_mois,
        })

    # Navigation mois precedent / suivant
    if mois == 1:
        prev_mois, prev_annee = 12, annee - 1
    else:
        prev_mois, prev_annee = mois - 1, annee

    if mois == 12:
        next_mois, next_annee = 1, annee + 1
    else:
        next_mois, next_annee = mois + 1, annee

    return render_template('variables_paie.html',
                           grille=grille,
                           mois=mois,
                           annee=annee,
                           nom_mois=NOMS_MOIS[mois],
                           prev_mois=prev_mois,
                           prev_annee=prev_annee,
                           next_mois=next_mois,
                           next_annee=next_annee,
                           conges_deja_clotures=conges_deja_clotures)


@variables_paie_bp.route('/variables_paie/enregistrer', methods=['POST'])
@login_required
def enregistrer_variables_paie():
    """Enregistre toutes les variables de paie du mois."""
    if not _peut_gerer_variables_paie():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    mois = request.form.get('mois', type=int)
    annee = request.form.get('annee', type=int)

    if not mois or not annee:
        flash("Mois ou annee invalide.", 'error')
        return redirect(url_for('variables_paie_bp.variables_paie'))

    # Recuperer la liste des user_id dans le formulaire
    user_ids = request.form.getlist('user_ids', type=int)

    conn = get_db()
    nb_saved = 0
    # Salaries dont une variable de paie change ce mois-ci : leur validation
    # eventuelle en preparation de paie sera retiree (case a recocher).
    uids_modifies = []

    try:
        for uid in user_ids:
            mutuelle = 1 if request.form.get(f'mutuelle_{uid}') else 0
            nb_enfants = request.form.get(f'nb_enfants_{uid}', 0, type=int)
            heures_reelles_str = request.form.get(f'heures_reelles_{uid}', '').strip()
            heures_reelles = float(heures_reelles_str) if heures_reelles_str else None
            heures_supps_str = request.form.get(f'heures_supps_{uid}', '').strip()
            heures_supps = float(heures_supps_str) if heures_supps_str else None
            # Heures supp payees deduites du compteur de recup (case a cocher,
            # cochee par defaut pour une nouvelle saisie).
            hs_deduites = 1 if request.form.get(f'hs_deduit_{uid}') else 0
            transport = request.form.get(f'transport_{uid}', 0, type=float)
            acompte = request.form.get(f'acompte_{uid}', 0, type=float)
            saisie_salaire = request.form.get(f'saisie_salaire_{uid}', 0, type=float)
            pret_avance = request.form.get(f'pret_avance_{uid}', 0, type=float)
            autres_reg = request.form.get(f'autres_regularisation_{uid}', 0, type=float)
            commentaire = request.form.get(f'commentaire_{uid}', '').strip() or None

            # Donnees existantes (sert a la fois a detecter un changement et a
            # l'upsert ci-dessous).
            existing = conn.execute(
                'SELECT * FROM variables_paie WHERE user_id = ? AND mois = ? AND annee = ?',
                (uid, mois, annee)
            ).fetchone()

            nouveau = {
                'mutuelle': mutuelle,
                'nb_enfants': nb_enfants,
                'heures_reelles': heures_reelles,
                'heures_supps': heures_supps,
                'transport': transport,
                'acompte': acompte,
                'saisie_salaire': saisie_salaire,
                'pret_avance': pret_avance,
                'autres_regularisation': autres_reg,
                'commentaire': commentaire,
            }
            if _variables_modifiees(existing, nouveau):
                uids_modifies.append(uid)

            # Upsert donnees mensuelles
            if existing:
                conn.execute('''
                    UPDATE variables_paie
                    SET mutuelle = ?, nb_enfants = ?, heures_reelles = ?, heures_supps = ?,
                        hs_deduites_compteur = ?,
                        transport = ?, acompte = ?,
                        saisie_salaire = ?, pret_avance = ?, autres_regularisation = ?,
                        commentaire = ?, saisi_par = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (mutuelle, nb_enfants, heures_reelles, heures_supps,
                      hs_deduites, transport, acompte,
                      saisie_salaire, pret_avance, autres_reg,
                      commentaire, session['user_id'], existing['id']))
            else:
                conn.execute('''
                    INSERT INTO variables_paie
                    (user_id, mois, annee, mutuelle, nb_enfants, heures_reelles, heures_supps,
                     hs_deduites_compteur, transport, acompte,
                     saisie_salaire, pret_avance, autres_regularisation, commentaire, saisi_par)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (uid, mois, annee, mutuelle, nb_enfants, heures_reelles, heures_supps,
                      hs_deduites, transport, acompte,
                      saisie_salaire, pret_avance, autres_reg, commentaire, session['user_id']))

            # Mettre a jour les valeurs persistantes
            existing_def = conn.execute(
                'SELECT id FROM variables_paie_defauts WHERE user_id = ?', (uid,)
            ).fetchone()

            if existing_def:
                conn.execute('''
                    UPDATE variables_paie_defauts
                    SET mutuelle = ?, nb_enfants = ?, saisie_salaire = ?, pret_avance = ?
                    WHERE user_id = ?
                ''', (mutuelle, nb_enfants, saisie_salaire, pret_avance, uid))
            else:
                conn.execute('''
                    INSERT INTO variables_paie_defauts
                    (user_id, mutuelle, nb_enfants, saisie_salaire, pret_avance)
                    VALUES (?, ?, ?, ?, ?)
                ''', (uid, mutuelle, nb_enfants, saisie_salaire, pret_avance))

            nb_saved += 1

        # Toute modification d'une variable retire la validation "traite" de la
        # preparation de paie pour ce salarie/mois : le prestataire doit ainsi
        # revoir et revalider les bulletins concernes. On ne touche que les
        # lignes encore cochees (traite = 1) afin de compter les seules
        # devalidations reelles.
        nb_devalidees = 0
        if uids_modifies:
            placeholders = ','.join('?' for _ in uids_modifies)
            cur = conn.execute(f'''
                UPDATE prepa_paie_statut
                SET traite = 0, updated_at = CURRENT_TIMESTAMP
                WHERE mois = ? AND annee = ? AND traite = 1
                  AND user_id IN ({placeholders})
            ''', (mois, annee, *uids_modifies))
            nb_devalidees = cur.rowcount

        # Trace d'audit dans la meme transaction que l'enregistrement
        journaliser_action(
            conn, ACTION_ENREG_VARIABLES_PAIE,
            cible_type='mois_paie',
            details=f"{nb_saved} salarie(s), mois={mois}/{annee}, "
                    f"{nb_devalidees} prepa paie devalidee(s)",
        )
        conn.commit()
        msg = f"Variables de paie enregistrees pour {nb_saved} salarie(s) - {NOMS_MOIS[mois]} {annee}."
        if nb_devalidees:
            msg += (f" {nb_devalidees} validation(s) de preparation de paie retiree(s) "
                    "suite a modification (a revalider par le prestataire).")
        flash(msg, 'success')
    except FicheVerrouillee as exc:
        conn.rollback()
        flash(str(exc), 'error')
    except Exception:
        conn.rollback()
        logger.exception(
            "Echec enregistrement variables paie (mois=%s, annee=%s, par=%s)",
            mois, annee, session.get('user_id'),
        )
        flash("Erreur lors de l'enregistrement. L'incident a ete journalise.", 'error')
    finally:
        conn.close()

    return redirect(url_for('variables_paie_bp.variables_paie', mois=mois, annee=annee))


@variables_paie_bp.route('/variables_paie/cloturer_conges', methods=['POST'])
@login_required
def cloturer_conges():
    """Cloture mensuelle des conges : acquisition CP et CC.

    Regles :
    - CP : +2.083333 j/mois dans cp_acquis (prorata si embauche en cours de mois)
    - Si cloture de mai : bascule cp_acquis vers cp_a_prendre, reset cp_acquis
    - Nettoyage pris : cp_a_prendre -= cp_pris, cp_pris = 0 (solde inchange)
    - CC : +1 j/mois d'octobre a mai dans cc_solde (prorata si embauche en cours de mois)
    - Hors profil directeur (forfait jour gere separement)
    - Sans contrat actif le dernier jour du mois : remise a zero de tous les soldes
      (cp_acquis, cp_a_prendre, cp_pris, cc_solde)
    """
    if not _peut_gerer_variables_paie():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    mois = request.form.get('mois', type=int)
    annee = request.form.get('annee', type=int)

    if not mois or not annee:
        flash("Mois ou annee invalide.", 'error')
        return redirect(url_for('variables_paie_bp.variables_paie'))

    conn = get_db()

    # Verifier si deja cloture
    existing = conn.execute(
        'SELECT id FROM conges_cloture_mensuelle WHERE mois = ? AND annee = ?',
        (mois, annee)
    ).fetchone()
    if existing:
        flash(f"Les conges de {NOMS_MOIS[mois]} {annee} ont deja ete clotures.", 'warning')
        conn.close()
        return redirect(url_for('variables_paie_bp.variables_paie', mois=mois, annee=annee))

    # Salaries actifs hors directeur et prestataire
    salaries = conn.execute('''
        SELECT id, cp_acquis, cp_a_prendre, cp_pris, cc_solde
        FROM users
        WHERE actif = 1 AND profil NOT IN ('directeur', 'prestataire')
    ''').fetchall()

    CP_MENSUEL = 25.0 / 12.0  # 2.083333...
    jours_dans_mois = calendar.monthrange(annee, mois)[1]
    # Mois d'acquisition CC : octobre (10) a mai (5)
    mois_cc = mois in (10, 11, 12, 1, 2, 3, 4, 5)

    # Salaries avec un contrat se poursuivant apres le dernier jour du mois, et
    # la date de debut de ce contrat : c'est elle (et non users.date_entree,
    # saisie a la creation et plus fiable) qui sert de reference pour le prorata
    # d'embauche en cours de mois. C'est le contrat qui compte.
    # Un contrat dont date_fin est exactement le dernier jour est exclu : les
    # conges acquis sont soldes en paie, les compteurs doivent repasser a zero.
    #
    # Cas multi-contrats (RARE) : si un salarie a plusieurs contrats encore
    # actifs en fin de mois, on retient le PLUS ANCIEN en cours de validite
    # (MIN(date_debut)) -> choix metier deliberé, favorable au salarie (mois
    # plein plutot qu'un prorata sur le contrat le plus recent).
    # Limite connue laissee de cote : en toute rigueur chaque contrat a son
    # propre solde de conges et ceux-ci devraient se CUMULER (un solde par
    # contrat). Ce n'est pas gere ici (cas exceptionnel, chantier a part). Si on
    # revient un jour dessus, c'est le point a reprendre.
    dernier_du_mois_str = date(annee, mois, jours_dans_mois).strftime('%Y-%m-%d')
    contrat_debut = {
        row['user_id']: row['date_debut'] for row in conn.execute(
            '''SELECT user_id, MIN(date_debut) AS date_debut FROM contrats
               WHERE date_debut <= ? AND (date_fin IS NULL OR date_fin > ?)
               GROUP BY user_id''',
            (dernier_du_mois_str, dernier_du_mois_str)
        ).fetchall()
    }
    ids_avec_contrat = set(contrat_debut.keys())

    nb_traites = 0
    nb_resets = 0
    details = []

    try:
        for sal in salaries:
            uid = sal['id']
            cp_acquis = sal['cp_acquis'] or 0
            cp_a_prendre = sal['cp_a_prendre'] or 0
            cp_pris = sal['cp_pris'] or 0
            cc_solde = sal['cc_solde'] or 0
            date_debut_contrat = contrat_debut.get(uid)

            # Sans contrat actif le dernier jour du mois : remise a zero des soldes
            if uid not in ids_avec_contrat:
                conn.execute('''
                    UPDATE users
                    SET cp_acquis = 0, cp_a_prendre = 0, cp_pris = 0, cc_solde = 0
                    WHERE id = ?
                ''', (uid,))
                nb_resets += 1
                details.append({'user_id': uid, 'reset_sans_contrat': True})
                continue

            # Calculer le prorata si embauche en cours de mois (= date de debut
            # du contrat en cours, et non plus users.date_entree)
            prorata = 1.0
            if date_debut_contrat:
                try:
                    d_entree = datetime.strptime(str(date_debut_contrat)[:10], '%Y-%m-%d').date()
                    premier_du_mois = date(annee, mois, 1)
                    dernier_du_mois = date(annee, mois, jours_dans_mois)
                    # Si l'entree est dans ce mois
                    if d_entree.year == annee and d_entree.month == mois:
                        jours_restants = (dernier_du_mois - d_entree).days + 1
                        prorata = jours_restants / jours_dans_mois
                    # Si l'entree est apres ce mois, ne pas acquérir
                    elif d_entree > dernier_du_mois:
                        prorata = 0
                except (ValueError, TypeError):
                    pass

            if prorata == 0:
                continue

            # 1. Acquisition CP
            acquisition_cp = round(CP_MENSUEL * prorata, 6)
            cp_acquis += acquisition_cp

            # 2. Si cloture de mai : bascule acquis vers a_prendre
            if mois == 5:
                cp_a_prendre += cp_acquis
                cp_acquis = 0

            # 3. Nettoyage pris : absorber dans a_prendre pour garder le meme solde
            if cp_pris > 0:
                cp_a_prendre -= cp_pris
                cp_pris = 0

            # 4. Acquisition CC (octobre a mai)
            acquisition_cc = 0
            if mois_cc:
                acquisition_cc = round(1.0 * prorata, 6)
                cc_solde += acquisition_cc

            # Mettre a jour
            conn.execute('''
                UPDATE users
                SET cp_acquis = ?, cp_a_prendre = ?, cp_pris = ?, cc_solde = ?
                WHERE id = ?
            ''', (round(cp_acquis, 6), round(cp_a_prendre, 6), cp_pris,
                  round(cc_solde, 6), uid))

            nb_traites += 1
            detail_line = {'user_id': uid, 'cp': round(acquisition_cp, 4)}
            if acquisition_cc:
                detail_line['cc'] = round(acquisition_cc, 4)
            if prorata < 1:
                detail_line['prorata'] = round(prorata, 4)
            details.append(detail_line)

        # Reset supplementaire : salaries inactifs (desactives avant la cloture)
        # sans contrat actif se poursuivant apres le dernier jour du mois.
        cur = conn.execute('''
            UPDATE users
            SET cp_acquis = 0, cp_a_prendre = 0, cp_pris = 0, cc_solde = 0
            WHERE actif = 0
            AND profil NOT IN ('directeur', 'prestataire')
            AND id NOT IN (
                SELECT DISTINCT user_id FROM contrats
                WHERE date_debut <= ? AND (date_fin IS NULL OR date_fin > ?)
            )
            AND (cp_acquis != 0 OR cp_a_prendre != 0 OR cp_pris != 0 OR cc_solde != 0)
        ''', (dernier_du_mois_str, dernier_du_mois_str))
        nb_resets += cur.rowcount

        # Enregistrer la cloture
        conn.execute('''
            INSERT INTO conges_cloture_mensuelle (mois, annee, cloture_par, nb_salaries_traites, detail)
            VALUES (?, ?, ?, ?, ?)
        ''', (mois, annee, session['user_id'], nb_traites, json.dumps(details)))

        # Trace d'audit dans la meme transaction que la cloture
        journaliser_action(
            conn, ACTION_CLOTURE_CONGES,
            cible_type='mois_paie',
            details=f"{nb_traites} salarie(s) traite(s), mois={mois}/{annee}",
        )
        conn.commit()

        msg = f"Cloture conges {NOMS_MOIS[mois]} {annee} : {nb_traites} salarie(s) traite(s)."
        msg += f" CP : +{CP_MENSUEL:.4f} j/pers."
        if mois_cc:
            msg += " CC : +1 j/pers."
        if mois == 5:
            msg += " Bascule acquis → a prendre effectuee."
        if nb_resets:
            msg += f" {nb_resets} solde(s) remis a zero (fin de contrat)."
        flash(msg, 'success')

    except Exception:
        conn.rollback()
        logger.exception(
            "Echec cloture conges (mois=%s, annee=%s, par=%s)",
            mois, annee, session.get('user_id'),
        )
        flash("Erreur lors de la cloture. L'incident a ete journalise.", 'error')
    finally:
        conn.close()

    return redirect(url_for('variables_paie_bp.variables_paie', mois=mois, annee=annee))
