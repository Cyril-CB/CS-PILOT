"""Ajout sans affectation automatique des demandes et délégations historiques."""
from schema_sites_approvisionnement import creer_schema

NOM = 'Sites physiques et produits d’entretien'
DESCRIPTION = 'Responsables par site/module, lieux demandeurs, catalogue, besoins et notifications de réception.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurer une sauvegarde cohérente pour conserver les demandes et leur historique.')
