"""
Options applicatives personnalisables par centre.
"""
from utils import get_setting, save_setting


OPTION_DEFINITIONS = {
    'saisie_afficher_declaration_conforme': {
        'label': 'Autoriser la déclaration conforme sur la saisie des heures',
        'description': (
            'Affiche la case "Je certifie avoir travaillé mes heures habituelles ce jour" '
            'sur la page de saisie des heures.'
        ),
        'default': True,
    },
    'vue_mensuelle_afficher_horaires': {
        'label': 'Afficher les horaires dans le détail journalier de la vue mensuelle',
        'description': (
            'Remplace les totaux d\'heures théoriques et réelles par les horaires '
            'théoriques et réels dans le tableau du mois.'
        ),
        'default': False,
    },
    'mon_equipe_masquer_motifs_absence_salaries': {
        'label': 'Masquer les motifs d\'absence sur Mon équipe pour les salariés',
        'description': (
            'Affiche simplement "Absent" à la place du motif détaillé sur la page '
            'Mon équipe pour les salariés uniquement.'
        ),
        'default': False,
    },
    'generation_contrats_responsable_autorise': {
        'label': 'Autoriser les responsables à accéder à la page Génération contrats',
        'description': (
            'Permet aux responsables d\'ouvrir la page de génération des contrats '
            'et d\'y accéder depuis l\'interface.'
        ),
        'default': True,
    },
    'budget_previsionnel_responsable_autorise': {
        'label': 'Autoriser les responsables à accéder à la page Budget prévisionnel',
        'description': (
            'Permet aux responsables d\'ouvrir la page Budget prévisionnel '
            'et d\'y accéder depuis l\'interface.'
        ),
        'default': True,
    },
}


def get_option_bool(key):
    """Retourne une option applicative sous forme de booléen."""
    definition = OPTION_DEFINITIONS.get(key, {})
    default = definition.get('default', False)
    value = get_setting(key)
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def set_option_bool(key, enabled):
    """Enregistre une option applicative booléenne."""
    save_setting(key, '1' if enabled else '0')


def get_options_context():
    """Retourne les options avec leur valeur courante pour l'affichage."""
    options = []
    for key, definition in OPTION_DEFINITIONS.items():
        options.append({
            'key': key,
            'label': definition['label'],
            'description': definition['description'],
            'value': get_option_bool(key),
        })
    return options
