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
   puis priorite, puis duree. Les taches recurrentes sont placees en dernier,
   « la ou il reste de la place ».
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

# Poids de tri des priorites (plus petit = traite en premier).
PRIORITE_POIDS = {'haute': 0, 'normale': 1, 'basse': 2}

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
        if self.capacite >= SEUIL_JOURNEE_CHARGEE:
            self.intervalle_pause, self.duree_pause = PAUSE_JOURNEE_CHARGEE
        else:
            self.intervalle_pause, self.duree_pause = PAUSE_JOURNEE_NORMALE

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
    """Cle de tri d'une tache : echeance, puis priorite, puis duree."""
    deadline = tache.get('deadline') or horizon_fin
    if isinstance(deadline, str):
        try:
            deadline = date.fromisoformat(deadline)
        except ValueError:
            deadline = horizon_fin
    # Les taches sans echeance passent apres celles qui en ont une.
    sans_echeance = 0 if tache.get('deadline') else 1
    priorite = PRIORITE_POIDS.get(tache.get('priorite', 'normale'), 1)
    return (sans_echeance, deadline, priorite, -int(tache.get('duree_min', 0)))


def _taille_chunk(duree, min_bloc, nb_jours_dispo, secable):
    """Determine la taille cible d'un bloc journalier pour une tache."""
    if not secable or duree <= SEUIL_FRAGMENTATION:
        return duree
    jours_souhaites = max(1, math.ceil(duree / CIBLE_PAR_JOUR))
    jours_souhaites = min(jours_souhaites, max(1, nb_jours_dispo))
    cible = math.ceil(duree / jours_souhaites)
    cible = max(min_bloc, min(cible, PLAFOND_TACHE_PAR_JOUR))
    return cible


def planifier(taches, occupes_par_date, horaires, date_debut, date_fin,
              jours_feries=None):
    """Calcule le placement des taches sur l'horizon donne.

    Args:
        taches: liste de dicts, chacun contenant :
            id, titre, duree_min (int), deadline (date|str|None),
            priorite ('haute'|'normale'|'basse'),
            preference ('matin'|'apres_midi'|'aucune'),
            secable (bool), duree_min_bloc (int),
            est_recurrente (bool, optionnel),
            date_min (date|str|None, optionnel : pas avant ce jour).
        occupes_par_date: dict 'YYYY-MM-DD' -> liste de (deb_min, fin_min)
            deja occupes (evenements fixes, blocs realises / verrouilles).
        horaires: dict jour_semaine (0=lundi..6=dimanche) -> liste de
            (deb_min, fin_min) representant les horaires de travail.
        date_debut, date_fin: objets date delimitant l'horizon (inclus).
        jours_feries: ensemble de chaines 'YYYY-MM-DD' a ne pas planifier.

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
            work = horaires.get(d.weekday(), [])
            if work:
                libres = _soustraire(work, occupes_par_date.get(date_str, []))
                if libres:
                    jours[date_str] = _PlanJour(d, libres)
        d += timedelta(days=1)

    # 2. Trier les taches : prioritaires (par urgence) puis recurrentes.
    prioritaires = [t for t in taches if not t.get('est_recurrente')]
    recurrentes = [t for t in taches if t.get('est_recurrente')]
    prioritaires.sort(key=lambda t: _cle_tri_tache(t, date_fin))

    blocs_resultat = []
    non_planifie = []

    def _jours_fenetre(tache):
        """Journees candidates pour une tache, dans sa fenetre [date_min, deadline]."""
        dmin = tache.get('date_min')
        if isinstance(dmin, str):
            dmin = date.fromisoformat(dmin) if dmin else None
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

    def _placer_tache(tache):
        duree = int(tache.get('duree_min', 0))
        if duree <= 0:
            return
        secable = bool(tache.get('secable', True))
        min_bloc = max(5, int(tache.get('duree_min_bloc') or 30))
        preference = tache.get('preference', 'aucune')
        candidats = _jours_fenetre(tache)

        if not candidats:
            non_planifie.append({
                'tache_id': tache['id'], 'minutes_restantes': duree,
                'raison': 'aucun creneau disponible avant l\'echeance',
            })
            return

        if not secable:
            # Bloc unique : essayer chaque jour, du moins charge au plus charge.
            for pj in sorted(candidats, key=lambda p: (p.charge, p.jour)):
                pos = pj.placer_bloc_entier(duree, preference)
                if pos:
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

        # Tache secable : repartir en respectant l'equilibrage de charge.
        restant = duree
        chunk = _taille_chunk(duree, min_bloc, len(candidats), secable)
        epuises = set()
        while restant > 0:
            dispo = [p for p in candidats
                     if id(p) not in epuises and p.capacite_restante() > 0]
            if not dispo:
                break
            pj = min(dispo, key=lambda p: (p.charge, p.jour))
            voulu = min(restant, chunk)
            # Sur le dernier reliquat, ne pas exiger le chunk plein.
            blocs, places = pj.placer_secable(voulu, preference)
            if places <= 0:
                epuises.add(id(pj))
                continue
            for deb, fin in blocs:
                blocs_resultat.append({
                    'tache_id': tache['id'], 'date': pj.jour.isoformat(),
                    'heure_debut': _to_hhmm(deb), 'heure_fin': _to_hhmm(fin),
                    'duree_min': fin - deb,
                })
            restant -= places
            if pj.capacite_restante() <= 0:
                epuises.add(id(pj))

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
