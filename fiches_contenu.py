"""Contenu métier commun aux fiches, signatures et PDF.

Aucune connexion secondaire, aucune écriture, aucune dépendance à la session.
Les opérations en cours sont lues dans la transaction fournie par l'appelant.
"""
from datetime import date, datetime, timedelta

from utils import (calculer_heures_reelles_jour, duree_pause_meridienne,
                   slot_horaire, get_heures_theoriques_jour, get_type_periode,
                   get_planning_valide_a_date, periodes_contrat, est_hors_contrat,
                   total_hs_payees)


def _formater_horaires(*horaires):
    plages = [f"{debut} - {fin}" for debut, fin in zip(horaires[::2], horaires[1::2])
              if debut and fin]
    return ' / '.join(plages) if plages else '-'


def calculer_contenu(conn, user_id, mois, annee, aujourdhui=date.max):
    """Valeurs signées ; date.max rend la complétude indépendante de l'horloge.

    L'interface peut demander une projection limitée aux jours déjà écoulés.
    Les signatures concernent exclusivement des mois terminés.
    """
    user = conn.execute('SELECT nom, prenom FROM users WHERE id=?', (user_id,)).fetchone()
    if user is None:
        raise ValueError('Salarié introuvable pour cette fiche.')
    # Premier et dernier jour du mois
    premier_jour = datetime(annee, mois, 1)
    if mois == 12:
        dernier_jour = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier_jour = datetime(annee, mois + 1, 1) - timedelta(days=1)

    # Heures reelles du mois
    heures_reelles = {}
    heures_rows = conn.execute('''
        SELECT * FROM heures_reelles
        WHERE user_id = ? AND date >= ? AND date <= ?
    ''', (user_id, premier_jour.strftime('%Y-%m-%d'), dernier_jour.strftime('%Y-%m-%d'))).fetchall()

    for h in heures_rows:
        heures_reelles[h['date']] = dict(h)

    jours_feries_rows = conn.execute('''
        SELECT date, libelle FROM jours_feries
        WHERE date >= ? AND date <= ?
    ''', (premier_jour.strftime('%Y-%m-%d'), dernier_jour.strftime('%Y-%m-%d'))).fetchall()
    jours_feries = {f['date']: f['libelle'] for f in jours_feries_rows}

    # Périodes d'emploi : hors contrat, une journée n'est ni due ni à saisir.
    # Le planning théorique ne peut pas en tenir lieu — il n'a pas de fin de
    # validité, celui d'un CDD reste donc « valide » longtemps après son
    # terme, et il n'existe pas avant son premier jour. C'est ce qui faisait
    # réclamer la saisie de journées où le salarié n'était pas employé.
    contrats_salarie = periodes_contrat(conn, user_id)

    # Generer toutes les journees du mois
    journees = []
    jour_actuel = premier_jour
    total_heures_theoriques = 0
    total_heures_reelles = 0

    while jour_actuel <= dernier_jour:
        date_str = jour_actuel.strftime('%Y-%m-%d')
        jour_semaine = jour_actuel.weekday()  # 0=lundi, 6=dimanche
        est_ferie = date_str in jours_feries
        libelle_ferie = jours_feries.get(date_str)

        if jour_semaine < 6:
            if jour_semaine == 5 and date_str not in heures_reelles and not est_ferie:
                jour_actuel += timedelta(days=1)
                continue

            type_periode = get_type_periode(date_str, conn=conn)
            jour_hors_contrat = est_hors_contrat(contrats_salarie, date_str)

            heures_theo_jour = 0
            horaires_theoriques = '-'
            planning_existe = False
            if jour_semaine == 5 or jour_hors_contrat:
                heures_theo_jour = 0
            else:
                planning = get_planning_valide_a_date(user_id, type_periode, date_str, conn=conn)
                if planning:
                    planning_existe = True
                    heures_theo_jour = get_heures_theoriques_jour(planning, jour_semaine)
                    jour_nom = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi'][jour_semaine]
                    horaires_theoriques = _formater_horaires(
                        planning[f'{jour_nom}_matin_debut'],
                        planning[f'{jour_nom}_matin_fin'],
                        planning[f'{jour_nom}_aprem_debut'],
                        planning[f'{jour_nom}_aprem_fin'],
                        slot_horaire(planning, f'{jour_nom}_soir_debut'),
                        slot_horaire(planning, f'{jour_nom}_soir_fin'),
                    )

            heures_reelles_jour = 0
            horaires_reels = '-'
            est_saisi = False
            est_declare = False
            type_saisie = None
            commentaire = None
            non_declare = False
            pause_remuneree_jour = False

            if date_str in heures_reelles:
                h = heures_reelles[date_str]
                est_declare = bool(h.get('declaration_conforme', 0))

                if est_declare:
                    heures_reelles_jour = heures_theo_jour
                    est_saisi = True
                    horaires_reels = horaires_theoriques
                else:
                    est_saisi = True
                    heures_reelles_jour = calculer_heures_reelles_jour(h)
                    pause_remuneree_jour = bool(h.get('pause_remuneree')) and duree_pause_meridienne(h) > 0
                    horaires_reels = _formater_horaires(
                        h['heure_debut_matin'],
                        h['heure_fin_matin'],
                        h['heure_debut_aprem'],
                        h['heure_fin_aprem'],
                        slot_horaire(h, 'heure_debut_soir'),
                        slot_horaire(h, 'heure_fin_soir'),
                    )

                type_saisie = h['type_saisie']
                commentaire = h['commentaire']
            elif est_ferie and jour_semaine < 5 and not jour_hors_contrat:
                heures_reelles_jour = heures_theo_jour
                horaires_reels = horaires_theoriques
                est_declare = True
                type_saisie = 'ferie'
                commentaire = libelle_ferie
            else:
                # Jour de repos planifié : un planning est défini et fixe des
                # heures théoriques nulles ce jour-là (ex. un mercredi non
                # travaillé). La déclaration y est facultative et ne bloque pas
                # la validation du mois.
                # À l'inverse, si AUCUN planning n'est défini (heures théoriques
                # nulles faute de configuration), on continue de réclamer la
                # déclaration afin de ne pas masquer ce manque et permettre la
                # validation d'une fiche entièrement vide.
                jour_repos_planifie = planning_existe and heures_theo_jour == 0
                if (jour_actuel.date() < aujourdhui
                        and jour_semaine < 5
                        and not jour_repos_planifie
                        and not jour_hors_contrat):
                    non_declare = True
                heures_reelles_jour = heures_theo_jour

            ecart = heures_reelles_jour - heures_theo_jour

            # Jour de repos habituel : jour ouvré (lun-ven) avec un planning
            # défini mais sans heures théoriques, ni férié, ni saisi. Permet
            # d'afficher un statut clair (« Repos ») au lieu d'une journée vide
            # à compléter. Un jour sans planning n'est PAS un repos habituel.
            est_repos_habituel = (
                jour_semaine < 5
                and planning_existe
                and heures_theo_jour == 0
                and not est_ferie
                and not est_saisi
            )

            total_heures_theoriques += heures_theo_jour
            total_heures_reelles += heures_reelles_jour

            noms_jours = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']

            journees.append({
                'date': date_str,
                'date_obj': jour_actuel,
                'jour_semaine': noms_jours[jour_semaine],
                'jour_semaine_idx': jour_semaine,
                'est_samedi': jour_semaine == 5,
                'heures_theoriques': heures_theo_jour,
                'heures_reelles': heures_reelles_jour,
                'horaires_theoriques': horaires_theoriques,
                'horaires_reels': horaires_reels,
                'ecart': ecart,
                'est_saisi': est_saisi,
                'est_declare': est_declare,
                'non_declare': non_declare,
                # Une saisie existante l'emporte sur l'affichage « hors
                # contrat » : des heures enregistrées se montrent toujours,
                # quitte à révéler un contrat oublié au dossier.
                'hors_contrat': jour_hors_contrat and not est_saisi,
                'est_repos_habituel': est_repos_habituel,
                'type_saisie': type_saisie,
                'commentaire': commentaire,
                'type_periode': type_periode,
                'est_ferie': est_ferie,
                'libelle_ferie': libelle_ferie,
                'pause_remuneree': pause_remuneree_jour,
            })

        jour_actuel += timedelta(days=1)

    # Solde du mois
    solde_mois = total_heures_reelles - total_heures_theoriques

    # Solde anterieur
    try:
        user_data = conn.execute('SELECT solde_initial FROM users WHERE id = ?', (user_id,)).fetchone()
        solde_anterieur = user_data['solde_initial'] if user_data and user_data['solde_initial'] else 0
    except (Exception,):
        solde_anterieur = 0

    heures_anterieures = conn.execute('''
        SELECT date, heure_debut_matin, heure_fin_matin,
               heure_debut_aprem, heure_fin_aprem,
               heure_debut_soir, heure_fin_soir, declaration_conforme,
               pause_remuneree
        FROM heures_reelles
        WHERE user_id = ? AND date < ?
        ORDER BY date
    ''', (user_id, premier_jour.strftime('%Y-%m-%d'))).fetchall()

    for h in heures_anterieures:
        date_obj_ant = datetime.strptime(h['date'], '%Y-%m-%d')
        jour_semaine_ant = date_obj_ant.weekday()

        type_periode = get_type_periode(h['date'], conn=conn)
        total_theorique = 0

        if jour_semaine_ant < 5:
            planning_ant = get_planning_valide_a_date(user_id, type_periode, h['date'], conn=conn)
            if planning_ant:
                total_theorique = get_heures_theoriques_jour(planning_ant, jour_semaine_ant)

        if h['declaration_conforme']:
            total_reel = total_theorique
        else:
            total_reel = calculer_heures_reelles_jour(h)

        solde_anterieur += (total_reel - total_theorique)

    # Heures supp payées (variables de paie, déduites du compteur) : les paies
    # antérieures au mois affiché sortent du solde antérieur, celle du mois
    # affiché sort du cumul — la fiche reste alignée sur le solde du dashboard.
    solde_anterieur -= total_hs_payees(conn, user_id,
                                       annee=annee, mois=mois, avant=True)
    hs_payees_mois = total_hs_payees(conn, user_id, annee=annee, mois=mois)
    solde_cumule = solde_anterieur + solde_mois - hs_payees_mois

    nb_jours_non_declares = sum(1 for j in journees if j.get('non_declare', False))

    return dict(
        format_contenu=1, user_id=user_id, mois=mois, annee=annee,
        identite=dict(user), journees=journees,
        absences=[dict(r) for r in conn.execute(
            "SELECT id, motif, date_debut, date_fin, commentaire, jours_ouvres FROM absences "
            "WHERE user_id=? AND date_debut<=? AND date_fin>=? ORDER BY id",
            (user_id, dernier_jour.strftime('%Y-%m-%d'), premier_jour.strftime('%Y-%m-%d')))],
        total_heures_theoriques=total_heures_theoriques,
        total_heures_reelles=total_heures_reelles, solde_mois=solde_mois,
        solde_anterieur=solde_anterieur, solde_cumule=solde_cumule,
        hs_payees_mois=hs_payees_mois, nb_jours_non_declares=nb_jours_non_declares,
        aucun_contrat=not contrats_salarie, jours_feries=jours_feries,
        premier_jour_semaine=premier_jour.weekday(), nb_jours_mois=dernier_jour.day,
    )
