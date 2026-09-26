# GitHub Copilot instructions for CS-PILOT

`AGENTS.md` est la source canonique des consignes applicables aux agents dans ce
dépôt. Copilot doit le lire avant toute intervention et le respecter dans son
intégralité. En cas de contradiction avec ce fichier, `AGENTS.md` prévaut.

## Indications spécifiques à Copilot

- Utiliser le contexte du dépôt et les fichiers proches avant de suggérer une
  nouvelle abstraction ; privilégier un diff petit et localisé.
- Pour une évolution de schéma, proposer une migration **Python** numérotée dans
  `migrations/` et la mise à jour du schéma final conformément à `AGENTS.md` ; les
  migrations de ce dépôt ne sont pas des fichiers SQL autonomes.
- Réutiliser les fixtures de `tests/conftest.py` dans les suggestions de tests.
- Conserver les textes destinés aux utilisateurs en français et suivre le style
  du fichier modifié.
- Ne jamais suggérer d'intégrer un secret, une donnée réelle ou le contenu d'un
  fichier `.env` dans le code, un test, une commande ou une pull request.
