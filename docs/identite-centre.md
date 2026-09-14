# Fiche d’identité du centre

Dans la barre intelligente, chercher **SIRET asso**, **SIREN association**,
**statuts association** ou **code de convention collective**. La fiche est
aussi disponible dans Tout explorer et le menu classique, accès **Identité du centre**, et à
`/centre/identite` en interface classique comme en flux.

Une installation contient une seule fiche commune : nom du centre, SIREN,
SIRET, code APE/NAF et code de convention collective (IDCC). Les champs sont
facultatifs pour permettre une saisie progressive. Les espaces des identifiants
sont retirés ; les zéros initiaux sont conservés. SIREN et SIRET comportent
respectivement 9 et 14 chiffres ; s’ils sont tous deux saisis, leur préfixe doit
correspondre. Le code APE est normalisé en quatre chiffres et une lettre.
Ces contrôles de format ne certifient pas l’existence des identifiants.
Le code de convention collective est informatif et ne change aucun calcul de paie.

La direction et la comptabilité peuvent modifier les informations, ajouter,
modifier et supprimer des champs **libellé + valeur texte**, et gérer les
documents. Les responsables peuvent consulter la fiche et télécharger les
documents. Salariés, prestataires et visiteurs non connectés n’y ont pas accès.
Les droits sont vérifiés côté serveur, y compris pour les téléchargements.

Les champs complémentaires sont limités à 30 : libellé de 80 caractères et
valeur de 2 000 caractères, sans formule ni calcul. Un libellé déjà utilisé est
refusé, y compris s'il ne diffère que par la casse Unicode (`É`/`é`) ou par une
forme Unicode équivalente. Une fiche modifiée depuis son ouverture doit être rechargée avant une
nouvelle écriture, pour éviter d’écraser le travail d’une autre personne.

Jusqu’à 50 documents communs peuvent être conservés, indépendamment des dossiers
de subvention : un fichier de 5 Mio maximum par ajout. Une limite d’installation
plus basse reste prioritaire. Formats : PDF, DOCX, XLSX, XLS, ODS, CSV, TXT, PNG,
JPG et JPEG. Les contrôles de nom, taille, signature et conteneur reprennent ceux
des propositions. Ils ne constituent pas un antivirus ; aucun document, lien,
macro ou formule n’est exécuté par l’application. Les fichiers sont téléchargés
en pièce jointe, sans aperçu actif et avec vérification de leur empreinte.

Chaque document porte un titre libre. Pour le remplacer, ajouter la nouvelle
version puis supprimer l’ancienne. Il n’existe pas d’historique documentaire ou
de corbeille dans ce module ; les sauvegardes restent le moyen de restauration.

## Données et mise à jour

La migration **0073** crée `identite_centre`, `identite_centre_champs` et
`identite_centre_documents`, sans modifier les autres données. Le schéma commun
`schema_identite_centre.py` sert aussi aux installations neuves ; la migration
est idempotente. Aucun identifiant réel n’est prérempli.

Les fichiers restent privés sous `DATA_DIR/documents/identite-centre/`, avec un
nom interne aléatoire. Les références et tables sont inscrites au diagnostic de
résilience. Le répertoire `documents` figure déjà dans `update-protocol.json`
et dans les sauvegardes : aucune nouvelle racine de données n’est nécessaire.
La mise à jour supervisée sauvegarde et migre la fiche avec le reste de
l’installation. Les tests vérifient restauration des champs et octets des pièces.

## Recette avec des données fictives

1. Avec un compte directeur ou comptable, chercher **SIRET asso**. Saisir un
   nom fictif, neuf zéros pour le SIREN, quatorze zéros pour le SIRET, `0000Z`
   pour l’APE et `TEST` pour le code de convention ; enregistrer puis recharger.
2. Ajouter une information « Référence interne », la modifier puis la supprimer.
   Une valeur commençant par `=` reste du texte. Un libellé vide ou trop long
   doit être refusé, sans effacer les autres informations.
3. Ajouter un fichier texte fictif titré « Statuts de test ». Le télécharger
   et vérifier son contenu. Un fichier exécutable ou un faux PDF doit être refusé.
4. Avec un responsable, retrouver la fiche et télécharger la pièce. Aucun
   formulaire de modification n’est proposé ; un POST direct est refusé.
5. Vérifier le refus avec un salarié ou un prestataire, y compris avec l’URL
   directe du document. Vérifier deux onglets de gestion : la seconde écriture
   depuis une version ancienne est refusée avec invitation à recharger.
6. Vérifier ordinateur/mobile, classique/flux et navigation clavier. Avec un
   gestionnaire, supprimer le document de test ; son ancienne URL ne fonctionne plus.

La correction des liens de proposition et du test du planificateur est suivie
séparément dans la PR #263 ; elle n’est pas dupliquée par ce module.
