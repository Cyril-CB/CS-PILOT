"""
Construction du fil d'actions — l'accueil sans menu, et les tableaux de bord
qui le précèdent (direction / responsable / comptable).

**Le fil ne porte aucune donnée informative fixe.** Chaque carte attend une
décision, signale un risque réel ou annonce une échéance — sinon elle
disparaît. C'est ce qui le sépare d'un tableau de bord d'indicateurs : un
compteur qui affiche la même chose tous les jours n'apprend rien et use
l'attention de son lecteur.

Deux conséquences pratiques, appliquées partout ici :

- **on nomme, on n'agrège pas.** « 30 fiches à valider » n'est pas
  actionnable — c'est décourageant, et rien n'indique par où commencer. Le fil
  montre donc une ou deux fiches, désignées par leur salarié et classées par
  ce qui les rend urgentes, puis une ligne discrète pour le reste. Traiter la
  première fait remonter la suivante ;
- **une carte qui n'appelle rien s'efface.** Les compteurs à zéro, les
  situations normales et les rappels déjà traités ne sont pas construits.

Chaque item porte un libellé, un détail (date), un lien et un niveau d'urgence
(retard / urgent / normal) pour le code couleur. Le tri place les plus urgents
en tête.
"""
import logging
from datetime import date, timedelta

from flask import url_for

from blueprints.delegations import (MISSION_SUIVI_COMMANDES_FOURNITURES,
                                    MISSION_SUIVI_VALIDATIONS_RELANCES,
                                    user_has_delegation)
import flux_circuits
from utils import (NOMS_MOIS, aujourd_hui, calculer_solde_recup, get_setting,
                   save_setting)

logger = logging.getLogger(__name__)

_ORDRE_URGENCE = {'retard': 0, 'urgent': 1, 'normal': 2}

# Nombre de cartes nominatives par famille avant de basculer sur « et N autres ».
# Deux : de quoi commencer sans que la famille noie le reste du fil.
MAX_CARTES_NOMMEES = 2

# Jour du mois où la préparation de paie se rappelle aux responsables et à la
# direction. Assez tôt pour laisser le temps de régulariser, assez tard pour
# que le mois soit presque écrit.
JOUR_RAPPEL_PAIE = 20


def _to_date(valeur):
    """Parse les 10 premiers caractères (YYYY-MM-DD) ; None si invalide."""
    if not valeur:
        return None
    try:
        return date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


def _fr(d):
    """date -> 'JJ/MM/AAAA'."""
    return d.strftime('%d/%m/%Y') if d else ''


def _fr_num(x):
    """Nombre -> notation française compacte ('3', '3,5')."""
    return f"{x:g}".replace('.', ',')


def _periode_demande(r):
    """« du 20/07/2026 au 24/07/2026 (5 j) » — ou « le 20/07/2026 (1 j) »."""
    debut, fin = _to_date(r['date_debut']), _to_date(r['date_fin'])
    if not debut:
        return ''
    quand = f"le {_fr(debut)}" if (not fin or fin == debut) else f"du {_fr(debut)} au {_fr(fin)}"
    return f"{quand} ({_fr_num(r['nb_jours'])} j)"


def _urgence_echeance(d, today):
    if not d:
        return 'normal'
    jours = (d - today).days
    if jours < 0:
        return 'retard'
    if jours <= 7:
        return 'urgent'
    return 'normal'


def _reste(nb, libelle, lien, lien_texte, cle, icone, categorie):
    """Carte discrète annonçant la file d'attente derrière les cartes nommées.

    Elle ne demande rien : elle dit seulement que le sujet ne s'arrête pas aux
    cartes visibles. Son urgence est toujours « normal » — c'est le rappel qui
    compte, pas l'alarme, et les cartes nommées portent déjà celle-ci.
    """
    return {
        'id': f'reste-{cle}',
        'categorie': categorie,
        'type': 'lien',
        'icone': icone,
        'titre': f"et {nb} autre{'s' if nb > 1 else ''} {libelle}",
        'detail': 'traitées ensuite, une fois les premières faites',
        'lien': lien,
        'lien_texte': lien_texte,
        'urgence': 'normal',
    }


def _urgence_depot(d, today):
    if not d:
        return 'normal'
    jours = (today - d).days
    if jours > 14:
        return 'retard'
    if jours > 7:
        return 'urgent'
    return 'normal'


def _solde_du_mois(conn, user_id, mois, annee, planning_cache, periode_cache):
    """Écart heures réelles − théoriques d'un salarié sur un mois.

    Sommer les journées saisies suffit : une journée non saisie est réputée
    conforme au planning et pèse zéro dans l'écart, exactement comme la fiche
    mensuelle la traite. Une lecture qui échoue vaut zéro plutôt que de faire
    tomber le fil entier.
    """
    from blueprints.worktime_metrics import compute_day_metrics

    dernier = (date(annee + (mois == 12), (mois % 12) + 1, 1) - timedelta(days=1))
    rows = conn.execute(
        '''SELECT * FROM heures_reelles
           WHERE user_id = ? AND date >= ? AND date <= ?''',
        (user_id, f'{annee:04d}-{mois:02d}-01', dernier.isoformat())
    ).fetchall()

    total = 0.0
    for row in rows:
        try:
            total += compute_day_metrics(conn, user_id, row,
                                         planning_cache, periode_cache)['delta']
        except Exception:
            logger.warning("Solde du mois : journée ignorée (user %s, %s)",
                           user_id, row['date'], exc_info=True)
    return round(total, 2)


def _est_cdd(conn, user_id, annee, mois):
    """Le salarié était-il en CDD sur ce mois ?

    Change ce que le circuit annonce : les heures d'un CDD se paient et se
    régularisent sur un nombre de bulletins compté, celles d'un CDI se
    récupèrent. La conséquence d'un retard n'est pas la même.
    """
    debut = f'{annee:04d}-{mois:02d}-01'
    fin = (date(annee + (mois == 12), (mois % 12) + 1, 1) - timedelta(days=1)).isoformat()
    return conn.execute(
        '''SELECT 1 FROM contrats
           WHERE user_id = ? AND UPPER(type_contrat) LIKE 'CDD%'
             AND date_debut <= ? AND (date_fin IS NULL OR date_fin >= ?)
           LIMIT 1''',
        (user_id, fin, debut)
    ).fetchone() is not None


def _deja_traite(role, mois, annee):
    """Condition SQL « cette fiche ne demande plus rien à ce lecteur ».

    Retourne le couple (fragment SQL, paramètres). Le fragment se lit à
    l'intérieur d'un `SELECT ... FROM validations v`.

    Toujours vraie quand la fiche est verrouillée. Vraie en plus, dès qu'un
    `role` est nommé ('responsable' ou 'directeur'), quand ce rôle a signé : le
    lecteur a fait sa part, la fiche appartient désormais à l'autre valideur.

    **Sauf si la fiche a bougé depuis.** Un salarié peut modifier ses heures
    tant que la fiche n'est pas verrouillée : `saisie.py` l'autorise, garde la
    signature en place et se contente d'enregistrer une anomalie. Ce qui a été
    approuvé n'existe alors plus, et masquer la carte laisserait la direction
    verrouiller une version que le responsable n'a jamais vue. Le journal des
    modifications (`historique_modifications`, alimenté par la saisie des
    heures comme par les absences) tranche : une trace postérieure à la
    signature remet la fiche dans le fil de son signataire, jusqu'à ce qu'il
    signe de nouveau.

    La comparaison exige une horloge unique : la date de signature et celle du
    journal sont toutes deux écrites par `utils.maintenant()`, jamais par le
    défaut SQLite `CURRENT_TIMESTAMP` qui est en UTC.

    `role` vient d'un choix fermé du code appelant (jamais d'une saisie) :
    l'interpolation des noms de colonnes est sûre.
    """
    if not role:
        return 'v.bloque = 1', ()
    signature, date_signature = f'validation_{role}', f'date_{role}'
    return (
        f"""v.bloque = 1
            OR (v.{signature} IS NOT NULL AND v.{signature} != ''
                AND NOT EXISTS (
                    SELECT 1 FROM historique_modifications h
                    WHERE h.user_id_modifie = v.user_id
                      AND h.date_concernee LIKE ?
                      AND h.date_modification > v.{date_signature}
                ))""",
        (f'{annee}-{mois:02d}-%',),
    )


def _fiches_a_valider(conn, profil, user_id, secteur_id, today):
    """Fiches d'heures du mois précédent encore non validées.

    Les deux plus lourdes sont nommées, le reste tient en une ligne. Le
    classement suit le **solde d'heures du mois**, décroissant : plus le solde
    est élevé, plus il pèse sur le compteur de récupération, et plus la
    validation tarde à venir. À enjeu égal on ne saurait pas par où commencer
    — c'est ce tri qui rend la carte actionnable.

    La carte dit **que la fiche attend une validation**, et rien d'autre. Le
    solde y figure comme un fait, pas comme un verdict : ce n'est pas ici
    qu'on qualifie un écart, et une fiche chargée n'est pas une anomalie. Les
    heures supplémentaires se récupèrent — elles ne se paient pas, sauf pour
    un CDD — donc rien à « trancher avant la paie ».

    Un responsable ne voit que son équipe, comme la vue d'ensemble le fait
    pour lui ; la direction et la comptabilité voient tout l'effectif.

    **Une fiche sort du fil de qui l'a validée**, sans attendre l'autre
    signature. Le verrouillage demande les deux — responsable puis direction
    — mais s'y fier laissait chacun devant une décision déjà prise : la
    direction retrouvait indéfiniment les fiches qu'elle avait signées, faute
    que le responsable ait fait sa part. Un fil qui redemande ce qui est fait
    cesse d'être cru.

    La comptabilité, qui ne signe pas, suit le circuit entier : pour elle la
    fiche reste jusqu'au verrouillage. Et une fiche modifiée après une
    signature revient dans le fil de son signataire — voir `_deja_traite`.
    """
    if profil == 'responsable':
        scope = 'AND (u.secteur_id = ? OR u.responsable_id = ?)'
        params = (secteur_id, user_id)
        role = 'responsable'
    elif profil in ('directeur', 'comptable'):
        scope, params = '', ()
        role = 'directeur' if profil == 'directeur' else None
    else:
        return []

    mois = today.month - 1 or 12
    annee = today.year if today.month > 1 else today.year - 1
    traite, params_traite = _deja_traite(role, mois, annee)

    salaries = conn.execute(
        f'''SELECT u.id, u.nom, u.prenom FROM users u
            WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
              {scope}
              AND NOT EXISTS (
                  SELECT 1 FROM validations v
                  WHERE v.user_id = u.id AND v.mois = ? AND v.annee = ?
                    AND ({traite})
              )
            ORDER BY u.nom, u.prenom''',
        params + (mois, annee) + params_traite
    ).fetchall()
    if not salaries:
        return []

    planning_cache, periode_cache = {}, {}
    classees = sorted(
        ((s, _solde_du_mois(conn, s['id'], mois, annee, planning_cache, periode_cache))
         for s in salaries),
        key=lambda couple: -couple[1]
    )

    # La paie attend ces fiches : passé le 10, le retard est réel.
    urgence = 'retard' if today.day > 10 else 'urgent'
    nom_mois = NOMS_MOIS[mois].lower()
    actions = []
    for salarie, solde in classees[:MAX_CARTES_NOMMEES]:
        arrondi = round(solde, 1)
        if arrondi > 0:
            detail = f"heures supplémentaires sur le mois : +{_fr_num(arrondi)} h"
        elif arrondi < 0:
            # « Heures supplémentaires : −3 h » se contredirait : un solde
            # négatif n'en est pas.
            detail = f"solde du mois : {_fr_num(arrondi)} h"
        else:
            detail = "solde du mois à l'équilibre"
        actions.append({
            'id': f"fiche-{salarie['id']}-{annee}-{mois:02d}",
            'categorie': 'validation',
            'type': 'lien',
            'icone': '✅',
            'titre': (f"Fiche à valider — {salarie['prenom']} {salarie['nom']}, "
                      f"{nom_mois}"),
            'detail': detail,
            'lien': url_for('validation_bp.vue_mensuelle', user_id=salarie['id'],
                            mois=mois, annee=annee),
            'lien_texte': 'Ouvrir la fiche',
            'urgence': urgence,
            'circuit': flux_circuits.fiche_heures(
                profil, today, est_cdd=_est_cdd(conn, salarie['id'], annee, mois),
                solde=arrondi),
        })

    reste = len(classees) - len(actions)
    if reste > 0:
        actions.append(_reste(
            reste, f"fiche{'s' if reste > 1 else ''} de {nom_mois}",
            url_for('validation_bp.vue_ensemble_validation'), 'Vue ensemble',
            f'fiches-{annee}-{mois:02d}', '✅', 'validation'))
    return actions


def _factures_a_valider(conn, profil, user_id, secteur_id, today):
    """Factures en attente d'approbation dans le périmètre d'un responsable.

    La direction reçoit déjà ses factures une par une (`_actions_etendues`) :
    seul le responsable n'avait rien dans son fil, alors que les factures de
    son secteur l'attendent. Même prédicat que la page d'approbation, pour ne
    pas annoncer plus que la destination n'affiche.
    """
    if profil != 'responsable' or not secteur_id:
        return []

    rows = conn.execute(
        '''SELECT f.id, f.numero_facture, f.montant_ttc, f.date_echeance,
                  fr.nom AS fournisseur_nom
           FROM factures f
           LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
           WHERE f.approbation = 'en_attente' AND f.secteur_id = ?
           ORDER BY f.date_echeance ASC, f.date_facture ASC''',
        (secteur_id,)
    ).fetchall()
    if not rows:
        return []

    actions = []
    for r in rows[:MAX_CARTES_NOMMEES]:
        ech = _to_date(r['date_echeance'])
        montant = f"{(r['montant_ttc'] or 0):,.2f}".replace(',', ' ').replace('.', ',')
        actions.append({
            'id': f"fact-{r['id']}",
            'categorie': 'facture',
            'type': 'facture',
            'facture_id': r['id'],
            'icone': '🧾',
            'titre': f"Facture {r['fournisseur_nom'] or r['numero_facture'] or ''} — {montant} €",
            'detail': (f"échéance le {_fr(ech)}" if ech else "en attente d'approbation"),
            'lien': url_for('factures_bp.detail_facture', facture_id=r['id']),
            'lien_texte': 'Détail',
            'urgence': _urgence_echeance(ech, today),
            'circuit': flux_circuits.facture('en_attente', r['date_echeance'],
                                             profil, today),
        })

    reste = len(rows) - len(actions)
    if reste > 0:
        actions.append(_reste(
            reste, f"facture{'s' if reste > 1 else ''} du secteur",
            url_for('factures_bp.approbation_factures'), 'Approbation',
            'factures-secteur', '🧾', 'facture'))
    return actions


def cle_preparation_paie(mois, annee, user_id):
    """Clé de mémorisation du rappel de préparation de paie, par personne.

    Le signalement se fait **hors de l'application** — un mail ou un mot à la
    comptabilité — et chacun ne répond que de son périmètre. Un rappel éteint
    collectivement laisserait le premier à cliquer effacer celui des autres,
    qui n'ont rien signalé.
    """
    return f'paie_signalee_{annee:04d}_{mois:02d}_u{user_id}'


def _preparation_paie(conn, profil, user_id, secteur_id, today):
    """Rappel daté : les cas particuliers que la paie ne devinera pas.

    Une fiche absente n'est pas toujours un oubli — un salarié mis à pied,
    licencié en cours de mois ou un CDD jamais saisi n'en produira jamais. La
    comptabilité doit les traiter à la main, et le seul moment utile pour y
    penser est avant la clôture, pas après.

    Elle s'adresse aux **responsables et à la direction**, qui signalent ; la
    comptabilité, elle, reçoit le signalement et a ses propres cartes.

    Chacun ne compte que son périmètre — un responsable son équipe, la
    direction tout l'effectif. Sans ce cadrage, un responsable lirait les
    situations RH des autres équipes, et éteindrait un rappel portant sur des
    salariés dont il n'a pas à répondre.

    Deux des quatre cas se calculent (CDD sans fiche, absence sans
    justificatif) et sont nommés. Les deux autres — mise à pied, licenciement
    — ne sont modélisés nulle part : `users` ne porte qu'un drapeau `actif`,
    sans motif de sortie. Aucun calcul ne peut les trouver, et c'est
    précisément pour cela qu'un humain doit y penser. La carte les rappelle
    donc en toutes lettres.

    Le geste attendu se fait hors de l'application : prévenir la comptabilité,
    par mail ou de vive voix. L'application ne peut donc rien constater — d'où
    le bouton « C'est fait », déclaratif, qui n'éteint le rappel que pour
    celui qui l'a signalé.
    """
    if profil not in ('directeur', 'responsable'):
        return []
    if today.day < JOUR_RAPPEL_PAIE:
        return []

    mois, annee = today.month, today.year
    if get_setting(cle_preparation_paie(mois, annee, user_id)):
        return []

    from blueprints.absences import MOTIFS_AVEC_JUSTIFICATIF

    debut = f'{annee:04d}-{mois:02d}-01'
    fin = (date(annee + (mois == 12), (mois % 12) + 1, 1) - timedelta(days=1)).isoformat()

    if profil == 'responsable':
        scope = 'AND (u.secteur_id = ? OR u.responsable_id = ?)'
        params = (secteur_id, user_id)
    else:
        scope, params = '', ()

    # CDD sous contrat sur le mois, sans la moindre saisie : la paie n'a rien.
    cdd_sans_fiche = conn.execute(
        f'''SELECT COUNT(DISTINCT u.id) AS nb FROM users u
            JOIN contrats c ON c.user_id = u.id
            WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
              {scope}
              AND UPPER(c.type_contrat) LIKE 'CDD%'
              AND c.date_debut <= ? AND (c.date_fin IS NULL OR c.date_fin >= ?)
              AND NOT EXISTS (
                  SELECT 1 FROM heures_reelles h
                  WHERE h.user_id = u.id AND h.date >= ? AND h.date <= ?
              )''',
        params + (fin, debut, debut, fin)
    ).fetchone()['nb']

    # Seuls les motifs qui appellent réellement une pièce. Un congé validé
    # crée une ligne d'absence sans justificatif par construction : le
    # compter ferait sonner ce rappel tous les mois pour rien.
    motifs = ','.join('?' for _ in MOTIFS_AVEC_JUSTIFICATIF)
    absences_sans_justificatif = conn.execute(
        f'''SELECT COUNT(*) AS nb FROM absences a
            JOIN users u ON u.id = a.user_id
            WHERE a.date_debut <= ? AND a.date_fin >= ?
              AND a.motif IN ({motifs})
              AND (a.justificatif_path IS NULL OR a.justificatif_path = '')
              {scope}''',
        (fin, debut) + MOTIFS_AVEC_JUSTIFICATIF + params
    ).fetchone()['nb']

    constats = []
    if cdd_sans_fiche:
        constats.append(f"{cdd_sans_fiche} CDD sans aucune fiche d'heures")
    if absences_sans_justificatif:
        constats.append(f"{absences_sans_justificatif} absence(s) sans justificatif")
    constats.append('signaler à la comptabilité les mises à pied et licenciements')

    return [{
        'id': f'paie-{annee}-{mois:02d}',
        'categorie': 'conges',
        'type': 'paie',
        'paie_mois': mois,
        'paie_annee': annee,
        'icone': '📆',
        'titre': f"Signaler à la comptabilité — paie de {NOMS_MOIS[mois].lower()}",
        'detail': ' · '.join(constats),
        'lien': url_for('validation_bp.vue_ensemble_validation'),
        'lien_texte': 'Vue ensemble',
        'urgence': 'urgent',
    }]


def _fournitures_en_attente(conn, profil, user_id, today):
    """Demandes de fournitures que personne n'a encore traitées.

    Réservées au **seul porteur de la délégation** « suivi des commandes ».
    C'est une mission confiée à quelqu'un : la servir aussi à la direction et
    à la comptabilité doublerait le travail et diluerait la responsabilité —
    chacun supposant que l'autre s'en charge. Sans délégué désigné, ces cartes
    n'apparaissent à personne, et c'est le comportement voulu : la file se
    consulte alors sur sa page, elle ne réclame personne en particulier.

    Classées par urgence déclarée, celle du demandeur — c'est la seule
    information dont on dispose sur ce qui presse.
    """
    if not user_has_delegation(user_id, MISSION_SUIVI_COMMANDES_FOURNITURES):
        return []

    rows = conn.execute(
        '''SELECT c.id, c.description, c.quantite, c.urgence, c.date_demande,
                  u.nom, u.prenom
           FROM commandes_salaries c
           JOIN users u ON u.id = c.user_id
           WHERE c.groupe = 'en_cours'
           ORDER BY CASE c.urgence WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1
                                   ELSE 2 END,
                    c.date_demande ASC'''
    ).fetchall()
    if not rows:
        return []

    # L'urgence déclarée décide de la couleur : « peut attendre » ne doit pas
    # se présenter comme une décision du jour.
    tons = {'urgent': 'urgent', 'normal': 'normal', 'peut_attendre': 'normal'}
    libelles = {'urgent': 'urgent', 'normal': 'normal', 'peut_attendre': 'peut attendre'}

    actions = []
    for r in rows[:MAX_CARTES_NOMMEES]:
        depot = _to_date(r['date_demande'])
        quantite = f"{r['quantite']} × " if (r['quantite'] or 1) > 1 else ''
        actions.append({
            'id': f"fourn-{r['id']}",
            'categorie': 'facture',
            'type': 'lien',
            'icone': '📦',
            'titre': f"{quantite}{r['description']} — {r['prenom']} {r['nom']}",
            'detail': (f"{libelles.get(r['urgence'], r['urgence'])}"
                       + (f", demandé le {_fr(depot)}" if depot else '')),
            'lien': url_for('commandes_salaries_bp.commandes_salaries'),
            'lien_texte': 'Traiter',
            'urgence': tons.get(r['urgence'], 'normal'),
            'circuit': flux_circuits.fourniture(r['date_demande'], profil, today,
                                                urgence=r['urgence']),
        })

    reste = len(rows) - len(actions)
    if reste > 0:
        actions.append(_reste(
            reste, f"demande{'s' if reste > 1 else ''} de fournitures",
            url_for('commandes_salaries_bp.commandes_salaries'), 'Fournitures',
            'fournitures', '📦', 'facture'))
    return actions


def _budgets_depasses(conn, profil, user_id, secteur_id, today):
    """Secteurs dont les dépenses réelles ont passé le budget prévu.

    Un dépassement est un fait accompli, pas une échéance : il ne se rattrape
    pas, il se décide (réaffecter, arbitrer, alerter). D'où le ton « retard ».
    La comparaison est celle de la page budget — poste par poste, un prévu à
    zéro n'étant jamais « dépassé » puisqu'il n'a rien prévu.

    Un responsable ne voit que son secteur ; direction et comptabilité voient
    tout.
    """
    if profil == 'responsable':
        if not secteur_id:
            return []
        scope, params = 'AND postes.secteur_id = ?', (secteur_id,)
    elif profil in ('directeur', 'comptable'):
        scope, params = '', ()
    else:
        return []

    # Un poste ALP est réparti sur plusieurs périodes (mercredis, vacances…) ;
    # la page budget le juge sur leur **total**, pas période par période. Sans
    # ce regroupement, 150 dépensés sur une période budgétée 100 crieraient au
    # dépassement alors que le poste, budgété 1000 au total, est largement
    # sous enveloppe. On agrège donc avant de comparer — un poste annuel n'a
    # qu'une ligne, l'agrégation le laisse intact.
    rows = conn.execute(
        f'''WITH postes AS (
                SELECT b.secteur_id,
                       p.poste_depense_id,
                       SUM(p.montant) AS prevu,
                       (SELECT COALESCE(SUM(r.montant), 0)
                        FROM budget_reel_lignes r
                        WHERE r.budget_id = p.budget_id
                          AND r.poste_depense_id = p.poste_depense_id) AS reel
                FROM budget_lignes p
                JOIN budgets b ON b.id = p.budget_id
                WHERE b.annee = ?
                GROUP BY p.budget_id, p.poste_depense_id
            )
            SELECT s.id AS secteur_id, s.nom AS secteur_nom,
                   COUNT(*) AS nb_postes,
                   SUM(postes.reel - postes.prevu) AS depassement
            FROM postes
            JOIN secteurs s ON s.id = postes.secteur_id
            WHERE postes.prevu > 0 AND postes.reel > postes.prevu
              {scope}
            GROUP BY s.id, s.nom
            ORDER BY depassement DESC''',
        (today.year,) + params
    ).fetchall()
    if not rows:
        return []

    actions = []
    for r in rows[:MAX_CARTES_NOMMEES]:
        euros = f"{(r['depassement'] or 0):,.0f}".replace(',', ' ')
        actions.append({
            'id': f"budget-{r['secteur_id']}-{today.year}",
            'categorie': 'subvention',
            'type': 'lien',
            'icone': '📉',
            'titre': f"Budget dépassé — {r['secteur_nom']}",
            'detail': (f"{euros} € au-dessus du prévu sur "
                       f"{r['nb_postes']} poste{'s' if r['nb_postes'] > 1 else ''}"),
            'lien': url_for('budget_bp.budget_secteur', secteur_id=r['secteur_id']),
            'lien_texte': 'Ouvrir le budget',
            'urgence': 'retard',
        })

    reste = len(rows) - len(actions)
    if reste > 0:
        actions.append(_reste(
            reste, f"secteur{'s' if reste > 1 else ''} en dépassement",
            url_for('budget_bp.gestion_budgets'), 'Budgets',
            'budgets', '📉', 'subvention'))
    return actions


def _taches_du_jour(conn, user_id, today):
    """Tâches que le planificateur a posées aujourd'hui.

    Volontairement agrégée : le planificateur est déjà l'écran qui détaille
    et réordonne. Le fil rappelle seulement qu'il y a une journée posée, et y
    conduit — le détail se lit là-bas, pas ici.
    """
    if not user_id:
        return []

    nb = conn.execute(
        '''SELECT COUNT(*) AS nb FROM planif_blocs b
           JOIN planif_taches t ON t.id = b.tache_id
           WHERE b.user_id = ? AND b.date = ?
             AND b.statut != 'fait' AND t.statut != 'fait' ''',
        (user_id, today.isoformat())
    ).fetchone()['nb']
    if not nb:
        return []

    return [{
        'id': f"planif-{today.isoformat()}",
        'categorie': 'surcharge',
        'type': 'lien',
        'icone': '🗂️',
        'titre': f"{nb} tâche{'s' if nb > 1 else ''} prévue{'s' if nb > 1 else ''} aujourd'hui",
        'detail': 'journée posée par le planificateur',
        'lien': url_for('planificateur_bp.planificateur'),
        'lien_texte': 'Planificateur',
        'urgence': 'urgent',
    }]


def _contrats_sans_pdf(conn, profil, today):
    """Contrats en cours dont le PDF signé manque au dossier.

    La comptabilité est seule concernée : c'est elle qui archive les pièces.
    Distinct du contrat absent de la base — ici le contrat existe, c'est le
    document scanné qui manque, et lui seul fait foi en cas de contrôle.
    """
    if profil != 'comptable':
        return []

    jour = today.isoformat()
    rows = conn.execute(
        '''WITH derniers AS (
               SELECT c.user_id, MAX(c.id) AS contrat_id
               FROM contrats c
               JOIN users u ON u.id = c.user_id
               WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
                 AND c.date_debut <= ? AND (c.date_fin IS NULL OR c.date_fin >= ?)
               GROUP BY c.user_id
           )
           SELECT u.id, u.nom, u.prenom, c.type_contrat
           FROM derniers d
           JOIN contrats c ON c.id = d.contrat_id
           JOIN users u ON u.id = d.user_id
           WHERE c.fichier_path IS NULL OR c.fichier_path = ''
           ORDER BY u.nom, u.prenom''',
        (jour, jour)
    ).fetchall()
    if not rows:
        return []

    actions = []
    for r in rows[:MAX_CARTES_NOMMEES]:
        actions.append({
            'id': f"contratpdf-{r['id']}",
            'categorie': 'conges',
            'type': 'lien',
            'icone': '📄',
            'titre': f"Contrat manquant au dossier — {r['prenom']} {r['nom']}",
            'detail': f"{r['type_contrat'] or 'Contrat'} en cours, PDF signé non déposé",
            'lien': url_for('infos_salaries_bp.infos_salaries', user_id=r['id']),
            'lien_texte': 'Fiche salarié',
            'urgence': 'normal',
        })

    reste = len(rows) - len(actions)
    if reste > 0:
        actions.append(_reste(
            reste, f"contrat{'s' if reste > 1 else ''} sans PDF",
            url_for('infos_salaries_bp.infos_salaries'), 'Infos salariés',
            'contrats-pdf', '📄', 'conges'))
    return actions


def construire_actions(conn, profil, user_id, secteur_id=None,
                       etendu=False, seuils=None, surcharges=None):
    """Retourne la liste des actions à faire du tableau de bord d'un profil.

    - directeur / comptable : toutes les demandes en attente + toutes les
      échéances de subventions.
    - responsable : demandes de son secteur + subventions dont il est assigné.

    En mode « étendu » (centre de contrôle direction), la liste s'enrichit
    d'items actionnables en un clic : factures à valider par la direction,
    fiches du mois précédent à relancer, salariés en surcharge (liste
    `surcharges` calculée par l'appelant, filtrée par seuil) et soldes de
    congés conventionnels au-dessus du seuil. Chaque item porte alors un
    `id` stable et un `type` ('facture' / 'demande' / 'relance' / 'lien')
    avec les données nécessaires à l'action.
    """
    actions = []
    today = aujourd_hui()
    seuils = seuils or {}

    # Seuls ces profils valident des demandes. Un salarié — même porteur d'une
    # délégation qui lui ouvre l'accueil sans menu — n'a rien à valider : lui
    # servir la branche « toutes les demandes » exposerait les congés, les
    # dates et les soldes de tout le monde.
    valide_des_demandes = profil in ('directeur', 'comptable', 'responsable')

    # 1. Demandes de récupération / congé à valider.
    if profil == 'responsable':
        # Équipe = secteur + rattachés directs (responsable_id), même d'un
        # autre secteur analytique.
        statut_clause = "d.statut = 'en_attente_responsable'"
        scope_clause = 'AND (u.secteur_id = ? OR u.responsable_id = ?)'
        scope_params = (secteur_id, user_id)
    else:  # directeur / comptable
        statut_clause = "d.statut IN ('en_attente_responsable', 'en_attente_direction')"
        scope_clause = ''
        scope_params = ()

    # Récupérations : dates de la période + solde de récupération du salarié.
    rows = conn.execute(
        f"""SELECT d.id, d.date_demande, d.statut, d.date_debut, d.date_fin,
                   d.nb_jours, d.nb_heures, u.id AS uid, u.nom, u.prenom
            FROM demandes_recup d JOIN users u ON u.id = d.user_id
            WHERE {statut_clause} {scope_clause}
            ORDER BY d.date_demande ASC
            LIMIT 25""",
        scope_params
    ).fetchall() if valide_des_demandes else []
    for r in rows:
        depot = _to_date(r['date_demande'])
        parts = [p for p in (_periode_demande(r),
                             f"déposée le {_fr(depot)}" if depot else '') if p]
        parts.append('validée responsable, à valider'
                     if r['statut'] == 'en_attente_direction'
                     else 'en attente du responsable')
        try:
            solde_h = calculer_solde_recup(r['uid'])
            if r['nb_heures']:
                parts.append(f"solde récup après validation : "
                             f"{solde_h - r['nb_heures']:.1f} h".replace('.', ','))
            else:
                parts.append(f"solde récup actuel : {solde_h:.1f} h".replace('.', ','))
        except Exception:
            pass   # le solde est une aide, jamais bloquant
        actions.append({
            'id': f"dem-recup-{r['id']}",
            'categorie': 'validation',
            'type': 'demande',
            'demande_id': r['id'],
            'demande_type': 'recup',
            'icone': '📋',
            'titre': f"Demande de récupération : {r['prenom']} {r['nom']}",
            'detail': ' — '.join(parts),
            'lien': url_for('recup_bp.validation_demandes_recup'),
            'lien_texte': 'Valider',
            'urgence': _urgence_depot(depot, today),
            'circuit': flux_circuits.demande_recup(
                r['statut'], r['date_demande'], profil, today),
        })

    # Congés : dates + solde du compteur concerné APRÈS validation (CP ou
    # congés conventionnels), pour valider en connaissance de cause.
    rows = conn.execute(
        f"""SELECT d.id, d.date_demande, d.statut, d.date_debut, d.date_fin,
                   d.nb_jours, d.type_conge, u.nom, u.prenom,
                   COALESCE(u.cp_a_prendre, 0) AS cp_a_prendre,
                   COALESCE(u.cp_pris, 0) AS cp_pris,
                   COALESCE(u.cc_solde, 0) AS cc_solde
            FROM demandes_conges d JOIN users u ON u.id = d.user_id
            WHERE {statut_clause} {scope_clause}
            ORDER BY d.date_demande ASC
            LIMIT 25""",
        scope_params
    ).fetchall() if valide_des_demandes else []
    for r in rows:
        depot = _to_date(r['date_demande'])
        parts = [p for p in (_periode_demande(r),
                             f"déposée le {_fr(depot)}" if depot else '') if p]
        parts.append('validée responsable, à valider'
                     if r['statut'] == 'en_attente_direction'
                     else 'en attente du responsable')
        if r['type_conge'] == 'Congé payé':
            apres = r['cp_a_prendre'] - r['cp_pris'] - r['nb_jours']
            parts.append(f"solde CP après validation : {_fr_num(apres)} j")
        elif r['type_conge'] == 'Congé conventionnel':
            apres = r['cc_solde'] - r['nb_jours']
            parts.append(f"solde CC après validation : {_fr_num(apres)} j")
        type_lbl = (r['type_conge'] or 'congé').lower()
        actions.append({
            'id': f"dem-conge-{r['id']}",
            'categorie': 'validation',
            'type': 'demande',
            'demande_id': r['id'],
            'demande_type': 'conge',
            'icone': '📋',
            'titre': f"Demande de {type_lbl} : {r['prenom']} {r['nom']}",
            'detail': ' — '.join(parts),
            'lien': url_for('recup_bp.validation_demandes_recup'),
            'lien_texte': 'Valider',
            'circuit': flux_circuits.demande_conge(
                r['statut'], r['date_demande'], profil, today,
                nb_jours=r['nb_jours']),
            'urgence': _urgence_depot(depot, today),
        })

    # 2. Subventions : étapes (sous-éléments) à échéance et non terminées.
    # Le responsable voit les étapes des subventions dont il est assigné (parent)
    # ainsi que celles des sous-éléments qui lui sont directement attribués — en
    # cohérence avec la notification d'attribution par e-mail.
    # Une carte de subvention mène à la page des subventions et propose de
    # marquer l'étape faite : les deux sont fermés à tout profil hors direction,
    # comptabilité et responsables. On ne propose donc pas d'action que le
    # lecteur ne pourrait ni ouvrir ni conclure.
    suit_des_subventions = profil in ('directeur', 'comptable', 'responsable')

    # La direction et la comptabilité suivent tous les dossiers ; un
    # responsable, seulement ceux qui lui sont confiés.
    if profil in ('directeur', 'comptable'):
        sub_scope = ''
        sub_params = ()
    else:
        sub_scope = 'AND (s.assignee_1_id = ? OR s.assignee_2_id = ? OR se.assignee_id = ?)'
        sub_params = (user_id, user_id, user_id)

    # On exclut uniquement les subventions refusées : une subvention acceptée
    # garde des échéances actionnables (bilans qualitatif / financier).
    rows = conn.execute(
        f"""SELECT se.id, se.nom AS etape, se.date_echeance, s.nom AS sub_nom, s.annee_action
            FROM subventions_sous_elements se
            JOIN subventions s ON s.id = se.subvention_id
            WHERE se.date_echeance IS NOT NULL AND se.date_echeance != ''
              AND se.statut != 'fait'
              AND s.groupe != 'refusee'
              {sub_scope}
            ORDER BY se.date_echeance ASC
            LIMIT 25""",
        sub_params
    ).fetchall() if suit_des_subventions else []
    # La page subventions filtre par année (année courante par défaut). Pour que
    # la subvention pointée reste visible, on cible son année si elle est dans la
    # plage du filtre (N-3..N+2), sinon « toutes » (année absente ou hors plage).
    annee_min, annee_max = today.year - 3, today.year + 2
    for r in rows:
        ech = _to_date(r['date_echeance'])
        annee = f" ({r['annee_action']})" if r['annee_action'] else ''
        annee_sub = (r['annee_action'] or '').strip()
        if annee_sub.isdigit() and len(annee_sub) == 4 and annee_min <= int(annee_sub) <= annee_max:
            lien_sub = url_for('subventions_bp.gestion_subventions', annee=annee_sub)
        else:
            lien_sub = url_for('subventions_bp.gestion_subventions', annee='toutes')
        actions.append({
            'id': f"sub-{r['id']}",
            'categorie': 'subvention',
            'type': 'subvention',
            'se_id': r['id'],
            'icone': '💶',
            'titre': f"{r['sub_nom']}{annee} — {r['etape']}",
            'detail': f"échéance le {_fr(ech)}" if ech else '',
            'lien': lien_sub,
            'lien_texte': 'Voir',
            'urgence': _urgence_echeance(ech, today),
            'circuit': flux_circuits.subvention(r['date_echeance'], profil, today,
                                                etape_nom=r['etape']),
        })

    # 3. Ce que chaque profil doit trancher, nommé plutôt que compté. Chaque
    # constructeur décide seul de son public et ne rend rien quand il n'y a
    # rien à dire : une famille sans objet ne laisse aucune trace dans le fil.
    for constructeur, arguments in (
        (_fiches_a_valider, (profil, user_id, secteur_id, today)),
        (_factures_a_valider, (profil, user_id, secteur_id, today)),
        (_preparation_paie, (profil, user_id, secteur_id, today)),
        (_fournitures_en_attente, (profil, user_id, today)),
        (_budgets_depasses, (profil, user_id, secteur_id, today)),
        (_taches_du_jour, (user_id, today)),
        (_contrats_sans_pdf, (profil, today)),
    ):
        try:
            actions.extend(constructeur(conn, *arguments))
        except Exception:
            # Une famille en panne (table absente, base verrouillée) ne doit
            # pas emporter le fil entier : les autres décisions restent dues.
            logger.warning("Fil d'actions : %s indisponible", constructeur.__name__,
                           exc_info=True)

    if etendu and profil in ('directeur', 'comptable'):
        actions.extend(_actions_etendues(conn, profil, user_id, today, seuils, surcharges))

    # Les plus urgents d'abord, puis par ordre d'insertion (déjà trié par date).
    actions.sort(key=lambda a: _ORDRE_URGENCE.get(a['urgence'], 2))
    return actions


def _actions_etendues(conn, profil, user_id, today, seuils, surcharges):
    """Items supplémentaires du centre de contrôle direction / comptable."""
    actions = []

    # 3. Factures à valider par la direction (approbation en un clic). On ne
    # retient que les factures assignées à la direction (`assigned_direction =
    # 1`) : celles rattachées à un secteur relèvent de son responsable (elles
    # restent traitées sur la page d'approbation), et une facture non assignée
    # n'est pas encore entrée dans le circuit. Le centre de contrôle direction
    # n'affiche donc que ce que la direction doit réellement traiter.
    rows = conn.execute('''
        SELECT f.id, f.numero_facture, f.montant_ttc, f.date_echeance,
               fr.nom AS fournisseur_nom
        FROM factures f
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        WHERE f.approbation = 'en_attente'
          AND f.assigned_direction = 1
        ORDER BY f.date_echeance ASC, f.date_facture ASC
        LIMIT 15
    ''').fetchall()
    for r in rows:
        ech = _to_date(r['date_echeance'])
        montant = f"{(r['montant_ttc'] or 0):,.2f}".replace(',', ' ').replace('.', ',')
        if ech:
            jours = (ech - today).days
            if jours < 0:
                detail = f"échéance dépassée de {-jours} jour(s) ({_fr(ech)})"
            else:
                detail = f"échéance dans {jours} jour(s) ({_fr(ech)})"
        else:
            detail = "en attente d'approbation"
        actions.append({
            'id': f"fact-{r['id']}",
            'categorie': 'facture',
            'type': 'facture',
            'facture_id': r['id'],
            'icone': '🧾',
            'titre': f"Facture {r['fournisseur_nom'] or r['numero_facture'] or ''} — {montant} €",
            'detail': detail,
            'lien': url_for('factures_bp.detail_facture', facture_id=r['id']),
            'lien_texte': 'Détail',
            'urgence': _urgence_echeance(ech, today),
        })

    # 4. Relance des responsables sur les fiches du mois précédent.
    # Les fiches elles-mêmes sont désormais nommées une à une par
    # `_fiches_a_valider` : il ne reste ici que le geste collectif — l'envoi
    # groupé d'un rappel — qui n'a pas d'équivalent carte par carte.
    mois_prec = today.month - 1 or 12
    annee_prec = today.year if today.month > 1 else today.year - 1
    peut_relancer = (profil == 'directeur'
                     or user_has_delegation(user_id, MISSION_SUIVI_VALIDATIONS_RELANCES))
    # On relance les responsables : ne comptent que les fiches qu'ils n'ont pas
    # signées — ou qui ont bougé depuis leur signature. Une fiche déjà signée
    # par eux et en attente de la direction n'attend rien d'un rappel qui leur
    # serait adressé.
    traite, params_traite = _deja_traite('responsable', mois_prec, annee_prec)
    fiches = conn.execute(f'''
        SELECT COUNT(*) AS nb FROM users u
        WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
          AND NOT EXISTS (
              SELECT 1 FROM validations v
              WHERE v.user_id = u.id AND v.mois = ? AND v.annee = ?
                AND ({traite})
          )
    ''', (mois_prec, annee_prec) + params_traite).fetchone()
    if fiches['nb'] > 0 and peut_relancer:
        actions.append({
            'id': f"relance-{annee_prec}-{mois_prec:02d}",
            'categorie': 'validation',
            'type': 'relance',
            'icone': '📧',
            'titre': f"Relancer les responsables — {NOMS_MOIS[mois_prec].lower()}",
            'detail': f"{fiches['nb']} fiche(s) encore non validée(s)",
            'lien': url_for('validation_bp.vue_ensemble_validation'),
            'lien_texte': 'Vue ensemble',
            'relance_mois': mois_prec,
            'relance_annee': annee_prec,
            # Urgent passé le 10 du mois (la paie attend les fiches).
            'urgence': 'urgent' if today.day > 10 else 'normal',
        })

    # 5. Salariés en surcharge (score calculé par l'appelant, déjà filtré par seuil).
    for s in (surcharges or [])[:5]:
        actions.append({
            'id': f"surch-{s['user_id']}",
            'categorie': 'surcharge',
            'type': 'lien',
            'icone': '🚨',
            'titre': f"Surcharge : {s['nom_complet']}",
            'detail': (f"score {s['score']}/100 ({s['category']['label']}) — "
                       f"{s['solde_actuel']:.1f} h à récupérer"),
            'lien': url_for('suivi_bp.alertes_surcharge'),
            'lien_texte': 'Alertes surcharge',
            'urgence': 'retard' if s['score'] >= 76 else 'urgent',
        })

    # 6. Soldes de congés conventionnels au-dessus du seuil : à planifier.
    # Même forme que les autres familles — les deux plus lourds nommés, le
    # reste en une ligne. Cinq cartes de congés d'affilée noyaient les
    # décisions du jour pour un sujet qui, lui, se planifie.
    seuil_conges = seuils.get('conges')
    if seuil_conges is not None:
        rows = conn.execute('''
            SELECT u.id, u.nom, u.prenom, COALESCE(u.cc_solde, 0) AS cc_solde
            FROM users u
            WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
              AND COALESCE(u.cc_solde, 0) >= ?
            ORDER BY u.cc_solde DESC
        ''', (seuil_conges,)).fetchall()

        nommes = []
        for r in rows[:MAX_CARTES_NOMMEES]:
            solde = f"{r['cc_solde']:g}".replace('.', ',')
            nommes.append({
                'id': f"conge-{r['id']}",
                'categorie': 'conges',
                'type': 'lien',
                'icone': '🏖️',
                'titre': f"Solde congés conventionnels élevé : {r['prenom']} {r['nom']}",
                'detail': f"{solde} j de congés conventionnels à planifier (seuil {seuil_conges:g} j)",
                'lien': url_for('absences_bp.absences', search_user_id=r['id']),
                'lien_texte': 'Planifier',
                'urgence': 'normal',
            })
        actions.extend(nommes)

        reste = len(rows) - len(nommes)
        if reste > 0:
            actions.append(_reste(
                reste, f"solde{'s' if reste > 1 else ''} au-dessus du seuil",
                url_for('infos_salaries_bp.soldes_conges'), 'Soldes de congés',
                'conges-eleves', '🏖️', 'conges'))

    return actions
