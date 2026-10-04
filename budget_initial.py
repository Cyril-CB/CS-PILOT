"""Calcul annuel normal, déterministe et indépendant de Flask et des fiches RH.

Les entrées monétaires restent des chaînes décimales. Les ventilations au
centime utilisent les plus grands restes, avec départage par ordre des clés.
Un montant inconnu propage None ; un zéro explicite reste un montant connu.
Ce module ne commite jamais et ne modifie aucune table de l'ancien parcours.
"""
import hashlib
import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP

CENT = Decimal('0.01')
ZERO = Decimal(0)
MOIS = tuple(str(i) for i in range(1, 13))
NATURES = ('salaire', 'depense', 'financement')
MODES = ('manuel', 'mensuel', 'proportionnel')


class InitialRefuse(ValueError):
    """Message français contrôlé, publiable sans détail technique."""


def nombre(value, minimum=None, maximum=Decimal('999999999.99')):
    if value in (None, ''):
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        n = Decimal(str(value).replace(',', '.'))
        if not n.is_finite() or abs(n) > maximum or (minimum is not None and n < minimum):
            raise ValueError
        return n
    except (InvalidOperation, ValueError, TypeError):
        raise InitialRefuse('Nombre invalide ou hors limites.') from None


def euros(value):
    if value is None:
        return None
    if not value.is_finite() or abs(value) > Decimal('999999999999.99'):
        raise InitialRefuse('Montant calculé hors limites : vérifiez les paramètres et l’assiette du taux.')
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def total(values):
    values = list(values)
    return None if any(v is None for v in values) else sum(values, ZERO)


def repartir(value, poids):
    """Répartit exactement les centimes, même les montants négatifs."""
    if value is None:
        return {k: None if p else ZERO for k, p in poids.items()}
    somme = sum(poids.values(), ZERO)
    if somme <= 0:
        raise InitialRefuse('La ventilation doit comporter au moins un poids positif.')
    centimes = int(abs(euros(value)) * 100)
    exact = {k: Decimal(centimes) * p / somme for k, p in poids.items()}
    parts = {k: int(v.to_integral_value(rounding=ROUND_FLOOR)) for k, v in exact.items()}
    ordre = sorted(poids, key=lambda k: (-(exact[k] - parts[k]), str(k)))
    for k in ordre[:centimes - sum(parts.values())]:
        parts[k] += 1
    signe = -1 if value < 0 else 1
    return {k: Decimal(parts[k] * signe) / 100 for k in poids}


def texte(value, limite=4000):
    if not isinstance(value, str) or len(value) > limite:
        raise InitialRefuse('Texte invalide ou trop long.')
    return value.strip()


def compte(value):
    if not isinstance(value, str) or not re.fullmatch(r'[67][0-9]{2,11}', value):
        raise InitialRefuse('Indiquez un compte de charges ou de produits (3 à 12 chiffres).')
    return value


def douze(value, defaut=None, minimum=None, maximum=Decimal('999999999.99')):
    if value is None:
        value = [defaut] * 12
    if not isinstance(value, list) or len(value) != 12:
        raise InitialRefuse('Renseignez exactement douze mois.')
    return [nombre(v, minimum, maximum) for v in value]


def normaliser_ligne(data, secteurs):
    if not isinstance(data, dict):
        raise InitialRefuse('Ligne invalide.')
    # Liste fermée : les futurs liens ne sont jamais acceptés depuis le client.
    d = {k: data.get(k) for k in (
        'libelle', 'nature', 'compte', 'secteurs', 'source', 'note', 'a_revoir',
        'mode', 'annuel', 'poids', 'mois', 'reference', 'salarie_id', 'poste',
        'contrat', 'base', 'brut_mensuel', 'brut_verifie', 'quotite', 'activite',
        'socle', 'point', 'pesee', 'anciennete', 'competence', 'maintien',
        'forfait_cee', 'jours_cee', 'complements', 'taux_charges', 'reference_charges')}
    d['libelle'] = texte(d['libelle'], 200)
    if not d['libelle'] or d['nature'] not in NATURES:
        raise InitialRefuse('Un libellé et une nature de ligne sont requis.')
    d['compte'] = compte(d['compte'])
    if d['nature'] == 'financement' and not d['compte'].startswith('7'):
        raise InitialRefuse('Un financement utilise un compte 7.')
    if d['nature'] != 'financement' and not d['compte'].startswith('6'):
        raise InitialRefuse('Une dépense utilise un compte 6.')
    for key in ('source', 'note'):
        d[key] = texte(d[key] or '')
    if d['a_revoir'] not in (None, True, False) or type(d['a_revoir']) not in (bool, type(None)):
        raise InitialRefuse('Indicateur de révision invalide.')
    d['a_revoir'] = bool(d['a_revoir'])
    if not isinstance(d['secteurs'], dict) or not d['secteurs']:
        raise InitialRefuse('Ventilez la ligne entre les secteurs.')
    parts = {}
    for sid, value in d['secteurs'].items():
        if str(sid) not in secteurs:
            raise InitialRefuse('Secteur absent ou supprimé : revoyez la ventilation.')
        p = nombre(value, ZERO, Decimal(100))
        if p is None or p <= 0:
            raise InitialRefuse('Chaque secteur retenu doit avoir une part positive.')
        parts[str(sid)] = str(p)
    if sum(map(Decimal, parts.values())) != 100:
        raise InitialRefuse('La ventilation sectorielle doit totaliser exactement 100 %.')
    d['secteurs'] = parts
    if d['nature'] == 'salaire':
        if not d['compte'].startswith('641') or d['base'] not in ('brut', 'alisfa', 'cee'):
            raise InitialRefuse('Choisissez une base de rémunération et un compte 641.')
        if d['contrat'] not in ('permanent', 'saisonnier', 'cee') or d['poste'] not in ('occupe', 'vacant'):
            raise InitialRefuse('Précisez le poste et son activité normale.')
        if (d['contrat'] == 'cee') != (d['base'] == 'cee'):
            raise InitialRefuse('Un CEE utilise un forfait journalier et des jours d’activité normale.')
        if d['salarie_id'] in (None, ''):
            d['salarie_id'] = None
        elif isinstance(d['salarie_id'], bool) or not re.fullmatch(r'[0-9]{1,18}', str(d['salarie_id'])) or int(d['salarie_id']) <= 0:
            raise InitialRefuse('Référence salarié invalide.')
        else:
            d['salarie_id'] = str(int(d['salarie_id']))
        if d['poste'] == 'vacant' and d['salarie_id']:
            raise InitialRefuse('Un poste vacant ne désigne pas de salarié.')
        d['quotite'] = _chaine(nombre(d['quotite'], ZERO, Decimal(100)))
        activite = douze(d['activite'], '1', ZERO, Decimal(1))
        if any(v is None for v in activite):
            raise InitialRefuse('Indiquez la fraction d’activité normale de chaque mois.')
        if d['contrat'] == 'permanent' and activite != [Decimal(1)] * 12:
            raise InitialRefuse('Un permanent est prévu sur douze mois, sans absences ou remplacements imprévisibles.')
        d['activite'] = list(map(str, activite))
        d['brut_verifie'] = d['brut_verifie'] is True
        for key in ('brut_mensuel', 'socle', 'point', 'pesee', 'anciennete', 'competence', 'maintien', 'forfait_cee'):
            d[key] = _chaine(nombre(d[key], ZERO))
        d['jours_cee'] = [_chaine(v) for v in douze(d['jours_cee'], None, ZERO, Decimal(31))]
        d['taux_charges'] = _chaine(nombre(d['taux_charges'], ZERO, Decimal(100)))
        d['reference_charges'] = normaliser_reference(d['reference_charges'])
        complements = d['complements'] or []
        if not isinstance(complements, list) or len(complements) > 50:
            raise InitialRefuse('Liste des compléments invalide (50 maximum).')
        d['complements'], vus = [], set()
        for c in complements:
            if not isinstance(c, dict):
                raise InitialRefuse('Complément invalide.')
            libelle = texte(c.get('libelle', ''), 200)
            code = compte(c.get('compte'))
            cle = libelle.casefold()
            if not libelle or cle in vus or code == d['compte'] or not code.startswith('641'):
                raise InitialRefuse('Chaque complément doit être nommé une seule fois, sur un autre compte 641 que la base.')
            vus.add(cle)
            d['complements'].append({'libelle': libelle, 'compte': code,
                                    'mois': [_chaine(v) for v in douze(c.get('mois'))]})
    else:
        if d['compte'].startswith('641'):
            raise InitialRefuse('Renseignez les 641 dans une ligne salarié ou poste pour éviter les doubles comptes.')
        if d['mode'] not in MODES:
            raise InitialRefuse('Choisissez un mode manuel, mensuel ou proportionnel.')
        d['annuel'] = _chaine(nombre(d['annuel']))
        d['poids'] = [_chaine(v) for v in douze(d['poids'], '1', ZERO)]
        if any(v is None for v in d['poids']) or sum(map(Decimal, d['poids'])) <= 0:
            raise InitialRefuse('Les poids mensuels doivent être connus, positifs ou nuls, avec un total positif.')
        d['mois'] = [_chaine(v) for v in douze(d['mois'])]
        d['reference'] = normaliser_reference(d['reference'])
    return d


def normaliser_reference(value):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise InitialRefuse('Référence de taux invalide.')
    d = {k: texte(value.get(k) or '', 1000) for k in ('source', 'assiette', 'perimetre', 'verification')}
    d['annee'] = texte(str(value.get('annee') or ''), 4)
    if d['annee'] and not re.fullmatch(r'(19|20|21|22)\d{2}', d['annee']):
        raise InitialRefuse('Année de référence invalide.')
    if d['verification']:
        try:
            date.fromisoformat(d['verification'])
        except ValueError:
            raise InitialRefuse('Date de vérification invalide.') from None
    d['complete_comparable'] = value.get('complete_comparable') is True
    for key in ('numerateur', 'denominateur'):
        d[key] = _chaine(nombre(value.get(key), ZERO if key == 'denominateur' else None))
    return d


def reference_complete(ref, annee, ratio=False):
    ok = (all(ref.get(k) for k in ('source', 'annee', 'assiette', 'perimetre', 'verification'))
          and int(ref['annee']) < annee and ref.get('complete_comparable'))
    if ratio:
        ok = ok and ref.get('numerateur') is not None and nombre(ref.get('denominateur')) not in (None, ZERO)
    return bool(ok)


def _chaine(v):
    return None if v is None else str(v)


def serialisable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: serialisable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialisable(v) for v in value]
    return value


def calculer(annee, hypotheses, lignes, secteurs, premiers=None, premiers_charges=None):
    """Consolide à partir des seules hypothèses enregistrées, jamais du réel/RH.

    premiers est fourni par l'adaptateur du budget existant : {secteur: 641}.
    Les 645–648 saisis restent mémorisés quand l'option individuelle est active.
    """
    option = hypotheses.get('taux_individuels', False)
    if type(option) is not bool:
        raise InitialRefuse('Option des taux individuels invalide.')
    calculs, ecritures, alertes = [], [], []
    secteurs = dict(secteurs)
    for l in lignes:
        for sid in l['donnees']['secteurs']:
            if sid not in secteurs:
                secteurs[sid] = 'Secteur supprimé'
                alertes.append({'id': l['id'], 'libelle': l['donnees']['libelle'],
                                'message': 'Secteur supprimé : corrigez la ventilation avant tout report.'})
    comptes = {sid: set() for sid in secteurs}
    for l in lignes:
        d = l['donnees']
        for sid in d['secteurs']:
            comptes[sid].add(d['compte'])
            for c in d.get('complements') or []:
                comptes[sid].add(c['compte'])
    bases, charges = {}, {}
    for sid, codes in comptes.items():
        bases[sid] = (premiers or {}).get(sid) or next(iter(sorted(c for c in codes if c.startswith('641'))), None)
        charges[sid] = (premiers_charges or {}).get(sid) or next(iter(sorted(c for c in codes if c.startswith('645'))), None)

    def ajouter(l, code, valeurs, explication):
        d = l['donnees']
        resultat = {'id': l['id'], 'libelle': d['libelle'], 'compte': code,
                    'mois': valeurs, 'total': total(valeurs), 'explication': explication,
                    'source': d['source'], 'note': d['note'],
                    'updated_at': l.get('updated_at'), 'secteurs': {}}
        poids = {sid: Decimal(p) for sid, p in d['secteurs'].items()}
        for i, v in enumerate(valeurs):
            for sid, part in repartir(v, poids).items():
                resultat['secteurs'].setdefault(sid, [ZERO] * 12)[i] = part
                ecritures.append((sid, code, i, part))
        calculs.append(resultat)
        return resultat

    def signaler(l, message):
        alertes.append({'id': l['id'], 'libelle': l['donnees']['libelle'], 'message': message})

    salaries, bruts = [], {sid: [ZERO] * 12 for sid in secteurs}
    for l in lignes:
        d = l['donnees']
        if d['a_revoir']:
            signaler(l, 'Ligne marquée à revoir.')
        if not d['source'] or not d['note']:
            signaler(l, 'Source ou justification manquante.')
        if d['nature'] != 'salaire':
            continue
        if any(d['compte'] != bases[sid] for sid in d['secteurs']):
            signaler(l, 'Le brut de base doit utiliser le premier 641 de chaque secteur retenu.')
        quotite = nombre(d['quotite'])
        base = None
        if d['base'] == 'brut':
            if d['brut_verifie']:
                base = nombre(d['brut_mensuel'])
            else:
                signaler(l, 'Vérifiez le brut mensuel à la quotité saisie, hors compléments listés séparément.')
            formule = ('Brut mensuel vérifié à la quotité saisie × fraction d’activité normale ; compléments séparés. '
                       f"Base mensuelle : {d['brut_mensuel'] or 'à compléter'} €, quotité : {d['quotite'] or 'à compléter'} %.")
        elif d['base'] == 'alisfa':
            vals = [nombre(d[k]) for k in ('socle', 'point', 'pesee', 'anciennete', 'competence', 'maintien')]
            if quotite is not None and all(v is not None for v in vals):
                socle, point, pesee, anciennete, competence, maintien = vals
                base = ((socle + pesee * point) * quotite / 100 + (anciennete + competence) * point) / 12 + maintien
            formule = '((Socle annuel + pesée × point) × quotité / 100 + (ancienneté + compétences) × point) / 12 + maintien mensuel ; puis activité.'
            formule += ' Paramètres : ' + ', '.join(f"{k} = {d[k] if d[k] is not None else 'à compléter'}" for k in (
                'socle', 'point', 'pesee', 'quotite', 'anciennete', 'competence', 'maintien')) + '.'
        else:
            formule = f"Forfait CEE de {d['forfait_cee'] or 'à compléter'} € par jour × jours mensuels d’activité normale."
        if quotite is None:
            signaler(l, 'Quotité non renseignée.')
        if d['base'] == 'cee':
            forfait = nombre(d['forfait_cee'])
            valeurs = [euros(forfait * j) if forfait is not None and j is not None else None for j in map(nombre, d['jours_cee'])]
        else:
            valeurs = [ZERO if Decimal(a) == 0 else euros(base * Decimal(a)) if base is not None else None for a in d['activite']]
        ajouter(l, d['compte'], valeurs, formule)
        brut = list(valeurs)
        for c in d['complements']:
            vals = [euros(nombre(v)) for v in c['mois']]
            ajouter(l, c['compte'], vals, 'Complément manuel « ' + c['libelle'] + ' », une seule fois dans le brut global.')
            brut = [total([b, v]) for b, v in zip(brut, vals)]
        if any(v is not None and v < 0 for v in brut):
            signaler(l, 'Le brut global mensuel ne peut pas être négatif. Vérifiez les compléments.')
        salaries.append((l, brut))

    # Même somme des 641 ventilés que celle affichée, centime par centime.
    for sid, code, i, v in ecritures:
        bruts[sid][i] = total([bruts[sid][i], v])

    for l in lignes:
        d = l['donnees']
        if d['nature'] == 'salaire':
            continue
        if option and d['compte'].startswith(('645', '646', '647', '648')):
            ajouter(l, d['compte'], [ZERO] * 12, 'Montants conservés en saisie ; regroupement des taux individuels sur le premier 645.')
            continue
        if d['mode'] == 'manuel':
            vals = list(repartir(nombre(d['annuel']), {m: Decimal(p) for m, p in zip(MOIS, d['poids'])}).values())
            formule = (f"Montant annuel manuel : {d['annuel'] if d['annuel'] is not None else 'à compléter'} €. "
                       'Répartition suivant les douze poids ; solde des centimes distribué sans perte.')
        elif d['mode'] == 'mensuel':
            vals = [euros(nombre(v)) for v in d['mois']]
            formule = 'Somme des douze montants mensuels saisis, sans reprise du réalisé.'
        else:
            ref = d['reference']
            ratio = nombre(ref.get('numerateur')) / nombre(ref['denominateur']) if reference_complete(ref, annee, True) else None
            if ratio is None:
                signaler(l, 'Référence annuelle complète et comparable à renseigner (2025 proposée), avec numérateur et assiette non nulle.')
            # Une ligne proportionnelle appartient à UN secteur : évite une double
            # ventilation d'une assiette déjà sectorisée.
            if len(d['secteurs']) != 1:
                raise InitialRefuse('Créez une ligne proportionnelle par secteur, à 100 %, pour une assiette non ambiguë.')
            sid = next(iter(d['secteurs']))
            vals = [euros(v * ratio) if v is not None and ratio is not None else None for v in bruts[sid]]
            formule = 'Brut global mensuel du secteur × (numérateur annuel / assiette annuelle de référence).'
            formule += (f" Référence {ref.get('annee') or 'à compléter'} : {ref.get('numerateur') or 'à compléter'}"
                        f" / {ref.get('denominateur') or 'à compléter'} ; source : {ref.get('source') or 'à compléter'} ;"
                        f" périmètre : {ref.get('perimetre') or 'à compléter'} ; vérifiée le {ref.get('verification') or 'à compléter'}.")
        ajouter(l, d['compte'], vals, formule)

    if option:
        for l, brut in salaries:
            d = l['donnees']
            taux = nombre(d['taux_charges'])
            if taux is None or not reference_complete(d['reference_charges'], annee):
                signaler(l, 'Taux individuel ou provenance annuelle complète et comparable à vérifier.')
                taux = None
            poids = {sid: Decimal(p) for sid, p in d['secteurs'].items()}
            # Ventiler d'abord le coût de chaque personne conserve le centime global.
            valeurs = [euros(v * taux / 100) if v is not None and taux is not None else None for v in brut]
            for sid in poids:
                code = charges[sid]
                if code is None:
                    signaler(l, 'Ajoutez une ligne sur le premier compte 645 de chaque secteur pour les charges individuelles.')
                    continue
                parts = [repartir(v, poids)[sid] for v in valeurs]
                copie = {**l, 'donnees': {**d, 'secteurs': {sid: '100'}}}
                ref = d['reference_charges']
                ajouter(copie, code, parts,
                        f"Brut global de la personne, compléments inclus, × {d['taux_charges'] or 'à compléter'} %. "
                        f"Référence {ref.get('annee') or 'à compléter'} : {ref.get('source') or 'à compléter'}, "
                        f"{ref.get('perimetre') or 'à compléter'}, vérifiée le {ref.get('verification') or 'à compléter'}. Comptes 63 inchangés.")

    ventilation = {}
    for sid, code, mois, value in ecritures:
        target = ventilation.setdefault(sid, {}).setdefault(code, [ZERO] * 12)
        target[mois] = total([target[mois], value])
    def synthese(comptes_mois):
        out = {}
        for nature, prefixe in [('charges', '6'), ('produits', '7')]:
            out[nature] = [total(vals[m] for c, vals in comptes_mois.items() if c.startswith(prefixe)) for m in range(12)]
            out[nature + '_annuel'] = total(out[nature])
        out['resultat'] = [p - c if p is not None and c is not None else None for p, c in zip(out['produits'], out['charges'])]
        out['resultat_annuel'] = total(out['resultat'])
        return out
    general = {}
    for comptes_mois in ventilation.values():
        for c, vals in comptes_mois.items():
            general[c] = [total([a, b]) for a, b in zip(general.get(c, [ZERO] * 12), vals)]
    for l in calculs:
        if l['total'] is None:
            signaler({'id': l['id'], 'donnees': l}, 'Montant inconnu : complétez les entrées du calcul.')
    return {'lignes': calculs, 'ventilation': ventilation,
            'secteurs': {sid: synthese(c) for sid, c in ventilation.items()},
            'general': synthese(general), 'alertes': alertes,
            'complet': bool(lignes) and not alertes}


def charger(conn, annee):
    row = conn.execute('SELECT * FROM budget_initial_hypotheses WHERE annee=?', (annee,)).fetchone()
    lignes = [dict(r) for r in conn.execute('SELECT * FROM budget_initial_lignes WHERE annee=? ORDER BY id', (annee,))]
    for l in lignes:
        l['donnees'] = json.loads(l['donnees'])
    return {'annee': annee, 'revision': row['revision'] if row else 0,
            'hypotheses': json.loads(row['donnees']) if row else {'note': '', 'taux_individuels': False},
            'updated_at': row['updated_at'] if row else None, 'lignes': lignes}


def verifier_revision(conn, annee, revision):
    if type(revision) is not int or revision != charger(conn, annee)['revision']:
        raise InitialRefuse('La construction a changé. Rechargez la page avant d’enregistrer.')


def enregistrer(conn, annee, revision, uid, secteurs, hypotheses=None, ligne=None, supprimer=None):
    verifier_revision(conn, annee, revision)
    if type(annee) is not int or not 1900 <= annee <= 2200:
        raise InitialRefuse('Année invalide.')
    conn.execute('INSERT OR IGNORE INTO budget_initial_hypotheses (annee) VALUES (?)', (annee,))
    if hypotheses is not None:
        if not isinstance(hypotheses, dict) or type(hypotheses.get('taux_individuels')) is not bool:
            raise InitialRefuse('Hypothèses invalides.')
        h = {'note': texte(hypotheses.get('note', '')), 'taux_individuels': hypotheses['taux_individuels']}
        conn.execute('UPDATE budget_initial_hypotheses SET donnees=? WHERE annee=?', (json.dumps(h, ensure_ascii=False), annee))
    if ligne is not None:
        if not isinstance(ligne, dict):
            raise InitialRefuse('Ligne invalide.')
        identifiant = ligne.get('id')
        if identifiant is not None and (not isinstance(identifiant, str) or len(identifiant) > 36):
            raise InitialRefuse('Identifiant de ligne invalide.')
        if identifiant and not conn.execute('SELECT 1 FROM budget_initial_lignes WHERE id=? AND annee=?', (identifiant, annee)).fetchone():
            raise InitialRefuse('Ligne absente de cette année.')
        d = normaliser_ligne(ligne.get('donnees'), secteurs)
        if d.get('salarie_id'):
            if not conn.execute('SELECT 1 FROM users WHERE id=?', (d['salarie_id'],)).fetchone():
                raise InitialRefuse('Salarié introuvable.')
            for existante in charger(conn, annee)['lignes']:
                if existante['id'] != identifiant and existante['donnees'].get('salarie_id') == d['salarie_id']:
                    raise InitialRefuse('Ce salarié possède déjà une ligne. Modifiez sa ventilation pour éviter un doublon.')
        if not identifiant and len(charger(conn, annee)['lignes']) >= 2000:
            raise InitialRefuse('La construction est limitée à 2 000 lignes par année.')
        identifiant = identifiant or str(uuid.uuid4())
        conn.execute('''INSERT INTO budget_initial_lignes (id, annee, donnees, updated_by)
            VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET donnees=excluded.donnees,
            updated_by=excluded.updated_by, updated_at=CURRENT_TIMESTAMP''',
            (identifiant, annee, json.dumps(d, ensure_ascii=False), uid))
    if supprimer is not None:
        if not isinstance(supprimer, str) or conn.execute('DELETE FROM budget_initial_lignes WHERE id=? AND annee=?', (supprimer, annee)).rowcount != 1:
            raise InitialRefuse('Ligne absente de cette année.')
    conn.execute('''UPDATE budget_initial_hypotheses SET revision=revision+1,
        updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE annee=?''', (uid, annee))


def preparer_report(conn, annee, calcul):
    """Proposition lisible, sans mutation ; l'empreinte inclut les anciens montants.

    Un report ne prend jamais possession d'une saisie déjà renseignée. Un
    ancien report modifié à la main est également conservé, même après recalcul.
    Les comptes automatiques restent pilotés par le parcours existant.
    """
    precedents = {(str(r['secteur_id']), r['compte_num']): r['montant'] for r in conn.execute(
        'SELECT * FROM budget_initial_reports WHERE annee=?', (annee,))}
    valeurs = {(sid, c): total(vals) for sid, comptes in calcul['ventilation'].items() for c, vals in comptes.items()}
    propositions = []
    for sid, code in sorted(set(valeurs) | set(precedents)):
        ancien = conn.execute('''SELECT valeur_temp, valeur_def, commentaire, updated_at FROM budget_prev_saisies
            WHERE type_budget='initial' AND annee=? AND secteur_id=? AND compte_num=?''', (annee, sid, code)).fetchone()
        mode = conn.execute('''SELECT mode FROM budget_modes_comptes WHERE type_budget='initial'
            AND annee=? AND secteur_id=? AND compte_num=?''', (annee, sid, code)).fetchone()
        simulation = conn.execute('''SELECT donnees FROM budget_paie_simulations
            WHERE type_budget='initial' AND annee=? AND secteur_id=?''', (annee, sid)).fetchone()
        donnees_sim = json.loads(simulation['donnees']) if simulation else {}
        avant = nombre(ancien['valeur_def']) if ancien else None
        temp = nombre(ancien['valeur_temp']) if ancien else None
        precedent = nombre(precedents.get((sid, code)))
        valeur = valeurs.get((sid, code), ZERO)
        motif = ''
        if not calcul['complet']:
            motif = 'Construction incomplète ou lignes à revoir.'
        elif mode and mode['mode'] != 'manuel':
            motif = 'Mode automatique existant conservé.'
        elif donnees_sim.get('utiliser_taux_charges') and code.startswith(('641', '645', '646', '647', '648')):
            motif = 'Simulation existante avec taux individuels conservée.'
        elif (avant is not None or temp is not None) and (precedent is None or avant != precedent or temp != precedent):
            motif = 'Saisie ou simulation manuelle existante conservée.'
        propositions.append({'secteur_id': sid, 'compte': code, 'avant': avant, 'montant': valeur,
                             'motif': motif, 'possible': not motif, 'retire': (sid, code) not in valeurs,
                             'ancien': dict(ancien) if ancien else None})
    brut = json.dumps(serialisable(propositions), sort_keys=True, ensure_ascii=False)
    return propositions, hashlib.sha256(brut.encode()).hexdigest()


def reporter(conn, annee, revision, uid, calcul, reference):
    verifier_revision(conn, annee, revision)
    propositions, empreinte = preparer_report(conn, annee, calcul)
    if not isinstance(reference, str) or reference != empreinte:
        raise InitialRefuse('Les montants du budget ont changé. Rechargez et vérifiez le report proposé.')
    if not calcul['complet']:
        raise InitialRefuse('Complétez la construction et les lignes à revoir avant le report.')
    reportes = 0
    for p in propositions:
        if not p['possible']:
            continue
        montant = str(euros(p['montant']))
        conn.execute('''INSERT INTO budget_prev_saisies
            (type_budget, annee, secteur_id, compte_num, valeur_temp, valeur_def, updated_by)
            VALUES ('initial', ?, ?, ?, ?, ?, ?) ON CONFLICT(type_budget, annee, secteur_id, compte_num)
            DO UPDATE SET valeur_temp=excluded.valeur_temp, valeur_def=excluded.valeur_def,
            updated_by=excluded.updated_by, updated_at=CURRENT_TIMESTAMP''',
            (annee, p['secteur_id'], p['compte'], montant, montant, uid))
        conn.execute('''INSERT INTO budget_initial_reports (annee, secteur_id, compte_num, montant, updated_by)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(annee, secteur_id, compte_num)
            DO UPDATE SET montant=excluded.montant, updated_by=excluded.updated_by, updated_at=CURRENT_TIMESTAMP''',
            (annee, p['secteur_id'], p['compte'], montant, uid))
        reportes += 1
    return reportes
