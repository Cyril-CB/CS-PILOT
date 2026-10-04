"""Tests autonomes stdlib : python -m unittest tests.test_budget_initial_moteur.

Aucune dépendance Flask, aucune base existante, aucune donnée personnelle.
"""
import copy
import importlib
import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from budget_initial import (
    InitialRefuse, calculer, charger, enregistrer, euros, nombre,
    normaliser_ligne, preparer_report, repartir, reporter, serialisable,
)
from schema_budget_initial import creer_schema

SECTEURS = {'1': 'Pilote synthétique', '2': 'Second synthétique'}


def reference(**champs):
    return {'source': 'Référence synthétique 2025', 'annee': '2025',
            'assiette': 'Brut global annuel', 'perimetre': 'Secteur pilote comparable',
            'verification': '2026-01-10', 'complete_comparable': True,
            'numerateur': '48000', 'denominateur': '120000', **champs}


def salaire(**champs):
    return {'libelle': 'Poste synthétique', 'nature': 'salaire', 'compte': '641100',
            'secteurs': {'1': '100'}, 'source': 'Hypothèse synthétique', 'note': 'Fonctionnement normal',
            'poste': 'vacant', 'contrat': 'permanent', 'base': 'brut', 'brut_mensuel': '2000',
            'brut_verifie': True, 'quotite': '100', 'taux_charges': '40',
            'reference_charges': reference(), **champs}


def depense(**champs):
    return {'libelle': 'Charge synthétique', 'nature': 'depense', 'compte': '606100',
            'secteurs': {'1': '100'}, 'source': 'Estimation synthétique', 'note': 'Douze mois normaux',
            'mode': 'manuel', 'annuel': '1200', **champs}


def lignes(*donnees):
    return [{'id': str(i), 'donnees': normaliser_ligne(d, SECTEURS)} for i, d in enumerate(donnees)]


def calcul(*donnees, option=False, **kwargs):
    return calculer(2026, {'taux_individuels': option}, lignes(*donnees), SECTEURS, **kwargs)


class MoteurInitialTest(unittest.TestCase):
    def test_pilote_explications_manuels_et_concordance(self):
        d = calcul(salaire(complements=[{'libelle': 'Prime unique', 'compte': '641200', 'mois': ['100'] * 12}]),
                   depense(compte='645100', mode='proportionnel', reference=reference()),
                   depense(), depense(nature='financement', compte='706100', annuel='40000'))
        self.assertTrue(d['complet'], d['alertes'])
        self.assertEqual(d['general']['charges_annuel'], D('36480'))
        self.assertEqual(d['general']['resultat_annuel'], D('3520'))
        self.assertEqual(d['ventilation']['1']['645100'], [D('840')] * 12)
        self.assertTrue(all(l['explication'] for l in d['lignes']))
        self.assertEqual(d['general'], d['secteurs']['1'])

    def test_arrondis_concordants_tous_signes(self):
        for cents in (-1001, -1, 0, 1, 1001, 100001):
            value = D(cents) / 100
            r = repartir(value, {'a': D(1), 'b': D(1), 'c': D(1)})
            self.assertEqual(sum(r.values()), value)
            self.assertLessEqual(max(r.values()) - min(r.values()), D('.01'))
            self.assertEqual(r, repartir(value, {'a': D(1), 'b': D(1), 'c': D(1)}))

    def test_concordance_sectorielle_mensuelle_avec_complements(self):
        d = calcul(salaire(brut_mensuel='0.01', secteurs={'1': '50', '2': '50'},
                           complements=[{'libelle': 'Prime', 'compte': '641200', 'mois': ['0.01'] * 12}]),
                   depense(compte='645100', mode='proportionnel', reference=reference(numerateur='100', denominateur='100')),
                   depense(secteurs={'1':'33.33','2':'66.67'}, annuel='100.01'))
        for i in range(12):
            self.assertEqual(sum(v['charges'][i] for v in d['secteurs'].values()), d['general']['charges'][i])
        s = d['ventilation']['1']
        self.assertEqual(s['645100'], [a+b for a,b in zip(s['641100'],s['641200'])])

    def test_inconnu_distinct_zero(self):
        absent = calcul(depense(annuel=None))
        connu = calcul(depense(annuel='0'))
        self.assertIsNone(absent['general']['charges_annuel'])
        self.assertIsNone(absent['general']['resultat_annuel'])
        self.assertFalse(absent['complet'])
        self.assertEqual(connu['general']['charges_annuel'], 0)
        self.assertTrue(connu['complet'])

    def test_alisfa_une_seule_base_active(self):
        d = calcul(salaire(base='alisfa', socle='24000', point='60', pesee='100', anciennete='10',
                           competence='5', maintien='50', quotite='50', brut_mensuel='999999'))
        self.assertEqual(d['lignes'][0]['total'], D('16500'))
        self.assertEqual(d['lignes'][0]['mois'][0], D('1375'))

    def test_brut_a_quotite_non_proratise_deux_fois(self):
        d = calcul(salaire(quotite='50', brut_mensuel='1000'))
        self.assertEqual(d['lignes'][0]['total'], 12000)

    def test_brut_non_verifie_inconnu(self):
        d = calcul(salaire(brut_verifie=False))
        self.assertFalse(d['complet'])
        self.assertIsNone(d['lignes'][0]['total'])

    def test_alisfa_incomplete_ne_devient_pas_zero(self):
        d = calcul(salaire(base='alisfa', socle='24000'))
        self.assertIsNone(d['lignes'][0]['total'])

    def test_permanent_douze_mois(self):
        with self.assertRaises(InitialRefuse):
            calcul(salaire(activite=['0'] + ['1'] * 11))

    def test_saisonnier_et_cee_activite_normale(self):
        d = calcul(salaire(contrat='saisonnier', activite=['0'] * 10 + ['0.5','1']),
                   salaire(libelle='CEE fictif', contrat='cee', base='cee', forfait_cee='100',
                           jours_cee=['0'] * 11 + ['10']))
        self.assertEqual(d['general']['charges_annuel'], 4000)
        self.assertEqual(d['general']['charges'][-2:], [D(1000), D(3000)])

    def test_complement_unique_sur_autre_641(self):
        for complements in [
            [{'libelle':'Prime','compte':'641100','mois':['0']*12}],
            [{'libelle':'Prime','compte':'641200','mois':['0']*12}]*2,
            [{'libelle':'Prime','compte':'645100','mois':['0']*12}],
        ]:
            with self.assertRaises(InitialRefuse):
                calcul(salaire(complements=complements))

    def test_premier_641_existant_respecte(self):
        d = calcul(salaire(), premiers={'1':'641000'})
        self.assertFalse(d['complet'])
        self.assertIn('premier 641', str(d['alertes']))

    def test_depense_641_refusee(self):
        with self.assertRaises(InitialRefuse):
            calcul(depense(compte='641200'))

    def test_taux_individuels_somme_brut_complements_63_conserve(self):
        d = calcul(salaire(complements=[{'libelle':'Prime','compte':'641200','mois':['100']*12}]),
                   salaire(libelle='Second poste', brut_mensuel='1000', taux_charges='20'),
                   depense(compte='645100', annuel='999'), depense(compte='645200', annuel='888'),
                   depense(compte='648100', annuel='777'), depense(compte='635100', annuel='123'), option=True)
        self.assertEqual(sum(d['ventilation']['1']['645100']), 12480)
        self.assertEqual(sum(d['ventilation']['1']['645200']), 0)
        self.assertEqual(sum(d['ventilation']['1']['648100']), 0)
        self.assertEqual(sum(d['ventilation']['1']['635100']), 123)
        self.assertTrue(d['complet'], d['alertes'])

    def test_desactivation_taux_retrouve_manuels(self):
        data = lignes(salaire(), depense(compte='645100', annuel='999'))
        avant = copy.deepcopy(data)
        calculer(2026, {'taux_individuels':True}, data, SECTEURS)
        d = calculer(2026, {'taux_individuels':False}, data, SECTEURS)
        self.assertEqual(data, avant)
        self.assertEqual(sum(d['ventilation']['1']['645100']), 999)

    def test_taux_manquant_et_zero_explicite(self):
        for taux, complet in [(None, False), ('0', True)]:
            d = calcul(salaire(taux_charges=taux), depense(compte='645100'), option=True)
            self.assertEqual(d['complet'], complet)
        self.assertEqual(sum(d['ventilation']['1']['645100']), 0)

    def test_taux_premier_645_existant(self):
        d = calcul(salaire(), depense(compte='645200'), option=True, premiers_charges={'1':'645100'})
        self.assertEqual(sum(d['ventilation']['1']['645100']), 9600)
        self.assertEqual(sum(d['ventilation']['1']['645200']), 0)

    def test_charge_sans_645_signalee(self):
        self.assertFalse(calcul(salaire(), option=True)['complet'])

    def test_assiette_trop_petite_refusee_sans_exception_decimal(self):
        with self.assertRaises(InitialRefuse):
            calcul(salaire(), depense(mode='proportionnel', reference=reference(denominateur='0.00000000000000001')))

    def test_brut_negatif_a_revoir(self):
        d = calcul(salaire(complements=[{'libelle':'Réduction','compte':'641200','mois':['-3000']*12}]))
        self.assertFalse(d['complet'])
        self.assertIn('négatif', str(d['alertes']))

    def test_reference_complete_comparable_pas_deduite_de_2025(self):
        for ref in [reference(complete_comparable=False), reference(annee='2026'), reference(source=''), reference(denominateur='0')]:
            d = calcul(salaire(), depense(compte='645100', mode='proportionnel', reference=ref))
            self.assertFalse(d['complet'])
            self.assertIsNone(sum(d['ventilation']['1']['645100']) if all(v is not None for v in d['ventilation']['1']['645100']) else None)

    def test_modes_charges_manuels_mensuels_proportionnels(self):
        d = calcul(salaire(), depense(compte='645100', annuel='1200'),
                   depense(compte='646100', mode='mensuel', mois=['1']*11+['2']),
                   depense(compte='635100', mode='proportionnel', reference=reference()))
        self.assertEqual(sum(d['ventilation']['1']['645100']),1200)
        self.assertEqual(sum(d['ventilation']['1']['646100']),13)
        self.assertEqual(sum(d['ventilation']['1']['635100']),9600)

    def test_proportionnel_multi_secteur_refuse(self):
        with self.assertRaises(InitialRefuse):
            calcul(depense(mode='proportionnel', secteurs={'1':'50','2':'50'}))

    def test_validation_nombres_et_ventilations(self):
        for value in ('NaN', 'Infinity', True, '-1', '100.01'):
            with self.assertRaises(InitialRefuse):
                normaliser_ligne(salaire(quotite=value), SECTEURS)
        for parts in ({'1':'99'}, {'1':'101','2':'-1'}, {'999':'100'}, {'1':''}):
            with self.assertRaises(InitialRefuse):
                normaliser_ligne(depense(secteurs=parts), SECTEURS)
        self.assertEqual(nombre('1,25'), D('1.25'))
        self.assertEqual(euros(D('1.005')), D('1.01'))

    def test_secteur_supprime_consultable_mais_non_reportable(self):
        data = lignes(depense())
        d = calculer(2026, {}, data, {'2':'Autre'})
        self.assertFalse(d['complet'])
        self.assertIn('supprimé', str(d['alertes']))

    def test_serialisation_sans_perte(self):
        d = calcul(depense(annuel='0.01'))
        self.assertEqual(json.loads(json.dumps(serialisable(d)))['general']['charges_annuel'],'0.01')


class PersistenceInitialTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'synthetique.sqlite')
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE users (id INTEGER PRIMARY KEY, nom TEXT);
            INSERT INTO users VALUES (1, 'FICTIF');
            CREATE TABLE secteurs (id INTEGER PRIMARY KEY, nom TEXT);
            INSERT INTO secteurs VALUES (1, 'PILOTE FICTIF');
            CREATE TABLE budget_prev_saisies (type_budget TEXT, annee INTEGER, secteur_id INTEGER,
                compte_num TEXT, valeur_temp REAL, valeur_def REAL, commentaire TEXT,
                updated_by INTEGER, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(type_budget, annee, secteur_id, compte_num));
            CREATE TABLE budget_modes_comptes (type_budget TEXT, annee INTEGER, secteur_id INTEGER, compte_num TEXT, mode TEXT);
            CREATE TABLE budget_paie_simulations (type_budget TEXT, annee INTEGER, secteur_id INTEGER, donnees TEXT);
            INSERT INTO budget_prev_saisies VALUES ('actualise',2026,1,'606100',-12.34,-12.34,'Commentaire fictif',1,'2026-01-01');
            INSERT INTO budget_paie_simulations VALUES ('actualise',2026,1,'{"ajouts":[]}');
        ''')
        creer_schema(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def save(self, d, identifiant=None, annee=2026):
        with self.conn:
            enregistrer(self.conn, annee, charger(self.conn,annee)['revision'], 1, SECTEURS,
                        ligne={'id':identifiant,'donnees':d})
        return charger(self.conn,annee)['lignes'][-1]['id']

    def calc(self):
        state=charger(self.conn,2026)
        return calculer(2026,state['hypotheses'],state['lignes'],SECTEURS)

    def report(self):
        calc=self.calc()
        _,ref=preparer_report(self.conn,2026,calc)
        with self.conn:
            return reporter(self.conn,2026,charger(self.conn,2026)['revision'],1,calc,ref)

    def test_migration_additive_idempotente_et_ancienne_base(self):
        migration=importlib.import_module('migrations.0077_budget_initial_detaille')
        avant=[tuple(r) for r in self.conn.execute('SELECT * FROM budget_prev_saisies')]
        migration.upgrade(self.conn); migration.upgrade(self.conn)
        self.assertEqual(avant,[tuple(r) for r in self.conn.execute('SELECT * FROM budget_prev_saisies')])
        self.assertEqual(charger(self.conn,2026)['lignes'],[])
        with self.assertRaises(RuntimeError): migration.downgrade(self.conn)

    def test_identite_reouverture_aucune_modification_rh_liens_inactifs(self):
        ident=self.save(salaire())
        self.conn.close(); self.conn=sqlite3.connect(self.path);self.conn.row_factory=sqlite3.Row
        self.assertEqual(charger(self.conn,2026)['lignes'][0]['id'],ident)
        self.save(salaire(brut_mensuel='2200', lien_type='contrat', lien_id='42'),ident)
        row=charger(self.conn,2026)['lignes'][0]
        self.assertEqual(row['id'],ident); self.assertIsNone(row['lien_type']); self.assertIsNone(row['lien_id'])
        self.assertEqual(tuple(self.conn.execute('SELECT * FROM users').fetchone()),(1,'FICTIF'))

    def test_revision_obsolete_transaction_sans_ecriture_partielle(self):
        self.save(depense())
        avant=charger(self.conn,2026)
        with self.assertRaises(InitialRefuse),self.conn:
            enregistrer(self.conn,2026,0,1,SECTEURS,ligne={'donnees':salaire()})
        self.assertEqual(avant,charger(self.conn,2026))

    def test_identifiant_autre_annee_et_suppression_refuses(self):
        ident=self.save(depense())
        with self.assertRaises(InitialRefuse): self.save(depense(),ident,2027)
        with self.assertRaises(InitialRefuse),self.conn:
            enregistrer(self.conn,2027,0,1,SECTEURS,supprimer=ident)
        self.assertEqual(len(charger(self.conn,2026)['lignes']),1)

    def test_salarie_en_double_refuse(self):
        self.save(salaire(poste='occupe',salarie_id='1'))
        with self.assertRaises(InitialRefuse):self.save(salaire(poste='occupe',salarie_id='1'))
        with self.assertRaises(InitialRefuse):self.save(salaire(poste='occupe',salarie_id='01'))
        with self.assertRaises(InitialRefuse):self.save(salaire(poste='occupe',salarie_id='999'))

    def test_report_initial_actualise_et_simulations_intacts(self):
        self.save(depense())
        avant=tuple(self.conn.execute("SELECT * FROM budget_prev_saisies WHERE type_budget='actualise'").fetchone())
        sim=[tuple(r) for r in self.conn.execute('SELECT * FROM budget_paie_simulations')]
        self.assertEqual(self.report(),1)
        self.assertEqual(tuple(self.conn.execute("SELECT * FROM budget_prev_saisies WHERE type_budget='actualise'").fetchone()),avant)
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM budget_paie_simulations')],sim)
        self.assertEqual(self.conn.execute("SELECT valeur_def FROM budget_prev_saisies WHERE type_budget='initial'").fetchone()[0],1200)

    def test_recalcul_preserve_manuel_et_commentaire(self):
        ident=self.save(depense());self.report()
        self.conn.execute("UPDATE budget_prev_saisies SET commentaire='Conservé' WHERE type_budget='initial'");self.conn.commit()
        self.save(depense(annuel='2400'),ident);self.assertEqual(self.report(),1)
        self.assertEqual(self.conn.execute("SELECT commentaire FROM budget_prev_saisies WHERE type_budget='initial'").fetchone()[0],'Conservé')
        self.conn.execute("UPDATE budget_prev_saisies SET valeur_def=777 WHERE type_budget='initial'");self.conn.commit()
        self.save(depense(annuel='3600'),ident);self.assertEqual(self.report(),0)
        self.assertEqual(self.conn.execute("SELECT valeur_def FROM budget_prev_saisies WHERE type_budget='initial'").fetchone()[0],777)

    def test_ancien_zero_manuel_ne_devient_pas_libre(self):
        self.save(depense())
        self.conn.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_def) VALUES ('initial',2026,1,'606100',0)");self.conn.commit()
        self.assertEqual(self.report(),0)

    def test_report_perime_refuse(self):
        self.save(depense());calc=self.calc();_,ref=preparer_report(self.conn,2026,calc)
        self.conn.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_def) VALUES ('initial',2026,1,'606100',123)");self.conn.commit()
        with self.assertRaises(InitialRefuse),self.conn:
            reporter(self.conn,2026,1,1,calc,ref)

    def test_automatique_existant_et_simulation_preserves(self):
        self.save(depense(compte='645100'))
        self.conn.execute("INSERT INTO budget_modes_comptes VALUES ('initial',2026,1,'645100','mensuel')");self.conn.commit()
        self.assertEqual(self.report(),0)
        self.conn.execute('DELETE FROM budget_modes_comptes')
        self.conn.execute('INSERT INTO budget_paie_simulations VALUES (?,?,?,?)',('initial',2026,1,'{"utiliser_taux_charges":true}'));self.conn.commit()
        self.assertEqual(self.report(),0)

    def test_report_incomplet_refuse(self):
        self.save(depense(annuel=None))
        with self.assertRaises(InitialRefuse):self.report()

    def test_suppression_ligne_report_zero_explicite(self):
        ident=self.save(depense());self.report()
        self.save(depense(compte='606200'))
        with self.conn:enregistrer(self.conn,2026,2,1,SECTEURS,supprimer=ident)
        prop,_=preparer_report(self.conn,2026,self.calc())
        self.assertTrue(next(p for p in prop if p['compte']=='606100')['retire'])
        self.report()
        self.assertEqual(self.conn.execute("SELECT valeur_def FROM budget_prev_saisies WHERE type_budget='initial' AND compte_num='606100'").fetchone()[0],0)


if __name__ == '__main__':
    unittest.main()
