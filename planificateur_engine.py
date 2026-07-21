"""
Moteur d'optimisation du planificateur de taches (Time Blocking).

Module *pur* (sans acces base de donnees) : il recoit des structures de
donnees simples et retourne le placement calcule. Cela le rend facilement
testable et permettrait de brancher un autre solveur (ex: OR-Tools) plus tard
sans toucher au reste de l'application.

Principe general (heuristique de placement glouton + equilibrage de charge) :

1. On reconstruit, pour chaque jour de l'horizon, les creneaux libres a partir
   des horaires de travail du salarie, desquels on retire les evenements fixes
   (rendez-vous, reunions) et les blocs deja realises ou verrouilles.
2. On traite les taches par ordre d'urgence : echeance la plus proche d'abord,
   puis priorite (numerique relative, plus grand = plus urgent), puis duree
   croissante (la plus rapide d'abord), puis la plus recente. Les taches
   recurrentes sont placees en dernier, « la ou il reste de la place ».
3. Pour chaque tache, on choisit a chaque etape le jour le moins charge de sa
   fenetre (equilibrage), en respectant la preference matin / apres-midi.
4. Les longues missions secables sont reparties sur plusieurs jours, avec des
   blocs ni trop petits (>= duree_min_bloc) ni demesures.
5. A l'interieur d'une journee, on intercale des respirations : 5 min par heure
   les journees chargees, 15 min toutes les 2 h les journees normales. Les
   pauses sont de simples « trous » dans le planning (espace laisse libre).
"""
from datetime import date, timedelta
import math

# Conversion de l'ancienne priorite texte vers l'echelle numerique relative
# (plus grand = plus urgent), utilisee quand priorite_num est absent.
PRIORITE_TEXTE_NUM = {'haute': 1, 'normale': 0, 'basse': -1}


def _priorite_valeur(tache):
    """Priorite numerique d'une tache (plus grand = plus urgent).

    `priorite_num` — l'echelle relative construite par comparaisons a la
    saisie — prime ; a defaut (anciennes taches), la priorite texte est
    convertie via PRIORITE_TEXTE_NUM.
    """
    num = tache.get('priorite_num')
    if num is not None:
        try:
            return int(num)
        except (TypeError, ValueError):
            pass
    return PRIORITE_TEXTE_NUM.get(tache.get('priorite', 'normale'), 0)

# Seuil (minutes de travail disponibles dans la journee) au-dela duquel la
# journee est consideree « chargee » et beneficie de micro-pauses rapprochees.
SEUIL_JOURNEE_CHARGEE = 360  # 6 h

# Regime de respiration : (intervalle de travail continu, duree de pause) en min.
PAUSE_JOURNEE_CHARGEE = (60, 5)    # 5 min toutes les heures
PAUSE_JOURNEE_NORMALE = (120, 15)  # 15 min toutes les 2 h

# En dessous de cette duree, une tache secable n'est pas fragmentee sur
# plusieurs jours (cela n'aurait pas de sens de la repartir).
SEUIL_FRAGMENTATION = 90  # 1 h 30

# Cible indicative de travail par jour pour une longue mission repartie.
CIBLE_PAR_JOUR = 120  # 2 h

# Plafond de minutes qu'une seule tache peut consommer sur une journee, pour
# eviter qu'une grosse mission ne sature un jour au detriment des autres.
PLAFOND_TACHE_PAR_JOUR = 240  # 4 h

# Une tache est jugee « substantielle » sur une journee si elle y occupe au
# moins cette duree. Le moteur repartit en priorite les taches substantielles :
# il remplit d'abord les jours qui en comptent le moins (souple, il monte a 4,
# 5... si tous les jours possibles sont deja pleins), afin de bien etaler la
# charge plutot que de tout regrouper des qu'un creneau se libere.
SEUIL_TACHE_SUBSTANTIELLE = 60  # 1 h


def _to_min(hhmm):
    """'HH:MM' -> minutes depuis minuit (None si invalide)."""
    if not hhmm:
        return None
    try:
        h, m = hhmm.split(':')
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _to_hhmm(minutes):
    """minutes depuis minuit -> 'HH:MM'."""
    minutes = int(round(minutes))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _normaliser_intervalles(intervalles):
    """Trie et fusionne une liste d'intervalles (debut, fin) en minutes."""
    propres = sorted((d, f) for d, f in intervalles if d is not None and f is not None and f > d)
    fusionnes = []
    for deb, fin in propres:
        if fusionnes and deb <= fusionnes[-1][1]:
            fusionnes[-1] = (fusionnes[-1][0], max(fusionnes[-1][1], fin))
        else:
            fusionnes.append((deb, fin))
    return fusionnes


def _soustraire(libres, occupes):
    """Retire les intervalles `occupes` des intervalles `libres`.

    Retourne la liste des segments restants (debut, fin), tries.
    """
    occupes = _normaliser_intervalles(occupes)
    resultat = []
    for deb, fin in _normaliser_intervalles(libres):
        courant = deb
        for o_deb, o_fin in occupes:
            if o_fin <= courant or o_deb >= fin:
                continue
            if o_deb > courant:
                resultat.append((courant, min(o_deb, fin)))
            courant = max(courant, o_fin)
            if courant >= fin:
                break
        if courant < fin:
            resultat.append((courant, fin))
    return [(d, f) for d, f in resultat if f > d]


class _PlanJour:
    """Gere le placement des blocs sur une journee donnee."""

    def __init__(self, jour, segments_libres):
        self.jour = jour  # objet date
        # Chaque segment : dict avec curseur de remplissage et compteur de
        # travail continu (remis a zero a chaque nouveau segment = pause
        # naturelle : pause dejeuner, evenement fixe, etc.).
        self.segments = [
            {'deb': d, 'fin': f, 'curseur': d, 'continu': 0}
            for d, f in segments_libres if f > d
        ]
        self.capacite = sum(f - d for d, f in segments_libres if f > d)
        self.charge = 0  # minutes de taches deja placees
        self.taches_min = {}  # tache_id -> minutes placees ce jour
        if self.capacite >= SEUIL_JOURNEE_CHARGEE:
            self.intervalle_pause, self.duree_pause = PAUSE_JOURNEE_CHARGEE
        else:
            self.intervalle_pause, self.duree_pause = PAUSE_JOURNEE_NORMALE

    def nb_substantielles(self):
        """Nombre de taches « substantielles » (>= 1 h) placees ce jour-la.

        La tache en cours de placement est comptee des qu'elle atteint le seuil :
        un jour ou elle a deja pose un morceau parait donc « plus rempli », ce
        qui pousse ses morceaux suivants a s'etaler sur d'autres jours plutot
        que de tout empiler la (et preserve l'equilibrage des longues missions).
        """
        return sum(1 for m in self.taches_min.values()
                   if m >= SEUIL_TACHE_SUBSTANTIELLE)

    def enregistrer(self, tache_id, minutes):
        """Comptabilise `minutes` placees pour une tache ce jour-la."""
        if minutes > 0:
            self.taches_min[tache_id] = self.taches_min.get(tache_id, 0) + minutes

    def _segments_ordonnes(self, preference):
        """Ordonne les segments selon la preference matin / apres-midi."""
        segs = [s for s in self.segments if s['curseur'] < s['fin']]
        if preference == 'matin':
            segs.sort(key=lambda s: s['curseur'])
        elif preference == 'apres_midi':
            # Apres-midi d'abord (segments commencant a 12h ou plus tard).
            segs.sort(key=lambda s: (s['curseur'] < 720, s['curseur']))
        else:
            segs.sort(key=lambda s: s['curseur'])
        return segs

    def placer_bloc_entier(self, duree, preference):
        """Place une tache non secable en un seul bloc contigu.

        Retourne (deb, fin) en minutes si reussi, sinon None.
        """
        for seg in self._segments_ordonnes(preference):
            curseur = seg['curseur']
            continu = seg['continu']
            # Pause prealable si le travail continu impose une respiration.
            if continu >= self.intervalle_pause:
                curseur += self.duree_pause
                continu = 0
            if seg['fin'] - curseur >= duree:
                deb, fin = curseur, curseur + duree
                seg['curseur'] = fin
                # On force une respiration apres une longue session.
                seg['continu'] = self.intervalle_pause
                self.charge += duree
                return (deb, fin)
        return None

    def placer_secable(self, minutes_voulues, preference):
        """Place jusqu'a `minutes_voulues` minutes en intercalant des pauses.

        Retourne (liste_de_blocs, minutes_placees).
        """
        blocs = []
        restant = minutes_voulues
        for seg in self._segments_ordonnes(preference):
            while restant > 0 and seg['curseur'] < seg['fin']:
                if seg['continu'] >= self.intervalle_pause:
                    if seg['fin'] - seg['curseur'] <= self.duree_pause:
                        break  # plus de place pour pause + travail
                    seg['curseur'] += self.duree_pause
                    seg['continu'] = 0
                run = min(
                    seg['fin'] - seg['curseur'],
                    self.intervalle_pause - seg['continu'],
                    restant,
                )
                if run <= 0:
                    break
                deb, fin = seg['curseur'], seg['curseur'] + run
                blocs.append((deb, fin))
                seg['curseur'] = fin
                seg['continu'] += run
                restant -= run
        placees = minutes_voulues - restant
        self.charge += placees
        return blocs, placees

    def capacite_restante(self):
        return sum(s['fin'] - s['curseur'] for s in self.segments)


def niveau_urgence(deadline, jour_ref, statut='a_faire'):
    """Niveau d'urgence d'une tache selon la proximite de l'echeance.

    Retourne l'un de : 'fait', 'retard', 'urgent', 'proche', 'a_venir',
    'sans_echeance'. Utilise pour le code couleur du calendrier.
    """
    if statut == 'fait':
        return 'fait'
    if not deadline:
        return 'sans_echeance'
    if isinstance(deadline, str):
        try:
            deadline = date.fromisoformat(deadline)
        except ValueError:
            return 'sans_echeance'
    jours = (deadline - jour_ref).days
    if jours < 0:
        return 'retard'
    if jours <= 1:
        return 'urgent'
    if jours <= 3:
        return 'proche'
    return 'a_venir'


def _cle_tri_tache(tache, horizon_fin):
    """Cle de tri d'une tache : echeance, puis (a echeance egale) les gros blocs
    contigus d'abord, puis priorite, puis duree croissante (la plus rapide
    d'abord), puis la plus recente (une tache ancienne jamais traitee peut
    attendre).

    Une grosse tache NON secable exige un long creneau contigu : c'est la plus
    difficile a caser. Si on la traitait apres de petites taches flexibles du
    meme jour, celles-ci fragmenteraient les demi-journees et la rendraient
    improuvable (elle devrait alors etre reportee). On la place donc en premier,
    quitte a bousculer un peu l'ordre de priorite entre taches de meme echeance.
    """
    deadline = tache.get('deadline') or horizon_fin
    if isinstance(deadline, str):
        try:
            deadline = date.fromisoformat(deadline)
        except ValueError:
            deadline = horizon_fin
    # Les taches sans echeance passent apres celles qui en ont une.
    sans_echeance = 0 if tache.get('deadline') else 1
    duree = int(tache.get('duree_min', 0))
    secable = bool(tache.get('secable', True))
    gros_bloc_contigu = 0 if (not secable and duree > CIBLE_PAR_JOUR) else 1
    return (sans_echeance, deadline, gros_bloc_contigu, -_priorite_valeur(tache),
            duree, -int(tache.get('id') or 0))


def _taille_chunk(duree, min_bloc, nb_jours_dispo, secable):
    """Determine la taille cible d'un bloc journalier pour une tache."""
    if not secable or duree <= SEUIL_FRAGMENTATION:
        return duree
    jours_souhaites = max(1, math.ceil(duree / CIBLE_PAR_JOUR))
    jours_souhaites = min(jours_souhaites, max(1, nb_jours_dispo))
    cible = math.ceil(duree / jours_souhaites)
    cible = max(min_bloc, min(cible, PLAFOND_TACHE_PAR_JOUR))
    return cible


def _cle_repartition(p):
    """Cle de tri d'une journee pour l'equilibrage : d'abord celle qui compte le
    MOINS de taches substantielles, puis la moins chargee, puis la plus tot.
    Repartir sur les jours peu remplis evite d'empiler les taches au meme endroit."""
    return (p.nb_substantielles(), p.charge, p.jour)


def planifier(taches, occupes_par_date, horaires, date_debut, date_fin,
              jours_feries=None, minute_courante=0):
    """Calcule le placement des taches sur l'horizon donne.

    Args:
        taches: liste de dicts, chacun contenant :
            id, titre, duree_min (int), deadline (date|str|None),
            priorite_num (int, optionnel : echelle relative, plus grand = plus
            urgent ; a defaut priorite texte 'haute'|'normale'|'basse'),
            preference ('matin'|'apres_midi'|'aucune'),
            secable (bool), duree_min_bloc (int),
            est_recurrente (bool, optionnel),
            date_min (date|str|None, optionnel : pas avant ce jour).
        occupes_par_date: dict 'YYYY-MM-DD' -> liste de (deb_min, fin_min)
            deja occupes (evenements fixes, blocs realises / verrouilles).
        horaires: dict 'YYYY-MM-DD' -> liste de (deb_min, fin_min) representant
            les horaires de travail de ce jour. Les horaires peuvent varier d'un
            jour a l'autre (periode scolaire / vacances, semaines alternees),
            c'est pourquoi ils sont indexes par date et non par jour de semaine.
        date_debut, date_fin: objets date delimitant l'horizon (inclus).
        jours_feries: ensemble de chaines 'YYYY-MM-DD' a ne pas planifier.
        minute_courante: minute (depuis minuit) deja ecoulee le premier jour
            (date_debut). On ne planifie pas dans le passe : la partie de la
            journee anterieure a cette minute est consideree occupee. A 0
            (defaut), toute la journee est disponible.

    Returns:
        dict {
            'blocs': [ {tache_id, date, heure_debut, heure_fin, duree_min} ],
            'non_planifie': [ {tache_id, minutes_restantes, raison} ],
        }
    """
    jours_feries = jours_feries or set()
    occupes_par_date = occupes_par_date or {}

    # 1. Construire les journees et leurs creneaux libres.
    jours = {}
    d = date_debut
    while d <= date_fin:
        date_str = d.isoformat()
        if date_str not in jours_feries:
            work = horaires.get(date_str, [])
            if work:
                occ = list(occupes_par_date.get(date_str, []))
                # Le premier jour, on ne planifie pas avant l'heure courante.
                if d == date_debut and minute_courante > 0:
                    occ.append((0, minute_courante))
                libres = _soustraire(work, occ)
                if libres:
                    jours[date_str] = _PlanJour(d, libres)
        d += timedelta(days=1)

    # 2. Trier les taches : prioritaires (par urgence) puis recurrentes.
    prioritaires = [t for t in taches if not t.get('est_recurrente')]
    recurrentes = [t for t in taches if t.get('est_recurrente')]
    prioritaires.sort(key=lambda t: _cle_tri_tache(t, date_fin))

    blocs_resultat = []
    non_planifie = []

    # Equilibrage global matin / apres-midi. Sans preference explicite, chaque
    # tache est orientee vers la demi-journee la moins chargee de TOUT l'horizon
    # (et pas seulement de la journee visee) : ainsi des taches etalees a raison
    # d'une par jour ne se retrouvent pas toutes le matin, l'apres-midi restant
    # vide. Le compteur suit la position REELLE des blocs poses (matin < 12 h).
    charge_demi = {'matin': 0, 'apres_midi': 0}

    def _demi(minute_debut):
        return 'matin' if minute_debut < 720 else 'apres_midi'

    def _pref_effective(preference):
        """Preference explicite conservee ; « aucune » -> demi-journee la moins
        chargee globalement (le matin a egalite, pour demarrer la journee tot)."""
        if preference in ('matin', 'apres_midi'):
            return preference
        return 'apres_midi' if charge_demi['apres_midi'] < charge_demi['matin'] else 'matin'

    def _jours_fenetre(tache, ignorer_echeance=False):
        """Journees candidates pour une tache.

        Par defaut, restreintes a la fenetre [date_min, deadline]. Avec
        `ignorer_echeance=True`, l'echeance est ignoree : ce jeu elargi sert de
        repli pour REPORTER le debordement sur les jours suivants quand la
        fenetre d'echeance est saturee.
        """
        dmin = tache.get('date_min')
        if isinstance(dmin, str):
            dmin = date.fromisoformat(dmin) if dmin else None
        deadline = None
        if not ignorer_echeance:
            deadline = tache.get('deadline')
            if isinstance(deadline, str):
                try:
                    deadline = date.fromisoformat(deadline)
                except ValueError:
                    deadline = None
        candidats = []
        for date_str, pj in jours.items():
            if dmin and pj.jour < dmin:
                continue
            if deadline and pj.jour > deadline:
                continue
            candidats.append(pj)
        return candidats

    def _repartir_secable(tache, jours_dispo, restant, chunk, preference):
        """Repartit `restant` minutes d'une tache secable sur `jours_dispo`, en
        privilegiant les jours les moins remplis. Retourne les minutes non placees."""
        epuises = set()
        while restant > 0:
            dispo = [p for p in jours_dispo
                     if id(p) not in epuises and p.capacite_restante() > 0]
            if not dispo:
                break
            pj = min(dispo, key=_cle_repartition)
            voulu = min(restant, chunk)
            blocs, places = pj.placer_secable(voulu, preference)
            if places <= 0:
                epuises.add(id(pj))
                continue
            pj.enregistrer(tache['id'], places)
            for deb, fin in blocs:
                charge_demi[_demi(deb)] += fin - deb
                blocs_resultat.append({
                    'tache_id': tache['id'], 'date': pj.jour.isoformat(),
                    'heure_debut': _to_hhmm(deb), 'heure_fin': _to_hhmm(fin),
                    'duree_min': fin - deb,
                })
            restant -= places
            if pj.capacite_restante() <= 0:
                epuises.add(id(pj))
        return restant

    def _placer_tache(tache):
        duree = int(tache.get('duree_min', 0))
        if duree <= 0:
            return
        secable = bool(tache.get('secable', True))
        min_bloc = max(5, int(tache.get('duree_min_bloc') or 30))
        preference = _pref_effective(tache.get('preference', 'aucune'))

        # Deux niveaux de jours candidats : d'abord la fenetre d'echeance, puis
        # (repli) les jours au-dela. Quand la fenetre est saturee, on REPORTE le
        # reste sur les jours suivants plutot que d'empiler les taches ou de les
        # laisser non planifiees. Les occurrences recurrentes ne sont jamais
        # reportees au-dela de leur jour (une reunion ratee ne se rattrape pas).
        fenetre = _jours_fenetre(tache)
        if tache.get('est_recurrente'):
            report = []
        else:
            ids_fenetre = {id(p) for p in fenetre}
            report = [p for p in _jours_fenetre(tache, ignorer_echeance=True)
                      if id(p) not in ids_fenetre]

        if not fenetre and not report:
            non_planifie.append({
                'tache_id': tache['id'], 'minutes_restantes': duree,
                'raison': 'aucun creneau disponible avant l\'echeance',
            })
            return

        if not secable:
            # Bloc unique : dans la fenetre (du mieux reparti au moins bon), puis
            # en report sur les jours suivants si aucun creneau contigu ne tient.
            for groupe in (fenetre, report):
                for pj in sorted(groupe, key=_cle_repartition):
                    pos = pj.placer_bloc_entier(duree, preference)
                    if pos:
                        charge_demi[_demi(pos[0])] += duree
                        pj.enregistrer(tache['id'], duree)
                        blocs_resultat.append({
                            'tache_id': tache['id'], 'date': pj.jour.isoformat(),
                            'heure_debut': _to_hhmm(pos[0]), 'heure_fin': _to_hhmm(pos[1]),
                            'duree_min': duree,
                        })
                        return
            non_planifie.append({
                'tache_id': tache['id'], 'minutes_restantes': duree,
                'raison': 'aucun creneau contigu assez long (tache non secable)',
            })
            return

        # Tache secable : repartir dans la fenetre, puis reporter le reliquat.
        restant = duree
        chunk = _taille_chunk(duree, min_bloc, len(fenetre) or len(report), secable)
        for groupe in (fenetre, report):
            if restant <= 0:
                break
            restant = _repartir_secable(tache, groupe, restant, chunk, preference)

        if restant > 0:
            non_planifie.append({
                'tache_id': tache['id'], 'minutes_restantes': restant,
                'raison': 'capacite insuffisante sur l\'horizon',
            })

    for tache in prioritaires:
        _placer_tache(tache)
    # Les taches recurrentes remplissent l'espace restant.
    for tache in recurrentes:
        _placer_tache(tache)

    return {'blocs': blocs_resultat, 'non_planifie': non_planifie}
