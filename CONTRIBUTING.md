# Contribuer à CS PILOT

Ce document résume le circuit de contribution. Les règles complètes et
canoniques applicables aux agents se trouvent dans `AGENTS.md`.

## Branches de référence

- `main` est la branche stable utilisée pour la production.
- `dev` est la branche d'intégration des changements validés.
- Toute branche de travail doit être créée depuis un `dev` propre et à jour.
- Une branche traite une seule demande et les pull requests ciblent `dev`.
- Trois développements non intégrés au maximum peuvent être menés en parallèle.

Exemple de préparation :

```bash
git fetch origin
git switch dev
git pull --ff-only origin dev
git switch -c docs/decrire-le-changement
```

## Nommer une branche

Utiliser un nom court et descriptif avec l'un des préfixes suivants :

- `feat/` : nouvelle fonctionnalité ;
- `fix/` : correction ;
- `chore/` : maintenance ou gouvernance ;
- `docs/` : documentation uniquement ;
- `test/` : ajout ou amélioration de tests ;
- `refactor/` : restructuration sans changement fonctionnel attendu.

## Cycle de contribution

1. Créer une branche de travail depuis `dev` à jour.
2. Réaliser un changement ciblé et relire le diff.
3. Exécuter les contrôles et tests pertinents.
4. Créer un ou plusieurs commits cohérents.
5. Pousser uniquement la branche de travail.
6. Ouvrir une pull request vers `dev` et remplir sa checklist.
7. Répondre aux retours de revue sur la même branche.
8. Attendre la validation humaine.

Les agents ne fusionnent pas les pull requests et ne réalisent aucun
déploiement. Seul Cyril fusionne et déploie. Aucun agent ne pousse directement
vers `main` ou `dev`.

## Tests et contrôles

- Commencer par les tests ciblés, puis exécuter la suite pertinente avant la
  pull request.
- Exécuter `git diff --check`.
- Indiquer dans la pull request toutes les commandes réellement exécutées,
  leurs résultats, les tests ignorés et les prérequis absents.
- Pour une modification visuelle, contrôler le rendu sur ordinateur et mobile.
- Les tests utilisent uniquement des données synthétiques, des bases temporaires
  et des services simulés.

Les commandes usuelles sont documentées dans `AGENTS.md`.

## Migrations

Une évolution de schéma doit couvrir à la fois une installation neuve et une
base existante. Elle nécessite le schéma final dans `database.py`, une migration
Python numérotée dans `migrations/` et les tests adaptés. Ne jamais modifier une
migration déjà livrée ni appliquer une migration à des données réelles.

Une règle métier ambiguë ou une transformation potentiellement destructive doit
être clarifiée et validée humainement avant implémentation.

## Dépendances

Aucune dépendance ne peut être ajoutée ou mise à jour sans approbation humaine
explicite. Toute évolution approuvée doit être justifiée dans la pull request et
faire l'objet des contrôles de compatibilité appropriés.

## Documentation et catalogue fonctionnel

Mettre à jour `README.md` ou `docs/` lorsqu'une commande, une configuration ou
un parcours utilisateur change. Toute évolution fonctionnelle doit actualiser
les fiches concernées de `docs/agent-catalogue/`, puis être vérifiée avec :

```bash
python scripts/validate_feature_catalogue.py
```

Si le changement n'a aucun impact sur le catalogue, l'indiquer dans la pull
request au lieu de modifier artificiellement une fiche.
