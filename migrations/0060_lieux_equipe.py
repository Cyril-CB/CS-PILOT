"""Lieux habituels d'intervention de l'equipe, activation facultative."""
NOM = "Lieux d'intervention facultatifs"
DESCRIPTION = "Activation par responsable et affectations hebdomadaires, sans planning."
def upgrade(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS lieux_equipe_options (
      responsable_id INTEGER PRIMARY KEY, actif INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS lieux_equipe_affectations (
      responsable_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
      jour INTEGER NOT NULL CHECK(jour BETWEEN 0 AND 4),
      demi_jour TEXT NOT NULL CHECK(demi_jour IN ('matin','aprem')),
      lieu TEXT NOT NULL,
      PRIMARY KEY(responsable_id,user_id,jour,demi_jour))""")
    conn.commit()
def downgrade(conn):
    pass
