"""Suivi des stagiaires accueillis au centre (migration 0075).

Un stagiaire porte ses études, son établissement, son tuteur dans la structure
et sa période de stage. Son emploi du temps est découpé en demi-journées, chacune
rattachée au secteur qui l'accueille : c'est ce qui permet d'annoncer l'arrivée
au responsable concerné.
"""


def creer_schema(conn):
    """Crée les deux tables sans altérer les données existantes."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS stagiaires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            etudes TEXT NOT NULL DEFAULT '',
            etablissement TEXT NOT NULL DEFAULT '',
            tuteur_id INTEGER,
            date_debut TEXT NOT NULL,
            date_fin TEXT NOT NULL,
            cree_par INTEGER,
            cree_le TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modifie_par INTEGER,
            modifie_le TEXT,
            CHECK (date_fin >= date_debut),
            FOREIGN KEY (tuteur_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (cree_par) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (modifie_par) REFERENCES users(id) ON DELETE SET NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS stagiaires_creneaux (
            stagiaire_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            demi_journee TEXT NOT NULL CHECK (demi_journee IN ('matin', 'apres_midi')),
            secteur_id INTEGER NOT NULL,
            PRIMARY KEY (stagiaire_id, date, demi_journee),
            FOREIGN KEY (stagiaire_id) REFERENCES stagiaires(id) ON DELETE CASCADE,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE
        )
    ''')
    # Lecture du fil d'actions : « qui arrive sur mon secteur demain ? ».
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_stagiaires_creneaux_secteur_date
        ON stagiaires_creneaux(secteur_id, date)
    ''')
