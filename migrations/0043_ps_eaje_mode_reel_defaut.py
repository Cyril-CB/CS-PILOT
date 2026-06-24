"""
Migration 0043 : compatibilité prévisionnel/réel du simulateur PS EAJE.

Le sélecteur « Prév/Réel » par mois devient fonctionnel :
- en « réel » (comportement historique) les heures facturées / réalisées et la
  participation sont saisies, le taux d'occupation et le taux horaire sont
  calculés ;
- en « prévisionnel » le taux d'occupation (%) et le taux horaire sont saisis,
  les heures et la participation sont calculées.

Les simulations déjà enregistrées contiennent des saisies « réel » (heures),
mais leurs mois pouvaient porter l'ancienne valeur par défaut « prev » (qui
n'avait alors aucun effet). On force donc ces mois à « reel » afin de préserver
les totaux existants une fois le mode prévisionnel actif.
"""
import json

NOM = "Compat simulateur PS EAJE prév/réel"
DESCRIPTION = ("Force les mois des simulations EAJE existantes en mode 'reel' "
               "pour préserver les totaux après activation du mode prévisionnel.")


def upgrade(conn):
    """Bascule chaque mois des simulations EAJE existantes en mode 'reel'."""
    rows = conn.execute(
        "SELECT id, donnees FROM budget_ps_simulations WHERE type_ps = 'eaje'"
    ).fetchall()
    for row in rows:
        if not row['donnees']:
            continue
        try:
            donnees = json.loads(row['donnees'])
        except (ValueError, TypeError):
            continue
        if not isinstance(donnees, dict):
            continue
        mois = donnees.get('mois')
        if not isinstance(mois, list):
            continue
        changed = False
        for m in mois:
            if isinstance(m, dict) and m.get('prev_reel') != 'reel':
                m['prev_reel'] = 'reel'
                changed = True
        if changed:
            conn.execute(
                "UPDATE budget_ps_simulations SET donnees = ? WHERE id = ?",
                (json.dumps(donnees), row['id']),
            )
    conn.commit()


def downgrade(conn):
    """Pas de downgrade : le mode 'reel' reproduit le calcul historique."""
    conn.commit()
