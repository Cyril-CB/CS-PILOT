"""
Migration 0044 : distinguer deux types de PS ALSH (PERISCO / EXTRASCO).

Le simulateur PS gère désormais trois types : EAJE, ALSH PERISCO (périscolaire)
et ALSH EXTRASCO (extrascolaire / vacances). La contrainte CHECK de
budget_ps_comptes est reconstruite (SQLite ne permet pas de la modifier en
place) et les éventuels comptes déjà rattachés au type générique 'alsh' sont
basculés vers 'alsh_extrasco'.
"""

NOM = "Types PS ALSH (perisco / extrasco)"
DESCRIPTION = (
    "Reconstruit budget_ps_comptes pour autoriser les types alsh_perisco et "
    "alsh_extrasco et migre les comptes 'alsh' existants vers alsh_extrasco."
)


def upgrade(conn):
    """Reconstruit la table avec la nouvelle contrainte CHECK."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_ps_comptes_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL UNIQUE,
            type_ps TEXT NOT NULL CHECK(type_ps IN ('eaje', 'alsh_perisco', 'alsh_extrasco')),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Copier en remappant l'ancien type générique 'alsh' -> 'alsh_extrasco'
    cursor.execute('''
        INSERT OR IGNORE INTO budget_ps_comptes_new (id, compte_num, type_ps, updated_at)
        SELECT id, compte_num,
               CASE WHEN type_ps = 'alsh' THEN 'alsh_extrasco' ELSE type_ps END,
               updated_at
        FROM budget_ps_comptes
    ''')
    cursor.execute('DROP TABLE budget_ps_comptes')
    cursor.execute('ALTER TABLE budget_ps_comptes_new RENAME TO budget_ps_comptes')


def downgrade(conn):
    """Rebascule vers la contrainte d'origine ('eaje', 'alsh')."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_ps_comptes_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL UNIQUE,
            type_ps TEXT NOT NULL CHECK(type_ps IN ('eaje', 'alsh')),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO budget_ps_comptes_old (id, compte_num, type_ps, updated_at)
        SELECT id, compte_num,
               CASE WHEN type_ps IN ('alsh_perisco', 'alsh_extrasco') THEN 'alsh' ELSE type_ps END,
               updated_at
        FROM budget_ps_comptes
    ''')
    cursor.execute('DROP TABLE budget_ps_comptes')
    cursor.execute('ALTER TABLE budget_ps_comptes_old RENAME TO budget_ps_comptes')
