# Assistant personnel — lots 1 à 3

Ouvrir directement **`/assistant`** après installation de la mise à jour et de la
migration 0084. Aucun accès n’est ajouté au menu ou à la recherche globale dans
ce premier lot. Les interfaces classique et flux conservent leur présentation.

## Accès et fournisseurs

Direction, comptabilité et responsables ont accès à la page. Les salariés
rattachés à un secteur nommé **Pilotage** y ont également accès : comparaison
sans distinction de casse, en ignorant les espaces de début et de fin. Les
prestataires externes restent exclus. Le secteur Pilotage n’accorde pas de
nouveaux droits aux données métier : un salarié conserve son propre planning,
ses accès personnels et ses éventuelles délégations.

Le dialogue utilise les clés API déjà configurées dans l’installation. Le modèle
est choisi sur la page parmi les fournisseurs configurés. Les clés restent côté
serveur ; seules les informations utiles à la demande et les souvenirs retenus
sont envoyés au fournisseur choisi. Sans clé, l’écran de mémoire reste utilisable.
Il n’y a pas de bascule automatique vers un autre fournisseur.

## Consultations proposées

- **Rechercher** une page ou un dossier : même moteur et mêmes filtres que la
  recherche actuelle. Pour les salariés de Pilotage, recherche dans la carte de
  navigation autorisée uniquement ; aucune extension de la recherche métier.
- **Priorités** : cartes du fil d’actions du profil et éléments de l’horizon.
- **Planificateur** : blocs personnels sur quatorze jours et tâches à faire.

Les résultats sont bornés et datés. Un résultat vide ne prouve pas l’absence
d’un dossier. Les liens de source proviennent du serveur. Le texte et le résumé
produits par le modèle ne constituent pas une validation métier.

Cette version ne lit pas le contenu des documents ni la convention collective.
Elle ne crée pas d’événement, n’approuve rien et ne modifie aucun dossier. Les
actions continuent de se faire dans les modules habituels.

## Conversation et petite mémoire

Une conversation privée par utilisateur est conservée côté serveur, avec ses
vingt derniers messages et un résumé de reprise limité à 1 800 caractères. Elle
expire après trente jours sans mise à jour. « Nouvelle conversation » efface le
dialogue et son résumé en conservant les souvenirs personnels.
Les contenus expirés sont écartés et nettoyés au prochain accès de l’utilisateur
à cet espace ; aucun traitement planifié en arrière-plan n’est installé.

« Ma mémoire » permet d’ajouter, modifier et supprimer trente souvenirs maximum,
de 400 caractères chacun :

- **Préférence** : conservée jusqu’à suppression.
- **Sujet suivi** : expire après trente jours ; une édition renouvelle ce délai.

La phrase **« Retiens que… »** ajoute un sujet suivi sans appel au fournisseur.
Aucun souvenir n’est enregistré automatiquement par le modèle. Un changement de
mémoire réinitialise le dialogue et le résumé, pour ne pas réinjecter une ancienne
information. « Tout oublier » efface les deux. La suppression n’efface pas les
dossiers métier et ne peut pas retirer des données déjà transmises au fournisseur.

Les conversations et souvenirs sont chiffrés avec la SECRET_KEY de l’installation.
Les sauvegardes et le rechiffrement de restauration les prennent en compte.
Après un changement de rôle, de périmètre d’équipe, de navigation ou d’affectation
des ressources bornées, l’ancien contexte est effacé avant réutilisation. Ces
informations ne sont pas partagées avec les autres utilisateurs, y compris la
direction.

## Limites, concurrence et erreurs

Chaque demande peut déclencher deux appels au modèle, avec trois consultations
maximum. Le serveur valide les outils et leurs arguments : aucune requête SQL,
URL libre ou action métier ne peut être exécutée depuis une réponse IA.

Le quota initial est de trente tentatives de dialogue par utilisateur et jour
applicatif, y compris les tentatives en erreur ; un débit de six messages par
minute s’ajoute. Ce plafond limite le nombre d’appels, pas leur coût monétaire.
Un bail de trois minutes empêche deux traitements simultanés du même utilisateur.
Les appels réseau s’effectuent sans verrou SQLite ouvert. Les droits sont revus
avant les consultations, avant le second envoi et avant l’enregistrement du retour.

Effacer un souvenir ou une conversation pendant un appel invalide son résultat :
une réponse tardive ne réintroduit pas les données supprimées. Le dernier tour
peut être réémis avec le même identifiant et contenu sans nouvel appel payant.
Les erreurs ne renvoient jamais de clé ni de message technique brut du fournisseur.

## Vérifications et suites possibles

Les tests utilisent des comptes et bases temporaires et des fournisseurs simulés.
Ils couvrent les profils, le secteur Pilotage, l’isolation personnelle, la
révocation des droits, les outils, la concurrence, les quotas, l’oubli, la migration
et le rechiffrement. Le rendu de la page doit aussi être contrôlé sur ordinateur
et mobile, avec et sans clé.

Les lots suivants pourront ajouter les documents et références sourcées, puis
les propositions d’actions à confirmer, en réutilisant cette liste fermée d’outils.
