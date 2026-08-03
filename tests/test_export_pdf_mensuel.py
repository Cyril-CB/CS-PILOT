"""
Cohérence du PDF mensuel avec la fiche qu'il reproduit.

Le PDF n'est délivré qu'une fois la fiche verrouillée : c'est le document
signé. Il refait pourtant le calcul du mois de son côté, ce qui l'expose à
diverger de l'écran validé. Ces tests verrouillent l'égalité.
"""
import base64
import re
import zlib

from blueprints.validation import _get_vue_mensuelle_data_impl
from database import get_db


def _texte_pdf(data):
    """Texte des flux de contenu d'un PDF reportlab (ASCII85 + Flate)."""
    morceaux = []
    for bloc in re.findall(rb'stream\r?\n(.*?)endstream', data, re.S):
        brut = bloc.strip()
        for essai in (
            lambda b: zlib.decompress(base64.a85decode(b, adobe=False)),
            lambda b: zlib.decompress(base64.a85decode(b.rstrip(b'~>'), adobe=False)),
            lambda b: zlib.decompress(b),
            lambda b: b,
        ):
            try:
                morceaux.append(essai(brut))
                break
            except Exception:
                continue
    return b'\n'.join(morceaux).decode('latin-1')


def _cellules(texte):
    """Chaînes réellement dessinées dans le document, dans l'ordre."""
    return re.findall(r'\(([^)]*)\) Tj', texte)


def _totaux(texte):
    """(théorique, réel) de la ligne TOTAL du tableau."""
    cellules = _cellules(texte)
    i = cellules.index('TOTAL')
    heures = [float(c[:-1]) for c in cellules[i + 1:i + 3]]
    return heures[0], heures[1]


def _preparer(app, db, uid, contrats=(), verrouiller=(12, 2024)):
    with app.app_context():
        for debut, fin in contrats:
            db.execute(
                "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
                "VALUES (?, 'CDD', ?, ?)", (uid, debut, fin)
            )
        mois, annee = verrouiller
        db.execute(
            "INSERT INTO validations (user_id, mois, annee, bloque) VALUES (?, ?, ?, 1)",
            (uid, mois, annee)
        )
        db.commit()


def _fiche(app, uid, mois, annee):
    """Données de la fiche mensuelle, telles que l'écran les montre."""
    with app.test_request_context(f'/vue_mensuelle?mois={mois}&annee={annee}'):
        from flask import session
        session['user_id'] = uid
        session['profil'] = 'salarie'
        conn = get_db()
        try:
            data, _ = _get_vue_mensuelle_data_impl(
                conn, mois, annee, None, 'validation_bp.vue_mensuelle')
        finally:
            conn.close()
    return data


class TestPdfEtContrat:
    """CDD du 09 au 20/12/2024 : douze jours ouvrés du mois sont hors contrat."""

    def test_le_pdf_ne_compte_pas_les_jours_hors_contrat(
            self, app, db, admin_client, sample_users, sample_planning):
        uid = sample_users['salarie_id']
        _preparer(app, db, uid, contrats=[('2024-12-09', '2024-12-20')])

        reponse = admin_client.get(
            f'/export_pdf_mensuel?user_id={uid}&mois=12&annee=2024')
        assert reponse.headers['Content-Type'] == 'application/pdf'
        texte = _texte_pdf(reponse.data)

        assert 'Hors contrat' in texte
        theorique, _ = _totaux(texte)
        # 10 jours ouvrés couverts à 7h. Le mois entier en compte 22 (154h) :
        # c'est ce que le PDF affirmait, en « conforme au planning ».
        assert theorique == 70.0

    def test_le_pdf_dit_la_meme_chose_que_la_fiche(
            self, app, db, admin_client, sample_users, sample_planning):
        """L'invariant : le document signé ne peut pas contredire l'écran validé."""
        uid = sample_users['salarie_id']
        _preparer(app, db, uid, contrats=[('2024-12-09', '2024-12-20')])

        texte = _texte_pdf(admin_client.get(
            f'/export_pdf_mensuel?user_id={uid}&mois=12&annee=2024').data)
        pdf_theorique, pdf_reel = _totaux(texte)

        fiche = _fiche(app, uid, 12, 2024)
        assert pdf_theorique == fiche['total_heures_theoriques']
        assert pdf_reel == fiche['total_heures_reelles']

    def test_sans_contrat_au_dossier_le_pdf_ne_change_pas(
            self, app, db, admin_client, sample_users, sample_planning):
        """Même garde-fou qu'ailleurs : sans référence, on ne retranche rien."""
        uid = sample_users['salarie_id']
        _preparer(app, db, uid)

        texte = _texte_pdf(admin_client.get(
            f'/export_pdf_mensuel?user_id={uid}&mois=12&annee=2024').data)

        assert 'Hors contrat' not in texte
        theorique, _ = _totaux(texte)
        assert theorique == 154.0        # les 22 jours ouvrés de décembre 2024
