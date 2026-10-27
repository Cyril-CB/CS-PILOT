"""Clôture administrative des fiches entièrement couvertes par des absences.

Les absences de la table absences sont déjà enregistrées par la direction/la
comptabilité ou issues d'un congé définitivement validé. Une clôture automatique
n'usurpe aucune des trois signatures du circuit ordinaire.
"""
from datetime import date

from fiches_contenu import calculer_contenu
from fiches_versions import enregistrer_version, evenement
from utils import maintenant


def salarie_absent_a_date(conn, user_id, jour):
    """Une absence enregistrée couvrant le jour, hors mi-temps thérapeutique."""
    jour_iso = jour.isoformat() if isinstance(jour, date) else jour
    return bool(conn.execute("""
        SELECT 1 FROM absences
        WHERE user_id=? AND date_debut<=? AND date_fin>=?
          AND motif != 'Mi-temps thérapeutique'
        LIMIT 1
    """, (user_id, jour_iso, jour_iso)).fetchone())


def cloturer_mois_absences_completes(conn, mois, annee, aujourdhui=None):
    """Clôture les fiches éligibles d'un mois fini, dans la transaction appelante.

    Appel idempotent : aucune signature existante n'est remplacée, aucune fiche
    déjà verrouillée ou réouverte n'est traitée. Ne fait jamais commit lui-même.
    Le processus n'est pas un traitement de paie et ne certifie aucun paiement.
    """
    today = aujourdhui or maintenant().date()
    if not 1 <= mois <= 12 or not 1 <= annee <= 9998 or (annee, mois) >= (today.year, today.month):
        return 0

    premier = f"{annee:04d}-{mois:02d}-01"
    suivant = f"{annee + (mois == 12):04d}-{(mois % 12) + 1:02d}-01"
    # Évite de recalculer les fiches de tout l'effectif lorsque personne n'a
    # été absent sur le mois concerné.
    candidats = conn.execute("""
        SELECT DISTINCT u.id FROM users u JOIN absences a ON a.user_id=u.id
        WHERE u.actif=1 AND u.profil NOT IN ('directeur', 'prestataire')
          AND a.date_debut < ? AND a.date_fin >= ?
          AND a.motif != 'Mi-temps thérapeutique'
    """, (suivant, premier)).fetchall()

    nb_cloturees = 0
    for candidat in candidats:
        uid = candidat['id']
        # Une validation partielle, même obsolète, reste à traiter par le
        # circuit habituel. Évite aussi de reclôturer après une réouverture.
        if conn.execute(
            'SELECT 1 FROM validations WHERE user_id=? AND mois=? AND annee=?',
            (uid, mois, annee)
        ).fetchone():
            continue
        if conn.execute("""
            SELECT 1 FROM fiches_evenements
            WHERE user_id=? AND mois=? AND annee=? AND evenement='reouverture'
            LIMIT 1
        """, (uid, mois, annee)).fetchone():
            continue

        contenu = calculer_contenu(conn, uid, mois, annee)
        if contenu['aucun_contrat'] or contenu['nb_jours_non_declares']:
            continue
        # Seuls les jours effectivement prévus au travail, dans un contrat et
        # hors férié, doivent être intégralement couverts. Sans aucune journée
        # attendue (planning absent ou mois hors contrat), aucune clôture.
        attendus = [
            j['date'] for j in contenu['journees']
            if j['heures_theoriques'] > 0 and not j['est_ferie'] and not j['hors_contrat']
        ]
        if not attendus:
            continue

        absences = conn.execute("""
            SELECT id, motif, date_debut, date_fin FROM absences
            WHERE user_id=? AND date_debut < ? AND date_fin >= ?
              AND motif != 'Mi-temps thérapeutique'
        """, (uid, suivant, premier)).fetchall()
        commentaires = {
            j: {f"Absence #{a['id']} - {a['motif']}"
                for a in absences if a['date_debut'] <= j <= a['date_fin']}
            for j in attendus
        }
        heures = conn.execute("""
            SELECT date, type_saisie, declaration_conforme, commentaire
            FROM heures_reelles WHERE user_id=? AND date>=? AND date<?
        """, (uid, premier, suivant)).fetchall()
        # Toute intervention autre qu'une projection d'absence (même une
        # déclaration conforme manuelle, y compris un samedi) interdit
        # explicitement la clôture automatique.
        if any(h['type_saisie'] != 'absence' or not h['declaration_conforme']
               for h in heures):
            continue
        par_jour = {h['date']: h for h in heures}
        if any(not commentaires[j] or j not in par_jour
               or par_jour[j]['commentaire'] not in commentaires[j] for j in attendus):
            continue

        version_id = enregistrer_version(conn, contenu, 'cloture_absence_complete')
        now = maintenant().isoformat(timespec='microseconds')
        # Circuit 3 : clôture administrative, distincte des circuits ordinaires
        # 1 (historique) et 2 (signatures salarié/responsable/direction).
        conn.execute("""
            INSERT INTO validations
                (user_id, mois, annee, bloque, circuit_version, version_courante_id)
            VALUES (?, ?, ?, 1, 3, ?)
        """, (uid, mois, annee, version_id))
        evenement(conn, uid, annee, mois, 'cloture_absence_complete', version_id,
                  details={'motif': 'Absences validées sur toutes les journées travaillées',
                           'circuit_version': 3, 'date_cloture': now},
                  date_evenement=now)
        nb_cloturees += 1
    return nb_cloturees
