"""
Migration 0061 : type de bénévolat, date de fin et suivi des heures.

Trois besoins exprimés par le secteur bénévolat :

1. Le type de bénévolat (Gouvernance, Activité, Coup de pouce, et leurs
   combinaisons) n'était pas saisissable : colonne `type_benevolat`.
2. Un bénévole qui arrête n'avait pas de date de fin : colonne `date_fin`.
3. Le volume d'heures de bénévolat était tenu à la main, fiche par fiche,
   sur un classeur. Il est calculé à partir de deux modèles, ceux du
   classeur utilisé jusqu'ici :
   - « à la séance » : on liste les dates (les jours de CA par exemple) avec
     leur durée, et on coche les présents ; le total additionne les séances
     réellement suivies ;
   - « au forfait » : l'activité régulière est budgétée pour un volume annuel
     (café sénior « sur 80 h à l'année ») et on retranche les absences au
     prorata du nombre de séances de l'année.
   S'y ajoutent les heures ponctuelles hors activité suivie (« Autre » sur le
   classeur) : une date, un libellé, un nombre d'heures.
"""

NOM = "Type de bénévolat, date de fin et suivi des heures"
DESCRIPTION = (
    "Ajoute benevoles.type_benevolat et benevoles.date_fin, et crée les "
    "tables du suivi des heures : activites, seances, participations, "
    "presences et heures ponctuelles."
)


def upgrade(conn):
    """Applique la migration (idempotente)."""
    import sqlite3
    cursor = conn.cursor()

    for colonne, definition in (('type_benevolat', 'TEXT'), ('date_fin', 'TEXT')):
        try:
            cursor.execute(f"SELECT {colonne} FROM benevoles LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE benevoles ADD COLUMN {colonne} {definition}")

    # Activité suivie en heures, définie pour une année donnée : le volume et
    # le calendrier changent d'un exercice à l'autre.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS benevoles_activites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            annee INTEGER NOT NULL,
            mode TEXT NOT NULL DEFAULT 'seance',
            heures_seance REAL DEFAULT 0,
            volume_annuel REAL DEFAULT 0,
            nb_seances INTEGER DEFAULT 0,
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Séances datées d'une activité « à la séance » (les jours de CA).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS benevoles_seances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activite_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            heures REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (activite_id) REFERENCES benevoles_activites(id)
        )
    ''')

    # Bénévoles rattachés à une activité. `absences` ne sert qu'au mode
    # forfait ; en mode séance, la présence est détaillée séance par séance.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS benevoles_participations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activite_id INTEGER NOT NULL,
            benevole_id INTEGER NOT NULL,
            absences INTEGER NOT NULL DEFAULT 0,
            UNIQUE (activite_id, benevole_id),
            FOREIGN KEY (activite_id) REFERENCES benevoles_activites(id),
            FOREIGN KEY (benevole_id) REFERENCES benevoles(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS benevoles_presences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seance_id INTEGER NOT NULL,
            benevole_id INTEGER NOT NULL,
            present INTEGER NOT NULL DEFAULT 0,
            UNIQUE (seance_id, benevole_id),
            FOREIGN KEY (seance_id) REFERENCES benevoles_seances(id),
            FOREIGN KEY (benevole_id) REFERENCES benevoles(id)
        )
    ''')

    # Heures ponctuelles, hors activité suivie.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS benevoles_heures_autres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benevole_id INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            date TEXT,
            libelle TEXT,
            heures REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (benevole_id) REFERENCES benevoles(id)
        )
    ''')

    conn.commit()


def downgrade(conn):
    """Supprime les tables du suivi des heures.

    Les deux colonnes ajoutées à `benevoles` restent en place : SQLite ne
    supprime pas simplement une colonne, et elles sont inertes tant que le
    code ne les lit pas.
    """
    cursor = conn.cursor()
    for table in ('benevoles_presences', 'benevoles_participations',
                  'benevoles_seances', 'benevoles_heures_autres',
                  'benevoles_activites'):
        cursor.execute(f'DROP TABLE IF EXISTS {table}')
    conn.commit()
