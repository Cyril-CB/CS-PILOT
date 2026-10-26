# Journée de solidarité

## Choisir la date annuelle

Dans **Gestion des jours fériés**, la direction ou la comptabilité désigne
un férié avec **Désigner comme solidarité**. Au maximum une date du lundi au
vendredi est désignée par année ; choisir une autre ligne remplace le choix
précédent. **Retirer la solidarité** retire une désignation non encore utilisée.

Le 15 août n'est jamais désigné ni reporté automatiquement. S'il tombe le
week-end, choisissez le férié de remplacement retenu pour cette année. Les
autres fériés, le calendrier général et le quota de repos forfait ne changent pas.

Définir cette date **avant** les demandes/absences concernées. Une demande ou
absence couvrant l'ancienne ou la nouvelle date, une récupération saisie ou une
saisie forfait explicite empêche la reconfiguration. Corriger les éléments
signalés d'abord ; aucune demande, absence ou compteur n'est recalculé en masse.
La suppression du férié désigné est protégée de la même façon.

## Poser le congé

Utiliser le circuit habituel : **Congé payé** (cas habituel) ou **Congé
conventionnel**. Le choix reste possible même si des CP sont disponibles :
il n'existe pas de bascule automatique de compteur ni de contrôle d'épuisement
préalable des CP. Les alertes existantes de solde négatif restent applicables.

- La solidarité compte comme **un jour entier** de CP ou CC, y compris si
  elle se trouve à l'intérieur d'une période plus longue. Pas de double décompte.
- Comme les congés actuels, le calcul repose sur lundi–vendredi ; il n'ajoute
  pas de prorata selon le planning individuel ni de gestion de demi-journées.
- Les autres fériés et les week-ends restent exclus.
- Le responsable puis la direction/comptabilité conservent leur circuit de
  validation. La direction au forfait conserve l'auto-validation.
- Après validation, l'absence, le compteur et la projection au calendrier sont
  enregistrés ensemble. Une nouvelle validation n'impute pas une seconde fois.
- Une saisie depuis **Absences** applique la même règle. Son aperçu tient compte
  du motif ; les autres motifs conservent leur exclusion des fériés.
- L'annulation depuis **Absences** restitue le compteur imputé et retire la
  projection. La direction suit ses congés dans le forfait, sans toucher aux
  colonnes CP/CC des salariés horaires.

**Pas de récupération**, ni journée entière ni créneau partiel. Une demande
englobant la date est refusée en totalité : séparer les récupérations autour
et poser un CP/CC sur la solidarité. La validation d'une ancienne demande et
la saisie directe d'une journée de récupération sont également contrôlées.

Les aperçus de **Mon espace**, de **Saisie des absences** et les calendriers
salarié/forfait reprennent le décompte ou le libellé de solidarité. Le calcul
partagé sert au décompte, au report et aux projections de solde de la direction.
Les modules hors congés continuent à considérer cette date comme fériée ;
aucune refonte de l'annualisation, des réservations ou de la cible forfait n'est incluse.

## Migration 0081

Ajout de `jours_feries.solidarite` (0/1, défaut 0) et d'un index unique partiel
sur l'année désignée. Schéma partagé entre installation neuve et migration,
idempotent. Aucune date présélectionnée, reprise de congés ou transformation
de compteur. Les lignes et colonnes préexistantes sont préservées.

Le calcul partagé des fiches reste compatible avec un schéma sans la colonne
`solidarite` : lors de la reprise historique par 0065, son absence signifie
qu'aucun férié n'est désigné. La migration 0081 peut ensuite s'appliquer sans
modifier les versions, événements, signatures ni heures reconstruits. Les
migrations historiques restent inchangées.

Le retour arrière refuse une désignation encore active ; sans désignation,
il retire l'index et conserve la colonne additive afin de ne pas reconstruire
la table. La sauvegarde couvre la table `jours_feries` existante ; aucune
nouvelle catégorie de fichier ou dépendance n'est ajoutée.

## Vérification

`tests/test_solidarite.py` couvre configuration/droits/week-ends, compteur CP/CC,
validation/idempotence/annulation, saisie manuelle, forfait, période englobante,
refus des récupérations, conservation des dates utilisées et migration.
Les tests HTTP utilisent les bases temporaires des fixtures ; ils ne prouvent
ni une mise à niveau ni un déploiement sur l'installation de production.

### Contrôles réalisés sur la branche

- Test de régression initial : demande CP sur un férié désigné refusée avant
  correctif, puis acceptée après ; 46 nouveaux cas dans `test_solidarite.py`.
- Suite complète après correction du P2 de reprise historique : **2 885 cas
  distincts réussis**, quatre lots (722, 721, 721 et 721 cas) répartis par
  fichiers de tests et pondérés par leur nombre de cas, sans échec, erreur ou test
  ignoré. L'union exacte des cas JUnit a été comparée à la collecte pytest.
- Reprise historique sans colonne `solidarite`, versions/signatures/heures
  préservées et application ultérieure de 0081 : 106 tests ciblés réussis ;
  régression reproduite en échec avant correctif, migrations livrées inchangées.
- Contrôle ciblé RH/forfait/saisie initial : 148 cas réussis ; après l'ajustement mobile
  du tableau des absences, 126 cas de congés, absences et interface réussis.
- Catalogue : 101 fonctionnalités, six domaines et 67 blueprints couverts.
- Chromium isolé : 1 440 et 390 px, habillages flux et téléphone classique ;
  désignation/rechargement, aperçu CP/CC, avertissement récupération,
  demande salarié, validation direction, refus de reconfiguration après
  application, calendrier et aperçu Absences. Aucune erreur JavaScript ;
  aucun débordement horizontal de la page (les tableaux défilent localement).
- Captures inspectées à l'état final des animations. CSRF et limitation de
  débit conservés dans le parcours navigateur. Aucun service externe sollicité.
- `compileall`, validation du catalogue et `git diff --check` réussis.

Ces vérifications sont isolées et synthétiques. La PR n'est ni une fusion,
ni un déploiement, ni une validation du fonctionnement au centre.
