"""
Panneau « Actions à faire » des tableaux de bord (dashboard_actions.py).
"""
from datetime import date, timedelta

from dashboard_actions import construire_actions


def _demande_recup(db, user_id, statut, date_demande='2026-06-01'):
    db.execute(
        "INSERT INTO demandes_recup (user_id, date_debut, date_fin, nb_jours, nb_heures, statut, date_demande) "
        "VALUES (?, '2026-06-10', '2026-06-10', 1, 7, ?, ?)",
        (user_id, statut, date_demande)
    )


def _subvention_avec_etape(db, nom, echeance, assignee_1_id=None,
                           groupe='en_cours', se_assignee_id=None):
    cur = db.execute(
        "INSERT INTO subventions (nom, groupe, annee_action, assignee_1_id) VALUES (?, ?, '2026', ?)",
        (nom, groupe, assignee_1_id)
    )
    sid = cur.lastrowid
    db.execute(
        "INSERT INTO subventions_sous_elements (subvention_id, nom, assignee_id, statut, date_echeance, ordre) "
        "VALUES (?, 'Préparer le dossier', ?, 'en_cours', ?, 0)",
        (sid, se_assignee_id, echeance)
    )
    return sid


def test_direction_voit_validations_et_subventions(app, db, sample_users):
    """La direction agrège toutes les demandes en attente et toutes les
    échéances de subventions."""
    _demande_recup(db, sample_users['salarie_id'], 'en_attente_direction')
    _subvention_avec_etape(db, 'CLAS', (date.today() + timedelta(days=3)).isoformat())
    db.commit()

    with app.test_request_context():
        actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

    categories = {a['categorie'] for a in actions}
    assert 'validation' in categories
    assert 'subvention' in categories
    titres = ' | '.join(a['titre'] for a in actions)
    assert 'CLAS' in titres and 'Préparer le dossier' in titres
    # Chaque item a un lien et un libellé d'action.
    assert all(a['lien'] and a['lien_texte'] for a in actions)


def test_echeance_passee_est_en_retard(app, db, sample_users):
    """Une étape de subvention dont l'échéance est passée est marquée 'retard'."""
    _subvention_avec_etape(db, 'Numerique', (date.today() - timedelta(days=2)).isoformat())
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'comptable', sample_users['comptable_id'])
    subv = [a for a in actions if a['categorie'] == 'subvention']
    assert subv and subv[0]['urgence'] == 'retard'


def test_responsable_scope_secteur_et_assignation(app, db, sample_users):
    """Le responsable ne voit que les demandes de son secteur et les subventions
    dont il est assigné."""
    resp_id = sample_users['responsable_id']
    # Demande d'un salarié de SON secteur, en attente responsable → visible.
    _demande_recup(db, sample_users['salarie_id'], 'en_attente_responsable')
    # Subvention NON assignée au responsable → non visible.
    _subvention_avec_etape(db, 'Autre', (date.today() + timedelta(days=3)).isoformat())
    # Subvention assignée au responsable → visible.
    _subvention_avec_etape(db, 'Amien', (date.today() + timedelta(days=3)).isoformat(),
                           assignee_1_id=resp_id)
    db.commit()

    with app.test_request_context():
        actions = construire_actions(db, 'responsable', resp_id, sample_users['secteur_id'])

    assert any(a['categorie'] == 'validation' for a in actions)
    titres_subv = [a['titre'] for a in actions if a['categorie'] == 'subvention']
    assert any('Amien' in t for t in titres_subv)
    assert not any('Autre' in t for t in titres_subv)


def test_etape_faite_non_listee(app, db, sample_users):
    """Une étape déjà 'fait' n'apparaît pas dans les actions."""
    cur = db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('Finie','en_cours','2026')")
    db.execute(
        "INSERT INTO subventions_sous_elements (subvention_id, nom, statut, date_echeance, ordre) "
        "VALUES (?, 'Bilan', 'fait', ?, 0)",
        (cur.lastrowid, (date.today() + timedelta(days=3)).isoformat())
    )
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'directeur', sample_users['directeur_id'])
    assert not any(a['categorie'] == 'subvention' for a in actions)


def test_responsable_voit_etape_de_sous_element_assigne(app, db, sample_users):
    """Un responsable attribué à un sous-élément (mais pas à la subvention parente)
    voit l'étape dans son panneau, en cohérence avec la notification e-mail."""
    resp_id = sample_users['responsable_id']
    _subvention_avec_etape(db, 'Portage', (date.today() + timedelta(days=3)).isoformat(),
                           assignee_1_id=None, se_assignee_id=resp_id)
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'responsable', resp_id, sample_users['secteur_id'])
    titres = [a['titre'] for a in actions if a['categorie'] == 'subvention']
    assert any('Portage' in t for t in titres)


def test_subvention_acceptee_garde_ses_echeances(app, db, sample_users):
    """Une subvention acceptée conserve ses échéances actionnables (bilans)."""
    _subvention_avec_etape(db, 'Acceptee', (date.today() + timedelta(days=3)).isoformat(),
                           groupe='acceptee')
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'directeur', sample_users['directeur_id'])
    assert any('Acceptee' in a['titre'] for a in actions if a['categorie'] == 'subvention')


def test_subvention_refusee_exclue_du_panneau(app, db, sample_users):
    """Une subvention refusée n'apparaît pas, même avec une échéance passée."""
    _subvention_avec_etape(db, 'Refusee', (date.today() - timedelta(days=1)).isoformat(),
                           groupe='refusee')
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'directeur', sample_users['directeur_id'])
    assert not any('Refusee' in a['titre'] for a in actions if a['categorie'] == 'subvention')
