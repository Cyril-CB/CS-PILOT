"""
Blueprint tresorerie_bp - Module de tresorerie avec projection de solde.

Fonctionnalites :
- Import de fichiers FEC (historique complet ou mise a jour banque mensuelle)
- Projection du solde de tresorerie sur plusieurs mois
- Gestion des comptes (activer/desactiver, libelle, ordre, type)
- Colonne Budget N ajustable par compte/mois
- Comptes 471xxx affiches separement (comptes d'attente)
- Exclusion automatique des comptes 512xxx, 531xxx (banque/caisse) et 580xxx (virements internes)
- Accessible aux profils directeur et comptable
"""
import csv
import io
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from database import get_db
from utils import login_required

tresorerie_bp = Blueprint('tresorerie_bp', __name__)

NOMS_MOIS = ['', 'Jan', 'Fev', 'Mar', 'Avr', 'Mai', 'Jun',
             'Jul', 'Aou', 'Sep', 'Oct', 'Nov', 'Dec']

NOMS_MOIS_COMPLET = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                     'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

# Comptes exclus de la tresorerie (contrepartie banque/caisse + virements internes)
COMPTES_EXCLUS_PREFIXES = ('512', '531', '580')
# Comptes d'attente affiches separement
COMPTES_ATTENTE_PREFIX = '471'


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


def _classifier_compte(compte_num):
    """Classifie un compte selon le plan comptable francais.

    Retourne 'produit' si c'est un compte de recettes/entrees,
    'charge' si c'est un compte de depenses/sorties,
    'attente' si c'est un compte d'attente (471xxx).
    """
    if compte_num.startswith(COMPTES_ATTENTE_PREFIX):
        return 'attente'

    premier = compte_num[0] if compte_num else ''
    # Classe 7 = Produits (revenus)
    if premier == '7':
        return 'produit'
    # Classe 6 = Charges (depenses) - sorties directes
    if premier == '6':
        return 'charge'
    # Comptes de tiers - plus nuance
    # 4xx : en general des tiers
    if premier == '4':
        deux = compte_num[:2] if len(compte_num) >= 2 else ''
        trois = compte_num[:3] if len(compte_num) >= 3 else ''
        # Fournisseurs (401), URSSAF (431), Apicil (433), Mutuelle (437),
        # Taxe salaires (447), Uniformation (448), PAS (442),
        # Comite etabl. (422), CNRACL (437100), Cotisation URSSAF (645100 -> 6xx)
        # Salaires (421), Auxiliaire salaries (467)
        # Tresor public (427)
        if deux in ('40', '42', '43', '44'):
            return 'charge'
        if trois in ('467',):
            return 'charge'
        # Clients/recettes : 411, 468 (subventions a recevoir), 445 (CAF)
        if trois in ('411', '445', '468'):
            return 'produit'
    # Classe 5 = Financiers (hors 512/531 deja exclus)
    # 511 = Cheques/valeurs a l'encaissement -> entree
    if compte_num.startswith('511'):
        return 'produit'

    # Par defaut, determiner selon le signe moyen historique
    return 'auto'


def _parse_fec_line(line_dict):
    """Parse une ligne de FEC et retourne les champs utiles.
    Retourne None si la ligne doit etre ignoree.
    """
    compte_num = (line_dict.get('CompteNum') or '').strip()
    if not compte_num:
        return None
    # Exclure les A nouveaux identifies par le journal AN
    if (line_dict.get('JournalCode') or '').strip().upper() == 'AN':
        return None
    # Exclure les comptes banque/caisse
    for prefix in COMPTES_EXCLUS_PREFIXES:
        if compte_num.startswith(prefix):
            return None
    # Exclure les A nouveaux sur comptes de bilan (1xx/2xx)
    texte_ecriture = ' '.join([
        (line_dict.get('JournalLib') or ''),
        (line_dict.get('EcritureLib') or ''),
        (line_dict.get('PieceRef') or ''),
    ]).lower().replace('à', 'a')
    if compte_num.startswith(('1', '2')) and (
        'a nouveaux' in texte_ecriture or 'a nouveau' in texte_ecriture
    ):
        return None

    date_str = (line_dict.get('EcritureDate') or '').strip()
    if len(date_str) != 8:
        return None

    try:
        annee = int(date_str[:4])
        mois = int(date_str[4:6])
    except (ValueError, IndexError):
        return None

    if mois < 1 or mois > 12:
        return None

    debit_str = (line_dict.get('Debit') or '0').strip().replace(',', '.')
    credit_str = (line_dict.get('Credit') or '0').strip().replace(',', '.')
    try:
        debit = float(debit_str) if debit_str else 0
        credit = float(credit_str) if credit_str else 0
    except ValueError:
        debit = 0
        credit = 0

    libelle = (line_dict.get('CompteLib') or '').strip()

    return {
        'compte_num': compte_num,
        'libelle': libelle,
        'annee': annee,
        'mois': mois,
        'debit': debit,
        'credit': credit,
        'net': credit - debit,  # positif = entree, negatif = sortie
    }


def _process_fec_content(content, conn, user_id, type_import='historique'):
    """Traite le contenu d'un fichier FEC et insere les donnees.

    Retourne un dict avec les statistiques d'import.
    """
    # Detecter le separateur (tab ou point-virgule)
    first_line = content.split('\n')[0] if content else ''
    if '\t' in first_line:
        delimiter = '\t'
    elif ';' in first_line:
        delimiter = ';'
    else:
        delimiter = '\t'

    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)

    # Accumuler les montants par compte/annee/mois
    totaux = {}  # {(compte_num, annee, mois): {'net': float, 'libelle': str}}
    nb_ecritures = 0
    comptes_vus = set()
    mois_min = None
    mois_max = None
    annee_val = None

    for row in reader:
        parsed = _parse_fec_line(row)
        if not parsed:
            continue

        nb_ecritures += 1
        key = (parsed['compte_num'], parsed['annee'], parsed['mois'])
        comptes_vus.add(parsed['compte_num'])

        if key not in totaux:
            totaux[key] = {'net': 0, 'libelle': parsed['libelle']}
        totaux[key]['net'] += parsed['net']
        # Garder le dernier libelle non vide
        if parsed['libelle']:
            totaux[key]['libelle'] = parsed['libelle']

        # Tracker les bornes
        annee_val = parsed['annee']
        period_key = (parsed['annee'], parsed['mois'])
        if mois_min is None or period_key < mois_min:
            mois_min = period_key
        if mois_max is None or period_key > mois_max:
            mois_max = period_key

    if nb_ecritures == 0:
        return {'error': 'Aucune ecriture valide trouvee dans le fichier.'}

    # Enregistrer l'import
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tresorerie_imports
        (type_import, fichier_nom, annee, mois_debut, mois_fin, nb_ecritures, nb_comptes, importe_par)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        type_import, 'import_fec',
        annee_val,
        mois_min[1] if mois_min else None,
        mois_max[1] if mois_max else None,
        nb_ecritures, len(comptes_vus), user_id
    ))
    import_id = cursor.lastrowid

    # Inserer/mettre a jour les donnees mensuelles
    for (compte_num, annee, mois), data in totaux.items():
        cursor.execute('''
            INSERT INTO tresorerie_donnees (compte_num, annee, mois, montant, import_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(compte_num, annee, mois)
            DO UPDATE SET montant = ?, import_id = ?, updated_at = CURRENT_TIMESTAMP
        ''', (compte_num, annee, mois, round(data['net'], 2), import_id,
              round(data['net'], 2), import_id))

    # Creer/mettre a jour les comptes
    for compte_num in comptes_vus:
        # Trouver un libelle pour ce compte
        libelle = ''
        for key, data in totaux.items():
            if key[0] == compte_num and data['libelle']:
                libelle = data['libelle']
                break

        type_compte = _classifier_compte(compte_num)

        # Si 'auto', determiner selon le signe du total
        if type_compte == 'auto':
            total = sum(d['net'] for k, d in totaux.items() if k[0] == compte_num)
            type_compte = 'produit' if total >= 0 else 'charge'

        existing = cursor.execute(
            'SELECT id FROM tresorerie_comptes WHERE compte_num = ?',
            (compte_num,)
        ).fetchone()

        if not existing:
            # Determiner l'ordre par defaut
            if type_compte == 'produit':
                ordre = 100
            elif type_compte == 'attente':
                ordre = 500
            else:
                ordre = 300

            cursor.execute('''
                INSERT INTO tresorerie_comptes
                (compte_num, libelle_original, libelle_affiche, type_compte, ordre_affichage)
                VALUES (?, ?, ?, ?, ?)
            ''', (compte_num, libelle, libelle, type_compte, ordre))
        else:
            # Mettre a jour le libelle original si vide
            cursor.execute('''
                UPDATE tresorerie_comptes
                SET libelle_original = COALESCE(NULLIF(libelle_original, ''), ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE compte_num = ? AND (libelle_original IS NULL OR libelle_original = '')
            ''', (libelle, compte_num))

    # Nettoyer les comptes exclus qui auraient ete importes precedemment
    for prefix in COMPTES_EXCLUS_PREFIXES:
        cursor.execute("DELETE FROM tresorerie_donnees WHERE compte_num LIKE ?",
                        (prefix + '%',))
        cursor.execute("DELETE FROM tresorerie_comptes WHERE compte_num LIKE ?",
                        (prefix + '%',))

    conn.commit()

    return {
        'success': True,
        'nb_ecritures': nb_ecritures,
        'nb_comptes': len(comptes_vus),
        'annee': annee_val,
        'mois_debut': mois_min[1] if mois_min else None,
        'mois_fin': mois_max[1] if mois_max else None,
        'import_id': import_id,
    }


def _build_projection(conn, annee_debut, mois_debut, nb_mois=18):
    """Construit les donnees de projection de tresorerie.

    Retourne un dict avec toutes les donnees necessaires au template.
    """
    # Generer la liste des periodes (annee, mois)
    periodes = []
    a, m = annee_debut, mois_debut
    for _ in range(nb_mois):
        periodes.append((a, m))
        m += 1
        if m > 12:
            m = 1
            a += 1

    # Recuperer le solde initial global (persiste en BDD)
    solde_row = conn.execute(
        'SELECT montant, annee_ref, mois_ref FROM tresorerie_solde_initial ORDER BY id DESC LIMIT 1'
    ).fetchone()
    solde_initial_global = solde_row['montant'] if solde_row else 0
    solde_ref_annee = solde_row['annee_ref'] if (solde_row and solde_row['annee_ref']) else annee_debut
    solde_ref_mois = solde_row['mois_ref'] if (solde_row and solde_row['mois_ref']) else mois_debut

    # Calculer le solde initial pour la vue actuelle en sommant les flux
    # entre la periode de reference et le debut de la vue
    solde_initial = solde_initial_global
    if (solde_ref_annee, solde_ref_mois) < (annee_debut, mois_debut):
        # Sommer les flux nets des mois entre ref et debut de vue
        pre_rows = conn.execute('''
            SELECT COALESCE(SUM(montant), 0) as total
            FROM tresorerie_donnees
            WHERE (annee > ? OR (annee = ? AND mois >= ?))
              AND (annee < ? OR (annee = ? AND mois < ?))
              AND compte_num NOT LIKE '512%'
              AND compte_num NOT LIKE '531%'
              AND compte_num NOT LIKE '580%'
              AND compte_num NOT LIKE '471%'
              AND compte_num IN (SELECT compte_num FROM tresorerie_comptes WHERE actif = 1)
        ''', (solde_ref_annee, solde_ref_annee, solde_ref_mois,
              annee_debut, annee_debut, mois_debut)).fetchone()
        solde_initial += pre_rows['total'] if pre_rows else 0

    # Ajuster aussi pour les mouvements d'epargne anterieurs a la vue
    pre_epargne = conn.execute('''
        SELECT COALESCE(SUM(
            CASE WHEN type_mouvement = 'retrait' THEN montant
                 WHEN type_mouvement = 'placement' THEN -montant
                 ELSE 0 END
        ), 0) as total
        FROM tresorerie_epargne_mouvements
        WHERE (annee > ? OR (annee = ? AND mois >= ?))
          AND (annee < ? OR (annee = ? AND mois < ?))
    ''', (solde_ref_annee, solde_ref_annee, solde_ref_mois,
          annee_debut, annee_debut, mois_debut)).fetchone()
    solde_initial += pre_epargne['total'] if pre_epargne else 0

    # Recuperer tous les comptes actifs
    comptes = conn.execute('''
        SELECT * FROM tresorerie_comptes
        WHERE actif = 1
        ORDER BY type_compte, ordre_affichage, compte_num
    ''').fetchall()
    comptes = [dict(c) for c in comptes]

    # Exclure les comptes qui correspondent aux prefixes exclus
    # (securite : au cas ou des donnees auraient ete importees avant l'ajout d'une exclusion)
    comptes = [c for c in comptes
               if not any(c['compte_num'].startswith(p) for p in COMPTES_EXCLUS_PREFIXES)]

    # Recuperer toutes les donnees de tresorerie pour la plage
    # Filtrer par comptes actifs (hors attente et prefixes exclus) pour que
    # dernier_reel ne soit pas pollue par des comptes inactifs/hors projection
    annee_fin = periodes[-1][0]
    comptes_nums_actifs = [c['compte_num'] for c in comptes]
    if comptes_nums_actifs:
        placeholders = ','.join('?' for _ in comptes_nums_actifs)
        donnees_rows = conn.execute(f'''
            SELECT compte_num, annee, mois, montant
            FROM tresorerie_donnees
            WHERE (annee > ? OR (annee = ? AND mois >= ?))
              AND (annee < ? OR (annee = ? AND mois <= ?))
              AND compte_num IN ({placeholders})
        ''', (annee_debut, annee_debut, mois_debut,
              annee_fin, annee_fin, periodes[-1][1],
              *comptes_nums_actifs)).fetchall()
    else:
        donnees_rows = []

    # Indexer: {(compte_num, annee, mois): montant}
    donnees = {}
    for row in donnees_rows:
        donnees[(row['compte_num'], row['annee'], row['mois'])] = row['montant']

    # Recuperer les Budget N
    budget_rows = conn.execute('''
        SELECT compte_num, annee, mois, montant
        FROM tresorerie_budget_n
        WHERE (annee > ? OR (annee = ? AND mois >= ?))
          AND (annee < ? OR (annee = ? AND mois <= ?))
    ''', (annee_debut, annee_debut, mois_debut,
          annee_fin, annee_fin, periodes[-1][1])).fetchall()

    budgets = {}
    for row in budget_rows:
        budgets[(row['compte_num'], row['annee'], row['mois'])] = row['montant']

    # Determiner le dernier mois avec des donnees reelles (pour marquer la projection)
    dernier_reel = None
    if donnees:
        all_periods = set((k[1], k[2]) for k in donnees.keys())
        if all_periods:
            dernier_reel = max(all_periods)

    # === PROJECTION AUTOMATIQUE ===
    # Logique : pour les mois sans donnees reelles, projeter en se basant sur N-1.
    # Mois restants de l'annee N : repartition du solde restant par rapport a N-1
    #   - Produits : max(0, cumul_N-1_jusqua_M - cumul_N_actuel)
    #   - Charges  : min(0, cumul_N-1_jusqua_M - cumul_N_actuel)
    # Annee N+1 : rejouer les valeurs mensuelles de N (reelles + projetees)
    projections_auto = {}
    a_n_1_disponible = False

    if dernier_reel:
        annee_n = dernier_reel[0]
        mois_reel_max = dernier_reel[1]
        annee_n_1 = annee_n - 1

        # Charger TOUTES les donnees N et N-1 (pas seulement la fenetre affichee)
        ref_rows = conn.execute('''
            SELECT compte_num, annee, mois, montant
            FROM tresorerie_donnees
            WHERE annee IN (?, ?)
        ''', (annee_n_1, annee_n)).fetchall()

        ref_data = {}
        for row in ref_rows:
            ref_data[(row['compte_num'], row['annee'], row['mois'])] = row['montant']

        # Verifier qu'on a des donnees N-1
        a_n_1_disponible = any(k[1] == annee_n_1 for k in ref_data.keys())

        if a_n_1_disponible:
            for c in comptes:
                compte_num = c['compte_num']
                type_compte = c['type_compte']
                if type_compte == 'attente':
                    continue

                # --- Mois restants de annee_n (apres dernier_reel) ---
                for m_proj in range(mois_reel_max + 1, 13):
                    # Cumul N-1 de janvier jusqu'au mois m_proj
                    cumul_n_1 = sum(
                        ref_data.get((compte_num, annee_n_1, mi), 0)
                        for mi in range(1, m_proj + 1)
                    )
                    # Cumul N : reel (jan -> dernier_reel) + projections deja calculees
                    cumul_n = 0
                    for mi in range(1, m_proj):
                        if mi <= mois_reel_max:
                            cumul_n += ref_data.get((compte_num, annee_n, mi), 0)
                        else:
                            cumul_n += projections_auto.get((compte_num, annee_n, mi), 0)

                    remaining = cumul_n_1 - cumul_n
                    if type_compte == 'produit':
                        proj_val = max(0.0, remaining)
                    else:
                        proj_val = min(0.0, remaining)

                    projections_auto[(compte_num, annee_n, m_proj)] = round(proj_val, 2)

                # --- Annee N+1 : rejouer les valeurs mensuelles de N ---
                for m_replay in range(1, 13):
                    val_n = ref_data.get((compte_num, annee_n, m_replay), 0)
                    proj_n = projections_auto.get((compte_num, annee_n, m_replay))
                    replay_val = proj_n if proj_n is not None else val_n
                    if replay_val:
                        projections_auto[(compte_num, annee_n + 1, m_replay)] = round(replay_val, 2)

    # Construire les lignes de comptes
    comptes_produits = []
    comptes_charges = []
    comptes_attente = []

    for c in comptes:
        ligne = {
            'compte_num': c['compte_num'],
            'libelle': c['libelle_affiche'] or c['libelle_original'] or c['compte_num'],
            'type_compte': c['type_compte'],
            'ordre': c['ordre_affichage'],
            'valeurs': [],
            'total_annuel': {},  # {annee: total}
        }

        for (a, m) in periodes:
            reel = donnees.get((c['compte_num'], a, m))
            budget = budgets.get((c['compte_num'], a, m))
            auto_proj = projections_auto.get((c['compte_num'], a, m))
            # Priorite : Budget N (manuel) > Reel > Projection auto
            if budget is not None:
                valeur = budget
            elif reel is not None:
                valeur = reel
            elif auto_proj is not None:
                valeur = auto_proj
            else:
                valeur = None
            ligne['valeurs'].append({
                'annee': a,
                'mois': m,
                'reel': reel,
                'budget': budget,
                'projection': auto_proj,
                'valeur': valeur,
                'is_reel': reel is not None and budget is None,
                'is_budget': budget is not None,
                'is_projection': auto_proj is not None and budget is None and reel is None,
                'is_vide': valeur is None,
            })

        if c['type_compte'] == 'produit':
            comptes_produits.append(ligne)
        elif c['type_compte'] == 'attente':
            comptes_attente.append(ligne)
        else:
            comptes_charges.append(ligne)

    # Calculer les sous-totaux par periode (solde_cumule calcule plus bas avec epargne)
    sous_total_produits = []
    sous_total_charges = []
    total_net = []

    for i, (a, m) in enumerate(periodes):
        st_prod = sum((l['valeurs'][i]['valeur'] or 0) for l in comptes_produits)
        st_charge = sum((l['valeurs'][i]['valeur'] or 0) for l in comptes_charges)
        net = st_prod + st_charge  # charges sont deja negatives

        sous_total_produits.append(round(st_prod, 2))
        sous_total_charges.append(round(st_charge, 2))
        total_net.append(round(net, 2))

    # Total comptes d'attente
    total_attente = []
    for i, (a, m) in enumerate(periodes):
        st_att = sum((l['valeurs'][i]['valeur'] or 0) for l in comptes_attente)
        total_attente.append(round(st_att, 2))

    # === EPARGNE : solde initial et mouvements ===
    epargne_solde_row = conn.execute(
        'SELECT montant FROM tresorerie_epargne_solde ORDER BY id DESC LIMIT 1'
    ).fetchone()
    epargne_solde_initial = epargne_solde_row['montant'] if epargne_solde_row else 0

    epargne_mvts_rows = conn.execute('''
        SELECT id, type_mouvement, annee, mois, montant, commentaire, created_at
        FROM tresorerie_epargne_mouvements
        ORDER BY annee, mois, id
    ''').fetchall()
    epargne_mouvements = [dict(r) for r in epargne_mvts_rows]

    # Indexer les mouvements epargne par (annee, mois) pour impact tresorerie
    epargne_par_mois = {}  # {(annee, mois): net impact on treasury}
    for mvt in epargne_mouvements:
        key = (mvt['annee'], mvt['mois'])
        if key not in epargne_par_mois:
            epargne_par_mois[key] = 0
        if mvt['type_mouvement'] == 'placement':
            epargne_par_mois[key] -= mvt['montant']  # sort de la tresorerie
        else:  # retrait
            epargne_par_mois[key] += mvt['montant']  # entre dans la tresorerie

    # Recalculer solde_cumule en integrant les mouvements d'epargne
    solde_courant = solde_initial
    solde_cumule = []
    epargne_impact_mois = []
    for i, (a, m) in enumerate(periodes):
        st_prod = sous_total_produits[i]
        st_charge = sous_total_charges[i]
        net = st_prod + st_charge
        impact_epargne = epargne_par_mois.get((a, m), 0)
        solde_courant += net + impact_epargne
        solde_cumule.append(round(solde_courant, 2))
        epargne_impact_mois.append(round(impact_epargne, 2))

    # Calculer le solde d'epargne cumule par periode
    # D'abord, integrer les mouvements anterieurs a la vue
    epargne_courante = epargne_solde_initial
    for mvt in epargne_mouvements:
        if (mvt['annee'], mvt['mois']) < (annee_debut, mois_debut):
            if mvt['type_mouvement'] == 'placement':
                epargne_courante += mvt['montant']
            else:
                epargne_courante -= mvt['montant']

    epargne_solde_cumule = []
    for (a, m) in periodes:
        for mvt in epargne_mouvements:
            if mvt['annee'] == a and mvt['mois'] == m:
                if mvt['type_mouvement'] == 'placement':
                    epargne_courante += mvt['montant']
                else:
                    epargne_courante -= mvt['montant']
        epargne_solde_cumule.append(round(epargne_courante, 2))

    # Recuperer les imports
    imports = conn.execute('''
        SELECT ti.*, u.prenom, u.nom
        FROM tresorerie_imports ti
        LEFT JOIN users u ON ti.importe_par = u.id
        ORDER BY ti.created_at DESC
        LIMIT 20
    ''').fetchall()

    return {
        'periodes': periodes,
        'solde_initial': solde_initial,
        'solde_initial_global': solde_initial_global,
        'solde_ref_annee': solde_ref_annee,
        'solde_ref_mois': solde_ref_mois,
        'comptes_produits': comptes_produits,
        'comptes_charges': comptes_charges,
        'comptes_attente': comptes_attente,
        'sous_total_produits': sous_total_produits,
        'sous_total_charges': sous_total_charges,
        'total_net': total_net,
        'solde_cumule': solde_cumule,
        'total_attente': total_attente,
        'dernier_reel': dernier_reel,
        'imports': [dict(i) for i in imports],
        'noms_mois': NOMS_MOIS,
        'noms_mois_complet': NOMS_MOIS_COMPLET,
        'epargne_solde_initial': epargne_solde_initial,
        'epargne_mouvements': epargne_mouvements,
        'epargne_solde_cumule': epargne_solde_cumule,
        'epargne_impact_mois': epargne_impact_mois,
    }


# ============================================================
# VUE PRINCIPALE : PROJECTION DE TRESORERIE
# ============================================================

@tresorerie_bp.route('/tresorerie')
@login_required
def tresorerie():
    """Vue principale de la projection de tresorerie."""
    if not _peut_acceder():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    now = datetime.now()

    conn = get_db()
    try:
        # Detecter l'annee par defaut en fonction des donnees existantes
        annee = request.args.get('annee', type=int)
        mois = request.args.get('mois', type=int, default=1)
        nb_mois = request.args.get('nb_mois', type=int, default=18)

        if annee is None:
            # Chercher la premiere annee avec des donnees importees
            row = conn.execute(
                'SELECT MIN(annee) as min_a FROM tresorerie_donnees'
            ).fetchone()
            if row and row['min_a']:
                annee = row['min_a']
                # Ajuster nb_mois pour couvrir jusqu'au mois courant + 6 mois
                if 'nb_mois' not in request.args:
                    months_needed = (now.year - annee) * 12 + (now.month - mois) + 6
                    if months_needed > nb_mois:
                        nb_mois = min(months_needed, 36)
            else:
                annee = now.year

        # Limiter
        if nb_mois < 6:
            nb_mois = 6
        elif nb_mois > 36:
            nb_mois = 36

        projection = _build_projection(conn, annee, mois, nb_mois)
    finally:
        conn.close()

    return render_template('tresorerie.html',
                           projection=projection,
                           annee=annee,
                           mois_debut=mois,
                           nb_mois=nb_mois,
                           now=now)


# ============================================================
# IMPORT FEC
# ============================================================

@tresorerie_bp.route('/api/tresorerie/import_fec', methods=['POST'])
@login_required
def api_import_fec():
    """Importe un fichier FEC (TXT tabule)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    fichier = request.files.get('fichier')
    if not fichier or not fichier.filename:
        return jsonify({'error': 'Fichier requis'}), 400

    type_import = request.form.get('type_import', 'historique')
    if type_import not in ('historique', 'banque'):
        type_import = 'historique'

    # Lire le contenu
    try:
        raw = fichier.read()
        # Essayer plusieurs encodages
        content = None
        for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
            try:
                content = raw.decode(encoding)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if content is None:
            return jsonify({'error': 'Impossible de décoder le fichier. Encodage non supporté.'}), 400
    except Exception as e:
        return jsonify({'error': f'Erreur de lecture du fichier: {str(e)}'}), 400

    conn = get_db()
    try:
        result = _process_fec_content(content, conn, session.get('user_id'), type_import)
        if 'error' in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Erreur lors de l\'import: {str(e)}'}), 500
    finally:
        conn.close()


# ============================================================
# SOLDE INITIAL
# ============================================================

@tresorerie_bp.route('/api/tresorerie/solde_initial', methods=['POST'])
@login_required
def api_solde_initial():
    """Definit le solde initial global de tresorerie.

    Le solde est stocke avec une periode de reference (annee_ref, mois_ref)
    correspondant au premier mois de donnees importees. Il persiste
    independamment de la vue affichee.
    """
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    montant = data.get('montant')
    if montant is None:
        return jsonify({'error': 'Montant requis'}), 400

    try:
        montant = float(montant)
    except (ValueError, TypeError):
        return jsonify({'error': 'Montant invalide'}), 400

    conn = get_db()
    try:
        # Determiner la periode de reference = premier mois de donnees
        first = conn.execute(
            'SELECT MIN(annee) as a, MIN(mois) as m FROM tresorerie_donnees WHERE annee = (SELECT MIN(annee) FROM tresorerie_donnees)'
        ).fetchone()
        annee_ref = first['a'] if first and first['a'] else datetime.now().year
        mois_ref = first['m'] if first and first['m'] else 1

        # Supprimer les anciens enregistrements et inserer le nouveau global
        conn.execute('DELETE FROM tresorerie_solde_initial')
        conn.execute('''
            INSERT INTO tresorerie_solde_initial (annee, mois, montant, saisi_par, annee_ref, mois_ref)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (annee_ref, mois_ref, montant, session.get('user_id'),
              annee_ref, mois_ref))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ============================================================
# BUDGET N (AJUSTEMENT)
# ============================================================

@tresorerie_bp.route('/api/tresorerie/budget_n', methods=['POST'])
@login_required
def api_budget_n():
    """Sauvegarde un ajustement Budget N pour un compte/mois."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    compte_num = data.get('compte_num')
    annee = data.get('annee')
    mois = data.get('mois')
    montant = data.get('montant')

    if not compte_num or annee is None or mois is None:
        return jsonify({'error': 'Paramètres incomplets'}), 400

    conn = get_db()
    try:
        if montant is None or montant == '' or montant == 'null':
            # Supprimer l'ajustement
            conn.execute('''
                DELETE FROM tresorerie_budget_n
                WHERE compte_num = ? AND annee = ? AND mois = ?
            ''', (compte_num, annee, mois))
        else:
            try:
                montant = float(montant)
            except (ValueError, TypeError):
                return jsonify({'error': 'Montant invalide'}), 400

            conn.execute('''
                INSERT INTO tresorerie_budget_n (compte_num, annee, mois, montant, saisi_par)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(compte_num, annee, mois)
                DO UPDATE SET montant = ?, saisi_par = ?, updated_at = CURRENT_TIMESTAMP
            ''', (compte_num, annee, mois, montant, session.get('user_id'),
                  montant, session.get('user_id')))

        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ============================================================
# GESTION DES COMPTES
# ============================================================

@tresorerie_bp.route('/tresorerie/comptes')
@login_required
def gestion_comptes():
    """Interface de gestion des comptes de tresorerie."""
    if not _peut_acceder():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        comptes = conn.execute('''
            SELECT tc.*,
                   (SELECT COUNT(*) FROM tresorerie_donnees td WHERE td.compte_num = tc.compte_num) as nb_donnees,
                   (SELECT COALESCE(SUM(td.montant), 0) FROM tresorerie_donnees td WHERE td.compte_num = tc.compte_num) as total_historique
            FROM tresorerie_comptes tc
            ORDER BY tc.type_compte, tc.ordre_affichage, tc.compte_num
        ''').fetchall()
        comptes = [dict(c) for c in comptes]
    finally:
        conn.close()

    return render_template('tresorerie_comptes.html', comptes=comptes)


@tresorerie_bp.route('/api/tresorerie/comptes/<compte_num>/modifier', methods=['POST'])
@login_required
def api_modifier_compte(compte_num):
    """Modifie un compte de tresorerie (libelle, type, ordre, actif)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    field = data.get('field')
    value = data.get('value')

    allowed_fields = {'libelle_affiche', 'type_compte', 'ordre_affichage', 'actif'}
    if field not in allowed_fields:
        return jsonify({'error': f'Champ non autorisé: {field}'}), 400

    if field == 'type_compte' and value not in ('produit', 'charge', 'attente'):
        return jsonify({'error': 'Type de compte invalide'}), 400

    if field == 'ordre_affichage':
        try:
            value = int(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Ordre invalide'}), 400

    if field == 'actif':
        value = 1 if value else 0

    conn = get_db()
    try:
        conn.execute(f'''
            UPDATE tresorerie_comptes
            SET {field} = ?, updated_at = CURRENT_TIMESTAMP
            WHERE compte_num = ?
        ''', (value, compte_num))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@tresorerie_bp.route('/api/tresorerie/comptes/reordonner', methods=['POST'])
@login_required
def api_reordonner_comptes():
    """Met a jour l'ordre d'affichage de plusieurs comptes."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    if not data or 'ordres' not in data:
        return jsonify({'error': 'Données manquantes'}), 400

    conn = get_db()
    try:
        for item in data['ordres']:
            conn.execute('''
                UPDATE tresorerie_comptes
                SET ordre_affichage = ?, updated_at = CURRENT_TIMESTAMP
                WHERE compte_num = ?
            ''', (item['ordre'], item['compte_num']))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ============================================================
# SUPPRESSION D'UN IMPORT
# ============================================================

@tresorerie_bp.route('/api/tresorerie/imports/<int:import_id>/supprimer', methods=['POST'])
@login_required
def api_supprimer_import(import_id):
    """Supprime un import et ses donnees associees."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        # Supprimer les donnees liees a cet import
        conn.execute('DELETE FROM tresorerie_donnees WHERE import_id = ?', (import_id,))
        conn.execute('DELETE FROM tresorerie_imports WHERE id = ?', (import_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ============================================================
# REINITIALISATION TRESORERIE
# ============================================================

# ============================================================
# EPARGNE
# ============================================================

@tresorerie_bp.route('/api/tresorerie/epargne/solde', methods=['POST'])
@login_required
def api_epargne_solde():
    """Definit le solde initial d'epargne."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    montant = data.get('montant')
    if montant is None:
        return jsonify({'error': 'Montant requis'}), 400

    try:
        montant = float(montant)
    except (ValueError, TypeError):
        return jsonify({'error': 'Montant invalide'}), 400

    conn = get_db()
    try:
        conn.execute('DELETE FROM tresorerie_epargne_solde')
        conn.execute('''
            INSERT INTO tresorerie_epargne_solde (montant, saisi_par)
            VALUES (?, ?)
        ''', (montant, session.get('user_id')))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@tresorerie_bp.route('/api/tresorerie/epargne/mouvement', methods=['POST'])
@login_required
def api_epargne_mouvement():
    """Ajoute un placement ou un retrait d'epargne."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    type_mvt = data.get('type_mouvement')
    annee = data.get('annee')
    mois = data.get('mois')
    montant = data.get('montant')
    commentaire = data.get('commentaire', '')

    if type_mvt not in ('placement', 'retrait'):
        return jsonify({'error': 'Type invalide (placement ou retrait)'}), 400

    if annee is None or mois is None or montant is None:
        return jsonify({'error': 'Paramètres incomplets'}), 400

    try:
        annee = int(annee)
        mois = int(mois)
        montant = float(montant)
    except (ValueError, TypeError):
        return jsonify({'error': 'Valeurs invalides'}), 400

    if mois < 1 or mois > 12:
        return jsonify({'error': 'Mois invalide'}), 400

    if montant <= 0:
        return jsonify({'error': 'Le montant doit être positif'}), 400

    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO tresorerie_epargne_mouvements
            (type_mouvement, annee, mois, montant, commentaire, saisi_par)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (type_mvt, annee, mois, montant, commentaire, session.get('user_id')))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@tresorerie_bp.route('/api/tresorerie/epargne/mouvement/<int:mouvement_id>/supprimer', methods=['POST'])
@login_required
def api_epargne_supprimer_mouvement(mouvement_id):
    """Supprime un mouvement d'epargne."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        conn.execute(
            'DELETE FROM tresorerie_epargne_mouvements WHERE id = ?',
            (mouvement_id,)
        )
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@tresorerie_bp.route('/api/tresorerie/reinitialiser', methods=['POST'])
@login_required
def api_reinitialiser_tresorerie():
    """Reinitialise toutes les donnees de tresorerie (sans toucher au reste)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    if not data or data.get('confirmation') != 'REINITIALISER_TRESORERIE':
        return jsonify({'error': 'Confirmation requise'}), 400

    conn = get_db()
    try:
        conn.execute('DELETE FROM tresorerie_donnees')
        conn.execute('DELETE FROM tresorerie_comptes')
        conn.execute('DELETE FROM tresorerie_imports')
        conn.execute('DELETE FROM tresorerie_solde_initial')
        conn.execute('DELETE FROM tresorerie_budget_n')
        conn.execute('DELETE FROM tresorerie_epargne_solde')
        conn.execute('DELETE FROM tresorerie_epargne_mouvements')
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()
