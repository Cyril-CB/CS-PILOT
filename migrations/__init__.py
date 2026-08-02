# Dossier de migrations de la base de donnees

# Liste de depart des fonctions proposees pour les salaries (migration 0064).
# Source unique : lue par la migration ET par la creation initiale du schema
# dans database.py, pour qu'une base neuve et une base migree partent du meme
# jeu. Elle n'est inseree qu'a la creation de la table : une fonction retiree
# par la direction ne reapparait pas au demarrage suivant.
FONCTIONS_INITIALES = [
    'Directeur',
    'Direction adjointe',
    'Comptable',
    'Responsable',
    'EJE',
    'Auxiliaire Puér.',
    'Aide Aux.',
    "Agent d'accueil",
    'Assist.Direction',
    'Accueil&Comm.',
    'Conseillé insertion',
    'Anim.Formateur',
    'Dir.Adjointe AL',
    'Entretien/restauration',
    'Entretien',
    'Gardien',
]
