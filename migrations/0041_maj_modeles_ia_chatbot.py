"""
Migration 0041 : mise à jour des identifiants de modèles IA.

Le catalogue des modèles Anthropic proposés a été modernisé
(claude-sonnet-4-6 / claude-opus-4-8 / claude-haiku-4-5). Le modèle de
l'assistant chatbot est persisté (chiffré) dans ``app_settings.chatbot_model``.
Si un directeur avait sélectionné un ancien identifiant, celui-ci n'est plus
proposé : sans remappage, l'assistant resterait « activé » mais renverrait
« Modèle inconnu ». Cette migration remappe la valeur persistée vers le nouvel
identifiant équivalent.
"""

NOM = "MAJ modèles IA (chatbot_model)"
DESCRIPTION = ("Remappe app_settings.chatbot_model des anciens identifiants "
               "Anthropic vers les nouveaux.")

# Ancien identifiant -> nouvel identifiant équivalent
OLD_TO_NEW = {
    'claude-sonnet-4-5-20250929': 'claude-sonnet-4-6',
    'claude-opus-4-6': 'claude-opus-4-8',
    'claude-haiku-4-5-20251001': 'claude-haiku-4-5',
}


def upgrade(conn):
    """Remappe la valeur chiffrée de chatbot_model si elle est obsolète."""
    # Les valeurs de app_settings sont chiffrées : on doit déchiffrer pour
    # comparer puis re-chiffrer la nouvelle valeur.
    from utils import encrypt_value, decrypt_value

    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = 'chatbot_model'"
    ).fetchone()
    if row:
        try:
            current = decrypt_value(row[0])
        except Exception:
            current = None
        new_model = OLD_TO_NEW.get(current)
        if new_model:
            conn.execute(
                "UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE key = 'chatbot_model'",
                (encrypt_value(new_model),),
            )
    conn.commit()


def downgrade(conn):
    """Pas de downgrade : le remappage est sans perte fonctionnelle."""
    conn.commit()
