"""Catalogue initial et notifications internes, sans SMTP ni gestion du transport."""
from sites_acces import peut_lire_entretien

PRODUITS_INITIAUX = (
    ('Mouchoirs', 'boîte'), ('Essuie-mains', 'paquet'),
    ('Tablettes de lave-vaisselle', 'boîte'), ('Gants en latex', 'boîte'),
    ('Gel WC', 'flacon'), ('Nettoyant pour le sol', 'bidon'), ('Lessive', 'bidon'),
    ('Liquide vaisselle à la main', 'bouteille'), ('Vinaigre blanc', 'bouteille'),
    ('Papier toilette', 'paquet'), ('Savon pour les mains', 'flacon'),
    ('Lavettes bleues', 'paquet'), ('Lavettes blanches', 'paquet'), ('Lavettes roses', 'paquet'),
    ('Bicarbonate', 'paquet'), ('Film alimentaire', 'rouleau'), ('Éponges', 'paquet'),
    ('Sacs poubelle 100 litres', 'rouleau'), ('Sacs poubelle 50 litres', 'rouleau'),
    ('Sacs poubelle 10 litres', 'rouleau'), ('Gaze pour la poussière', 'paquet'),
    ('Spray nettoyant pour les surfaces', 'flacon'),
)


def initialiser_catalogue(conn, site_id):
    """Action explicite et rejouable : n'écrase pas un produit personnalisé."""
    conn.executemany('INSERT OR IGNORE INTO entretien_produits (site_id, nom, unite) VALUES (?, ?, ?)',
                     [(site_id, nom, unite) for nom, unite in PRODUITS_INITIAUX])


def notifications_non_lues(conn, user_id):
    rows = conn.execute('''
        SELECT d.*, n.created_at AS notification_date, s.nom AS site_nom
        FROM entretien_notifications n JOIN entretien_demandes d ON d.id = n.demande_id
        JOIN sites s ON s.id = d.site_id
        WHERE n.user_id = ? AND n.lu_le IS NULL AND d.statut = 'recue'
        ORDER BY n.created_at DESC, d.id DESC
    ''', (user_id,)).fetchall()
    return [r for r in rows if peut_lire_entretien(conn, user_id, r)]
