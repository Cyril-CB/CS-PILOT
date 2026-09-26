# Investigation du forfait jours des directions en 2026

## Règle fournie par la carte

Pour un contrat de 210 jours, la carte fixe le repos forfait initial à
`365 − 104 − 25 − 8 − 9 − 210 = 9` jours en 2026. Les 9 jours fériés sont
des jours ouvrés chômés. Le quota initial doit rester fixe quand une absence
ou un repos est saisi ; le solde de repos disponible diminue lorsqu'un repos
forfait est pris.

## Sources et règles de mise à jour

- `utils.py`, `calculer_jours_ouvres` (lignes 572–600), compte les lundis à
  vendredis en excluant les dates de `jours_feries`.
- `utils.py`, `calculer_stats_forfait_jour` (lignes 603–667), fixe le contrat à
  210 jours, les congés payés à 25 et les congés conventionnels à 8. Il compte
  les jours fériés ouvrés présents en base, calcule le quota initial, puis
  agrège les types de `presence_forfait_jour`. Le type `forfait_jour` est compté
  avec `repos_forfait`. Le solde vaut quota initial moins repos saisis.
- `blueprints/forfait.py` initialise l'année consultée en `travaille` pour les
  jours ouvrés non fériés sans écraser les saisies existantes. Le tableau de
  bord appelle ensuite le calcul des statistiques.
- `blueprints/absences.py` (lignes 50–59 et 172–214) reporte une absence sur
  les jours ouvrés non fériés du calendrier : `Arrêt maladie` devient
  `maladie` et `Forfait jour` devient `forfait_jour`. La journée remplacée
  cesse donc de compter parmi les jours travaillés. Le tableau de bord affiche
  le repos pris, le solde et le quota dans
  `templates/dashboard_forfait_jour.html` (lignes 49–55).

## Scénario 2026 reproductible

Hypothèses : année complète initialisée pour un directeur, 9 jours fériés
ouvrés enregistrés dans `jours_feries`, aucune autre saisie. Une absence pour
maladie est ensuite reportée sur le 2 mars 2026, puis un repos « Forfait jour »
sur le 3 mars 2026 ; ces deux dates sont des jours ouvrés non fériés dans ce
scénario. L'année comporte 261 lundis à vendredis, soit 252 jours préremplis
`travaille` après exclusion des 9 jours fériés.

| Étape | Travaillés | Maladie | Repos pris | Quota initial calculé | Solde calculé | Quota attendu | Solde attendu |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Avant saisie | 252 | 0 | 0 | 0 | 0 | 9 | 9 |
| Après une journée de maladie | 251 | 1 | 0 | 0 | 0 | 9 | 9 |
| Après un repos « Forfait jour » | 250 | 1 | 1 | 0 | −1 | 9 | 8 |

Ces valeurs sont déduites des sources et des entrées du scénario ; elles ne
constituent pas un résultat de test exécuté pour cette investigation.

## Conclusion et suite envisagée

Le défaut de formule est confirmé : `calculer_jours_ouvres` retire déjà les
9 jours fériés, puis `calculer_stats_forfait_jour` les retire une seconde fois.
La formule actuelle donne `252 − 9 − 25 − 8 − 210 = 0`, contre
`252 − 25 − 8 − 210 = 9` selon la carte. Une correction ultérieure devrait
supprimer cette seconde déduction et vérifier par test que le quota reste à
9 après maladie et repos, tandis que le solde passe de 9 à 8 après le repos.
Le quota dépend aussi des jours fériés enregistrés : préciser comment figer
ou réviser le quota si ce calendrier change après l'initialisation de l'année.
