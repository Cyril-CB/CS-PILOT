## Objet et périmètre

<!-- Décrire le besoin, le changement réalisé et ce qui reste hors périmètre. -->

- [ ] La pull request traite une seule demande et cible `dev`.
- [ ] Le diff est limité aux fichiers nécessaires et a été relu intégralement.

## Risque et utilisateurs concernés

**Niveau de risque :** faible / modéré / élevé

**Profils utilisateurs concernés :** salarié / responsable / comptable / directeur / prestataire / aucun

<!-- Justifier le niveau de risque, notamment pour les domaines sensibles. -->

## Données et migrations

- [ ] Aucune migration n'est nécessaire.
- [ ] Les migrations éventuelles sont décrites et testées sur une base temporaire.
- [ ] Le changement reste compatible avec une base existante.
- [ ] Aucune migration ou transformation n'a été appliquée à des données réelles.

<!-- Décrire les migrations, la compatibilité et le retour arrière éventuel. -->

## Tests et validations

- [ ] Les tests positifs pertinents ont été exécutés.
- [ ] Les tests négatifs pertinents ont été exécutés.
- [ ] `git diff --check` réussit.

**Commandes exécutées et résultats :**

```text
À compléter
```

**Tests ignorés, échecs ou prérequis absents :**

```text
Aucun, ou préciser
```

## Documentation et catalogue

- [ ] La documentation a été actualisée lorsque nécessaire.
- [ ] Le catalogue fonctionnel a été actualisé et validé lorsque nécessaire.
- [ ] Aucun changement de catalogue n'est nécessaire, avec justification ci-dessous.

<!-- Lister les documents et IDs du catalogue modifiés, ou justifier l'absence d'impact. -->

## Interface

- [ ] Aucune interface n'est modifiée.
- [ ] Le rendu a été contrôlé sur ordinateur et mobile.
- [ ] Les états vide, erreur, survol, focus et les libellés français ont été vérifiés lorsque pertinents.

## Sécurité et revue humaine

- [ ] Aucun secret, fichier `.env`, jeton, donnée réelle, base, archive, sauvegarde, journal métier ou artefact local n'est ajouté.
- [ ] Aucun service réel ou payant n'a été appelé pendant les tests.
- [ ] Aucune dépendance n'est ajoutée ou mise à jour sans approbation humaine explicite.
- [ ] Une validation humaine est requise avant fusion.
- [ ] Cette pull request ne sera ni fusionnée ni déployée par un agent.
