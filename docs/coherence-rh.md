# Absences, préparation de paie et récupérations (audit B7/B8/B9)

## Vérification initiale sur main

Base : `3d72329` (PR #250 fusionnée, après #247 et #248). Les 111 tests
existants des absences, récupérations, congés, préparation/variables de paie
et versions mensuelles passent avant modification.

| Constat | Reproduction actuelle | Cause |
| --- | --- | --- |
| B7 | Toujours reproductible : deux CP consomment deux jours et une seule projection subsiste. | Comptage par absence, remplacement d'une ligne unique par date, suppression fondée sur un préfixe de commentaire. |
| B8 | Toujours reproductible : une absence ajoutée après traitement laisse le statut traité. | Seule la route des variables invalide le statut ; aucune référence des données consultées. |
| B9 | Partiellement corrigé : #247 annule déjà les reports sur mois verrouillé. Le planning absent conserve encore le statut final sans report. | Le helper renvoie `False`, mais l'appelant committe la décision et annonce la validation. |

Trois tests de régression ont échoué sur cette base avant les corrections.
Aucune donnée de production n'a été consultée.

## Règles retenues pour les absences

Le modèle existant propose une absence entière par intervalle de dates et une
seule ligne de calendrier par jour. Il ne possède ni fraction de journée ni
priorité entre motifs. « Mi-temps thérapeutique » est actuellement un motif,
pas un créneau horaire. La récupération partielle possède un créneau, mais
son report remplace lui aussi l'unique ligne de la journée.

Les nouvelles absences concurrentes sont donc **refusées avec un conflit
explicite**. Cela vaut pour CP/CP, CP/maladie, maladie/maladie, congé
conventionnel/autre, les intervalles partiellement communs, les périodes sur
plusieurs mois, les congés approuvés et les récupérations déjà reportées.
Deux créneaux de récupération distincts sur le même jour ne sont pas fusionnés
implicitement. Les contrôles des nouvelles décisions relisent les droits,
l'état et les sources sous `BEGIN IMMEDIATE`.

Pour corriger une absence manuelle : supprimer l'ancienne depuis Absences,
puis saisir la bonne période/le bon motif. Il n'existe actuellement pas de
route de modification directe d'une absence. Une fiche verrouillée exige
auparavant la réouverture explicite et motivée déjà prévue par CS PILOT.

Chaque nouveau report conserve une origine structurée dans `rh_projections`
(absence ou demande de récupération, calendrier, salarié, date et contenu
reporté). `absences.demande_conge_id` identifie les nouveaux congés à l'origine
d'une absence. Les saisies manuelles de calendrier ne peuvent écraser un
report encore actif, même par POST direct : la vérification avant commit
annule l'ensemble des écritures. Les anciens commentaires sont comparés
**entièrement**, jamais par préfixe (`#1` ne correspond pas à `#10`).

La suppression retire seulement la source concernée. Si une seule absence
historique reste sur un jour ainsi libéré, son report est restauré ; si
plusieurs resteraient et nécessiteraient un arbitrage, la suppression est
refusée. Une projection appartenant déjà à une autre absence est conservée.
Les mécanismes existants de restitution des compteurs, y compris après
clôture mensuelle des congés, sont conservés.

### Décision métier à confirmer

Un éventuel remplacement automatique CP → maladie, une priorité entre motifs
ou le cumul de fractions de journée nécessiteraient une décision métier et un
modèle capable de représenter ces fractions. Les options sont : conserver le
refus explicite actuel, ajouter un remplacement explicite avec restitution des
compteurs, ou modéliser des créneaux cumulables. Cette PR ne choisit aucune
priorité implicite et ne procède à aucun remplacement automatique.

## Préparation de paie

« Traité » signifie désormais : les données actuellement affichées ont été
vérifiées. Une empreinte SHA-256 porte uniquement sur le dossier réellement
présenté, indépendamment du versionnement des fiches mensuelles.

| Source | Effet sur la vérification |
| --- | --- |
| Nom, prénom et secteur affichés | Nouvelle vérification si modification. |
| Contrats actifs sur le mois : type, dates, forfait, jours, temps hebdomadaire, PDF lié | Nouvelle vérification si modification. Un contrat entièrement hors mois n'a pas d'effet. |
| Absences du mois : motif, dates, reprise, jours, commentaire, justificatif lié | Nouvelle vérification si ajout, suppression ou modification. |
| Variables de paie affichées | Nouvelle vérification ; l'invalidation existante lors d'une saisie est conservée. |
| Heures réelles/supplémentaires de la grille | Il s'agit des **variables de paie**, pas d'un calcul en direct de la fiche mensuelle. |
| Planning, heures brutes, récupérations | Pas directement affichés dans cette grille. Leur report dans une variable de paie rend ensuite la vérification obsolète. |
| Documents salariés hors grille, email, préférences, sessions | Aucun effet direct sur la vérification. |

La page et l'export indiquent « Traité », « À vérifier » ou « Modifié depuis
la dernière vérification ». La date de vérification est conservée ; la première
modification qui l'invalide est datée et journalisée. Les nouveaux changements
sur un dossier déjà à vérifier ne produisent pas de notifications répétées.
Le parcours de variables conserve également son message d'invalidation.

Chaque ligne de formulaire comporte une référence signée liant salarié, mois,
année, empreinte affichée et révision du statut. Le POST relit les sources et
les droits dans une transaction. Une page ancienne, un autre dossier, une
référence absente/modifiée ou un changement concurrent de statut provoquent
un refus de **tout le formulaire**, avant toute écriture. Cela protège aussi
contre une ancienne page qui décocherait une vérification plus récente.
La lecture initiale de la grille utilise une transaction SQLite cohérente.

## Récupérations

Modèle A : **décision et application atomiques**. Les validations intermédiaires
responsable et les possibilités existantes de décision direction/comptabilité
restent inchangées. L'étape finale ne réussit que si le report réussit.

Un mois verrouillé, un planning manquant, un créneau devenu sans effet, un
volume partiel modifié depuis la demande ou un conflit provoquent un refus
compréhensible. La demande reste dans son état d'attente antérieur. Après
correction du planning ou réouverture des mois concernés, la même action peut
être tentée de nouveau. Un volume partiel changé exige de corriger la demande.

Pour plusieurs mois, la transaction porte sur la totalité de la période.
Ouvrir un seul de deux mois verrouillés ne permet pas un report partiel.
L'UPDATE conditionné par l'état, le verrou SQLite et la provenance conservent
une seule application, même lors de deux requêtes simultanées. L'application
est tracée avec l'identifiant de demande et sa date réelle. Les notifications
de décision finale partent seulement après commit réussi.

Une nouvelle version mensuelle issue du report rend les anciennes approbations
insuffisantes. Après réouverture, le circuit complet salarié → responsable →
direction reprend. Aucun contournement de `ConnexionFiches` n'est introduit.

## Migration 0068 et exploitation

Le schéma est identique via `init_db()` ou `0068_coherence_rh.upgrade()` :
référence du congé source, tables de provenance/file transactionnelle,
colonnes de vérification de paie, file des salariés/mois affectés et index.
Migration idempotente, sans reconstruction des origines historiques.

Les anciennes absences, récupérations, heures, compteurs, signatures, verrous
et instantanés sont conservés. Les chevauchements historiques apparaissent
sur la page Absences, avec filtre salarié et affichage limité à 100 paires.
Aucune absence historique n'est supprimée ni départagée automatiquement.

Les anciens statuts de paie cochés ne permettent pas de connaître les données
qui avaient été consultées : ils deviennent « À vérifier — traitement
historique sans référence de données ». Leur ancienne date reste conservée ;
aucune empreinte actuelle n'est présentée comme une preuve ancienne.

Aucune révocation globale des sessions n'est nécessaire. Les pages de paie
ouvertes avant la mise à jour devront être rechargées. Un retour à une version
antérieure exige la sauvegarde préalable ; le downgrade refuse une suppression
silencieuse des preuves. Un échec de migration annule les écritures dans la
transaction appelante. Le gestionnaire de migrations (B10) reste hors périmètre.

## Validation et limites

Les nouveaux tests couvrent conflits et restauration, CP/CC/forfait,
chevauchements sur deux mois, origines de congés/récupérations, dates invalides,
POST directs, sessions révoquées, données réellement affichées en paie,
ancienne page, concurrence, notifications, absence de planning, verrouillage,
réouverture et trois nouvelles approbations. Les refus comparent les demandes,
absences, heures, forfait, compteurs, versions/événements, paie, historique et
provenances avant/après ; les notifications sont observées séparément.
Migration : installation, ancien schéma, répétition, conservation et rollback.

Mesure synthétique : 1 224 dossiers de paie (51 salariés × 24 mois), un ajout
d'absence ne recalcule qu'une empreinte (salarié/mois concerné). Mesure locale
HTTP + commit : environ 21 ms, à titre indicatif, sans seuil fragile en test.

Le navigateur cloud refuse l'accès local (`ERR_BLOCKED_BY_CLIENT`). La
validation visuelle ordinateur/mobile n'a donc pas été réalisée. Les parcours
HTTP et les rendus HTML/Excel font l'objet de vérifications distinctes.

Les anciennes récupérations déjà affichées « validées » dont un report aurait
été perdu ne sont pas rejouées automatiquement : une reprise supposerait de
connaître les modifications ultérieures et le volume réellement appliqué.
Les arbitrages d'anciens chevauchements, annulations de récupérations déjà
validées, fractions d'absence et corrections directes de fichiers par un
opérateur restent des interventions à examiner séparément. Les exports
comptables, sauvegardes et autres constats de l'audit ne sont pas modifiés.
