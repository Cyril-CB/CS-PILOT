"""Gel et suivi annuel déterministes. L'appelant détient la transaction d'écriture.

Les montants sont des chaînes décimales dans les archives ; aucun calcul RH ou
aucune lecture d'une source métier n'intervient après le gel.
"""
import hashlib
import io
import json
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.sax.saxutils import escape

from budget_initial import serialisable


class SuiviRefuse(ValueError):
    """Message métier contrôlé, sans données techniques."""


def encoder(value):
    return json.dumps(serialisable(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def empreinte(value):
    return hashlib.sha256(encoder(value).encode()).hexdigest()


def montant(value):
    if value is None or value == '':
        return None
    try:
        if isinstance(value, bool) or len(str(value)) > 40:
            raise ValueError
        n = Decimal(str(value).replace(',', '.'))
        if not n.is_finite() or abs(n) > Decimal('999999999.99') or n.as_tuple().exponent < -10:
            raise ValueError
        return n.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    except (ValueError, InvalidOperation):
        raise SuiviRefuse('Montant invalide ou hors limites.') from None


def texte(value, limite=4000):
    if not isinstance(value, str) or len(value) > limite:
        raise SuiviRefuse('Texte invalide ou trop long.')
    return value.strip()


def verifier_initial(conn, annee):
    """Copie les définitifs une seule fois, avec les explications disponibles."""
    from blueprints.budget_initial import _calcul
    from blueprints.budget import _compute_budget_previsionnel
    from budget_initial import preparer_report
    etat, secteurs, _, calcul = _calcul(conn, annee)
    reports, _ = preparer_report(conn, annee, calcul)
    rapprochement = {(p['secteur_id'], p['compte']): p for p in reports}
    lignes, alertes, blocages = [], [], []
    for sid, nom in secteurs.items():
        rows = _compute_budget_previsionnel(conn, 'initial', annee, int(sid))['rows']
        codes = {r['compte_num'] for r in rows}
        for code in calcul['ventilation'].get(sid, {}):
            if code not in codes:
                rows.append({'compte_num': code, 'libelle': code, 'def': None,
                             'temp': None, 'a_recalculer': False, 'commentaire': ''})
        if not rows:
            blocages.append(f'{nom} : aucun compte vérifié. Renseignez les comptes, y compris les zéros explicites.')
        for row in rows:
            code = row['compte_num']
            p = rapprochement.get((sid, code), {})
            retenu = montant(row['def'])
            proposition = montant(p.get('montant', row.get('temp')))
            etats = []
            if retenu is None:
                blocages.append(f'{nom} / {code} : montant définitif manquant.')
                etats.append('À compléter')
            if row.get('a_recalculer'):
                blocages.append(f'{nom} / {code} : calcul à actualiser dans le tableau budgétaire.')
                etats.append('Calcul à actualiser')
            if proposition != retenu:
                etats.append('Proposition différente du retenu')
            if p.get('motif'):
                etats.append(p['motif'])
            elif not p:
                etats.append('Montant du tableau conservé')
            lignes.append({'id': f'{annee}:{sid}:{code}', 'secteur_id': sid, 'secteur': nom,
                           'compte': code, 'libelle': row['libelle'], 'montant': retenu,
                           'proposition': proposition, 'commentaire': row.get('commentaire', ''),
                           'controle': etats})
    if etat['lignes'] and not calcul['complet']:
        blocages.extend(a['message'] for a in calcul['alertes'])
    if not lignes:
        blocages.append('Aucun montant initial à figer.')
    # Capture les méthodes, taux et simulations historiques sans modifier le lot 1.
    sources = {}
    for table in ('budget_prev_saisies', 'budget_parametres', 'budget_modes_comptes',
                  'budget_paie_simulations', 'budget_ps_simulations', 'budget_fiches_travail'):
        sources[table] = [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} WHERE annee=? AND type_budget='initial' ORDER BY secteur_id", (annee,))]
    # Les éléments détaillés ne deviennent des bases d'écart que si leur somme
    # concorde avec le définitif retenu. Une divergence manuelle ne s'invente pas
    # une ventilation : le compte entier reste alors le seul lien disponible.
    elements = {}
    for detail in calcul['lignes']:
        for sid, mois in detail['secteurs'].items():
            parent = f"{annee}:{sid}:{detail['compte']}"
            ligne = next((l for l in lignes if l['id'] == parent), None)
            proposition = rapprochement.get((sid, detail['compte']), {}).get('montant')
            if ligne is None or ligne['montant'] is None or montant(proposition) != ligne['montant'] or any(v is None for v in mois):
                continue
            ident = f"{parent}:{detail['id']}"
            element = elements.setdefault(ident, {'id': ident, 'parent_id': parent,
                'ligne_initiale_id': detail['id'], 'secteur_id': sid,
                'secteur': secteurs[sid], 'compte': detail['compte'],
                'libelle': detail['libelle'], 'montant': Decimal(0)})
            element['montant'] += sum((montant(v) for v in mois), Decimal(0))
    contenu = serialisable({'annee': annee, 'secteurs': secteurs, 'lignes': lignes,
        'construction': etat, 'calcul': calcul, 'sources': sources, 'elements': list(elements.values()),
        'alertes': alertes, 'blocages': blocages})
    return {**contenu, 'empreinte': empreinte(contenu)}


def figer(conn, annee, reference, auteur, motif, confirme):
    if confirme is not True:
        raise SuiviRefuse('Confirmez la vérification de l’exercice complet et de tous les secteurs.')
    motif = texte(motif, 500)
    if not motif:
        raise SuiviRefuse('Indiquez le motif du gel ou de sa correction.')
    controle = verifier_initial(conn, annee)
    if reference != controle['empreinte']:
        raise SuiviRefuse('Le budget a changé. Rechargez et vérifiez avant de figer.')
    if controle['blocages']:
        raise SuiviRefuse('Le gel est bloqué : complétez les montants et actualisez les calculs signalés.')
    precedent = conn.execute('SELECT * FROM budget_gels WHERE annee=? ORDER BY version DESC LIMIT 1', (annee,)).fetchone()
    if precedent and precedent['empreinte'] == reference:
        raise SuiviRefuse('Cette référence est déjà figée.')
    ident = str(uuid.uuid4())
    conn.execute('INSERT INTO budget_gels (id,annee,version,donnees,empreinte,motif,auteur) VALUES (?,?,?,?,?,?,?)',
                 (ident, annee, precedent['version'] + 1 if precedent else 1, encoder(controle), reference, motif, auteur))
    # Une correction crée une version, mais ne déplace JAMAIS le suivi existant.
    conn.execute('INSERT OR IGNORE INTO budget_suivis (annee,gel_id) VALUES (?,?)', (annee, ident))
    return ident


def reference_suivi(conn, annee):
    row = conn.execute('''SELECT s.revision, g.* FROM budget_suivis s
        JOIN budget_gels g ON g.id=s.gel_id WHERE s.annee=?''', (annee,)).fetchone()
    if row is None:
        raise SuiviRefuse('Figez d’abord une référence annuelle complète.')
    return dict(row)


def historiques(conn, annee):
    return [{**dict(r), 'donnees': json.loads(r['donnees'])} for r in conn.execute(
        'SELECT * FROM budget_evenements WHERE annee=? ORDER BY revision', (annee,))]


def derniers(events):
    result = {}
    for event in events:
        if event['donnees']['operation'] == 'ajustement':
            result[event['element_id']] = event
    return result


def _revision(ref, value):
    if type(value) is not int or value != ref['revision']:
        raise SuiviRefuse('Page périmée : rechargez le suivi avant de réessayer.')


def _ajouter_evenement(conn, ref, ident, donnees, auteur):
    revision = ref['revision'] + 1
    conn.execute('INSERT INTO budget_evenements (annee,element_id,revision,donnees,auteur) VALUES (?,?,?,?,?)',
                 (ref['annee'], ident, revision, encoder(donnees), auteur))
    conn.execute('UPDATE budget_suivis SET revision=? WHERE annee=?', (revision, ref['annee']))


def ajuster(conn, annee, revision, auteur, data, ident=None, annuler=False, source=None):
    """Une révision remplace l'impact. `source` est réservé au futur adaptateur.

    Un adaptateur devra réutiliser ident, jamais créer un second événement métier.
    Aucune route de ce lot ne peut fournir source ni appeler un module externe.
    """
    ref = reference_suivi(conn, annee)
    _revision(ref, revision)
    actifs = derniers(historiques(conn, annee))
    ancien = actifs.get(ident) if isinstance(ident, str) else None
    if ident and ancien is None:
        raise SuiviRefuse('Ajustement introuvable dans cet exercice.')
    if ancien and ancien['donnees'].get('source_type') != 'manuel' and source is None:
        raise SuiviRefuse('Cet élément est piloté par sa source.')
    if annuler:
        if not ancien or ancien['donnees']['annule']:
            raise SuiviRefuse('Ajustement absent ou déjà annulé.')
        d = {**ancien['donnees'], 'annule': True}
    else:
        if not isinstance(data, dict):
            raise SuiviRefuse('Ajustement invalide.')
        d = {k: texte(data.get(k, ''), 500 if k == 'libelle' else 4000)
             for k in ('libelle', 'note', 'justificatif')}
        if not d['libelle']:
            raise SuiviRefuse('Renseignez un libellé.')
        nature = data.get('nature')
        compte = texte(data.get('compte', ''), 20)
        sid = str(data.get('secteur_id', ''))
        contenu = json.loads(ref['donnees'])
        if nature not in ('charge', 'recette') or not compte.isdigit() or not compte.startswith('6' if nature == 'charge' else '7'):
            raise SuiviRefuse('Choisissez un compte de classe 6 pour une charge ou 7 pour une recette.')
        if sid not in contenu['secteurs']:
            raise SuiviRefuse('Secteur absent de la référence annuelle.')
        comptes_figes = {l['compte'] for l in contenu['lignes']}
        if compte not in comptes_figes and not conn.execute('SELECT 1 FROM plan_comptable_general WHERE compte_num=?', (compte,)).fetchone():
            raise SuiviRefuse('Choisissez un compte du plan général.')
        try:
            debut, fin = date.fromisoformat(data.get('debut', '')), date.fromisoformat(data.get('fin', ''))
            if debut.year != annee or fin.year != annee or debut > fin:
                raise ValueError
        except (ValueError, TypeError):
            raise SuiviRefuse('La période doit appartenir à l’exercice, dans l’ordre début puis fin.') from None
        valeur = montant(data.get('montant'))
        etat = data.get('etat')
        if etat not in ('estime', 'confirme', 'a_completer'):
            raise SuiviRefuse('État invalide.')
        lien = texte(data.get('initial_id', ''), 150)
        initial = next((l for l in contenu['lignes'] + contenu['elements'] if l['id'] == lien), None)
        if valeur is not None and valeur < 0 and not lien:
            raise SuiviRefuse('Saisissez un montant positif pour un élément nouveau ; la nature détermine le signe de l’impact.')
        if lien and (initial is None or initial['secteur_id'] != sid or initial['compte'] != compte):
            raise SuiviRefuse('Le lien prévu doit appartenir au même secteur et au même compte.')
        for cle, event in actifs.items():
            other = event['donnees']
            other_base = next((l for l in contenu['lignes'] + contenu['elements'] if l['id'] == other['initial_id']), None)
            chevauche = lien and other_base and (other['initial_id'] == lien or
                other_base.get('parent_id') == lien or (initial and initial.get('parent_id') == other['initial_id']))
            if cle != ident and not other['annule'] and chevauche:
                raise SuiviRefuse('Ce montant prévu est déjà suivi. Modifiez son ajustement pour éviter un double impact.')
        if ancien and (sid != ancien['donnees']['secteur_id'] or compte != ancien['donnees']['compte']):
            raise SuiviRefuse('Pour changer le secteur ou le compte, annulez puis créez un nouvel ajustement.')
        d.update(operation='ajustement', nature=nature, compte=compte, secteur_id=sid,
                 debut=debut.isoformat(), fin=fin.isoformat(), montant=valeur,
                 etat='a_completer' if valeur is None else etat, initial_id=lien,
                 annule=False, source_type='manuel', source_id=None, remplace_revision=None)
        if source is not None:
            if not ancien or not isinstance(source, dict) or source.get('type') not in ('subvention', 'facture', 'contrat', 'ij'):
                raise SuiviRefuse('Rattachement de source invalide.')
            source_id = texte(source.get('id', ''), 200)
            if not source_id:
                raise SuiviRefuse('Identifiant de source manquant.')
            if ancien['donnees']['source_type'] != 'manuel' and (source['type'], source_id) != (
                    ancien['donnees']['source_type'], ancien['donnees']['source_id']):
                raise SuiviRefuse('La source stable d’un élément déjà raccordé ne peut pas être remplacée.')
            for cle, event in actifs.items():
                other = event['donnees']
                if cle != ident and other.get('source_type') == source['type'] and other.get('source_id') == source_id:
                    raise SuiviRefuse('Cette source est déjà rattachée à un élément stable.')
            d.update(source_type=source['type'], source_id=source_id, remplace_revision=ancien['revision'])
    ident = ident or str(uuid.uuid4())
    _ajouter_evenement(conn, ref, ident, d, auteur)
    return ident


def changer_reference(conn, annee, revision, gel_id, auteur, motif):
    ref = reference_suivi(conn, annee)
    _revision(ref, revision)
    cible = conn.execute('SELECT * FROM budget_gels WHERE id=? AND annee=?', (gel_id, annee)).fetchone()
    motif = texte(motif, 500)
    if not cible or cible['id'] == ref['id'] or not motif:
        raise SuiviRefuse('Choisissez une autre version du même exercice et indiquez le motif.')
    contenu = json.loads(cible['donnees'])
    comptes = {l['id'] for l in contenu['lignes'] + contenu['elements']}
    for e in derniers(historiques(conn, annee)).values():
        d = e['donnees']
        if not d['annule'] and (d['secteur_id'] not in contenu['secteurs'] or (d['initial_id'] and d['initial_id'] not in comptes)):
            raise SuiviRefuse('La nouvelle référence ne couvre pas tous les ajustements. Annulez les éléments concernés avant de changer.')
    _ajouter_evenement(conn, ref, str(uuid.uuid4()), {'operation': 'reference', 'avant': ref['id'],
                      'apres': gel_id, 'motif': motif}, auteur)
    conn.execute('UPDATE budget_suivis SET gel_id=? WHERE annee=?', (gel_id, annee))


def suivi(conn, annee, secteur_id=None, confidentiel=True):
    ref = reference_suivi(conn, annee)
    contenu = json.loads(ref['donnees'])
    sid = str(secteur_id) if secteur_id is not None else None
    secteurs = {s: n for s, n in contenu['secteurs'].items() if sid is None or s == sid}
    if sid is not None and sid not in secteurs:
        raise SuiviRefuse('Secteur absent de cette référence.')
    lignes = [dict(l) for l in contenu['lignes'] if l['secteur_id'] in secteurs]
    base = {l['id']: l for l in contenu['lignes'] + contenu['elements']}
    evenements = historiques(conn, annee)
    details, incomplets, rubriques = [], 0, {}
    initial = sum((montant(l['montant']) * (-1 if l['compte'].startswith('6') else 1) for l in lignes), Decimal(0))
    impact = Decimal(0)
    for ident, e in derniers(evenements).items():
        d = e['donnees']
        if d['secteur_id'] not in secteurs:
            continue
        prevu = montant(base[d['initial_id']]['montant']) if d['initial_id'] in base else Decimal(0)
        courant = montant(d['montant'])
        delta = Decimal(0) if d['annule'] else None if courant is None else (courant - prevu) * (-1 if d['nature'] == 'charge' else 1)
        if not d['annule'] and (delta is None or d['etat'] == 'a_completer'):
            incomplets += 1
        impact += delta or Decimal(0)
        rubrique = rubriques.setdefault(d['compte'][:2], {'impact': Decimal(0), 'incomplet': False})
        rubrique['impact'] += delta or Decimal(0)
        rubrique['incomplet'] |= not d['annule'] and (delta is None or d['etat'] == 'a_completer')
        historique = [dict(h) for h in evenements if h['element_id'] == ident]
        detail = {**d, 'id': ident, 'revision': e['revision'], 'date': e['date'], 'auteur': e['auteur'],
                  'prevu': prevu, 'courant': courant, 'impact': delta, 'historique': historique}
        if not confidentiel:
            # Aucun texte libre, auteur ni détail RH n'est exposé aux responsables,
            # y compris dans l'historique et les PDF.
            detail.update(libelle='Ajustement ' + d['compte'], note='', justificatif='', auteur=None,
                          source_id=None)
            detail['historique'] = [{'revision': h['revision'], 'date': h['date'],
                'donnees': {k: h['donnees'][k] for k in ('montant', 'etat', 'annule', 'source_type')}} for h in historique]
        details.append(detail)
    if not confidentiel:
        lignes = [{k: l[k] for k in ('id', 'secteur_id', 'secteur', 'compte', 'montant')} for l in lignes]
    changements = [e for e in evenements if e['donnees']['operation'] == 'reference'] if confidentiel else []
    return serialisable({'annee': annee, 'secteurs': secteurs, 'secteur_id': sid,
        'gel_id': ref['id'], 'version': ref['version'], 'date_gel': ref['date'], 'revision': ref['revision'],
        'date': evenements[-1]['date'] if evenements else ref['date'], 'initial': initial,
        'impact': impact, 'courant': initial + impact, 'incomplets': incomplets,
        'lignes': lignes, 'elements': [l for l in contenu['elements'] if l['secteur_id'] in secteurs] if confidentiel else [], 'details': details, 'rubriques': rubriques, 'changements': changements,
        'tous_secteurs': contenu['secteurs'] if confidentiel else secteurs,
        'sources': {s: 'Non connectée' for s in ('Subventions', 'Factures', 'Contrats', 'IJ')},
        'construction': contenu['construction'] if confidentiel else None})


def pdf_suivi(data, detail=False):
    """PDF autonome ; les octets sont archivés au moment de l'instantané."""
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    def p(value):
        return Paragraph(escape(str(value)), styles['BodyText'])
    story = [Paragraph('Suivi budgétaire · ' + str(data['annee']), styles['Title']),
             p(f"Instantané {data['instantane_date']} · référence v{data['version']} · révision {data['revision']}"),
             p('Secteurs : ' + ', '.join(data['secteurs'].values())),
             p(f"Résultat initial : {data['initial']} € ; impacts connus : {data['impact']} € ; courant : {data['courant']} €"),
             p(f"Ajustements à compléter : {data['incomplets']}. Les totaux sont provisoires si ce nombre est non nul."),
             p('Sources non connectées : ' + ', '.join(data['sources'])), Spacer(1, 5*mm)]
    rows = [[p('Rubrique'), p('Impact connu (€)')]]
    rows += [[p(k), p(v['impact'] + (' · à compléter' if v['incomplet'] else ''))] for k, v in sorted(data['rubriques'].items())]
    table = Table(rows, colWidths=[80*mm, 90*mm], repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f6')), ('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(table)
    if detail:
        story.append(Paragraph('Montants initiaux retenus', styles['Heading2']))
        for l in data['lignes']:
            story.append(p(f"{l['secteur']} · {l['compte']} : {l['montant']} €"))
        for d in data['details']:
            story += [Paragraph(escape(d['libelle']), styles['Heading2']),
                p(f"{data['secteurs'][d['secteur_id']]} · {d['compte']} · {d['debut']} au {d['fin']} · {d['etat']}"),
                p(f"Prévu {d['prevu']} € · courant {d['courant'] if d['courant'] is not None else 'À compléter'} € · impact {d['impact'] if d['impact'] is not None else 'À compléter'} € · origine {d['source_type']} · annulé : {d['annule']}"),
                p(d['note']), p(d['justificatif'])]
            for h in d['historique']:
                story.append(p(f"Révision {h['revision']} · {h['date']} · {encoder(h['donnees'])}"))
        for e in data['changements']:
            story.append(p('Changement de référence : ' + encoder(e)))
    SimpleDocTemplate(buffer, title='Instantané budgétaire', author='CS-PILOT').build(story)
    return buffer.getvalue()
