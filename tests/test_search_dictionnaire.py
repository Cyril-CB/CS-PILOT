"""Mesure la richesse du dictionnaire de la barre intelligente.

Les autres tests de recherche vérifient des cas précis. Celui-ci mesure autre
chose : **la part des demandes réelles à laquelle la barre sait répondre**. Il
fait passer un corpus de formulations telles qu'un utilisateur les tape — mot
unique, pluriel, phrase parlée, jargon du secteur, abréviation, faute de frappe
— et vérifie qu'elles mènent à la bonne page.

La comparaison porte sur le **chemin d'arrivée**, pas sur le libellé : la page
« Compte de résultat & bilan » de la carte et le résultat « Compte de résultat
2026 » du moteur ouvrent le même écran, les deux comptent comme une réussite.

Pour enrichir le dictionnaire, la marche à suivre est toujours la même :
prendre dans le journal de recherche (Sécurité → Barre intelligente) les termes
restés sans résultat, les ajouter ici, puis compléter `mots=` ou `expressions=`
de la page visée dans `navigation.py` jusqu'à ce que le test repasse.
"""
from datetime import date

import pytest

import navigation
from search_engine import analyser_recherche
from search_palette import construire_suggestions

# Seuils de non-régression, volontairement sous la mesure du jour (98 % / 100 %)
# pour laisser respirer un ajout de page, sans laisser le dictionnaire se vider.
TAUX_MIN_PREMIER = 0.92
TAUX_MIN_TROIS = 0.98

# (profil, requête, chemin attendu)
CORPUS = [
    # ── Validations & suivi ──────────────────────────────────────────────
    ('directeur', "valider les heures", '/vue_ensemble_validation'),
    ('directeur', "fiches non validées", '/vue_ensemble_validation'),
    ('directeur', "qui n'a pas validé ses heures", '/vue_ensemble_validation'),
    ('directeur', "relancer les responsables", '/vue_ensemble_validation'),
    ('directeur', "état des validations", '/vue_ensemble_validation'),
    ('directeur', "congés à valider", '/validation_demandes_recup'),
    ('directeur', "demandes en attente", '/validation_demandes_recup'),
    ('directeur', "valider une récup", '/validation_demandes_recup'),
    ('directeur', "récupérations à valider", '/validation_demandes_recup'),
    ('directeur', "historique des demandes", '/historique_demandes_recup'),
    ('directeur', "demandes déjà traitées", '/historique_demandes_recup'),
    ('directeur', "qui a modifié quoi", '/historique_modifications'),
    ('directeur', "historique des modifications", '/historique_modifications'),
    ('directeur', "journal des changements", '/historique_modifications'),
    ('directeur', "anomalies", '/suivi_anomalies'),
    ('directeur', "erreurs de saisie", '/suivi_anomalies'),
    ('directeur', "incohérences", '/suivi_anomalies'),
    ('directeur', "surcharge de travail", '/alertes_surcharge'),
    ('directeur', "alertes de surcharge", '/alertes_surcharge'),
    ('directeur', "amplitude horaire", '/alertes_surcharge'),
    ('directeur', "factures à approuver", '/factures/approbation'),
    ('directeur', "approuver les factures", '/factures/approbation'),
    ('directeur', "factures en attente", '/factures/approbation'),

    # ── Temps & plannings ────────────────────────────────────────────────
    ('responsable', "saisir mes heures", '/saisie_heures'),
    ('responsable', "pointer mes heures", '/saisie_heures'),
    ('responsable', "ma fiche d'heures", '/vue_mensuelle'),
    ('responsable', "feuille de temps", '/vue_mensuelle'),
    ('responsable', "heures du mois", '/vue_mensuelle'),
    ('responsable', "vue calendrier", '/vue_calendrier'),
    ('responsable', "mon équipe", '/mon_equipe'),
    ('directeur', "plannings des salariés", '/planning_theorique'),
    ('directeur', "planning théorique", '/planning_theorique'),
    ('responsable', "mon planning", '/planning_theorique'),
    ('directeur', "qui est présent aujourd'hui", '/presence-effectif'),
    ('directeur', "présence de l'effectif", '/presence-effectif'),
    ('directeur', "temps annualisé", '/planning_enfance'),
    ('directeur', "annualisation", '/planning_enfance'),
    ('directeur', "modulation alsh", '/planning_enfance'),
    ('directeur', "forfait jour", '/dashboard_forfait_jour'),
    ('directeur', "cadres au forfait", '/dashboard_forfait_jour'),
    ('directeur', "calendrier forfait jour", '/calendrier_forfait_jour'),

    # ── Ressources humaines ──────────────────────────────────────────────
    ('directeur', "infos salariés", '/infos_salaries'),
    ('directeur', "dossier du personnel", '/infos_salaries'),
    ('directeur', "fiche d'un salarié", '/infos_salaries'),
    ('directeur', "coordonnées d'un salarié", '/infos_salaries'),
    ('directeur', "générer un contrat", '/generation_contrats'),
    ('directeur', "rédiger un cdd", '/generation_contrats'),
    ('directeur', "modèle de contrat", '/generation_contrats'),
    ('directeur', "absences", '/absences'),
    ('directeur', "arrêt maladie", '/absences'),
    ('directeur', "qui est en arrêt", '/absences'),
    ('directeur', "soldes de congés", '/soldes_conges'),
    ('directeur', "compteurs de congés", '/soldes_conges'),
    ('directeur', "statistiques rh", '/rh/statistiques'),
    ('directeur', "effectif etp", '/rh/statistiques'),
    ('directeur', "pyramide des âges", '/rh/statistiques'),
    ('directeur', "pesée alisfa", '/pesee_alisfa'),
    ('directeur', "cotation d'un poste", '/pesee_alisfa'),
    ('directeur', "classification", '/pesee_alisfa'),
    ('directeur', "postes alisfa", '/postes_alisfa'),
    ('directeur', "assistant rh", '/assistant_rh'),
    ('directeur', "question convention collective", '/assistant_rh'),
    ('directeur', "variables de paie", '/variables_paie'),
    ('directeur', "éléments variables", '/variables_paie'),
    ('directeur', "evp", '/variables_paie'),
    ('directeur', "préparer la paie", '/prepa_paie'),
    ('directeur', "paie du mois", '/prepa_paie'),
    ('directeur', "contrôler la paie", '/prepa_paie'),

    # ── Factures & achats ────────────────────────────────────────────────
    ('directeur', "factures", '/factures'),
    ('directeur', "importer des factures", '/factures'),
    ('directeur', "dépenses", '/factures'),
    ('directeur', "fournisseurs", '/fournisseurs'),
    ('directeur', "annuaire des fournisseurs", '/fournisseurs'),
    ('directeur', "règles comptables", '/regles-comptables'),
    ('directeur', "imputation automatique", '/regles-comptables'),
    ('directeur', "écritures", '/ecritures'),
    ('directeur', "saisie comptable", '/ecritures'),
    ('directeur', "exporter vers aiga", '/exportation'),
    ('directeur', "exportation", '/exportation'),
    ('directeur', "commander des fournitures", '/commandes-salaries'),
    ('directeur', "commandes salariés", '/commandes-salaries'),
    ('directeur', "achat de fournitures", '/commandes-salaries'),

    # ── Comptabilité ─────────────────────────────────────────────────────
    ('directeur', "compte de résultat", '/compte-resultat'),
    ('directeur', "charges et produits", '/compte-resultat'),
    ('directeur', "indicateurs financiers", '/indicateurs-financiers'),
    ('directeur', "ratios financiers", '/indicateurs-financiers'),
    ('directeur', "fonds de roulement", '/indicateurs-financiers'),
    ('directeur', "import bi", '/import-bi'),
    ('directeur', "importer le fec", '/import-bi'),
    ('directeur', "plan comptable analytique", '/plan-comptable-analytique'),
    ('directeur', "codes analytiques", '/plan-comptable-analytique'),
    ('directeur', "plan comptable général", '/plan-comptable-general'),
    ('directeur', "grand livre", '/plan-comptable-general'),

    # ── Financier ────────────────────────────────────────────────────────
    ('directeur', "budgets", '/gestion_budgets'),
    ('directeur', "gestion des budgets", '/gestion_budgets'),
    ('directeur', "budget prévisionnel", '/budget-previsionnel'),
    ('directeur', "bp", '/budget-previsionnel'),
    ('directeur', "prévisionnel actualisé", '/budget-previsionnel'),
    ('directeur', "subventions", '/subventions'),
    ('directeur', "dossiers de subvention", '/subventions'),
    ('directeur', "échéances de subventions", '/subventions'),
    ('directeur', "financeurs", '/subventions'),
    ('directeur', "trésorerie", '/tresorerie'),
    ('directeur', "solde bancaire", '/tresorerie'),
    ('directeur', "bilan secteurs", '/bilan-secteurs'),
    ('directeur', "résultat par secteur", '/bilan-secteurs'),
    ('directeur', "budget action", '/bilan-action'),
    ('directeur', "analyse alsh", '/analyse-alsh'),
    ('directeur', "fréquentation alsh", '/analyse-alsh'),

    # ── Vie associative ──────────────────────────────────────────────────
    ('directeur', "bénévoles", '/benevoles'),
    ('directeur', "heures de bénévolat", '/benevoles'),
    ('directeur', "cse", '/cse'),
    ('directeur', "comité social et économique", '/cse'),

    # ── Mon espace ───────────────────────────────────────────────────────
    ('directeur', "mes compteurs", '/mon-espace'),
    ('directeur', "mon espace", '/mon-espace'),
    ('directeur', "demander un congé", '/demande_conge'),
    ('directeur', "poser des congés", '/demande_conge'),
    ('directeur', "mes demandes", '/mes_demandes_conges'),

    # ── Accès directs ────────────────────────────────────────────────────
    ('directeur', "réserver une salle", '/salles'),
    ('directeur', "salles", '/salles'),
    ('directeur', "planificateur", '/planificateur'),
    ('directeur', "mes tâches", '/planificateur'),
    ('directeur', "gérer les utilisateurs", '/gestion_users'),
    ('directeur', "créer un compte", '/gestion_users'),
    ('directeur', "journal des accès", '/securite/journal-acces'),
    ('directeur', "vacances scolaires", '/gestion_vacances'),
    ('directeur', "jours fériés", '/gestion_jours_feries'),
    ('directeur', "clés api", '/gestion_cles_api'),
    ('directeur', "notifications email", '/configuration_email'),
    ('directeur', "délégations", '/delegations'),
    ('directeur', "options", '/administration/options'),
    ('directeur', "sauvegardes", '/sauvegardes'),
    ('directeur', "mise à jour de l'application", '/mise-a-jour'),

    # ── Fautes de frappe et formulations parlées ─────────────────────────
    ('directeur', "factrues", '/factures'),
    ('directeur', "plannig", '/planning_theorique'),
    ('directeur', "subvension", '/subventions'),
    ('directeur', "tresorerie", '/tresorerie'),
    ('directeur', "je veux voir les factures", '/factures'),
    ('directeur', "où sont les subventions", '/subventions'),
    ('directeur', "montre moi la trésorerie", '/tresorerie'),
    ('directeur', "comment poser des congés", '/demande_conge'),
]


def _contexte(profil):
    """Droits les plus larges du profil : on mesure le vocabulaire, pas le filtrage."""
    return {
        'profil': profil, 'user_id': 1, 'is_cse_membre': True,
        'is_delegue_benevoles': True, 'can_access_vue_ensemble_validation': True,
        'generation_contrats_responsable_autorise': True,
        'budget_previsionnel_responsable_autorise': True,
    }


def _chemin(url):
    return (url or '').split('?')[0]


@pytest.fixture
def mesures(app):
    """Passe tout le corpus et retourne le rang obtenu par chaque requête."""
    import database
    with app.test_request_context('/'):
        conn = database.get_db()
        try:
            cartes = {p: navigation.carte_navigation(_contexte(p))
                      for p in ('directeur', 'responsable')}
            chemins = {p: {_chemin(page['lien'])
                           for groupe in c['zones'] + c['directs']
                           for page in groupe['pages']}
                       for p, c in cartes.items()}
            lignes = []
            for profil, requete, attendu in CORPUS:
                carte = cartes[profil]
                verdict = analyser_recherche(conn, requete, profil, date.today(),
                                             user_id=1)
                precis = [s for s in construire_suggestions(carte, requete, verdict)
                          if s['action'] != 'ensemble']
                rang = next((i for i, s in enumerate(precis)
                             if _chemin(s.get('url')) == attendu), None)
                lignes.append((profil, requete, attendu, rang,
                               [s['titre'] for s in precis[:3]],
                               attendu in chemins[profil]))
        finally:
            conn.close()
    return lignes


def test_chaque_requete_du_corpus_trouve_sa_destination(mesures):
    perdues = [(p, r, a, t) for p, r, a, rang, t, _ok in mesures if rang is None]
    assert not perdues, "Requêtes sans destination — enrichir `mots`/`expressions` :\n" + \
        '\n'.join(f"  [{p}] {r!r} → {a} (proposé : {t or 'rien'})" for p, r, a, t in perdues)


def test_la_bonne_destination_arrive_en_tete(mesures):
    taux = len([m for m in mesures if m[3] == 0]) / len(mesures)
    mauvaises = [(p, r, a, rang + 1, t) for p, r, a, rang, t, _ok in mesures
                 if rang not in (0, None)]
    assert taux >= TAUX_MIN_PREMIER, (
        f"{taux:.0%} des requêtes seulement mènent en tête (minimum "
        f"{TAUX_MIN_PREMIER:.0%}) :\n" +
        '\n'.join(f"  [{p}] {r!r} → {a} en position {pos} ({t})"
                  for p, r, a, pos, t in mauvaises))


def test_la_bonne_destination_est_visible_sans_defiler(mesures):
    trois = [m for m in mesures if m[3] is not None and m[3] <= 2]
    taux = len(trois) / len(mesures)
    assert taux >= TAUX_MIN_TROIS, (
        f"{taux:.0%} des requêtes seulement placent leur destination dans les "
        f"trois premières (minimum {TAUX_MIN_TROIS:.0%})")


def test_le_corpus_ne_vise_que_des_pages_reellement_accessibles(mesures):
    """Garde-fou du corpus : une attente hors carte fausserait la mesure."""
    hors = [(p, r, a) for p, r, a, _rang, _t, atteignable in mesures
            if not atteignable]
    assert not hors, "Destinations attendues absentes de la carte :\n" + \
        '\n'.join(f"  [{p}] {r!r} → {a}" for p, r, a in hors)


# ── « Mes heures » mène au mois, pas au formulaire d'une journée ────────────

def _premiere_destination(app, db, profil, requete):
    """Chemin de la première proposition précise, pour un profil donné."""
    import navigation
    from database import get_db

    with app.test_request_context('/'):
        carte = navigation.carte_navigation({'profil': profil, 'user_id': 1})
        conn = get_db()
        try:
            verdict = analyser_recherche(conn, requete, profil, date.today(),
                                         user_id=1)
        finally:
            conn.close()
        precises = [s for s in construire_suggestions(carte, requete, verdict)
                    if s['action'] != 'ensemble' and s.get('url')]
    return _chemin(precises[0]['url']) if precises else None


REQUETES_MES_HEURES = ('mes heures', "ma fiche d'heures", 'saisir mon temps',
                       'heures du mois', 'mon temps de travail',
                       'feuille de temps')

# Personne ne tape une expression nue. Ces tournures-là contiennent
# l'expression déclarée sans lui être égales : c'est le cas que l'égalité
# stricte manquait, et la requête retombait alors sur ses mots isolés —
# réduite à « heure », elle proposait la demande de récupération, voire les
# bénévoles, avant la fiche du mois.
REQUETES_PARLEES = ('voir mes heures', 'où sont mes heures',
                    'je veux voir mes heures', 'consulter mes heures',
                    'où en sont mes heures du mois',
                    'je voudrais voir ma fiche d\'heures')


@pytest.mark.parametrize('profil', ['salarie', 'responsable', 'comptable'])
def test_mes_heures_mene_au_mois_entier(app, db, sample_users, profil):
    """La vue mensuelle montre le solde, désigne le jour à corriger et
    l'ouvre en saisie d'un clic. Le formulaire d'une journée, lui, ne répond
    qu'à une question déjà précise."""
    for requete in REQUETES_MES_HEURES + REQUETES_PARLEES:
        assert _premiere_destination(app, db, profil, requete) == '/vue_mensuelle', (
            profil, requete)


def test_la_direction_arrive_sur_son_forfait_jour(app, db, sample_users):
    """Elle est au forfait jour : elle n'a pas de fiche d'heures, et la vue
    mensuelle lui est fermée. L'envoyer là serait l'envoyer dans le mur."""
    for requete in REQUETES_MES_HEURES + REQUETES_PARLEES:
        assert _premiere_destination(app, db, 'directeur', requete) == (
            '/calendrier_forfait_jour'), requete


def test_la_saisie_reste_atteignable_par_son_nom(app, db, sample_users):
    """Qui demande explicitement le formulaire l'obtient."""
    assert _premiere_destination(app, db, 'salarie',
                                 'saisir mes heures') == '/saisie_heures'


def test_une_question_de_paie_ne_part_pas_vers_la_fiche_du_mois(app, db, sample_users):
    """« primes heures supplémentaires » contient la chaîne « mes heures ».

    Sans frontières de mots, la question partait vers la vue mensuelle — et
    vers le forfait jour pour un directeur.
    """
    for profil in ('salarie', 'responsable', 'comptable', 'directeur'):
        destination = _premiere_destination(app, db, profil,
                                            'primes heures supplémentaires')
        assert destination not in ('/vue_mensuelle', '/calendrier_forfait_jour'), (
            profil, destination)
