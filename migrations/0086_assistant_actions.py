"""Rendez-vous et tâches préparés, confirmés explicitement par leur propriétaire."""
NOM = 'Assistant : rendez-vous et tâches préparés'
DESCRIPTION = 'Propositions chiffrées, révisions et exécution unique dans le planificateur personnel.'


def upgrade(conn):
    from schema_assistant_actions import creer_schema
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable pour conserver les propositions et leur historique.')
