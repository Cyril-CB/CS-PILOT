"""Étapes du circuit et confirmations historiques ; aucune écriture implicite."""
from utils import est_dans_equipe_responsable

ROLES = ('salarie', 'responsable', 'directeur')
LIBELLES_ETAPES = {'salarie': 'En attente de validation du salarié',
                   'responsable': 'En attente de validation du responsable',
                   'directeur': 'En attente de validation de la direction',
                   'termine': 'Fiche verrouillée'}


def creer_schema(conn):
    """Bascule unique : anciens verrous conservés, fiches ouvertes à resigner."""
    colonnes = {r[1] for r in conn.execute('PRAGMA table_info(validations)')}
    if 'circuit_version' not in colonnes:
        from fiches_versions import evenement
        conn.execute('ALTER TABLE validations ADD COLUMN circuit_version INTEGER NOT NULL DEFAULT 2')
        for row in conn.execute('SELECT * FROM validations').fetchall():
            circuit = 1 if row['bloque'] else 2
            evenement(conn, row['user_id'], row['annee'], row['mois'], 'bascule_circuit',
                      row['version_courante_id'], details={
                          'circuit_version': circuit,
                          'approbations_avant_bascule': [
                              {'role': r, 'nom': row[f'validation_{r}'], 'date': row[f'date_{r}'],
                               'version_id': row[f'version_{r}_id']} for r in ROLES
                              if row[f'validation_{r}']],
                          'verrouillage_conserve': bool(row['bloque']),
                      })
            if row['bloque']:
                conn.execute('UPDATE validations SET circuit_version=1 WHERE id=?', (row['id'],))
            else:
                conn.execute('''UPDATE validations SET version_salarie_id=NULL,
                                version_responsable_id=NULL, version_directeur_id=NULL WHERE id=?''', (row['id'],))
    conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_confirmation_historique_unique
                    ON fiches_evenements(user_id, annee, mois, version_id)
                    WHERE evenement='confirmation_historique' ''')


def accord_courant(v, role):
    if not v:
        return False
    return bool(v['version_courante_id'] and v[f'version_{role}_id'] == v['version_courante_id']
                and v[f'validation_{role}'])


def etape_courante(v):
    if v and v['bloque']:
        return 'termine'
    for role in ROLES:
        if not accord_courant(v, role):
            return role
    return 'termine'


def roles_applicables(conn, acteur_id, profil, cible_id):
    if acteur_id == cible_id:
        # Remplace l'ancienne dispense de responsable sur sa fiche personnelle
        # par deux approbations réellement enregistrées, même sans secteur.
        return ('salarie', 'responsable') if profil == 'responsable' else ('salarie',)
    roles = []
    if profil in ('responsable', 'directeur') and est_dans_equipe_responsable(conn, acteur_id, cible_id):
        roles.append('responsable')
    if profil == 'directeur':
        roles.append('directeur')
    return tuple(roles)


def planifier_signature(conn, acteur_id, profil, cible_id, v):
    """Plan complet avant écriture, ou refus ; les prérequis sont séquentiels."""
    possibles = roles_applicables(conn, acteur_id, profil, cible_id)
    if not possibles:
        return (), "Vous n'avez pas le droit de valider cette fiche"
    if v and v['bloque']:
        return (), 'Cette fiche est déjà verrouillée.'
    acquis = {r for r in ROLES if accord_courant(v, r)}
    plan = []
    for role in possibles:
        if role in acquis:
            continue
        precedents = ROLES[:ROLES.index(role)]
        if any(r not in acquis for r in precedents):
            manquant = next(r for r in precedents if r not in acquis)
            return (), LIBELLES_ETAPES[manquant] + ' sur la version courante.'
        plan.append(role)
        acquis.add(role)
    return tuple(plan), '' if plan else 'Votre approbation est déjà enregistrée sur cette version.'


def confirmation_historique(conn, v):
    if not v:
        return None
    return conn.execute('''SELECT * FROM fiches_evenements
                           WHERE user_id=? AND annee=? AND mois=? AND version_id=?
                             AND evenement='confirmation_historique' ''',
                        (v['user_id'], v['annee'], v['mois'], v['version_courante_id'])).fetchone()


def historique_a_confirmer(conn, v):
    return bool(v and v['bloque'] and v['circuit_version'] == 1
                and not accord_courant(v, 'salarie') and not confirmation_historique(conn, v))


def fiches_historiques_a_confirmer(conn, user_id=None):
    sql = '''SELECT v.*, u.nom, u.prenom FROM validations v JOIN users u ON u.id=v.user_id
             WHERE v.bloque=1 AND v.circuit_version=1 AND u.actif=1
               AND NOT (v.version_salarie_id IS NOT NULL AND v.version_salarie_id=v.version_courante_id
                        AND COALESCE(v.validation_salarie, '') != '')
               AND NOT EXISTS (SELECT 1 FROM fiches_evenements e WHERE e.user_id=v.user_id
                   AND e.annee=v.annee AND e.mois=v.mois AND e.version_id=v.version_courante_id
                   AND e.evenement='confirmation_historique')'''
    params = ()
    if user_id is not None:
        sql += ' AND v.user_id=?'
        params = (user_id,)
    return conn.execute(sql + ' ORDER BY v.annee, v.mois, u.nom, u.prenom', params).fetchall()


def destinataires_etape(conn, cible_id, v):
    """Acteurs actuellement habilités pour la prochaine étape, sans suppléance."""
    etape = etape_courante(v)
    if etape == 'termine':
        return etape, []
    if etape == 'salarie':
        return etape, conn.execute('SELECT * FROM users WHERE id=? AND actif=1', (cible_id,)).fetchall()
    candidats = conn.execute("SELECT * FROM users WHERE actif=1 AND profil IN ('responsable','directeur')").fetchall()
    return etape, [u for u in candidats if etape in roles_applicables(conn, u['id'], u['profil'], cible_id)]
