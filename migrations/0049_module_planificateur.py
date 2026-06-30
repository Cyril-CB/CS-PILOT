"""
Migration 0049 : Module Planificateur de taches (Time Blocking).

Ajoute les tables du gestionnaire de taches inspire de FlowSavvy :
- planif_recurrences : definitions des taches recurrentes ;
- planif_taches      : taches et evenements fixes (rendez-vous, reunions) ;
- planif_blocs       : blocs de temps calcules par le moteur d'optimisation ;
- planif_horaires    : horaires de travail par salarie et par jour.

Le planning est strictement prive : chaque utilisateur ne voit que ses
propres taches et blocs (aucun acces transversal, meme pour la direction).
"""

NOM = "Module Planificateur de taches"
DESCRIPTION = (
    "Ajoute les tables planif_recurrences, planif_taches, planif_blocs et "
    "planif_horaires pour le gestionnaire de taches avec planification "
    "automatique (Time Blocking)."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS planif_recurrences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            titre TEXT NOT NULL,
            description TEXT DEFAULT '',
            duree_min INTEGER DEFAULT 30,
            priorite TEXT DEFAULT 'normale',
            preference TEXT DEFAULT 'aucune',
            secable INTEGER DEFAULT 0,
            duree_min_bloc INTEGER DEFAULT 30,
            frequence TEXT NOT NULL DEFAULT 'hebdomadaire',
            jour_semaine INTEGER,
            jour_mois INTEGER,
            date_debut TEXT NOT NULL,
            date_fin TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS planif_taches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL DEFAULT 'tache',
            titre TEXT NOT NULL,
            description TEXT DEFAULT '',
            couleur TEXT DEFAULT '',
            duree_min INTEGER DEFAULT 60,
            deadline TEXT,
            date_min TEXT,
            priorite TEXT DEFAULT 'normale',
            preference TEXT DEFAULT 'aucune',
            secable INTEGER DEFAULT 1,
            duree_min_bloc INTEGER DEFAULT 30,
            date_fixe TEXT,
            heure_debut TEXT,
            heure_fin TEXT,
            statut TEXT DEFAULT 'a_faire',
            recurrence_id INTEGER,
            occurrence_jour TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (recurrence_id) REFERENCES planif_recurrences(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_planif_taches_user ON planif_taches(user_id, statut)'
    )

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS planif_blocs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tache_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            heure_debut TEXT NOT NULL,
            heure_fin TEXT NOT NULL,
            duree_min INTEGER NOT NULL,
            statut TEXT DEFAULT 'planifie',
            verrouille INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tache_id) REFERENCES planif_taches(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_planif_blocs_user_date ON planif_blocs(user_id, date)'
    )

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS planif_horaires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            jour_semaine INTEGER NOT NULL,
            actif INTEGER DEFAULT 1,
            matin_debut TEXT,
            matin_fin TEXT,
            aprem_debut TEXT,
            aprem_fin TEXT,
            UNIQUE(user_id, jour_semaine),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()


def downgrade(conn):
    """Annule la migration."""
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS planif_blocs')
    cursor.execute('DROP TABLE IF EXISTS planif_taches')
    cursor.execute('DROP TABLE IF EXISTS planif_recurrences')
    cursor.execute('DROP TABLE IF EXISTS planif_horaires')
    conn.commit()
