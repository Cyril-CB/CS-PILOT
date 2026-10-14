"""Périmètres physiques indépendants des secteurs analytiques et des profils RH.

Les helpers utilisent la connexion de l'appelant : lecture et autorisation
restent dans la transaction qui modifie la ressource. Aucun droit en cookie.
"""

PROFILS_INTERNES = ('directeur', 'comptable', 'responsable', 'salarie')
MODULES = {'fournitures': 'Commandes de fournitures', 'entretien': 'Produits d’entretien'}


def compte_interne(conn, user_id):
    row = conn.execute('SELECT id, profil FROM users WHERE id = ? AND actif = 1', (user_id,)).fetchone()
    return row if row and row['profil'] in PROFILS_INTERNES else None


def est_administrateur(conn, user_id):
    compte = compte_interne(conn, user_id)
    return bool(compte and compte['profil'] in ('directeur', 'comptable'))


def gere_site(conn, user_id, module, site_id):
    """Droit courant, limité à un module d'un site actif."""
    if module not in MODULES or not compte_interne(conn, user_id):
        return False
    site = conn.execute('SELECT actif FROM sites WHERE id = ?', (site_id,)).fetchone()
    if not site or not site['actif']:
        return False
    return est_administrateur(conn, user_id) or bool(conn.execute(
        'SELECT 1 FROM sites_responsables_modules WHERE site_id = ? AND module = ? AND user_id = ?',
        (site_id, module, user_id)).fetchone())


def fournitures_globales(conn, user_id):
    """L'ancienne mission ne donne aucun accès aux nouvelles files par site."""
    if not compte_interne(conn, user_id):
        return False
    return est_administrateur(conn, user_id) or bool(conn.execute(
        "SELECT 1 FROM delegations_missions WHERE mission_key = 'suivi_commandes_fournitures' AND delegated_user_id = ?",
        (user_id,)).fetchone())


def sites_fournitures(conn, user_id):
    """Sites où l'utilisateur peut déposer un besoin de fournitures."""
    if not compte_interne(conn, user_id):
        return []
    if est_administrateur(conn, user_id):
        return conn.execute('SELECT * FROM sites WHERE actif = 1 ORDER BY nom').fetchall()
    return conn.execute('''
        SELECT s.* FROM sites s WHERE s.actif = 1 AND (
            EXISTS (SELECT 1 FROM sites_utilisateurs a WHERE a.site_id = s.id AND a.user_id = ?)
            OR EXISTS (SELECT 1 FROM sites_responsables_modules r
                       WHERE r.site_id = s.id AND r.module = 'fournitures' AND r.user_id = ?))
        ORDER BY s.nom
    ''', (user_id, user_id)).fetchall()


def peut_creer_fourniture(conn, user_id, site_id):
    if not compte_interne(conn, user_id):
        return False
    if site_id is None:
        # Le parcours historique reste disponible tant qu'aucun site n'a été
        # créé. Archiver tous les sites ne doit pas rouvrir un périmètre global.
        return not conn.execute('SELECT 1 FROM sites LIMIT 1').fetchone()
    return any(s['id'] == site_id for s in sites_fournitures(conn, user_id))


def peut_traiter_fourniture(conn, user_id, site_id):
    return (fournitures_globales(conn, user_id) if site_id is None
            else gere_site(conn, user_id, 'fournitures', site_id))


def lieux_entretien(conn, user_id, actifs=True):
    if not compte_interne(conn, user_id):
        return []
    actif_sql = 'AND l.actif = 1 AND s.actif = 1' if actifs else ''
    return conn.execute(f'''
        SELECT l.*, s.nom AS site_nom, s.actif AS site_actif
        FROM entretien_lieux l JOIN sites s ON s.id = l.site_id
        WHERE (? = 1 OR l.demandeur_id = ? OR (s.actif = 1 AND EXISTS (
            SELECT 1 FROM sites_responsables_modules r
            WHERE r.site_id = s.id AND r.module = 'entretien' AND r.user_id = ?)))
        {actif_sql} ORDER BY s.nom, l.nom
    ''', (int(est_administrateur(conn, user_id)), user_id, user_id)).fetchall()


def peut_demander_entretien(conn, user_id, lieu_id):
    if not compte_interne(conn, user_id):
        return False
    lieu = conn.execute('''SELECT l.* FROM entretien_lieux l
        JOIN sites s ON s.id = l.site_id WHERE l.id = ? AND l.actif = 1 AND s.actif = 1''',
        (lieu_id,)).fetchone()
    # Le gestionnaire passe les commandes ; le demandeur désigné exprime les
    # besoins. La direction/comptabilité peut remplacer un demandeur absent.
    return bool(lieu and (lieu['demandeur_id'] == user_id or est_administrateur(conn, user_id)))


def peut_lire_entretien(conn, user_id, demande):
    if not compte_interne(conn, user_id):
        return False
    if est_administrateur(conn, user_id) or gere_site(conn, user_id, 'entretien', demande['site_id']):
        return True
    return bool(conn.execute('''SELECT 1 FROM entretien_lieux l JOIN sites s ON s.id = l.site_id
        WHERE l.id = ? AND l.site_id = ? AND l.demandeur_id = ? AND l.actif = 1 AND s.actif = 1''',
        (demande['lieu_id'], demande['site_id'], user_id)).fetchone())


def a_acces_entretien(conn, user_id):
    return bool(est_administrateur(conn, user_id) or lieux_entretien(conn, user_id)
                or sites_geres(conn, user_id, 'entretien'))


def sites_geres(conn, user_id, module):
    if module not in MODULES or not compte_interne(conn, user_id):
        return []
    return conn.execute('''SELECT s.* FROM sites s WHERE s.actif = 1 AND (? = 1 OR EXISTS (
        SELECT 1 FROM sites_responsables_modules r
        WHERE r.site_id = s.id AND r.module = ? AND r.user_id = ?)) ORDER BY s.nom''',
        (int(est_administrateur(conn, user_id)), module, user_id)).fetchall()


def utilisateurs_internes(conn):
    return conn.execute("SELECT id, nom, prenom, profil FROM users WHERE actif = 1 AND profil IN ('directeur','comptable','responsable','salarie') ORDER BY nom, prenom").fetchall()


def entier_id(raw):
    if raw is None or not str(raw).isascii() or not str(raw).isdigit() or len(str(raw)) > 12:
        raise ValueError('Identifiant invalide.')
    value = int(raw)
    if value < 1:
        raise ValueError('Identifiant invalide.')
    return value


def texte(raw, maximum, libelle):
    value = (raw or '').strip()
    if not value or len(value) > maximum:
        raise ValueError(f'{libelle} est obligatoire et limité à {maximum} caractères.')
    return value
