# Modèles IA

Catalogue vérifié le 15 novembre 2026 pour l’assistant RH et la pesée ALISFA.
L’assistant flottant sur toutes les pages, ses routes `/api/chatbot/*` et son
réglage d’activation sont supprimés. Les anciennes préférences `chatbot_model`
ne sont plus lues ; aucune clé ni donnée existante n’est effacée.

- OpenAI : GPT-5.4, GPT-5.5 (choix conseillé), GPT-5.6 Sol/Terra/Luna,
  GPT-6 Sol/Luna, GPT-6.1 Sol/Terra. Pas de mini, nano, Astra ni de variante Pro.
- Claude : Sonnet 5.5 (choix conseillé), Opus 5.5 et Haiku 5.5. Pas de Fable.
- Groq : `openai/gpt-oss-120b` et `qwen/qwen3.8-27b` (préversion).

Les menus sont alimentés par le même catalogue et filtrés selon les clés
configurées. Les anciennes valeurs admises par les modules métier passent à un
modèle actuel du même fournisseur. Le choix d’un modèle inconnu reste refusé.
Il n’y a pas de migration de base pour cette évolution.

OpenAI utilise `max_completion_tokens` et l’effort configuré (medium par défaut),
sans température ni seed pour GPT-5/6. Les appels structurés demandent du JSON.
Claude 5.5 omet temperature/top_p/top_k ; seuls les blocs texte sont lus, même
si un bloc de raisonnement les précède. Groq utilise un effort medium et
`include_reasoning: false` pour GPT-OSS, `reasoning_format: hidden` pour Qwen,
afin de garder une réponse finale exploitable en texte ou JSON.

L’enregistrement d’une clé la vérifie avec GPT-5.4, GPT-OSS 120B ou Haiku 5.5.
Une réponse 429 n’établit pas la disponibilité du quota. Les tests automatisés
simulent les fournisseurs, sans appel payant ni lecture des clés existantes.

Références officielles :

- [OpenAI, catalogue API](https://developers.openai.com/api/docs/models/all)
- [Claude, catalogue et identifiants](https://platform.claude.com/docs/en/models/overview)
- [Groq, modèles](https://console.groq.com/docs/models)
- [Groq, paramètres de raisonnement](https://console.groq.com/docs/reasoning)

Les clés API sont saisies dans des champs dédiés, masqués visuellement, sans
champ de type mot de passe. Chaque fournisseur possède son propre formulaire
avec autoremplissage désactivé. La recherche est identifiée comme une recherche
et isolée : le navigateur ne doit pas la traiter comme un identifiant associé
aux clés. La connexion conserve son formulaire habituel.
