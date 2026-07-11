"""
Tests du « Centre de contrôle » (tableau de bord direction v2).

Couvre : accès, blocs principaux, exemples de recherche, seuils d'alerte
(défauts + enregistrement), prochaine action / file d'actions en un clic,
KPI par exception (trésorerie, budget, congés conventionnels) et
suggestions « Aller plus loin ».
"""
from datetime import datetime


def _seed_facture(db, montant=1240.50, fournisseur='EDF'):
    db.execute("INSERT INTO fournisseurs (nom) VALUES (?)", (fournisseur,))
    fid = db.execute("SELECT id FROM fournisseurs WHERE nom=?", (fournisseur,)).fetchone()['id']
    db.execute("INSERT INTO factures (numero_facture, fournisseur_id, montant_ttc, approbation, date_echeance) "
               "VALUES ('F-100', ?, ?, 'en_attente', '2026-07-05')", (fid, montant))
    db.commit()
    return db.execute("SELECT id FROM factures WHERE numero_facture='F-100'").fetchone()['id']


# ──────────────────────────────────────────────────────────────────────────
#  Accès et structure
# ──────────────────────────────────────────────────────────────────────────

def test_dashboard_direction_refuse_salarie(client, sample_users):
    from tests.conftest import _login
    _login(client, 'salarie_test', 'sal123')
    response = client.get('/dashboard_direction', follow_redirects=False)
    assert response.status_code == 302


def test_page_rend_les_blocs_principaux(admin_client):
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'Centre de contrôle' in html
    assert "Seuils d'alerte" in html
    assert 'À faire maintenant' in html
    assert 'Aller plus loin' in html
    assert 'indicateurs dans la normale' in html


def test_comptable_accede(comptable_client):
    resp = comptable_client.get('/dashboard_direction')
    assert resp.status_code == 200


def test_exemples_recherche_sous_la_barre(admin_client):
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    for exemple in ('budget prévisionnel', 'CDD en cours', 'facture à valider', 'arrêts maladies'):
        assert f'data-ds-exemple="{exemple}"' in html


def test_suggestions_trois_cartes(admin_client):
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert html.count('class="cc-suggestion"') == 3


# ──────────────────────────────────────────────────────────────────────────
#  Seuils d'alerte
# ──────────────────────────────────────────────────────────────────────────

def test_seuils_par_defaut_dans_la_fenetre(admin_client):
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'id="ccSeuilTreso" value="50000"' in html
    assert 'id="ccSeuilBudget" value="80"' in html
    assert 'id="ccSeuilConges" value="5"' in html
    assert 'id="ccSeuilSurcharge" value="55"' in html


def test_seuils_enregistrement_et_relecture(admin_client):
    r = admin_client.post('/api/dashboard-direction/seuils', json={
        'treso': 30000, 'budget': 90, 'conges': 10, 'surcharge': 70})
    data = r.get_json()
    assert r.status_code == 200 and data['success']
    assert data['seuils']['treso'] == 30000.0
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'id="ccSeuilTreso" value="30000"' in html
    assert 'id="ccSeuilSurcharge" value="70"' in html


def test_seuils_valeur_invalide_refusee(admin_client):
    assert admin_client.post('/api/dashboard-direction/seuils',
                             json={'treso': 'abc'}).status_code == 400
    assert admin_client.post('/api/dashboard-direction/seuils',
                             json={'budget': -5}).status_code == 400


def test_seuils_refuses_au_salarie(auth_client):
    r = auth_client.post('/api/dashboard-direction/seuils', json={'treso': 1})
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
#  File d'actions et prochaine action
# ──────────────────────────────────────────────────────────────────────────

def test_facture_en_attente_devient_action_un_clic(admin_client, db, sample_users):
    fid = _seed_facture(db)
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'Facture EDF' in html
    assert f'data-facture-id="{fid}"' in html
    assert 'data-cc-act="facture"' in html
    # La prochaine action existe (bandeau affiché, rempli côté client).
    assert 'id="ccProchaine"' in html
    assert 'display:none' not in html.split('id="ccProchaine"')[1][:80]


def test_demande_en_attente_valider_refuser(admin_client, db, sample_users):
    db.execute("INSERT INTO demandes_recup (user_id, date_debut, date_fin, nb_jours, nb_heures, statut) "
               "VALUES (?, '2026-07-20', '2026-07-20', 1, 7, 'en_attente_direction')",
               (sample_users['salarie_id'],))
    db.commit()
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'Demande de récupération : Jean Martin' in html
    assert 'validée responsable, à valider' in html
    assert 'data-cc-act="valider"' in html
    assert 'data-cc-act="refuser"' in html


def test_fiches_mois_precedent_a_relancer(admin_client, db, sample_users):
    # Aucun mois validé : l'item de relance du mois précédent apparaît.
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'non validée(s)' in html
    assert 'data-cc-act="relance"' in html


def test_conges_conventionnels_au_dessus_du_seuil(admin_client, db, sample_users):
    db.execute("UPDATE users SET cc_solde = 12 WHERE id = ?", (sample_users['salarie_id'],))
    db.commit()
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    # KPI par exception + action de planification.
    assert 'Congés conventionnels à planifier' in html
    assert 'Solde congés conventionnels élevé : Jean Martin' in html
    assert '12 j de congés conventionnels à planifier' in html


def test_conges_sous_le_seuil_dans_la_normale(admin_client, db, sample_users):
    db.execute("UPDATE users SET cc_solde = 2 WHERE id = ?", (sample_users['salarie_id'],))
    db.commit()
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'Congés conventionnels à planifier' not in html
    assert 'Congés conv. max' in html


# ──────────────────────────────────────────────────────────────────────────
#  KPI par exception
# ──────────────────────────────────────────────────────────────────────────

def test_alerte_tresorerie_sous_le_seuil(admin_client, db):
    now = datetime.now()
    db.execute("INSERT INTO tresorerie_solde_initial (annee, mois, montant, annee_ref, mois_ref) "
               "VALUES (?, ?, 8420, ?, ?)", (now.year, now.month, now.year, now.month))
    db.commit()
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'Trésorerie sous le seuil' in html
    assert '8 420 €' in html


def test_tresorerie_au_dessus_du_seuil_dans_la_normale(admin_client, db):
    now = datetime.now()
    db.execute("INSERT INTO tresorerie_solde_initial (annee, mois, montant, annee_ref, mois_ref) "
               "VALUES (?, ?, 120000, ?, ?)", (now.year, now.month, now.year, now.month))
    db.commit()
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'Trésorerie sous le seuil' not in html
    assert '120 000 €' in html          # dans les indicateurs « dans la normale »


def test_alerte_budget_presque_epuise(admin_client, db, sample_users):
    annee = datetime.now().year
    db.execute("INSERT INTO budgets (secteur_id, annee, montant_global) VALUES (?, ?, 50000)",
               (sample_users['secteur_id'], annee))
    bid = db.execute("SELECT id FROM budgets ORDER BY id DESC LIMIT 1").fetchone()['id']
    db.execute("INSERT INTO postes_depense (nom) VALUES ('Test poste')")
    pid = db.execute("SELECT id FROM postes_depense ORDER BY id DESC LIMIT 1").fetchone()['id']
    db.execute("INSERT INTO budget_reel_lignes (budget_id, poste_depense_id, montant) "
               "VALUES (?, ?, 46500)", (bid, pid))
    db.commit()
    html = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'Budget presque épuisé' in html
    assert '93' in html                 # 46 500 / 50 000 = 93 %
