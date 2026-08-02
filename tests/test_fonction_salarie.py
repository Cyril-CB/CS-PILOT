"""
Tests de la fonction du salarié.

La fonction est renseignée avec les informations de contrat, choisie dans une
liste complétable, et s'affiche sous le nom dans l'interface sans menu.
"""
import pytest

from migrations import FONCTIONS_INITIALES


def _fonctions(db):
    return [r['libelle'] for r in
            db.execute('SELECT libelle FROM fonctions ORDER BY ordre').fetchall()]


def _fonction_de(db, user_id):
    return db.execute('SELECT fonction FROM users WHERE id = ?',
                      (user_id,)).fetchone()['fonction']


# ── Référentiel ────────────────────────────────────────────────────────────

def test_la_liste_est_prete_a_l_installation(app, db):
    """Une base neuve porte déjà les fonctions courantes d'un centre social."""
    libelles = _fonctions(db)
    assert libelles == FONCTIONS_INITIALES
    for attendu in ('Directeur', 'EJE', 'Auxiliaire Puér.', "Agent d'accueil",
                    'Conseillé insertion', 'Gardien'):
        assert attendu in libelles


def test_la_liste_est_proposee_sur_la_fiche(admin_client, sample_users):
    corps = admin_client.get(
        f"/infos_salaries?user_id={sample_users['salarie_id']}").get_data(as_text=True)
    assert 'Fonction' in corps
    assert 'Auxiliaire Puér.' in corps
    assert 'Ajouter une fonction' in corps


# ── Enregistrement ─────────────────────────────────────────────────────────

def test_enregistrer_une_fonction_de_la_liste(admin_client, db, sample_users):
    admin_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['salarie_id'], 'fonction': 'EJE'},
        follow_redirects=True)
    assert _fonction_de(db, sample_users['salarie_id']) == 'EJE'


def test_ajouter_une_fonction_enrichit_la_liste(admin_client, db, sample_users):
    """La fonction créée est affectée ET proposée ensuite à tout le monde."""
    admin_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['salarie_id'],
        'fonction': '__autre__',
        'nouvelle_fonction': 'Médiateur numérique'}, follow_redirects=True)
    assert _fonction_de(db, sample_users['salarie_id']) == 'Médiateur numérique'
    assert 'Médiateur numérique' in _fonctions(db)


def test_ajouter_une_fonction_deja_presente_ne_cree_pas_de_doublon(
        admin_client, db, sample_users):
    admin_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['salarie_id'],
        'fonction': '__autre__', 'nouvelle_fonction': 'EJE'}, follow_redirects=True)
    assert _fonctions(db).count('EJE') == 1
    assert _fonction_de(db, sample_users['salarie_id']) == 'EJE'


def test_choisir_ajouter_sans_rien_saisir_n_enregistre_rien(
        admin_client, db, sample_users):
    """La valeur technique de l'entrée « + Ajouter » ne doit jamais être stockée."""
    reponse = admin_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['salarie_id'], 'fonction': '__autre__'},
        follow_redirects=True)
    assert 'Saisissez le nom de la nouvelle fonction' in reponse.get_data(as_text=True)
    assert _fonction_de(db, sample_users['salarie_id']) is None


def test_une_fonction_hors_referentiel_est_refusee(admin_client, db, sample_users):
    """Le référentiel reste la seule source des libellés."""
    admin_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['salarie_id'], 'fonction': 'Grand manitou'},
        follow_redirects=True)
    assert _fonction_de(db, sample_users['salarie_id']) is None
    assert 'Grand manitou' not in _fonctions(db)


def test_retirer_la_fonction(admin_client, db, sample_users):
    admin_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['salarie_id'], 'fonction': 'EJE'},
        follow_redirects=True)
    admin_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['salarie_id'], 'fonction': ''},
        follow_redirects=True)
    assert _fonction_de(db, sample_users['salarie_id']) is None


def test_fonction_trop_longue_refusee(admin_client, db, sample_users):
    admin_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['salarie_id'], 'fonction': '__autre__',
        'nouvelle_fonction': 'x' * 61}, follow_redirects=True)
    assert _fonction_de(db, sample_users['salarie_id']) is None


# ── Droits ─────────────────────────────────────────────────────────────────

def test_un_salarie_ne_peut_pas_modifier_les_fonctions(auth_client, db, sample_users):
    auth_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['salarie_id'], 'fonction': 'EJE'},
        follow_redirects=True)
    assert _fonction_de(db, sample_users['salarie_id']) is None


def test_un_responsable_ne_sort_pas_de_son_equipe(resp_client, db, sample_users):
    """Le comptable n'est pas dans l'équipe du responsable de test."""
    resp_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['comptable_id'], 'fonction': 'Comptable'},
        follow_redirects=True)
    assert _fonction_de(db, sample_users['comptable_id']) is None


# ── Affichage dans l'interface sans menu ───────────────────────────────────

def test_la_fonction_remplace_le_profil_en_haut_a_droite(admin_client, db, sample_users):
    admin_client.post('/infos_salaries/fonction', data={
        'user_id': sample_users['directeur_id'], 'fonction': 'Direction adjointe'},
        follow_redirects=True)
    corps = admin_client.get('/accueil').get_data(as_text=True)
    assert 'Direction adjointe' in corps


def test_sans_fonction_le_profil_reste_affiche(admin_client):
    corps = admin_client.get('/accueil').get_data(as_text=True)
    assert 'flx-identite-role' in corps
    assert 'direction' in corps


# ── Migration ──────────────────────────────────────────────────────────────

def test_la_migration_recree_la_liste_et_reste_idempotente(app, db):
    """Rejouer la migration ne double rien et répare une table manquante."""
    import importlib.util
    import os

    chemin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'migrations', '0064_fonction_salarie.py')
    spec = importlib.util.spec_from_file_location('migration_0064', chemin)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    # Base d'avant la migration : la liste n'existe pas encore.
    db.execute('DROP TABLE IF EXISTS fonctions')
    db.commit()

    migration.upgrade(db)
    assert _fonctions(db) == FONCTIONS_INITIALES

    # Une fonction ajoutée par la direction survit à un nouveau passage, et la
    # liste initiale n'est pas dupliquée.
    db.execute("INSERT INTO fonctions (libelle, ordre) VALUES ('Médiateur', 99)")
    db.commit()
    migration.upgrade(db)
    libelles = _fonctions(db)
    assert 'Médiateur' in libelles
    assert len(libelles) == len(FONCTIONS_INITIALES) + 1
