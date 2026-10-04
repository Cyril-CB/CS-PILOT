# Budget initial et actualisé : références et calculs

La direction et la comptabilité disposent également d’une
[construction détaillée de l’initial annuel](budget-initial.md) : lignes
identifiées, hypothèses et ventilation mensuelle/sectorielle. Son activation
et ses reports sont explicites ; elle ne convertit pas les budgets existants
et ne modifie pas l’actualisé. Les règles du parcours ci-dessous sont conservées.

Dans **Budget prévisionnel**, choisir l'année, le secteur et le type de budget.
Les paramètres sont propres à ce triplet : un réglage ne modifie pas les autres
secteurs ni les budgets d'autres années. Tous les numéros de comptes viennent
des données du centre ; aucun compte de cotisation précis n'est imposé.

## Choisir le réalisé et la référence annuelle

Dans « Référence annuelle, arrêté du réalisé et modes des comptes 63/64 » :

1. Pour l'actualisé, choisir le réalisé à retenir : fin juin, fin septembre,
   etc., ou « Aucun réalisé ». Une écriture future ne déplace plus cet arrêté.
2. Choisir une année de référence antérieure au budget, importée pour le secteur.
3. Confirmer que l'import couvre **l'exercice complet, régularisations incluses**.
   Cette confirmation porte sur cet import et ce périmètre analytique précis.
   Une réimportation ou un changement des données/périmètre impose une nouvelle
   vérification. La présence de mouvements dans douze mois n'est pas une preuve
   de clôture ; inversement, une charge annuelle peut n'avoir qu'un mouvement.

Le module ne déduit jamais qu'une année est complète de son seul numéro, et
n'invente pas de taux si la référence manque. Une référence indisponible laisse
les montants enregistrés intacts et signale les calculs à revoir. Le budget
initial porte sur les douze mois de l'année choisie ; l'actualisé conserve le
réalisé jusqu'à l'arrêté et projette seulement la suite.

## Brut de base, compléments et brut global

Le **premier compte 641**, dans l'ordre des comptes affichés, représente le brut
de base. Il peut être saisi directement dans « Budget [année] » ou alimenté par
le simulateur de paie. Le simulateur n'y ajoute pas les autres comptes 641.

Les autres 641 (indemnités, éléments variables…) ont leur propre mode :

| Mode | Comportement |
|---|---|
| Montant manuel | Montant annuel choisi, conservé lors des recalculs, y compris zéro. |
| Projection mensuelle | Réalisé à l'arrêté + projection des mois restants + ajustements de la fiche de travail. |
| Proportionnel au brut | Ratio annuel du complément au **premier 641**, appliqué au brut de base restant à prévoir. |

Le **brut global** est ensuite la somme de tous les 641. Un montant non renseigné
n'est pas assimilé à zéro : compléter les comptes 641 nécessaires avant le
calcul des charges.

## Charges 63/64

Chaque autre compte 63/64, y compris 649, est paramétrable directement dans le
module avec les mêmes trois modes. Par défaut il reste **manuel**. Aucun impôt,
cotisation, remboursement ou compte nouveau n'est lié au brut sans ce choix.

Pour une charge proportionnelle :

**Taux = montant du compte sur l'année complète de référence / total des 641
sur cette même année et ce même secteur.**

**Actualisé = charges réelles à l'arrêté + (brut global prévu − brut global
déjà réalisé) × taux annuel.**

Exemple : référence annuelle 48 000 € / 120 000 € = 40 %. Réalisé :
64 000 € de brut et 30 000 € de charges. Brut global annuel prévu : 130 000 €.
La charge actualisée vaut 30 000 + (130 000 − 64 000) × 40 % = **56 400 €**.

À fin décembre, les comptes automatiques proportionnels reprennent le réalisé :
il ne reste aucune période à projeter et aucun ratio n'est nécessaire.

## Saisir, calculer, contrôler

Modifier les montants ou commentaires, puis cliquer **Enregistrer les saisies
et recalculer**. Les lignes modifiées sont enregistrées ensemble ; les comptes
automatiques sont ensuite recalculés côté serveur si les montants ont changé.
Un commentaire seul conserve les montants enregistrés, sans report automatique.
Les choix d'année/secteur
sont bloqués pendant une saisie pour éviter un report dans un autre budget.
Annuler permet de retrouver la dernière version enregistrée.

Le changement vers un mode automatique autorise le remplacement du montant de
ce compte par son calcul. Le retour au mode manuel conserve le dernier montant.
Les autres comptes manuels ne sont jamais écrasés. La proposition, le taux et
ses deux montants de référence restent consultables. Une ancienne page est
refusée si les paramètres, sources, fiches de travail ou saisies ont changé.

Après un nouvel import du réalisé, consulter les propositions puis utiliser
**Recalculer et reporter les comptes automatiques**. Le module indique les
calculs devenus différents des montants enregistrés. Les fiches de travail et
montants manuels restent à examiner explicitement.

Le budget général additionne les budgets sectoriels et signale les arrêtés
différents. Le PDF utilise les valeurs enregistrées ; il indique les montants
non saisis et avertit lorsqu'un budget reste à compléter ou recalculer.

Les deux exports PDF — **secteur** et **budget global** — présentent les charges
puis les produits dans deux tableaux distincts. Chaque famille de comptes à deux
chiffres porte son sous-total (« Sous-total 60xxxx », « Sous-total 61xxxx »…) et
chaque section se termine par son total. La composition des colonnes est
inchangée : N-2, N-1, N, proposition et définitif au budget initial ; N-2, N-1,
budget initial, actualisé et écart au budget actualisé. Les sous-totaux ne sont
pas libellés par un intitulé comptable : le plan comptable du centre ne contient
pas nécessairement les comptes à deux chiffres, et aucun libellé n'est inventé.

Un montant manquant rend le total de sa catégorie, le total des charges ou des
produits concerné et le résultat **À compléter**. Les totaux entièrement
renseignés restent visibles ; un zéro saisi compte comme une valeur connue.
Cette règle s'applique aux propositions et aux montants définitifs, dans le
secteur, la consolidation et le PDF. Aucun écart de résultat n'est calculé
tant que le résultat actualisé est incomplet.

## Effacer tous les montants

Dans **Budget secteur**, la direction et la comptabilité disposent du bouton
**Effacer tous les montants**, pour l’initial comme pour l’actualisé. Enregistrer
ou annuler d’abord les saisies du tableau : l’action est bloquée tant qu’elles
ne sont pas traitées, sans les perdre. La confirmation rappelle le **secteur,
l’exercice et le type de budget** sélectionnés. Annuler cette confirmation
ne modifie rien.

Confirmer vide les montants définitifs **et temporaires enregistrés** de tous
les comptes de ce périmètre, y compris les zéros et les anciens temporaires
masqués derrière « Non renseigné ». L’enregistrement est immédiat et atomique :
il n’est pas nécessaire de cliquer ensuite sur Enregistrer. Le message de
réussite apparaît seulement après confirmation de l’enregistrement par le
serveur. Une erreur d’écriture annule l’ensemble ; en cas de réponse réseau
perdue, recharger pour vérifier l’état avant de réessayer. Les doubles clics
sont bloqués et une page périmée est refusée.

Les comptes et commentaires sont conservés, ainsi que les simulations de paie,
PS, fiches de travail et modes de calcul. **Abandonner une simulation reste
une action distincte.** Aucun recalcul ni report n’est lancé par l’effacement.
Des propositions calculées peuvent donc rester visibles ; elles ne sont pas
des montants enregistrés. Après rechargement, modifier seulement un commentaire
ne réenregistre pas ces propositions et ne repeuple pas les comptes automatiques.
Un nouveau report explicite ou une nouvelle saisie de montant peut les alimenter.

Les autres secteurs, exercices et types de budget, les écritures comptables,
la construction initiale détaillée et toutes les données RH restent inchangés.
Pour reporter depuis l’initial détaillé, recharger son rapprochement : une
simulation ou un mode automatique conservé continue de protéger son compte.

Recette sur base synthétique, avec Flask, SQLite et CSRF réels, si Playwright
et Chromium sont déjà disponibles :

```bash
python -m pytest tests/test_budget_effacement.py
PYTHON=/chemin/vers/python node tests/budget_effacement_live_checks.cjs
```

Le contrôle navigateur couvre ordinateur (1440 px) et mobile (390 px), les
deux types, les saisies non enregistrées, l’annulation, l’erreur réseau, les
doubles clics, l’attente de l’enregistrement, les commentaires et le rechargement.
Les captures sont écrites uniquement dans un dossier temporaire.

## Simulateur de paie

Les valeurs saisies et les scénarios restent dans le budget. **Enregistrer une
simulation ne modifie jamais la pesée, les compétences ou le maintien dans les
fiches salariés**, même en réouvrant une ancienne simulation. Pour modifier une
donnée RH réelle, utiliser la fiche salarié.

### Utiliser les taux de charges des salariés

La direction et la comptabilité peuvent saisir **T%Ch.** pour chaque salarié et
chaque ajout CDI/CDD, ainsi qu'un **taux global pour les CEE**. Cocher
**Utiliser les taux de charges par salarié** pour appliquer ces taux. L'option
est désactivée par défaut, y compris dans les simulations existantes.

Le taux d'un salarié s'applique à son brut total, quel que soit le compte 641.
Le budget ne ventilant pas les compléments 641 par salarié, ceux-ci sont
répartis au prorata des bruts simulés. Cela revient à calculer :

**Taux moyen = somme (brut simulé de chaque salarié × son taux, CEE compris)
/ somme des bruts simulés.**

Ce même taux moyen s'applique à **l'ensemble des comptes 641**, y compris les
indemnités et éléments variables saisis dans les autres 641. Exemple :
24 000 € à 40 % et 12 000 € à 20 % donnent 12 000 € de charges, soit un taux
moyen de 33,333… %. Avec 3 600 € de compléments 641, le brut global de
39 600 € donne **13 200 € de charges**. Le taux moyen affiché est arrondi pour
la lecture ; le calcul conserve sa précision et arrondit le report au centime.

Dans l'actualisé, la pondération utilise seulement les bruts simulés après
l'arrêté. Les **charges réalisées 645 à 648 sont conservées**, puis on ajoute
**(brut global annuel − brut global réalisé) × taux moyen**. À fin décembre,
seules les charges réalisées sont reprises. Le socle de salaire reste annuel :
le simulateur le divise par douze avant d'appliquer la durée du contrat.

Le total est reporté sur le **premier compte 645 du secteur**, dans l'ordre
des numéros de comptes. Tous les autres comptes **645, 646, 647 et 648** passent
à zéro dans le budget ; leurs écritures réalisées restent intactes. Les
comptes **63** et les autres comptes conservent leurs modes et leurs règles,
notamment la référence à une année complète pour le calcul proportionnel.

Saisir un taux entre **0 et 100 %** pour chaque ligne au brut simulé positif.
Un champ vide signifie « à compléter » ; saisir **0** si aucune charge n'est
prévue. Un compte 645 doit exister et les autres 641 doivent être renseignés.
Les refus n'enregistrent ni la simulation, ni le brut, ni une partie des charges.

Pendant l'utilisation des taux, les montants et modes 645 à 648 sont pilotés
par le simulateur. **Décocher l'option et reporter** restaure leurs anciens
montants manuels puis recalcule les comptes qui étaient automatiques. Les
commentaires et fiches de travail restent conservés. Les taux sont ignorés
quand l'option est décochée : une valeur invalide ne bloque pas ce retour au
mode habituel. Ils sont contrôlés à nouveau à la réactivation. Les taux sont mémorisés
avec la simulation, par année, secteur et type de budget ; ils ne changent
aucune fiche salarié. Aucune nouvelle migration ni reconnexion n'est requise.
Recharger la page après la mise à jour.

## Migration 0070

La migration ajoute uniquement les tables des paramètres et des modes. Elle est
idempotente et commune à une installation neuve et à une mise à jour. Les
montants, commentaires et simulations existants sont conservés. Aucun ancien
montant zéro n'est requalifié en donnée inconnue ; les nouvelles lignes sans
saisie utilisent une valeur distincte de zéro.

Aucun ancien arrêté ni aucune confirmation de complétude n'est inventé. Après
mise à jour, recharger les pages et paramétrer les budgets à poursuivre. Aucune
reconnexion générale n'est requise. Un retour arrière exige une sauvegarde
cohérente ; le downgrade refuse de supprimer ces paramètres silencieusement.

Les montants produits sont des estimations budgétaires. Ce chantier ne change
ni les règles de paie, ni les imports AIGA, ni les règles d'appartenance aux équipes.
