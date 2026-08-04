"""
Le « Pourquoi ? » des cartes du fil (flux_circuits.py).

Vérifient ce qui fait la valeur du circuit, et qui se casse sans bruit :
l'étape mise en avant est bien celle qui attend, elle est reconnue comme
« la vôtre » pour le bon profil, et la conséquence dit ce qui est arrêté.
"""
from datetime import date

import flux_circuits


def _courante(circuit):
    return next(e for e in circuit['etapes'] if e['statut'] == 'courant')


class TestPositionDeLEtape:
    """Le circuit s'ouvre sur ce qui attend, pas sur ce qui est fait."""

    def test_conge_en_attente_responsable(self):
        circuit = flux_circuits.demande_conge(
            'en_attente_responsable', '2026-07-25', 'responsable', date(2026, 8, 3))
        assert circuit['rang'] == 2
        assert _courante(circuit)['role'] == 'responsable'
        assert circuit['a_moi'] is True

    def test_conge_en_attente_direction(self):
        circuit = flux_circuits.demande_conge(
            'en_attente_direction', '2026-07-25', 'directeur', date(2026, 8, 3))
        assert circuit['rang'] == 3
        assert _courante(circuit)['role'] == 'direction'
        assert circuit['a_moi'] is True

    def test_la_vôtre_ne_se_dit_qu_au_bon_profil(self):
        """Un comptable qui lit une décision de direction n'est pas concerné."""
        circuit = flux_circuits.demande_conge(
            'en_attente_direction', '2026-07-25', 'comptable', date(2026, 8, 3))
        assert circuit['a_moi'] is False

    def test_les_etapes_precedentes_sont_faites_et_les_suivantes_a_venir(self):
        circuit = flux_circuits.demande_conge(
            'en_attente_direction', '2026-07-25', 'directeur', date(2026, 8, 3))
        statuts = [e['statut'] for e in circuit['etapes']]
        assert statuts == ['fait', 'fait', 'courant', 'a_venir', 'a_venir']


class TestConsequence:
    """Le schéma seul ne dit pas pourquoi ça compte : la phrase du bas, si."""

    def test_une_attente_longue_est_chiffree(self):
        circuit = flux_circuits.demande_conge(
            'en_attente_direction', '2026-07-25', 'directeur', date(2026, 8, 3))
        assert '9 jours sans réponse' in circuit['consequence']

    def test_une_demande_fraiche_ne_reproche_rien(self):
        circuit = flux_circuits.demande_conge(
            'en_attente_direction', '2026-08-03', 'directeur', date(2026, 8, 3))
        assert circuit['consequence'] is None

    def test_le_cdd_a_sa_propre_consequence(self):
        """Ses heures se paient et il ne reste qu'un nombre fini de bulletins."""
        cdd = flux_circuits.fiche_heures('directeur', date(2026, 8, 3), est_cdd=True)
        cdi = flux_circuits.fiche_heures('directeur', date(2026, 8, 3), est_cdd=False)
        assert 'bulletin' in cdd['consequence']
        assert 'mois reste ouvert' in cdi['consequence']
        assert cdd['consequence'] != cdi['consequence']

    def test_la_consequence_ne_prete_rien_au_compteur_de_recuperation(self):
        """Il est tenu à jour dès la saisie : la validation ne le conditionne pas.

        Annoncer le contraire ferait valider pour une raison inexistante — et
        décrédibiliserait les conséquences que le circuit annonce par ailleurs.
        """
        for est_cdd in (True, False):
            circuit = flux_circuits.fiche_heures('directeur', date(2026, 8, 3),
                                                 est_cdd=est_cdd)
            assert 'compteur' not in circuit['consequence'], circuit['consequence']

    def test_une_echeance_de_facture_depassee_se_compte(self):
        circuit = flux_circuits.facture('en_attente', '2026-07-30', 'directeur',
                                        date(2026, 8, 3))
        assert 'dépassée de 4 jour(s)' in circuit['consequence']


class TestAlimentationsAnnexes:
    """Le circuit montre que l'application relie les éléments entre eux."""

    def test_la_paie_est_aussi_alimentee_par_les_arrets_maladie(self):
        circuit = flux_circuits.fiche_heures('directeur', date(2026, 8, 3))
        notes = [e['note'] for e in circuit['etapes'] if e['note']]
        assert any('arrêts maladie' in n for n in notes)


class TestFormeDesCircuits:
    """Chaque circuit reste lisible : rôle connu, liaisons nommées."""

    def _tous(self):
        aujourdhui = date(2026, 8, 3)
        return [
            flux_circuits.demande_conge('en_attente_direction', '2026-07-25',
                                        'directeur', aujourdhui, nb_jours=5),
            flux_circuits.demande_recup('en_attente_direction', '2026-07-25',
                                        'directeur', aujourdhui),
            flux_circuits.fiche_heures('directeur', aujourdhui, solde=7),
            flux_circuits.facture('en_attente', '2026-08-10', 'directeur', aujourdhui),
            flux_circuits.subvention('2026-08-10', 'directeur', aujourdhui),
            flux_circuits.fourniture('2026-07-25', 'directeur', aujourdhui),
        ]

    def test_chaque_etape_porte_un_role_connu(self):
        for circuit in self._tous():
            for etape in circuit['etapes']:
                assert etape['role'] in flux_circuits.ROLES
                assert etape['role_couleur'].startswith('#')

    def test_chaque_circuit_a_exactement_une_etape_courante(self):
        for circuit in self._tous():
            courantes = [e for e in circuit['etapes'] if e['statut'] == 'courant']
            assert len(courantes) == 1, circuit['intitule']

    def test_toutes_les_etapes_sauf_la_derniere_nomment_leur_liaison(self):
        for circuit in self._tous():
            for etape in circuit['etapes'][:-1]:
                assert etape['liaison'], (circuit['intitule'], etape['titre'])


class TestCouleursDesRoles:
    """Le rôle se lit à sa couleur : elle doit rester distincte et lisible."""

    def test_chaque_role_a_une_couleur_distincte(self):
        couleurs = [couleur for _, couleur in flux_circuits.ROLES.values()]
        assert len(set(couleurs)) == len(couleurs)

    def test_les_couleurs_tiennent_sur_les_deux_themes(self):
        """Ni trop sombres ni trop claires : le thème nuit a un fond vert
        sombre, le thème par défaut un beige clair. Un ton extrême disparaît
        sur l'un des deux."""
        for role, (_, couleur) in flux_circuits.ROLES.items():
            rouge = int(couleur[1:3], 16)
            vert = int(couleur[3:5], 16)
            bleu = int(couleur[5:7], 16)
            # Luminance perçue, formule usuelle.
            luminance = (0.299 * rouge + 0.587 * vert + 0.114 * bleu) / 255
            assert 0.28 < luminance < 0.78, (role, couleur, round(luminance, 2))
