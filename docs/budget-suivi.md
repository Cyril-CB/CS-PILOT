# Initial figé et suivi en direct — lot 2

## Parcours

Depuis l’initial détaillé ou le budget prévisionnel, ouvrir **Vérifier et figer
l’initial**, choisir l’exercice et contrôler tous les secteurs et comptes.
Le gel reprend **les définitifs enregistrés**, une fois, sans report ni recalcul
implicite. L’écran montre proposition, retenu, divergences et manuels conservés.
Les montants manquants, calculs à actualiser et lignes de construction à revoir
bloquent le gel. Un secteur vide doit recevoir ses comptes vérifiés, avec des
zéros explicites si nécessaire. Un compte non pertinent peut être retiré dans
le parcours initial avant vérification ; le gel ne devine pas son inutilité.

Après confirmation de l’exercice complet et saisie d’un motif, une version
indépendante conserve les montants, les libellés, secteurs, UUID de construction,
hypothèses, taux, ventilations mensuelles, calculs expliqués, méthodes,
simulations et fiches de travail disponibles. La date et l’identifiant de
l’auteur sont conservés. Les données RH ou paramètres ultérieurs n’interviennent
plus dans son calcul. L’ancien budget de travail reste modifiable.

Un nouveau gel constitue une **correction versionnée**. Il ne change jamais
la référence d’un suivi existant. Dans le suivi, **Changer explicitement la
référence** exige une autre version du même exercice et un motif. Cette action
conserve les événements, recalcule les écarts liés à l’initial choisi et inscrit
l’ancienne et la nouvelle référence dans l’historique. Une référence qui ne
couvre plus un élément lié actif est refusée : annuler ou revoir cet élément
explicitement d’abord. Les instantanés antérieurs restent identiques.

## Ajustements et calcul

Direction et comptabilité saisissent libellé, charge/recette, compte général,
secteur, période dans l’exercice, montant annuel, état estimé/confirmé/à compléter.
Note et référence textuelle du justificatif sont facultatives ; il n’y a pas
de nouvel espace de téléversement. Pour un élément nouveau, le montant est positif : la nature fixe le
signe. Un total de remplacement lié à l’initial peut être signé (par exemple
un remboursement déjà prévu sur un compte de charges). Le calcul utilise Decimal, arrondi au centime à la saisie, HALF_UP.

- Élément non prévu : charge de 300 € → impact −300 € ; recette → +300 €.
- Élément prévu de 1 200 €, nouveau total annuel 1 500 € : charge → −300 €.
  Le montant saisi est le nouveau total de l’élément choisi, pas son écart.
- La période décrit l’événement, sans prorata automatique ni multiplication.
- Une révision remplace l’impact de l’UUID existant. Elle ne s’additionne pas aux
  anciennes versions. Une annulation ramène son impact à zéro, en conservant
  toutes les versions. Modifier un annulé le réactive explicitement.
- Vide reste inconnu : état forcé « à compléter », impact indéterminé et alerte.
  Le courant affiche initial + impacts connus, explicitement **provisoire**.
  Un état « à compléter » avec montant connu conserve également l’avertissement.

Les liens possibles portent sur un compte initial entier ou un élément détaillé
(UUID de ligne, secteur, compte). Une base détaillée n’est proposée que si la
somme des propositions détaillées correspond au définitif retenu du compte.
En cas de manuel divergent, seule la base du compte entier est certaine ;
aucune ventilation du montant retenu n’est inventée. Les éléments d’une même
ligne sur un même compte/secteur sont regroupés. On ne peut suivre simultanément
le compte entier et l’un de ses détails, ni deux fois le même élément.

Un changement de secteur ou de compte d’un événement exige annulation puis
nouvel événement, afin que le périmètre de tout son historique reste stable.
Les nouveaux comptes doivent appartenir au plan général (classe 6/7). Les
comptes déjà figés restent utilisables s’ils ont été retirés du plan courant.

## Droits et exports

Direction/comptabilité : lecture consolidée et filtrée, création des gels,
ajustements, changements de référence et instantanés. Responsable : lecture de
son secteur courant, déterminé côté serveur ; pas d’écriture ni de choix d’un
autre secteur. Ce nouveau suivi est accessible aux responsables indépendamment
de l’option de l’ancien budget prévisionnel. Les profils salarié et prestataire
n’y accèdent pas.

Pour les responsables, aucun détail initial nominatif, auteur, texte libre,
référence de justificatif ou identifiant de source métier n’est transmis. Les
libellés d’ajustement sont remplacés par le compte ; l’historique ne contient
que montant, état, annulation, type d’origine et date/révision. Les synthèses
sectorielles salariales restent visibles, sans détail individuel.

Le suivi indique version/date de référence, date de dernière variation,
initial/courant/écart, synthèse par rubrique et détail prévu/courant/impact/
origine/historique. Les sources **non connectées** sont distinctes d’aucune
variation manuelle. Les filtres portent sur exercice et secteur.

**Créer un instantané daté et ses PDF** archive le contenu sélectionné et les
octets exacts des PDF synthèse/détail, dans une transaction. Les téléchargements
ultérieurs utilisent ces octets ; ni nouveau calcul ni données courantes ne
modifient le document. Les PDF indiquent les incomplets et sources non connectées.
Les archives et PDF détaillés restent réservés à direction/comptabilité car
ils peuvent contenir des notes confidentielles. Pas d’envoi automatique au CA.

## Contrat des raccordements futurs — non activés

Aucun connecteur, synchronisation ou création de dossier n’est livré dans ce
lot. Les sources affichent « Non connectée », y compris lorsqu’aucun ajustement
n’a été enregistré. Le modèle conserve :

- version du gel, compte/secteur et identifiant stable `année:secteur:compte` ;
- UUID de chaque ligne initiale, détail des ventilations et base détaillée
  `année:secteur:compte:UUID`, quand le définitif permet cette correspondance ;
- UUID d’événement, révisions immuables et champs `source_type`, `source_id`,
  `remplace_revision`, ainsi que le lien facultatif `initial_id`.

L’adaptateur futur devra vérifier ses propres droits et sa donnée métier puis
remplacer le manuel via **le même UUID**, sous transaction et révision attendue.
Le service teste cette transition mais aucune route publique ne l’active. Une
source ne peut posséder deux UUID, même si le premier a été annulé ; sa prochaine
révision reprend cet UUID. Une source déjà raccordée reste stable. Une même
source ne doit pas être importée comme un nouvel élément à chaque synchronisation.

### Subventions : deux variantes conservées

1. Créer ultérieurement les dossiers à partir des éléments détaillés du gel,
   avec une clé d’idempotence gel/UUID de ligne et les ventilations compte/secteur.
   Le dossier créé n’est pas une recette nouvelle : seule une différence de
   montant prévu à encaisser modifie le suivi.
2. Créer un dossier après le gel, puis rattacher explicitement secteur, compte
   général et, si pertinent, ligne initiale figée. Si le retenu diverge du détail,
   demander une correspondance vérifiée plutôt qu’inventer une ventilation.

Aucune de ces variantes ne crée de subvention automatiquement dans le lot 2.

### Factures, contrats et IJ

Une facture imprévue sera **marquée dans Factures**, jamais déduite du BI.
Secteur et compte peuvent être connus au marquage, ou enrichis ultérieurement
lors de l’assignation puis de la validation de l’écriture. Le futur adaptateur
conservera sa clé de source dès la détection, avec un état incomplet **sans
impact comptable** tant que la correspondance est insuffisante. Il enrichira
ensuite le même UUID ; validation, paiement et import BI ne doivent pas générer
trois impacts. Le lot actuel exige secteur/compte pour ses ajustements manuels ;
il n’expose pas de formulaire de facture incomplète ni de synchronisation.

Les contrats référenceront leurs identifiants stables et les lignes/postes
prévus ; seul l’écart par rapport au prévu peut être retenu. Les IJ seront
alimentées par les montants **réellement reçus**, via BI et comptes configurés,
avec déduplication de la source. Pas d’IJ estimée déduite automatiquement d’une
absence, et aucune configuration de compte supposée par ce lot.

### Contrôle mensuel des comptes stables (idée ultérieure)

Pour énergie et autres comptes stables : comparer les mois à une référence
vérifiée et saisonnalisée (prix, consommation, calendrier), puis réviser la
**projection annuelle du même élément prévu**. Chaque facture ordinaire ne
constitue pas une nouvelle dépense budgétaire. Historiser hypothèses, période
de référence, réalisé et projection restante ; remplacer la révision précédente
au lieu d’empiler les écarts mensuels. Ce contrôle n’est pas implémenté.

## Migration 0078, concurrence et retour arrière

Migration additive/idempotente et schéma commun aux installations neuves :
`budget_gels`, `budget_suivis`, `budget_evenements`, `budget_instantanes` et index.
Aucune conversion de l’actualisé 2026 ni d’un autre exercice. Les calculs,
simulations, commentaires et exports existants gardent leur parcours.

Les transactions `BEGIN IMMEDIATE` revérifient session et révision avant écriture.
Le gel compare également l’empreinte complète du contrôle. Un double gel
identique est refusé ; deux modifications concurrentes ne peuvent valider la
même révision. Les triggers SQLite refusent UPDATE/DELETE sur gels, événements
et instantanés. Les archives copient les libellés et identifiants, sans dépendre
d’une suppression ou d’un renommage futur des référentiels.

Les tables sont déclarées à la résilience et incluses dans la sauvegarde SQLite.
Pas de fichiers métier nouveaux. Le downgrade refuse la destruction des
archives : restaurer une sauvegarde cohérente pour revenir en arrière. Tester
la migration sur copie synthétique ; ne jamais l’exécuter sur des données réelles
dans la recette agent. Aucun outil ni dépendance ajouté.

## Recette reproductible

```bash
CSPILOT_DATA_DIR=$(mktemp -d) python -m pytest tests/test_budget_suivi.py
PYTHON=/chemin/venv/bin/python node tests/budget_suivi_live_checks.cjs
CSPILOT_DATA_DIR=$(mktemp -d) python -m pytest
python scripts/validate_feature_catalogue.py
python -m compileall -q app.py budget_suivi.py schema_budget_suivi.py blueprints migrations tests
git diff --check
```

Le harnais navigateur exige les outils déjà disponibles Playwright/Chromium,
crée une base temporaire, garde CSRF et sessions actifs et bloque les requêtes
externes. Il couvre ordinateur/mobile, flux/classique, vide/incomplet/complet,
gel, ajustement/révision, erreur de validation avec conservation de saisie et PDF.
Les captures restent dans `/tmp`. Les tests couvrent aussi négatifs d’accès,
révocation, concurrence par connexions distinctes, échecs atomiques, éléments
prévus uniques, remplacement futur de source, migration répétée et PDF immuables.
