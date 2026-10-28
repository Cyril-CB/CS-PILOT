"""Droits ALSH courants, communs aux routes et aux deux navigations."""


def droits_alsh(conn, user_id):
    """Pas de cache ni de confiance dans le profil/secteur envoyé par le client.

    Le secteur nommé exactement Enfance (casse/espaces ignorés) est ciblé :
    ni un autre accueil de loisirs ni la petite enfance n'héritent du droit.
    """
    refus = {'consulter': False, 'saisir_noe': False, 'configurer': False}
    if not user_id:
        return refus
    user = conn.execute('''
        SELECT u.profil, u.actif, s.nom AS secteur_nom
        FROM users u LEFT JOIN secteurs s ON s.id = u.secteur_id
        WHERE u.id = ?
    ''', (user_id,)).fetchone()
    if not user or user['actif'] != 1:
        return refus
    gestionnaire = user['profil'] in ('directeur', 'comptable')
    enfance = (user['profil'] == 'responsable'
               and (user['secteur_nom'] or '').strip().casefold() == 'enfance')
    return {'consulter': gestionnaire or enfance,
            'saisir_noe': gestionnaire or enfance, 'configurer': gestionnaire}
