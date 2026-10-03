# Suivi des stagiaires

Le module répond à une demande du secteur Adulte-Famille-Séniors : tenir un
tableau des stagiaires accueillis au centre — des élèves de 3e en stage
d'observation, le plus souvent — et prévenir chaque responsable lorsque l'un
d'eux arrive sur son secteur.

## Qui y a accès

| Profil | Accès |
| --- | --- |
| Direction | lecture et écriture de toutes les fiches |
| Comptabilité | lecture et écriture de toutes les fiches |
| Responsable | lecture et écriture de toutes les fiches ; carte dans son fil pour son secteur |
| Salarié, prestataire | aucun accès, y compris par URL directe |

Les fiches ne sont pas cloisonnées par secteur : un stagiaire passe d'un
secteur à l'autre au fil de la semaine, son emploi du temps se construit donc à
plusieurs. La page se trouve dans la zone **Vie associative** (interface sans
menu), dans le menu latéral (**🎓 Stagiaires**) et par la barre intelligente
(« stagiaires », « stage de 3e », « tuteur du stagiaire »…).

## La fiche

- **Prénom, nom** : obligatoires.
- **Études** et **lieu d'études** : texte libre (suggestions : 3e, Seconde,
  Bac pro, CAP, BTS, BUT, Licence, Master).
- **Tuteur dans la structure** : un responsable (compte actif). Il peut rester
  « à désigner ». Si le compte du tuteur est désactivé ensuite, il reste
  affiché « (compte désactivé) » et la fiche peut toujours être corrigée sans
  en changer.
- **Premier et dernier jour** : obligatoires, période de 92 jours au plus
  (borne technique de la grille, pas une règle de stage).

Les stagiaires de 3e sont mineurs : la fiche se limite à ce qui sert à les
accueillir. Aucune coordonnée, date de naissance ni pièce n'est demandée.

## L'emploi du temps

Une fois la fiche créée, la page affiche chaque jour de la période — week-ends
compris, un centre pouvant accueillir le samedi — avec deux listes : **Matin**
et **Après-midi**. Chacune propose les secteurs du centre ; « — » signifie que
le stagiaire n'est pas au centre ce moment-là.

L'enregistrement remplace tout l'emploi du temps en une fois. Un secteur
supprimé entre-temps fait refuser l'enregistrement, la saisie restant affichée
pour être corrigée. Raccourcir la période sur la fiche retire les demi-journées
qui en sortent ; le message indique combien. Supprimer un secteur (Administration →
Secteurs) retire aussi les demi-journées qui lui étaient rattachées, le
message l'indique.

## L'annonce dans le fil

Le responsable dont le secteur accueille le stagiaire voit, dans son fil
d'actions (et dans « Actions à faire » du tableau de bord classique) :

> Demain, accueil d’un(e) stagiaire sur votre secteur : Léa Martin
> Toute la journée — 3e · Collège Jean Moulin — tuteur : Jean Martin

- La carte paraît **le jour même et la veille**. Du lundi au jeudi, la veille
  est le jour précédent. Le vendredi annonce tout ce qui arrive jusqu'au lundi
  inclus — samedi et dimanche compris, puisque personne ne consulte le fil le
  week-end ; le samedi et le dimanche annoncent de même jusqu'au lundi.
  Les jours fériés ne sont pas pris en compte.
- Une carte par stagiaire et par jour : matin et après-midi sur le même secteur
  donnent « Toute la journée ».
- Comme les autres familles du fil : deux cartes nommées au plus, puis « et N
  autres accueils de stagiaire » vers la liste.
- La carte est placée en tête des éléments du jour. **J’ai lu** la masque
  uniquement pour le responsable connecté et met à jour les compteurs du fil.
  La lecture persiste après rechargement, par stagiaire, jour et secteur ;
  elle ne supprime ni la fiche ni les annonces des autres responsables.
  La carte groupée liste les accueils concernés et permet de les marquer lus
  ensemble. Sans lecture, l’annonce disparaît une fois la date passée.
  Son étiquette dit le jour
  concerné (« Aujourd'hui », « Demain » ou le jour de la semaine).
- Seul le responsable du secteur d'accueil la reçoit (secteur de son compte).
  Le tuteur, qui est un responsable et a construit le planning, n'est pas
  prévenu à ce titre ; la direction non plus.

## Données et conservation

La migration **0075** ajoute `stagiaires` et `stagiaires_creneaux`. Le schéma
neuf et la migration utilisent `schema_stagiaires.creer_schema`. Les tables
sont déclarées dans `resilience.py` ; aucun fichier n'est stocké. La migration
**0076** ajoute les lectures personnelles (`stagiaires_annonces_lectures`),
avec le même schéma pour une installation neuve.

**Six mois après le dernier jour du stage, la fiche est anonymisée
automatiquement** (décision du centre), le jour anniversaire : un stage fini
le 1er avril est anonymisé le 1er octobre ; un stage fini le 31 août, le
28 (ou 29) février :

- le nom devient « Stagiaire-<numéro de fiche> », le prénom et le lieu
  d'études sont effacés ;
- le niveau d'études, la période, le tuteur et les secteurs d'accueil sont
  conservés pour le suivi d'activité ;
- la fiche n'est plus modifiable (le serveur refuse les écritures), seulement
  consultable et supprimable.

Sans planificateur externe, l'anonymisation tourne une fois par jour à la
première requête de l'application, quelle que soit la page ouverte
(`blueprints/stagiaires._anonymisation_quotidienne`), comme la synthèse
quotidienne de la direction. Une application arrêtée pendant des semaines
anonymise donc au redémarrage. Une fiche créée ou modifiée avec une date de
fin déjà échue est anonymisée immédiatement dans la même transaction, même
si le traitement quotidien a déjà eu lieu. Le message de confirmation le
précise et la fiche reste en lecture seule.

Les sauvegardes antérieures contiennent encore
les noms : leur durée de conservation relève de la politique de sauvegarde.

Sur un petit effectif, niveau d'études, dates et secteurs peuvent encore
permettre de reconnaître un stagiaire : c'est une pseudonymisation de
confort, pas une anonymisation au sens strict. La suppression d'une fiche
efface définitivement son emploi du temps.

## Limites connues

- Pas de pièce jointe (convention de stage) ni de coordonnées de
  l'établissement ou du représentant légal.
- Pas d'historique des modifications : seuls l'auteur et la date de la dernière
  modification sont conservés ; en cas d'édition simultanée, la dernière
  enregistrée l'emporte.
- Jours fériés et fermetures du centre ignorés.
- Délai de six mois fixé dans le code (`DELAI_ANONYMISATION_MOIS`), sans
  réglage dans les options.
