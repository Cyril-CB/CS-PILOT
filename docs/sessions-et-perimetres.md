# Sessions et périmètres des responsables

## Règles appliquées

L'équipe d'un responsable est l'union des salariés de son secteur et de ses
rattachés directs (`users.responsable_id`). Un rattachement direct ouvre les
mêmes droits même si le salarié dépend d'un autre secteur analytique. Deux
secteurs NULL ne constituent pas un lien d'équipe.

Sur le POST `/validation_demandes_recup`, ce périmètre est contrôlé avec
`est_dans_equipe_responsable` pour chaque approbation et chaque refus de congé,
de récupération à la journée ou de récupération partielle. Le responsable
intervient seulement sur les demandes `en_attente_responsable`, comme dans sa
liste. Direction et comptabilité conservent la décision finale aux deux états
d'attente. Les types et actions inconnus sont refusés.

Le compte, la cible, son propriétaire, l'équipe et l'état sont relus sous
`BEGIN IMMEDIATE`, sur la connexion qui écrit la décision et ses reports.
L'autorisation précède les écritures, compteurs, historique et notifications.
Une demande absente, inaccessible ou déjà traitée produit le même refus
français. Les emails restent envoyés seulement après le commit réussi.

## Validité et révocation des sessions

La session Flask contient un identifiant utilisateur et la `session_version`
lue lors d'une authentification réussie. Avant les vues, le garde global relit
le compte par sa clé primaire, vérifie son existence, son activation et la
version, puis actualise les champs utilisés par les contrôles de rôle.

| Changement en base | Effet sur les sessions déjà ouvertes |
| --- | --- |
| Désactivation ou suppression | Reconnexion imposée à la prochaine requête ; le compte inactif ne peut plus se connecter. |
| Réactivation | Les anciens cookies restent révoqués, même s'ils n'ont fait aucune requête pendant la désactivation. |
| Réinitialisation administrative ou par email | Révocation de toutes les sessions après commit ; la connexion avec le mot de passe temporaire impose son remplacement. Un échec d'envoi avec rollback ne révoque rien. |
| Changement personnel du mot de passe | Les autres sessions sont révoquées ; seule celle qui vient de prouver le mot de passe courant reçoit la nouvelle version. |
| Profil modifié | Rôle courant appliqué dès la prochaine requête, sans fermer la session. |
| Secteur ou responsable hiérarchique modifié | Périmètre courant appliqué dès la prochaine requête. |
| Délégation ou appartenance CSE retirée | Contrôles métier relus en base, sans reconnexion. |
| Changement obligatoire du mot de passe activé seul | Les anciennes sessions sont limitées à son changement, à la déconnexion et aux ressources statiques. |

Un trigger SQLite incrémente la version lorsque `actif` ou le hachage du mot
de passe change. Il couvre les formulaires et les autres écritures SQL sur
ces champs. Son effet est annulé avec la transaction si celle-ci échoue.
Aucun hachage ni mot de passe n'est ajouté au cookie ou aux journaux.

Les champs `nom`, `prenom`, `profil`, `secteur_id` et
`force_password_change` sont rafraîchis depuis la base : leur ancienne valeur
dans le cookie ne fait pas autorité. Le lien hiérarchique, les missions,
les délégations salles/bénévoles et l'appartenance CSE ne sont pas conservés
en session et restent lus par leurs helpers métier.

La révocation détectée est tracée dans le journal d'accès. Les formulaires de
modification/désactivation conservent leur journal atomique, avec l'ancien et
le nouveau profil ou l'indication de révocation. Les réinitialisations et
changements de mot de passe conservent leurs événements existants.

## Routes examinées

| Routes ou famille | Protection vérifiée / correction |
| --- | --- |
| `/validation_demandes_recup` | B5 corrigé sur les deux actions et les trois formes de demande ; compte et périmètre sous verrou d'écriture. |
| `/valider_mois`, `/deverrouiller_mois` | Équipe/versions déjà contrôlées ; ajout de la relecture du compte sous le verrou existant et du rôle de direction pour réouvrir. |
| `/modifier_user/<id>`, `/toggle_user/<id>` | Contrôles direction/comptabilité et relecture du compte sous le verrou de mutation ; journal enrichi. |
| `/changer_mot_de_passe` | Mot de passe et validité de session vérifiés dans la transaction de changement. |
| `/absences`, suppression et justificatifs | Mutations déjà réservées à direction/comptabilité ; justificatifs également accessibles au prestataire. Aucun droit responsable ajouté. |
| `/infos_salaries/*` (informations, contrats, documents), `/generation_contrats/*` | Contrôles de profil et de salarié visible existants, incluant les rattachés hors secteur ; refus de suppression d'un document extérieur vérifié avant l'accès au fichier. |
| `/planning_theorique`, suppression, `/saisie_heures` | Contrôles serveur existants de cible et d'équipe ; suppression d'un planning extérieur testée sans effet. |
| `/gestion_users`, `/infos_salaries`, `/prepa_paie`, `/dashboard_direction`, `/dashboard_comptable`, `/exportation` | Accès GET refusés avec les anciennes sessions après rétrogradation. |
| Vue des validations et relances, bénévoles, salles, CSE | Délégations et qualité de membre lues en base ; retrait de mission/gestion bénévoles/CSE testé avec session ouverte, tests existants des salles conservés. |

Le garde global s'applique à toutes les vues avec session, y compris celles
qui ne passent pas par `login_required`. Seuls les visiteurs sans identité
en session n'ont pas cette lecture. CSRF et limitation de débit restent en
place : un rejet préalable ne donne jamais accès à la mutation.

## Concurrence et coût

Une modification validée avant le contrôle global est effective sur la
requête suivante. Les décisions de demandes, signatures, réouvertures et
modifications de comptes ont en plus un second contrôle sous leur verrou
SQLite : une modification validée entre le garde global et la transaction
métier est donc aussi prise en compte. Un changement concurrent de
propriétaire, d'équipe ou d'état ne peut pas s'intercaler entre contrôle et
mutation de demande. Une opération déjà autorisée et engagée ne peut pas
être annulée rétroactivement par une révocation ultérieure.

Le garde valide ne fait qu'un SELECT indexé sur `users.id`, sans écriture SQL
ni cache. Mesure indicative de 1 000 ouvertures de connexion + vérifications
+ fermetures sur une base fictive locale : médiane **0,915 ms**, p95
**1,294 ms**. Cela ne mesure ni un serveur chargé ni le rendu complet d'une
page. Les décisions sensibles font une seconde lecture sur leur connexion.

## Mise en service et limites

La migration **0066**, également intégrée à `init_db`, ajoute le compteur
et le trigger sans modifier les comptes ou données RH existants. Elle est
idempotente. Toutes les sessions antérieures à cette version, sans compteur,
imposent **une reconnexion**. Tous les processus applicatifs doivent utiliser
la nouvelle version après mise à niveau du schéma ; un ancien processus ne
connaît pas le garde. Ne pas mélanger durablement les deux versions.

Ce chantier ne refond pas les durées de session, la déconnexion individuelle,
les sauvegardes/restaurations ni le routage général. Il ne modifie pas les
chevauchements d'absences, exports comptables, statuts de préparation de paie
ou récupérations validées sans report. Les erreurs de notification après
commit conservent leur comportement existant. Aucune fusion ni aucun
déploiement n'est effectué par cette correction.
