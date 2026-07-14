"""
Heures supplémentaires payées, déduites du compteur de récupération.

Payer des heures supp (variables de paie, colonne « H. supps ») doit pouvoir
les retirer du solde de récupération du salarié — sinon double compensation
possible (payées PUIS récupérées), surtout pour les CDD en fin de contrat.
La déduction est pilotée par la case « déduire du compteur » de la grille
Variables Paie (cochée par défaut) ; les saisies antérieures à la migration
0057 (hs_deduites_compteur à NULL) ne déduisent rien rétroactivement.
"""
from utils import calculer_solde_recup, total_hs_payees


def _poser_solde_initial(db, user_id, heures):
    db.execute('UPDATE users SET solde_initial = ? WHERE id = ?', (heures, user_id))
    db.commit()


def _payer_hs(client, user_id, heures, mois=3, annee=2026, deduire=True):
    """Enregistre la grille variables paie avec des heures supp pour un salarié."""
    data = {
        'mois': str(mois), 'annee': str(annee),
        'user_ids': str(user_id),
        f'heures_supps_{user_id}': str(heures),
    }
    if deduire:
        data[f'hs_deduit_{user_id}'] = '1'
    return client.post('/variables_paie/enregistrer', data=data)


def _payer_hs_db(db, user_id, heures, mois=3, annee=2026, deduit=1):
    """Ligne de paie insérée en base (les fixtures client partagent la même
    session : impossible de mixer comptable_client et auth_client)."""
    db.execute('''INSERT INTO variables_paie
                  (user_id, mois, annee, heures_supps, hs_deduites_compteur)
                  VALUES (?, ?, ?, ?, ?)''',
               (user_id, mois, annee, heures, deduit))
    db.commit()


# ── Déduction du solde ──

def test_hs_payees_deduites_du_solde(comptable_client, app, db, sample_users):
    uid = sample_users['salarie_id']
    _poser_solde_initial(db, uid, 10)
    _payer_hs(comptable_client, uid, 4, mois=3)
    with app.app_context():
        assert calculer_solde_recup(uid) == 6      # 10 - 4 payées


def test_hs_payees_cumulees_sur_plusieurs_mois(comptable_client, app, db, sample_users):
    uid = sample_users['salarie_id']
    _poser_solde_initial(db, uid, 10)
    _payer_hs(comptable_client, uid, 4, mois=3)
    _payer_hs(comptable_client, uid, 2.5, mois=4)
    with app.app_context():
        assert calculer_solde_recup(uid) == 3.5    # 10 - 4 - 2.5


def test_hs_non_deduites_si_case_decochee(comptable_client, app, db, sample_users):
    uid = sample_users['salarie_id']
    _poser_solde_initial(db, uid, 10)
    _payer_hs(comptable_client, uid, 4, deduire=False)
    with app.app_context():
        assert calculer_solde_recup(uid) == 10     # payées mais hors compteur


def test_lignes_anterieures_migration_non_deduites(app, db, sample_users):
    """Saisies d'avant la migration 0057 : hs_deduites_compteur NULL → aucune
    déduction rétroactive."""
    uid = sample_users['salarie_id']
    _poser_solde_initial(db, uid, 10)
    db.execute('''INSERT INTO variables_paie (user_id, mois, annee, heures_supps)
                  VALUES (?, 1, 2026, 8)''', (uid,))
    db.commit()
    with app.app_context():
        assert calculer_solde_recup(uid) == 10


def test_total_hs_payees_filtres_periode(comptable_client, app, db, sample_users):
    """Le helper distingue « avant le mois » et « le mois précis » (fiche
    mensuelle : solde antérieur vs cumul du mois)."""
    from database import get_db
    uid = sample_users['salarie_id']
    _payer_hs(comptable_client, uid, 4, mois=3, annee=2026)
    _payer_hs(comptable_client, uid, 2, mois=5, annee=2026)
    with app.app_context():
        conn = get_db()
        try:
            assert total_hs_payees(conn, uid) == 6
            assert total_hs_payees(conn, uid, annee=2026, mois=5, avant=True) == 4
            assert total_hs_payees(conn, uid, annee=2026, mois=5) == 2
            assert total_hs_payees(conn, uid, annee=2026, mois=4) == 0
        finally:
            conn.close()


# ── Grille Variables Paie ──

def test_grille_affiche_solde_recup(comptable_client, db, sample_users):
    _poser_solde_initial(db, sample_users['salarie_id'], 7.5)
    html = comptable_client.get('/variables_paie').get_data(as_text=True)
    assert 'Solde recup' in html
    assert '7.50 h' in html
    assert 'deduire du compteur' in html


def test_grille_case_cochee_par_defaut_et_persistee(comptable_client, db, sample_users):
    uid = sample_users['salarie_id']
    # Avant toute saisie : case cochée par défaut pour ce salarié.
    html = comptable_client.get('/variables_paie?mois=3&annee=2026').get_data(as_text=True)
    assert f'name="hs_deduit_{uid}" value="1"\n                                       checked' in html \
        or 'checked' in html.split(f'name="hs_deduit_{uid}"')[1][:120]
    # Décochée à l'enregistrement → l'état est repris décoché.
    _payer_hs(comptable_client, uid, 4, mois=3, deduire=False)
    html = comptable_client.get('/variables_paie?mois=3&annee=2026').get_data(as_text=True)
    assert 'checked' not in html.split(f'name="hs_deduit_{uid}"')[1][:120]


def test_vue_salarie_dashboard_utilise_le_solde_net(auth_client, db, sample_users):
    """Le salarié voit partout le solde net des heures payées (dashboard via
    calculer_solde_recup — vérifié indirectement par le formulaire de demande)."""
    uid = sample_users['salarie_id']
    _poser_solde_initial(db, uid, 10)
    _payer_hs_db(db, uid, 4, mois=3)
    html = auth_client.get('/demande_recup').get_data(as_text=True)
    assert '6.00' in html      # solde affiché net


# ── Traces ──

def test_trace_salarie_mes_demandes(auth_client, db, sample_users):
    uid = sample_users['salarie_id']
    _payer_hs_db(db, uid, 4, mois=3, annee=2026)
    html = auth_client.get('/mes_demandes_recup').get_data(as_text=True)
    assert 'Heures supplémentaires payées' in html
    assert 'Paie de mars 2026' in html
    assert '4.00 h' in html


def test_trace_salarie_absente_sans_paiement(auth_client, sample_users):
    html = auth_client.get('/mes_demandes_recup').get_data(as_text=True)
    assert 'Heures supplémentaires payées' not in html


def test_trace_salarie_ignore_hs_non_deduites(auth_client, db, sample_users):
    uid = sample_users['salarie_id']
    _payer_hs_db(db, uid, 4, mois=3, deduit=0)
    html = auth_client.get('/mes_demandes_recup').get_data(as_text=True)
    assert 'Heures supplémentaires payées' not in html


def test_trace_historique_direction(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    _payer_hs_db(db, uid, 4, mois=3, annee=2026)
    html = admin_client.get('/historique_demandes_recup').get_data(as_text=True)
    assert 'Heures supplémentaires payées' in html
    assert 'Martin Jean' in html
    assert 'Paie de mars 2026' in html


# ── Fiche mensuelle (vue + PDF alignés sur le compteur) ──

def test_vue_mensuelle_deduit_les_hs_payees(auth_client, db, sample_users):
    """Paiement sur la paie de mars → le solde cumulé d'avril (mois suivant)
    l'intègre via le solde antérieur ; celui de mars via le cumul du mois."""
    uid = sample_users['salarie_id']
    _poser_solde_initial(db, uid, 10)
    _payer_hs_db(db, uid, 4, mois=3, annee=2026)

    # Fiche d'avril : les 4 h payées en mars sortent du solde antérieur.
    html = auth_client.get(f'/vue_mensuelle?user_id={uid}&mois=4&annee=2026').get_data(as_text=True)
    assert '6.00h' in html      # 10 (initial) - 4 (payées avant avril)

    # Fiche de mars : mention explicite du paiement du mois.
    html = auth_client.get(f'/vue_mensuelle?user_id={uid}&mois=3&annee=2026').get_data(as_text=True)
    assert 'payées sur la paie de ce mois (4.00h)' in html


def _texte_pdf(data):
    """Concatène les flux décompressés du PDF (le texte y est en clair).

    ReportLab encode ses flux en ASCII85 puis Flate ; on tente les deux
    décodages (a85 -> zlib, puis zlib direct) et on ignore le reste (polices…).
    """
    import base64
    import re
    import zlib
    morceaux = []
    for m in re.findall(rb'stream\r?\n(.*?)endstream', data, re.S):
        m = m.strip()
        for decode in (lambda b: zlib.decompress(base64.a85decode(b, adobe=True)),
                       zlib.decompress):
            try:
                morceaux.append(decode(m))
                break
            except Exception:
                continue
    return b''.join(morceaux)


def _valider_mois(db, uid, mois, annee):
    """Le PDF n'est disponible que pour un mois validé/bloqué."""
    db.execute('''INSERT INTO validations (user_id, mois, annee, validation_salarie,
                  validation_responsable, validation_directeur, date_salarie,
                  date_responsable, date_directeur, bloque)
                  VALUES (?, ?, ?, 'Jean M.', 'Marie D.', 'Dir', '2026-04-01',
                          '2026-04-02', '2026-04-03', 1)''', (uid, mois, annee))
    db.commit()


def test_export_pdf_avec_hs_payees(admin_client, db, sample_users):
    """PDF du mois du paiement : part du solde initial (revue Codex), affiche
    la ligne « H. supp payées ce mois » et un cumul aligné sur le dashboard."""
    uid = sample_users['salarie_id']
    _poser_solde_initial(db, uid, 10)
    _payer_hs_db(db, uid, 4, mois=3, annee=2026)
    _valider_mois(db, uid, 3, 2026)
    r = admin_client.get(f'/export_pdf_mensuel?user_id={uid}&mois=3&annee=2026')
    assert r.status_code == 200
    assert r.data[:4] == b'%PDF'
    texte = _texte_pdf(r.data)
    assert b'+10.00h' in texte     # solde antérieur = solde initial (pas 0)
    assert b'-4.00h' in texte      # H. supp payées ce mois
    assert b'+6.00h' in texte      # cumulé : 10 + 0 - 4, comme le dashboard


def test_export_pdf_mois_suivant_deduit_les_paies_anterieures(admin_client, db, sample_users):
    """PDF d'un mois postérieur au paiement : les heures payées sortent du
    solde antérieur (10 - 4 = 6), toujours aligné sur le dashboard."""
    uid = sample_users['salarie_id']
    _poser_solde_initial(db, uid, 10)
    _payer_hs_db(db, uid, 4, mois=3, annee=2026)
    _valider_mois(db, uid, 4, 2026)
    r = admin_client.get(f'/export_pdf_mensuel?user_id={uid}&mois=4&annee=2026')
    assert r.status_code == 200
    texte = _texte_pdf(r.data)
    assert b'+6.00h' in texte      # solde antérieur net des 4 h payées en mars
    assert b'-4.00h' not in texte  # pas de ligne « payées ce mois » en avril
