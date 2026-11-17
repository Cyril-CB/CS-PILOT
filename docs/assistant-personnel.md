# Assistant personnel — lots 1 à 4

Ouvrir directement **`/assistant`** après installation de la mise à jour et des
migrations 0084 et 0085. Aucun accès n’est ajouté au menu, à l’accueil ou à la
recherche globale. Les interfaces classique et flux conservent leur présentation.

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
- **Planificateur** : douze blocs personnels maximum, d’aujourd’hui à J+14 inclus.
  Les rendez-vous remontent par leurs blocs datés et conservent leurs horaires.
  Une liste distincte contient huit tâches à faire maximum, sans échéance ou
  avec une échéance jusqu’à cette borne, y compris les tâches en retard.
- **Document sélectionné** : trois pages pertinentes du PDF personnel, avec des
  liens de source vers les pages consultées. Choisir « Poser une question sur ce
  PDF » dans la boîte de réception. Le document n’est pas partagé avec les autres
  utilisateurs, y compris la direction.

Les résultats sont bornés et datés. Un résultat vide ne prouve pas l’absence
d’un dossier. Les liens de source proviennent du serveur. Le texte et le résumé
produits par le modèle ne constituent pas une validation métier.

La convention collective n’est pas chargée automatiquement. Le dialogue reste
en consultation, ne crée pas de rendez-vous et n’approuve rien. Les créations
documentaires ci-dessous passent par un traitement distinct à liste fermée.

## Boîte de réception — lot 4

Déposer un PDF, avec ou sans commentaire. Exemple : « Cette facture est pour le
secteur Enfance ». Le fichier attendu est un **PDF numérique original**, issu
d’un logiciel, **pas un scan**. Limites : 16 Mo, 60 pages, 150 000 caractères
extraits. Aucun OCR, aucune image du PDF envoyée au modèle : seulement le texte
et les commentaires. Le contrôle refuse les pages principalement constituées
d’images et les PDF sans texte exploitable ; il ne certifie pas la provenance
d’un fichier. Les PDF chiffrés ou illisibles sont refusés.

La réception et l’analyse sont privées. Un dépôt sans clé reste conservé pour
analyse ultérieure. Le modèle identifie la nature du document, propose une
synthèse des informations et chiffres, cite les extraits utilisés pour les
champs et relève les obligations : signature, bilan, justificatifs, solde, etc.
Un champ non justifié par un extrait du PDF ou une précision explicite du
commentaire est demandé à l’utilisateur avant création.
Les dates sont comparées dans leur intégralité : un extrait citant le 21 juin
ne valide pas une extraction au 1er juin.
Le texte du document ne peut donner de droits ni autoriser des commandes.

Les droits restent ceux des modules actuels :

| Profil | Factures | Subventions | Contrats |
| --- | --- | --- | --- |
| Direction / comptabilité | Création et affectation | Création et dossiers accessibles | Salariés visibles |
| Responsable | Analyse seulement | Création ; rapprochement limité aux dossiers assignés | Équipe et salariés autorisés par la fiche RH |
| Salarié du secteur Pilotage | Analyse seulement | Analyse seulement | Analyse seulement |

### Facture

L’import depuis la page Factures et la réception utilisent le même service
d’enregistrement : fournisseur rapproché par nom/alias ou créé, PDF conservé,
facture « à traiter » et approbation en attente, historique. Aucune écriture
comptable ni paiement n’est produit par la réception. L’utilisateur poursuit
dans **Factures**, dont le lien est fourni.

Un secteur ou la direction n’est affecté que sur indication explicite du
commentaire ou dans les précisions de l’utilisateur. Le contenu du PDF ne sert
jamais à deviner cette affectation. Un secteur ambigu appelle une question.
Sans indication, la facture est importée sans affectation.

### Convention et notification de financement

Le résumé reprend les montants, conditions et démarches importantes. L’année
de l’action est distincte de la date du document : une signature en 2026 ne
devient pas une année de financement par défaut. Une année absente, ambiguë ou
non explicitement justifiée est demandée.

Un dossier de même nom et même année, unique dans le périmètre autorisé, peut
être rapproché automatiquement. Une correspondance partielle ou multiple
appelle un choix ; l’utilisateur peut également choisir une nouvelle subvention.
Un dossier sans année exige un choix explicite. Les noms proches ne sont pas
considérés comme une preuve d’identité.

La nouvelle subvention est créée dans **_A classer**, catégorie créée si absente,
avec le statut initial habituel du module. Les personnes indiquées explicitement
dans le commentaire sont recherchées sans ambiguïté ; sinon l’utilisateur peut
choisir zéro, un ou deux salariés. Les étapes datées et justifiées par le PDF
sont créées ; sans échéance détectée, l’utilisateur peut en ajouter ou laisser
la liste vide. Les étapes identiques déjà présentes sont conservées.

Si le justificatif principal est vide, le PDF y est rattaché. **S’il existe déjà,
il est conservé et un sous-élément dédié reçoit le nouveau PDF.** Une pièce déjà
jointe à l’identique n’est pas copiée une seconde fois. Les montants, années,
affectations et statuts d’un dossier existant ne sont pas édités. Le lien cible
l’année du dossier, ou « toutes » pour les années hors de la plage du module.

### Contrat de travail

Un nouveau contrat est ajouté à un salarié existant et accessible : type CDI,
CDD, CEE ou Autre, début, fin éventuelle, temps hebdomadaire et PDF. Une identité
ambiguë ou un champ nécessaire manquant appelle une question. Aucun salarié
n’est créé et aucun contrat existant n’est remplacé. Une correspondance déjà
présente renvoie à la fiche pour contrôle manuel.

La connexion métier applique les protections des fiches mensuelles et les
contrôles de préparation de paie habituels. Une création qui changerait une fiche
verrouillée est annulée, copies provisoires comprises. Le PDF reçu est conservé
et la fiche **Infos salariés** reste le lieu de contrôle et de correction.

### Arrêt maladie et autre document

Un arrêt maladie est identifié puis orienté vers **Absences**, sans création
d’absence ni analyse médicale dans le compte rendu. Les droits de cette page
restent inchangés. Un autre document reçoit un résumé et peut servir de support
à une discussion ; il ne déclenche aucune création métier.

### Précisions, doublons et conservation

Une nature incertaine peut être confirmée. Tant qu’aucun dossier métier n’est
rattaché, l’utilisateur peut demander un réexamen avec un type et un commentaire
complémentaires ; les analyses précédentes restent conservées. Après classement,
les corrections se font dans les modules habituels.

Un dépôt identique par le même utilisateur retrouve la même réception, sans
nouvel appel ni création en double. Une facture de même fournisseur/référence/
date/montant, y compris avec un alias fournisseur, est signalée comme existante.
Les précisions portent une révision : une ancienne page ne peut pas remplacer
une réponse plus récente. Les droits sont revérifiés sous transaction avant les
écritures. Aucun appel fournisseur n’a lieu avec un verrou SQLite ouvert.

L’assistant ne dispose d’aucune opération de suppression ou d’édition générale
des dossiers. L’ajout d’un justificatif principal vide et la création de nouvelles
pièces/sous-éléments sont les seules suites possibles sur une subvention existante.
Les affectations initiales sont enregistrées avec la création de la facture ou
de la subvention. Aucune notification e-mail automatique n’est émise par ce lot.

Les 50 derniers PDF sont affichés ; les autres restent conservés. Les noms,
commentaires, textes et analyses sont chiffrés dans la base. Les fichiers PDF
sont dans `documents/assistant_reception`, sous noms aléatoires, avec un accès
réservé à leur propriétaire. Ils sont sauvegardés et contrôlés avec les autres
documents ; le rechiffrement de restauration couvre aussi leurs métadonnées.
« Nouvelle conversation » et « Tout oublier » ne suppriment ni PDF ni dossier.

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

Le quota initial est de trente tentatives par utilisateur et jour applicatif,
partagées entre dialogue, analyses et réexamens de PDF, y compris les erreurs.
Un débit de six requêtes par minute protège le dialogue et chaque entrée
documentaire coûteuse. Ce plafond limite les appels, pas leur coût monétaire.
Un bail de trois minutes protège le tour de dialogue et chaque analyse de document.
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

Les documents sont testés sur données synthétiques et fournisseurs simulés ;
leur compréhension par le modèle choisi doit être appréciée sur des exemples
représentatifs. OCR, autres formats, création de rendez-vous, paiements et
génération d’écritures depuis la réception restent hors de ce lot.
