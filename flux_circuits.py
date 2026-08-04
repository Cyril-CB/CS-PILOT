"""
Le « Pourquoi ? » des cartes du fil : le circuit dans lequel s'inscrit une
décision, centré sur l'étape qui attend.

Une carte dit quoi faire. Elle ne dit pas ce qui est arrêté derrière. « Fiche à
valider — Marie Dupont » ne laisse pas deviner que la préparation de la paie
est à l'arrêt tant que ce n'est pas fait, ni qu'un CDD n'aura plus qu'un
bulletin pour se régulariser. Le circuit répond à cette question-là, et
seulement quand elle est posée : il est replié par défaut.

Trois principes de lecture :

- **le circuit se lit d'un coup d'œil.** Chaque étape porte le rôle qui la
  traite (couleur), ce qu'elle fait, et où elle en est — faite, en cours,
  à venir. Les liaisons nomment le geste qui mène à la suivante ;
- **l'étape courante prend le ton de la carte**, pas la couleur de son rôle :
  une décision en retard se signale en rouge jusque dans son circuit. Le rôle
  reste lisible sur sa pastille ;
- **la conséquence se dit en une phrase**, avec les vraies dates. C'est elle
  qui répond à « pourquoi c'est important » — le schéma seul ne le dit pas.

Certains circuits reçoivent une **alimentation annexe** : une étape peut
dépendre d'informations saisies ailleurs (les arrêts maladie de la
comptabilité nourrissent la préparation de paie). Elles se notent sur l'étape
concernée, pour montrer que l'application relie ces éléments.
"""
from datetime import date

# Rôle qui traite une étape → (libellé, couleur). Elle teinte la pastille ET
# le libellé : c'est ce qui permet de voir qui tient chaque étape sans lire.
# « Application » désigne ce que le logiciel fait seul, d'où son gris — rien
# n'est attendu de personne à cette étape.
#
# Tons moyens, choisis pour rester lisibles sur le beige clair du thème par
# défaut comme sur le vert sombre du thème nuit. Un vert profond, par exemple,
# disparaîtrait sur le second.
ROLES = {
    'salarie': ('Salarié', '#3d7fc1'),
    'responsable': ('Responsable', '#8b5cf6'),
    'direction': ('Direction', '#d97706'),
    'comptabilite': ('Comptabilité', '#10a37f'),
    'prestataire': ('Prestataire', '#6b7f95'),
    'application': ('Application', '#9aa0a6'),
}

# Profil du lecteur → rôle qu'il tient dans les circuits. Sert à dire « la
# vôtre » sur l'étape courante quand c'est bien lui qu'on attend.
_ROLE_DU_PROFIL = {
    'directeur': 'direction',
    'comptable': 'comptabilite',
    'responsable': 'responsable',
    'salarie': 'salarie',
    'prestataire': 'prestataire',
}


def _etape(role, titre, *lignes, liaison=None, note=None):
    """Une étape du circuit. `liaison` nomme le geste vers la suivante."""
    return {
        'role': role,
        'role_label': ROLES[role][0],
        'role_couleur': ROLES[role][1],
        'titre': titre,
        'lignes': [ligne for ligne in lignes if ligne],
        'liaison': liaison,
        'note': note,
    }


def _monter(intitule, etapes, courante, profil, consequence=None):
    """Assemble un circuit : pose les statuts et situe l'étape en attente.

    `courante` est l'index de l'étape qui attend (0-based). Tout ce qui
    précède est fait, tout ce qui suit est à venir. Un index hors bornes rend
    un circuit sans étape courante — le circuit se lit encore, il n'attend
    simplement plus personne.
    """
    for rang, etape in enumerate(etapes):
        if rang < courante:
            etape['statut'] = 'fait'
        elif rang == courante:
            etape['statut'] = 'courant'
        else:
            etape['statut'] = 'a_venir'

    a_moi = (0 <= courante < len(etapes)
             and etapes[courante]['role'] == _ROLE_DU_PROFIL.get(profil))
    return {
        'intitule': intitule,
        'etapes': etapes,
        'rang': courante + 1,
        'total': len(etapes),
        'a_moi': a_moi,
        'consequence': consequence,
    }


def _jours_depuis(valeur, today):
    """Nombre de jours écoulés depuis une date ISO, ou None."""
    if not valeur:
        return None
    try:
        depuis = date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None
    return (today - depuis).days


def _attente(jours):
    """« Neuf jours sans réponse » — ou rien si l'attente est fraîche."""
    if not jours or jours < 2:
        return None
    return f"{jours} jours sans réponse"


# ── Les six circuits ────────────────────────────────────────────────────────

def demande_conge(statut, date_demande, profil, today, nb_jours=None):
    """De la demande au planning et aux compteurs."""
    etapes = [
        _etape('salarie', 'Demande posée',
               f"{_fr_jours(nb_jours)} ouvré{'s' if (nb_jours or 0) > 1 else ''}"
               if nb_jours else None,
               liaison='soumet'),
        _etape('responsable', 'Validation responsable',
               'Vérifie la couverture du secteur', liaison='transmet'),
        _etape('direction', 'Décision',
               'Approuve ou refuse', liaison='met à jour'),
        _etape('application', 'Absence au calendrier',
               'Posée sur le planning de l\'équipe', liaison='alimente'),
        _etape('comptabilite', 'Compteurs et préparation de paie',
               'Solde décrémenté, congé visible en paie',
               note='Aussi alimentée par les arrêts maladie saisis en comptabilité'),
    ]
    courante = 1 if statut == 'en_attente_responsable' else 2

    jours = _jours_depuis(date_demande, today)
    attente = _attente(jours)
    consequence = None
    if attente:
        consequence = (f"{attente} : le salarié ne sait pas s'il part, et le "
                       "planning de son secteur se construit sur une hypothèse.")
    return _monter('De la demande au planning et aux compteurs.',
                   etapes, courante, profil, consequence)


def demande_recup(statut, date_demande, profil, today):
    """De la demande au report sur la fiche d'heures."""
    etapes = [
        _etape('salarie', 'Demande posée', liaison='soumet'),
        _etape('responsable', 'Validation responsable',
               'Vérifie le solde de récupération', liaison='transmet'),
        _etape('direction', 'Décision', 'Approuve ou refuse', liaison='reporte'),
        _etape('application', 'Récupération portée sur la fiche',
               'Journée posée, compteur décrémenté'),
    ]
    courante = 1 if statut == 'en_attente_responsable' else 2

    attente = _attente(_jours_depuis(date_demande, today))
    consequence = None
    if attente:
        consequence = (f"{attente} : la journée n'est ni posée ni décomptée, "
                       "et la fiche du mois reste incomplète.")
    return _monter('De la demande au report sur la fiche.',
                   etapes, courante, profil, consequence)


def fiche_heures(profil, today, nom=None, est_cdd=False, solde=None):
    """De la fiche d'heures au bulletin de paie."""
    heures = None
    if solde and solde > 0:
        heures = f"{solde:g} h au-delà du contrat".replace('.', ',')

    etapes = [
        _etape('salarie', 'Saisie du mois',
               'Journées saisies ou déclarées conformes', liaison='alerte'),
        _etape('responsable', 'Validation responsable',
               'Confirme ou corrige la fiche', liaison='transmet'),
        _etape('direction', 'Validation direction',
               heures or 'Confirme la fiche', liaison='verrouille'),
        _etape('application', 'Verrouillage',
               'La fiche devient le document de référence', liaison='alimente'),
        _etape('comptabilite', 'Préparation de la paie',
               'Heures à payer pour un CDD, à récupérer sinon',
               note='Aussi alimentée par les arrêts maladie saisis en comptabilité',
               liaison='transmet'),
        _etape('prestataire', 'Transmission au prestataire',
               'Export des variables de paie'),
    ]
    # La fiche n'est pas encore verrouillée : la décision attendue est celle
    # de la direction, après le passage du responsable.
    courante = 2

    # Ce qu'une fiche non validée bloque réellement — et ce qu'elle ne bloque
    # pas. Le compteur de récupération, lui, est tenu à jour dès la saisie :
    # la validation ne le conditionne pas. Ce qu'elle conditionne, c'est le
    # verrouillage du mois, donc l'existence d'une base arrêtée. Les heures
    # n'entrent en paie que si elles sont payées — le cas du CDD.
    if est_cdd:
        consequence = ("Non validée, la fiche part sans ses heures : pour un "
                       "CDD elles se paient, et il ne restera qu'un bulletin "
                       "pour régulariser.")
    else:
        consequence = ("Tant qu'elle n'est pas validée, le mois reste ouvert : "
                       "la fiche peut encore changer, et la préparation de la "
                       "paie n'a pas de base arrêtée.")
    return _monter('De la fiche d\'heures au bulletin de paie.',
                   etapes, courante, profil, consequence)


def facture(approbation, date_echeance, profil, today):
    """De l'import de la facture à son archivage comptable."""
    etapes = [
        _etape('application', 'Import et extraction',
               'Montants et fournisseur relevés', liaison='oriente'),
        _etape('comptabilite', 'Assignation',
               'Rattachée à un secteur ou à la direction', liaison='soumet'),
        _etape('direction', 'Approbation',
               'Direction ou responsable du secteur', liaison='génère'),
        _etape('application', 'Génération des écritures',
               'Écriture comptable en brouillon', liaison='soumet'),
        _etape('comptabilite', 'Validation comptable',
               'Contrôle et validation de l\'écriture', liaison='exporte'),
        _etape('comptabilite', 'Export Aiga et archivage',
               'La facture sort de l\'application'),
    ]
    courante = 2 if approbation == 'en_attente' else 4

    consequence = None
    jours = _jours_depuis(date_echeance, today)
    if jours is not None and jours > 0:
        consequence = (f"Échéance dépassée de {jours} jour(s) : le fournisseur "
                       "attend, et l'écriture comptable ne peut pas être générée.")
    elif jours is not None:
        consequence = (f"Payable dans {-jours} jour(s) : sans approbation, "
                       "l'écriture comptable ne part pas.")
    return _monter('De l\'import de la facture à son archivage.',
                   etapes, courante, profil, consequence)


def subvention(date_echeance, profil, today, etape_nom=None):
    """Du dossier déposé à la prochaine échéance."""
    etapes = [
        _etape('responsable', 'Dossier déposé',
               'Demande constituée et transmise', liaison='découpe'),
        _etape('application', 'Étapes datées',
               'Bilans, justificatifs, versements', liaison='ouvre'),
        _etape('direction', etape_nom or 'Étape en cours',
               'À traiter avant son échéance', liaison='appelle'),
        _etape('application', 'Prochaine échéance',
               'L\'étape suivante prend le relais'),
    ]
    courante = 2

    jours = _jours_depuis(date_echeance, today)
    consequence = None
    if jours is not None and jours > 0:
        consequence = (f"Échéance dépassée de {jours} jour(s) : un bilan remis "
                       "en retard peut coûter le versement du solde.")
    return _monter('Du dossier déposé à la prochaine échéance.',
                   etapes, courante, profil, consequence)


def fourniture(date_demande, profil, today, urgence=None):
    """De la demande déposée à la commande."""
    etapes = [
        _etape('salarie', 'Demande déposée',
               'Description, quantité et urgence', liaison='ouvre'),
        _etape('comptabilite', 'En cours de traitement',
               'Arbitrage et recherche du fournisseur', liaison='conclut'),
        _etape('comptabilite', 'Commandée ou annulée',
               'La demande sort de la file'),
    ]
    courante = 1

    consequence = None
    attente = _attente(_jours_depuis(date_demande, today))
    if attente and urgence == 'urgent':
        consequence = (f"{attente} sur une demande marquée urgente : "
                       "le salarié n'a pas de quoi travailler.")
    elif attente:
        consequence = f"{attente} : le demandeur ne sait pas si sa demande suit."
    return _monter('De la demande déposée à la commande.',
                   etapes, courante, profil, consequence)


def _fr_jours(nb):
    """« 5 jours » / « 1 jour », en notation française."""
    if not nb:
        return None
    entier = f"{nb:g}".replace('.', ',')
    return f"{entier} jour" + ('s' if nb > 1 else '')
