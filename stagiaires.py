"""Règles du suivi des stagiaires : fiche, emploi du temps et annonce d'arrivée.

Fonctions sans route ni session, pour être testées seules. Les routes
(`blueprints/stagiaires.py`) et le fil d'actions (`dashboard_actions.py`) s'y
réfèrent pour ne pas diverger.

Les stagiaires de 3e sont mineurs : la fiche se limite à ce qui sert à les
accueillir (nom, études, établissement, tuteur, période, secteurs). Aucune
coordonnée ni date de naissance n'est demandée.
"""
from datetime import date, timedelta
import re

# Direction, comptabilité et responsables tiennent ensemble les fiches : un
# stagiaire passe d'un secteur à l'autre, son emploi du temps se construit à
# plusieurs. Aucun autre profil n'y accède.
GESTIONNAIRES = ('directeur', 'comptable', 'responsable')

DEMI_JOURNEES = (('matin', 'Matin'), ('apres_midi', 'Après-midi'))
LIBELLES_DEMI_JOURNEES = dict(DEMI_JOURNEES)

# Borne technique de la grille (184 demi-journées au plus), pas une règle de
# stage : un stage d'observation de 3e dure quelques jours.
MAX_JOURS_STAGE = 92

# Simples propositions de saisie : le champ reste libre.
SUGGESTIONS_ETUDES = ('3e', 'Seconde', 'Bac pro', 'CAP', 'BTS', 'BUT', 'Licence', 'Master')

MAX_NOM = 80
MAX_ETUDES = 80
MAX_ETABLISSEMENT = 160

_JOURS = ('Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche')
_MOIS = ('', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
         'août', 'septembre', 'octobre', 'novembre', 'décembre')
_ENTIER = re.compile(r'[0-9]{1,18}')
_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')


def texte(valeur, maximum, libelle, obligatoire=False):
    """Texte d'une ligne, espaces normalisés ; ValueError si vide ou trop long."""
    propre = ' '.join(str(valeur or '').split())
    if obligatoire and not propre:
        raise ValueError(f'{libelle} : champ obligatoire.')
    if len(propre) > maximum:
        raise ValueError(f'{libelle} : {maximum} caractères au maximum.')
    return propre


def lire_date(valeur, libelle):
    """Date ISO (AAAA-MM-JJ) reçue du navigateur ; ValueError sinon."""
    brut = str(valeur or '').strip()
    if not brut:
        raise ValueError(f'{libelle} : champ obligatoire.')
    if not _DATE.fullmatch(brut):
        raise ValueError(f'{libelle} : date invalide.')
    try:
        jour = date.fromisoformat(brut)
    except ValueError:
        raise ValueError(f'{libelle} : date invalide.') from None
    if not 2000 <= jour.year <= 2100:
        raise ValueError(f'{libelle} : date invalide.')
    return jour


def lire_identifiant(valeur):
    """Entier positif reçu du navigateur, ou None s'il est vide ou illisible."""
    brut = str(valeur or '').strip()
    if not _ENTIER.fullmatch(brut):
        return None
    identifiant = int(brut)
    return identifiant if identifiant >= 1 else None


def valider_fiche(form, conn, tuteur_actuel=None):
    """Valide la fiche d'un stagiaire et renvoie les valeurs à enregistrer.

    Le tuteur doit être un compte actif du centre (pas le prestataire paie).
    Un tuteur déjà enregistré dont le compte a été désactivé depuis reste
    accepté tant qu'il n'est pas changé : corriger une date ne doit pas obliger
    à désigner un autre tuteur.
    """
    valeurs = {
        'nom': texte(form.get('nom'), MAX_NOM, 'Nom', obligatoire=True),
        'prenom': texte(form.get('prenom'), MAX_NOM, 'Prénom', obligatoire=True),
        'etudes': texte(form.get('etudes'), MAX_ETUDES, 'Études'),
        'etablissement': texte(form.get('etablissement'), MAX_ETABLISSEMENT,
                               "Établissement d'études"),
    }

    brut_tuteur = str(form.get('tuteur_id') or '').strip()
    tuteur_id = None
    if brut_tuteur:
        tuteur_id = lire_identifiant(brut_tuteur)
        if tuteur_id is None:
            raise ValueError('Tuteur inconnu. Rechargez la page avant de réessayer.')
        if tuteur_id != tuteur_actuel and not conn.execute(
                "SELECT 1 FROM users WHERE id = ? AND actif = 1 AND profil != 'prestataire'",
                (tuteur_id,)).fetchone():
            raise ValueError('Tuteur inconnu. Rechargez la page avant de réessayer.')
    valeurs['tuteur_id'] = tuteur_id

    debut = lire_date(form.get('date_debut'), 'Date de début')
    fin = lire_date(form.get('date_fin'), 'Date de fin')
    if fin < debut:
        raise ValueError('La date de fin doit suivre ou égaler la date de début.')
    if (fin - debut).days + 1 > MAX_JOURS_STAGE:
        raise ValueError(f'La période de stage est limitée à {MAX_JOURS_STAGE} jours.')
    valeurs['date_debut'] = debut.isoformat()
    valeurs['date_fin'] = fin.isoformat()
    return valeurs


def jours_du_stage(debut, fin):
    """Tous les jours de la période, bornes comprises (week-ends inclus).

    Aucun jour n'est écarté d'office : un centre peut accueillir le samedi.
    Une demi-journée laissée vide signifie simplement « pas au centre ».
    """
    debut = date.fromisoformat(str(debut)[:10])
    fin = date.fromisoformat(str(fin)[:10])
    return [debut + timedelta(days=i) for i in range((fin - debut).days + 1)]


def libelle_jour(jour):
    """date -> « Lundi 12 octobre »."""
    return f"{_JOURS[jour.weekday()]} {jour.day} {_MOIS[jour.month]}"


def nom_champ(jour, demi_journee):
    """Nom du champ de formulaire d'une demi-journée."""
    return f"creneau_{jour.isoformat()}_{demi_journee}"


def lire_emploi_du_temps(form, jours, secteurs_ids):
    """Demi-journées renseignées du formulaire : [(date ISO, demi-journée, secteur_id)].

    Seuls les jours de la période enregistrée sont lus, jamais une date fournie
    par le navigateur. Un secteur inconnu refuse tout l'enregistrement.
    """
    creneaux = []
    for jour in jours:
        for cle, _ in DEMI_JOURNEES:
            brut = str(form.get(nom_champ(jour, cle)) or '').strip()
            if not brut:
                continue
            secteur_id = lire_identifiant(brut)
            if secteur_id is None or secteur_id not in secteurs_ids:
                raise ValueError("Un secteur choisi n'existe plus. "
                                 "Rechargez la page avant de réessayer.")
            creneaux.append((jour.isoformat(), cle, secteur_id))
    return creneaux


def fin_fenetre_annonce(today):
    """Dernier jour annoncé dans le fil : le prochain jour du lundi au vendredi.

    Du lundi au jeudi, c'est le lendemain. Le vendredi et le week-end, la
    fenêtre s'étend jusqu'au lundi : l'arrivée du lundi s'annonce avant le
    week-end, pas le matin même. Les jours fériés ne sont pas pris en compte.
    """
    jour = today + timedelta(days=1)
    while jour.weekday() >= 5:
        jour += timedelta(days=1)
    return jour


def quand(jour, today):
    """« Aujourd'hui », « Demain » ou « Lundi 12 octobre »."""
    ecart = (jour - today).days
    if ecart == 0:
        return "Aujourd'hui"
    if ecart == 1:
        return 'Demain'
    return libelle_jour(jour)


def moment(demi_journees):
    """{'matin', 'apres_midi'} -> « Toute la journée », sinon la demi-journée."""
    demi_journees = set(demi_journees)
    if demi_journees >= {'matin', 'apres_midi'}:
        return 'Toute la journée'
    if 'matin' in demi_journees:
        return 'Matin'
    return 'Après-midi'
