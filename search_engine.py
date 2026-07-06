"""
Moteur de la barre de recherche intelligente (tableaux de bord direction /
comptable).

100 % règles (déterministe, testable, sans IA). Une requête est analysée pour
détecter une intention (mot-clé + entité + période) et renvoyer un verdict :

- {'type': 'redirect', 'url': ..., 'label': ...}
- {'type': 'choices',  'prompt': ..., 'options': [{'label','sous_titre','url'}]}
- {'type': 'none',     'message': ..., 'exemples': [...]}

Le module est pur (aucun accès `session`/`request`) : il reçoit `conn`, la
requête, le profil et la date du jour. Les URLs sont construites avec `url_for`
(nécessite un contexte d'application — les tests utilisent
`app.test_request_context()`, comme dashboard_actions.py).
"""
import re
import unicodedata
from flask import url_for

from utils import NOMS_MOIS


# ── Normalisation (minuscules + sans accents) ──

def _normaliser(texte):
    """Minuscule, sans accents, ponctuation → espaces, espaces compactés."""
    if not texte:
        return ''
    nfkd = unicodedata.normalize('NFKD', str(texte))
    sans_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
    minus = sans_accents.lower()
    # Remplacer tout ce qui n'est pas alphanumérique par une espace.
    nettoye = re.sub(r"[^a-z0-9]+", ' ', minus)
    return re.sub(r'\s+', ' ', nettoye).strip()


# Mois : nom normalisé → numéro (Janvier→1 … Décembre→12, + variantes courantes).
_MOIS_NUM = {}
for _i, _nom in enumerate(NOMS_MOIS):
    if _nom:
        _MOIS_NUM[_normaliser(_nom)] = _i
_MOIS_NUM.update({'fevrier': 2, 'aout': 8, 'decembre': 12})  # sécurité sans accents


# ── Période (mois / année / relatifs) ──

def _extraire_periode(tokens, today):
    """Extrait mois/année (explicites ou relatifs) et retourne les tokens restants.

    Retourne (mois, annee, annee_explicite, reste_tokens). `mois`/`annee` valent
    None s'ils ne sont pas déterminés (le caller applique alors des défauts).
    """
    mois = None
    annee = None
    annee_explicite = False
    reste = []

    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        suivant = tokens[i + 1] if i + 1 < n else ''

        # Relatifs multi-mots
        if t == 'mois' and suivant == 'dernier':
            m = today.month - 1 or 12
            y = today.year - 1 if today.month == 1 else today.year
            mois, annee, annee_explicite = m, y, True
            i += 2
            continue
        if t in ('annee', 'année') and suivant in ('derniere', 'dernier'):
            annee, annee_explicite = today.year - 1, True
            i += 2
            continue
        if t == 'ce' and suivant == 'mois':
            mois, annee, annee_explicite = today.month, today.year, True
            i += 2
            continue
        if t == 'cette' and suivant == 'annee':
            annee, annee_explicite = today.year, True
            i += 2
            continue
        if t == 'cette' and suivant == 'semaine':
            mois, annee, annee_explicite = today.month, today.year, True
            i += 2
            continue
        if t.startswith('aujourd'):  # aujourd'hui → aujourdhui / aujourd hui
            if t == 'aujourd' and suivant == 'hui':
                i += 1
            mois, annee, annee_explicite = today.month, today.year, True
            i += 1
            continue

        # Mois nommé
        if t in _MOIS_NUM:
            mois = _MOIS_NUM[t]
            i += 1
            continue
        # Année à 4 chiffres
        if re.fullmatch(r'(19|20)\d{2}', t):
            annee = int(t)
            annee_explicite = True
            i += 1
            continue

        reste.append(t)
        i += 1

    return mois, annee, annee_explicite, reste


# ── Résolveurs d'entités (normalisés, insensibles casse/accents) ──

def _resoudre_fournisseur(conn, terme):
    terme_n = _normaliser(terme)
    if not terme_n:
        return []
    rows = conn.execute(
        'SELECT id, nom, alias1, alias2, code_comptable FROM fournisseurs ORDER BY nom'
    ).fetchall()
    exact, prefixe = [], []
    for r in rows:
        champs = [_normaliser(r[c]) for c in ('nom', 'alias1', 'alias2', 'code_comptable')]
        champs = [c for c in champs if c]
        if terme_n in champs:
            exact.append(r)
        elif any(c.startswith(terme_n) for c in champs):
            prefixe.append(r)
    return exact or prefixe


def _resoudre_secteur(conn, terme):
    terme_n = _normaliser(terme)
    if not terme_n:
        return []
    rows = conn.execute('SELECT id, nom, synonymes FROM secteurs ORDER BY nom').fetchall()
    exact, prefixe = [], []
    for r in rows:
        termes = [_normaliser(r['nom'])]
        for syn in (r['synonymes'] or '').split(','):
            syn_n = _normaliser(syn)
            if syn_n:
                termes.append(syn_n)
        if terme_n in termes:
            exact.append(r)
        elif any(t.startswith(terme_n) for t in termes):
            prefixe.append(r)
    return exact or prefixe


def _resoudre_salarie(conn, terme):
    terme_n = _normaliser(terme)
    if not terme_n:
        return []
    mots = terme_n.split()
    rows = conn.execute(
        "SELECT u.id, u.nom, u.prenom, s.nom AS secteur_nom "
        "FROM users u LEFT JOIN secteurs s ON u.secteur_id = s.id "
        "WHERE u.actif = 1 AND u.profil != 'prestataire' ORDER BY u.nom, u.prenom"
    ).fetchall()
    exact, prefixe = [], []
    for r in rows:
        nom_n = _normaliser(r['nom'] or '')
        prenom_n = _normaliser(r['prenom'] or '')
        if len(mots) >= 2:
            # Nom + prénom (dans un sens ou l'autre)
            paire = {mots[0], mots[1]}
            if paire == {nom_n, prenom_n}:
                exact.append(r)
            elif (prenom_n.startswith(mots[0]) and nom_n.startswith(mots[1])) or \
                 (nom_n.startswith(mots[0]) and prenom_n.startswith(mots[1])):
                prefixe.append(r)
        else:
            if terme_n in (nom_n, prenom_n):
                exact.append(r)
            elif prenom_n.startswith(terme_n) or nom_n.startswith(terme_n):
                prefixe.append(r)
    return exact or prefixe


def anonymiser_terme_salaries(conn, texte):
    """Masque les noms/prénoms de salariés dans un texte de recherche.

    Remplace par « salarié » tout mot correspondant (normalisé) à un nom ou un
    prénom d'utilisateur, afin que le journal des recherches ne révèle pas quels
    salariés font l'objet de recherches (confidentialité RH). Les « salarié »
    consécutifs sont fusionnés (« absence Marie Dupont » → « absence salarié »).
    Fonction pure et défensive : renvoie le texte inchangé en cas d'erreur.
    """
    if not texte:
        return texte
    try:
        noms = set()
        for r in conn.execute("SELECT nom, prenom FROM users").fetchall():
            for champ in (r['nom'], r['prenom']):
                for mot in _normaliser(champ or '').split():
                    if len(mot) >= 2:
                        noms.add(mot)
        if not noms:
            return texte
        resultat, masque_precedent = [], False
        for tok in texte.split():
            sous_mots = _normaliser(tok).split()
            est_nom = bool(sous_mots) and any(m in noms for m in sous_mots)
            if est_nom:
                if not masque_precedent:
                    resultat.append('salarié')
                    masque_precedent = True
            else:
                resultat.append(tok)
                masque_precedent = False
        return ' '.join(resultat).strip()
    except Exception:
        return texte


def _resoudre_action(conn, terme):
    terme_n = _normaliser(terme)
    if not terme_n:
        return []
    rows = conn.execute('SELECT id, nom FROM comptabilite_actions ORDER BY nom').fetchall()
    exact = [r for r in rows if _normaliser(r['nom']) == terme_n]
    if exact:
        return exact
    return [r for r in rows if _normaliser(r['nom']).startswith(terme_n)]


def _resoudre_subvention(conn, terme):
    terme_n = _normaliser(terme)
    if not terme_n or len(terme_n) < 2:
        return []
    rows = conn.execute('SELECT id, nom, annee_action FROM subventions ORDER BY nom').fetchall()
    exact = [r for r in rows if _normaliser(r['nom']) == terme_n]
    if exact:
        return exact
    return [r for r in rows if terme_n in _normaliser(r['nom'])]


def _resoudre_facture_numero(conn, numero):
    num = (numero or '').strip()
    if not num:
        return []
    return conn.execute(
        'SELECT f.id, f.numero_facture, f.date_facture, fr.nom AS fournisseur_nom '
        'FROM factures f LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id '
        'WHERE f.numero_facture = ? ORDER BY f.date_facture DESC', (num,)
    ).fetchall()


# ── Constructeurs de verdicts ──

def _redirect(url, label):
    return {'type': 'redirect', 'url': url, 'label': label}


def _choices(prompt, options):
    return {'type': 'choices', 'prompt': prompt, 'options': options}


_EXEMPLES = [
    'facture 225678', 'factures edf', 'budget clas 2025', 'budget babilhome',
    'trésorerie avril', 'bilan 2025', 'liste subventions 2026',
    'absence Marie', 'heures Marie', 'contrats avril', 'CDD se terminant en juillet',
]


def _aide(message="Tapez un nom (fournisseur, secteur, salarié), un mot-clé ou un numéro de facture."):
    return {'type': 'none', 'message': message, 'exemples': _EXEMPLES}


# ── Fiche salarié / choix (désambiguïsation) ──

def _url_salarie(uid, ancre=''):
    return url_for('infos_salaries_bp.infos_salaries', user_id=uid) + ancre


def _salarie_ou_choix(salaries, faire_url, prompt, ancre=''):
    """Redirige si un seul salarié, propose un choix si plusieurs."""
    if len(salaries) == 1:
        s = salaries[0]
        return _redirect(faire_url(s['id']), f"{s['prenom']} {s['nom']}")
    options = []
    for s in salaries:
        options.append({
            'label': f"{s['prenom']} {s['nom']}",
            'sous_titre': s['secteur_nom'] or '',
            'url': faire_url(s['id']),
        })
    return _choices(prompt, options)


# ── Détection d'intention principale ──

_KW_FACTURE = {'facture', 'factures'}
_KW_BUDGET = {'budget', 'budgets'}
_KW_PREV = {'prev', 'previsionnel', 'previsionnels', 'actualise',
            'bp',    # budget prévisionnel
            'bpa'}   # budget prévisionnel actualisé
_KW_TRESO = {'tresorerie', 'treso', 'solde'}
_KW_SUBV = {'subvention', 'subventions'}
_KW_INDIC = {'indicateur', 'indicateurs'}
_KW_SALARIE = {'salarie', 'salaries', 'salariee', 'fiche', 'employe', 'employee'}
_KW_ABSENCE = {'absence', 'absences', 'conge', 'conges',
               # Synonymes courants : arrêt / congé maladie.
               'maladie', 'maladies', 'malade', 'arret', 'arrets'}
_KW_PESEE = {'pesee', 'pese'}
_KW_HEURES = {'heure', 'heures', 'temps'}
_KW_CONTRAT = {'contrat', 'contrats', 'cdd', 'cdi'}
_KW_PLANNING = {'planning', 'plannings', 'horaire', 'horaires'}
_KW_SALLES = {'salle', 'salles', 'reservation', 'reservations'}

# Nombre d'années passées présélectionnables par la page « Budget action »
# (bilan_action.py : annees = current+1 … current-4). Au-delà (année réalisée
# plus ancienne), la construction budgétaire n'est plus proposée : on renvoie la
# consultation du clôturé vers bilan-secteurs, qui accepte n'importe quelle année.
_BILAN_ACTION_ANNEES_PASSEES = 4

# Déposer une demande de congés : « demande (de) congé(s) », « poser congé(s) »,
# « prendre congé(s) » (+ variantes « demander », « faire une demande de… »).
# Le verbe est requis : « congé Marie » reste l'intention « absences ».
_RE_DEMANDE_CONGE = re.compile(
    r'\b(?:demande|demandes|demander|demandez|pose|poser|posez|prendre|prends|prend|prenez)\b'
    r'(?:\s+(?:de|d|un|une|des|mes|ma|mon|le|la|les|nouvelle))*'
    r'\s+conges?\b'
)

# Mots outils ignorés en tête de requête (« voir budget », « liste subventions »…)
_MOTS_OUTILS = {'liste', 'listes', 'voir', 'afficher', 'montre', 'montrer', 'montrez',
                'ouvre', 'ouvrir', 'les', 'la', 'le', 'des', 'du', 'de', 'mes', 'mon', 'ma'}


def analyser_recherche(conn, query, profil, today):
    """Analyse une requête et renvoie un verdict de routage. Fonction pure."""
    q = (query or '').strip()
    if not q or q in ('?', 'aide', 'help'):
        return _aide()

    norm = _normaliser(q)
    tokens = norm.split()
    mois, annee, annee_explicite, reste = _extraire_periode(tokens, today)
    annee_eff = annee if annee is not None else today.year
    reste_str = ' '.join(reste).strip()

    # ── Phrases multi-mots (avant les mots-clés simples et le retrait des mots outils) ──
    if 'plan comptable' in norm or reste_str in ('liste compte', 'liste comptes', 'plan comptable'):
        return _redirect(url_for('plan_comptable_general_bp.plan_comptable_general'),
                         'Plan comptable général')
    if 'compte de resultat' in norm or 'compte resultat' in norm:
        return _redirect(url_for('compte_resultat_bp.compte_resultat', annee=annee_eff, vue='cr'),
                         f'Compte de résultat {annee_eff}')
    if 'prevision tresorerie' in norm or 'solde banque' in norm:
        params = {'annee': annee_eff}
        if mois:
            params['mois'] = mois
        return _redirect(url_for('tresorerie_bp.tresorerie', **params), 'Trésorerie')
    # RH : « infos RH », « information RH », « RH »
    if reste_str in ('rh', 'info rh', 'infos rh', 'information rh', 'informations rh'):
        return _redirect(url_for('rh_statistiques_bp.rh_statistiques'), 'Statistiques RH')
    # Pesée / analyse de poste ALISFA (outil de cotation)
    if any(p in norm for p in ('analyse poste', 'analyse pesee', 'calcul pesee',
                               'estimation pesee', 'cotation poste')):
        return _redirect(url_for('pesee_alisfa_bp.pesee_alisfa'), 'Analyse / pesée ALISFA')
    # Déposer une demande de congés (direction et comptable y ont accès).
    if _RE_DEMANDE_CONGE.search(norm):
        return _redirect(url_for('recup_bp.demande_conge'), 'Demande de congés')

    # Retirer les mots outils en tête (« voir », « liste », « les »…) pour révéler le mot-clé.
    while reste and reste[0] in _MOTS_OUTILS:
        reste = reste[1:]
    reste_str = ' '.join(reste).strip()
    kw = reste[0] if reste else ''
    apres_kw = ' '.join(reste[1:]).strip()

    # ── A. Compta / finance ──
    if kw in _KW_FACTURE:
        return _intention_facture(conn, apres_kw, mois, annee_eff)
    if kw in _KW_BUDGET or kw in _KW_PREV:
        return _intention_budget(conn, kw, apres_kw, annee_eff, annee_explicite, today)
    if kw in _KW_TRESO or 'tresorerie' in reste:
        params = {'annee': annee_eff}
        if mois:
            params['mois'] = mois
        return _redirect(url_for('tresorerie_bp.tresorerie', **params), 'Trésorerie')
    if kw in _KW_SUBV:
        return _intention_subvention(conn, apres_kw, annee, annee_explicite)
    if kw == 'bilan':
        # « bilan » seul → compte-résultat (bilan de la structure) ; « bilan <secteur|action> »
        # → bilan-secteurs (consultation).
        return _intention_bilan(conn, apres_kw, annee_eff)
    if kw in ('cr', 'resultat'):
        return _redirect(url_for('compte_resultat_bp.compte_resultat', annee=annee_eff, vue='cr'),
                         f'Compte de résultat {annee_eff}')
    if kw in _KW_INDIC:
        return _redirect(url_for('indicateurs_financiers_bp.indicateurs_financiers'),
                         'Indicateurs financiers')
    if kw in ('compte', 'comptes'):
        return _redirect(url_for('plan_comptable_general_bp.plan_comptable_general'),
                         'Plan comptable général')
    if kw in _KW_SALLES:
        return _redirect(url_for('salles_bp.salles'), 'Réservation de salles')

    # ── B. RH ──
    if kw in _KW_CONTRAT:
        return _intention_contrat(conn, kw, apres_kw, mois, annee_eff, today)
    if kw in _KW_ABSENCE:
        salaries = _resoudre_salarie(conn, apres_kw) if apres_kw else []
        if apres_kw and salaries:
            return _salarie_ou_choix(
                salaries,
                lambda uid: url_for('absences_bp.absences', search_user_id=uid),
                f"Plusieurs salariés « {apres_kw} » — absences de :")
        return _redirect(url_for('absences_bp.absences'), 'Absences')
    if kw in _KW_PESEE:
        # postes_alisfa n'a pas de filtre par personne : la pesée d'un salarié est
        # affichée sur sa fiche → « pesée Marie » y renvoie ; « pesée » seul ouvre
        # l'outil de pesée ALISFA.
        salaries = _resoudre_salarie(conn, apres_kw) if apres_kw else []
        if apres_kw and salaries:
            return _salarie_ou_choix(
                salaries, lambda uid: _url_salarie(uid),
                f"Plusieurs salariés « {apres_kw} » — pesée de :")
        return _redirect(url_for('pesee_alisfa_bp.postes_alisfa'), 'Pesée comptable (ALISFA)')
    if kw in _KW_HEURES:
        salaries = _resoudre_salarie(conn, apres_kw) if apres_kw else []
        if apres_kw and salaries:
            return _salarie_ou_choix(
                salaries,
                lambda uid: url_for('validation_bp.vue_mensuelle', user_id=uid,
                                    mois=mois or today.month, annee=annee_eff),
                f"Plusieurs salariés « {apres_kw} » — fiche temps de :")
        return _aide("Précisez un salarié : ex. « heures Marie ».")
    if kw in _KW_SALARIE:
        salaries = _resoudre_salarie(conn, apres_kw) if apres_kw else []
        ancre = '#contrats' if 'contrat' in reste else ''
        if apres_kw and salaries:
            return _salarie_ou_choix(
                salaries, lambda uid: _url_salarie(uid, ancre),
                f"Plusieurs salariés « {apres_kw} » :", ancre)
        return _aide("Précisez un salarié : ex. « salarié Marie ».")
    if kw in _KW_PLANNING:
        salaries = _resoudre_salarie(conn, apres_kw) if apres_kw else []
        if apres_kw and salaries:
            return _salarie_ou_choix(
                salaries, lambda uid: url_for('planning_bp.planning_theorique', user_id=uid),
                f"Plusieurs salariés « {apres_kw} » — planning de :")
        return _redirect(url_for('planning_bp.planning_theorique'), 'Planning théorique')
    if kw == 'rh':
        return _redirect(url_for('rh_statistiques_bp.rh_statistiques'), 'Statistiques RH')

    # ── Mot(s) seul(s) : résolution multi-types ──
    return _resoudre_terme_libre(conn, reste_str, annee, annee_explicite, mois, today)


def _intention_facture(conn, terme, mois, annee_eff):
    terme_n = _normaliser(terme)
    # Numéro de facture (ex. « facture 225678 »)
    if re.fullmatch(r'\d{3,}', terme_n):
        factures = _resoudre_facture_numero(conn, terme_n)
        if len(factures) == 1:
            return _redirect(url_for('factures_bp.detail_facture', facture_id=factures[0]['id']),
                             f"Facture {terme_n}")
        if len(factures) > 1:
            options = [{
                'label': f"Facture {f['numero_facture']}",
                'sous_titre': f"{f['fournisseur_nom'] or ''} — {f['date_facture'] or ''}",
                'url': url_for('factures_bp.detail_facture', facture_id=f['id']),
            } for f in factures]
            return _choices(f"Plusieurs factures « {terme_n} » :", options)
        return _aide(f"Aucune facture au numéro « {terme_n} ».")
    # Nom de fournisseur (ex. « factures edf ») → fiche fournisseur (liste incluse)
    if terme:
        fournisseurs = _resoudre_fournisseur(conn, terme)
        if len(fournisseurs) == 1:
            return _redirect(
                url_for('fournisseurs_bp.detail_fournisseur',
                        fournisseur_id=fournisseurs[0]['id'], annee=annee_eff),
                f"Factures — {fournisseurs[0]['nom']}")
        if len(fournisseurs) > 1:
            options = [{
                'label': f['nom'], 'sous_titre': f['code_comptable'] or '',
                'url': url_for('fournisseurs_bp.detail_fournisseur', fournisseur_id=f['id'], annee=annee_eff),
            } for f in fournisseurs]
            return _choices(f"Plusieurs fournisseurs « {terme} » :", options)
    # Générique
    return _redirect(url_for('factures_bp.liste_factures'), 'Factures')


def _intention_bilan(conn, terme, annee_eff):
    """« bilan » : sans entité → compte-résultat (bilan de la structure) ; avec un
    secteur ou une action → bilan-secteurs (consultation du clôturé / réalisé)."""
    if not terme:
        return _redirect(url_for('compte_resultat_bp.compte_resultat', annee=annee_eff, vue='bilan'),
                         f'Bilan {annee_eff}')
    secteurs = _resoudre_secteur(conn, terme)
    actions = _resoudre_action(conn, terme)
    if len(secteurs) == 1 and not actions:
        s = secteurs[0]
        return _redirect(url_for('bilan_secteurs_bp.bilan_secteurs', secteur_id=s['id'], annee=annee_eff),
                         f"Bilan — {s['nom']} {annee_eff}")
    if len(actions) == 1 and not secteurs:
        a = actions[0]
        return _redirect(url_for('bilan_secteurs_bp.bilan_secteurs', action_id=a['id'], annee=annee_eff),
                         f"Bilan — {a['nom']} {annee_eff}")
    options = []
    for s in secteurs:
        options.append({'label': f"Secteur {s['nom']}", 'sous_titre': f'Bilan {annee_eff}',
                        'url': url_for('bilan_secteurs_bp.bilan_secteurs', secteur_id=s['id'], annee=annee_eff)})
    for a in actions:
        options.append({'label': f"Action {a['nom']}", 'sous_titre': f'Bilan {annee_eff}',
                        'url': url_for('bilan_secteurs_bp.bilan_secteurs', action_id=a['id'], annee=annee_eff)})
    if options:
        return _choices(f"« {terme} » — bilan de :", options)
    return _redirect(url_for('compte_resultat_bp.compte_resultat', annee=annee_eff, vue='bilan'),
                     f'Bilan {annee_eff}')


def _url_budget_action(a, annee_eff, passe, is_prev, today):
    """(url, libellé) de budget pour une action selon l'année demandée.

    La page « Budget action » (bilan-action) ne présélectionne que les années de
    sa fenêtre (année courante et les quatre précédentes). Pour une année réalisée
    plus ancienne, la présélection serait ignorée et la page retomberait sur
    l'année courante : on renvoie alors la consultation du clôturé vers
    bilan-secteurs, qui accepte n'importe quelle année."""
    if passe and annee_eff < today.year - _BILAN_ACTION_ANNEES_PASSEES:
        return (url_for('bilan_secteurs_bp.bilan_secteurs', action_id=a['id'], annee=annee_eff),
                f"Bilan — {a['nom']} {annee_eff}")
    onglet = 'realise' if (passe and not is_prev) else 'previsionnel'
    return (url_for('bilan_action_bp.bilan_action', action_id=a['id'], annee=annee_eff, onglet=onglet),
            f"Budget action — {a['nom']} {annee_eff}")


def _intention_budget(conn, kw, terme, annee_eff, annee_explicite, today):
    """Budget / prévisionnel / actualisé :
    - sans entité, ou « prev/budget <année> » → budget-prévisionnel (général) ;
    - secteur année courante/future → budget-prévisionnel (secteur) ; secteur année
      passée (clôturé) → bilan-secteurs ;
    - action → bilan-action (« Budget action », construction ; onglet réalisé si
      année passée)."""
    is_prev = kw in _KW_PREV
    passe = annee_explicite and annee_eff < today.year

    if not terme:
        return _redirect(url_for('budget_bp.budget_previsionnel', annee=annee_eff),
                         f'Budget prévisionnel {annee_eff}')

    secteurs = _resoudre_secteur(conn, terme)
    actions = _resoudre_action(conn, terme)

    if len(secteurs) == 1 and not actions:
        s = secteurs[0]
        if passe:
            return _redirect(
                url_for('bilan_secteurs_bp.bilan_secteurs', secteur_id=s['id'], annee=annee_eff),
                f"Bilan — {s['nom']} {annee_eff}")
        return _redirect(
            url_for('budget_bp.budget_previsionnel', annee=annee_eff, secteur_id=s['id']),
            f"Budget prévisionnel — {s['nom']} {annee_eff}")

    if len(actions) == 1 and not secteurs:
        url, label = _url_budget_action(actions[0], annee_eff, passe, is_prev, today)
        return _redirect(url, label)

    options = []
    for s in secteurs:
        url = (url_for('bilan_secteurs_bp.bilan_secteurs', secteur_id=s['id'], annee=annee_eff) if passe
               else url_for('budget_bp.budget_previsionnel', annee=annee_eff, secteur_id=s['id']))
        options.append({'label': f"Secteur {s['nom']}", 'sous_titre': f'Budget {annee_eff}', 'url': url})
    for a in actions:
        url, label = _url_budget_action(a, annee_eff, passe, is_prev, today)
        options.append({'label': f"Action {a['nom']}", 'sous_titre': label, 'url': url})
    if options:
        return _choices(f"« {terme} » — budget de :", options)

    return _redirect(url_for('budget_bp.budget_previsionnel', annee=annee_eff),
                     f'Budget prévisionnel {annee_eff}')


def _intention_subvention(conn, terme, annee, annee_explicite):
    if terme and terme not in ('liste', 'toutes'):
        subs = _resoudre_subvention(conn, terme)
        if len(subs) == 1:
            an = subs[0]['annee_action'] or 'toutes'
            return _redirect(url_for('subventions_bp.gestion_subventions', annee=an),
                             f"Subvention — {subs[0]['nom']}")
        if len(subs) > 1:
            options = [{
                'label': s['nom'], 'sous_titre': f"Année {s['annee_action'] or '—'}",
                'url': url_for('subventions_bp.gestion_subventions', annee=s['annee_action'] or 'toutes'),
            } for s in subs]
            return _choices(f"Plusieurs subventions « {terme} » :", options)
    an = annee if annee_explicite else 'toutes'
    return _redirect(url_for('subventions_bp.gestion_subventions', annee=an), 'Subventions')


def _intention_contrat(conn, kw, terme, mois, annee_eff, today):
    # « contrat <salarié> » → sa fiche (section contrats)
    if terme:
        salaries = _resoudre_salarie(conn, terme)
        if salaries:
            return _salarie_ou_choix(
                salaries, lambda uid: _url_salarie(uid, '#contrats'),
                f"Plusieurs salariés « {terme} » — contrats de :", '#contrats')
    # Sinon → nouvelle page contrats du mois (filtre selon les mots)
    params = {'mois': mois or today.month, 'annee': annee_eff}
    if kw in ('cdd', 'cdi'):
        params['type'] = kw.upper()
    reste_n = _normaliser(terme)
    if 'terminant' in reste_n or 'echeance' in reste_n or 'fin' in reste_n:
        params['filtre'] = 'echeance'
        params['type'] = 'CDD'
    elif 'signe' in reste_n:
        params['filtre'] = 'signe'
    return _redirect(url_for('contrats_bp.liste_contrats', **params), 'Contrats')


def _resoudre_terme_libre(conn, terme, annee, annee_explicite, mois, today):
    """Mot(s) seul(s) sans mot-clé : essaie fournisseur / secteur / salarié / action / subvention."""
    if not terme:
        return _aide()

    # Numéro seul → facture
    if re.fullmatch(r'\d{4,}', _normaliser(terme)):
        return _intention_facture(conn, terme, mois, annee if annee else today.year)

    candidats = []  # (type_label, nom, url, sous_titre)
    for f in _resoudre_fournisseur(conn, terme):
        candidats.append(('Fournisseur', f['nom'],
                          url_for('fournisseurs_bp.detail_fournisseur', fournisseur_id=f['id']),
                          f['code_comptable'] or ''))
    for s in _resoudre_secteur(conn, terme):
        candidats.append(('Secteur', s['nom'],
                          url_for('bilan_secteurs_bp.bilan_secteurs', secteur_id=s['id'],
                                  annee=annee if annee_explicite else today.year), 'Bilan secteur'))
    for u in _resoudre_salarie(conn, terme):
        candidats.append(('Salarié', f"{u['prenom']} {u['nom']}",
                          _url_salarie(u['id']), u['secteur_nom'] or ''))
    for sv in _resoudre_subvention(conn, terme):
        candidats.append(('Subvention', sv['nom'],
                          url_for('subventions_bp.gestion_subventions',
                                  annee=sv['annee_action'] or 'toutes'),
                          f"Année {sv['annee_action'] or '—'}"))

    an = annee if annee_explicite else today.year
    actions = _resoudre_action(conn, terme)

    # Action seule → doute consultation / construction : proposer les deux.
    if not candidats and len(actions) == 1:
        a = actions[0]
        return _choices(f"« {a['nom'] } » — que voir ?", [
            {'label': f"Budget action — {a['nom']}", 'sous_titre': 'Construction du budget',
             'url': url_for('bilan_action_bp.bilan_action', action_id=a['id'], annee=an, onglet='previsionnel')},
            {'label': f"Bilan — {a['nom']}", 'sous_titre': 'Consultation (réalisé / clôturé)',
             'url': url_for('bilan_secteurs_bp.bilan_secteurs', action_id=a['id'], annee=an)},
        ])
    # Sinon, une action rejoint les autres candidats (construction du budget par défaut).
    for a in actions:
        candidats.append(('Budget action', a['nom'],
                          url_for('bilan_action_bp.bilan_action', action_id=a['id'], annee=an,
                                  onglet='previsionnel'), 'Construction du budget'))

    if len(candidats) == 1:
        c = candidats[0]
        return _redirect(c[2], f"{c[0]} — {c[1]}")
    if len(candidats) > 1:
        options = [{'label': f"{c[0]} — {c[1]}", 'sous_titre': c[3], 'url': c[2]} for c in candidats]
        return _choices(f"« {terme} » correspond à plusieurs éléments :", options)

    return _aide(f"Rien trouvé pour « {terme} ».")
