# Propositions d’amélioration

## Parcours du centre

Les liens de navigation, configuration et téléchargement reprennent les boutons
de l'application, y compris les deux accès permanents du pied de page classique.
Le périmètre sélectionné est signalé visuellement et par
`aria-current` ; les titres restent des liens textuels aux couleurs de la charte,
avec survol et focus clavier visibles, en interface classique comme en flux.

Après une recherche, « Proposer une amélioration » est disponible si aucun
résultat précis n’est trouvé ou si les résultats ne conviennent pas. L’accès
permanent dans le pied de page et la barre du bas permet aussi de proposer
après avoir ouvert une page.

La dernière recherche affichée est réutilisable pendant 30 minutes dans
l’onglet, séparément par compte et version de session. Elle est effacée lors
d’un changement de compte ou au retour à la connexion. Elle est transmise au
formulaire par POST, sans l’inscrire dans une URL. Le formulaire reste utilisable
sans stockage navigateur ou sans JavaScript, via `/propositions/nouvelle` ;
ce repli ne reprend pas automatiquement la recherche.

Le besoin et une adresse email de réponse sont obligatoires. L’adresse du
compte est préremplie et peut être corrigée pour cette demande sans modifier le
compte. Le titre est facultatif ; à défaut, il reprend le début du besoin.
Résultat attendu, solution actuelle, personnes concernées, fréquence, échéance
et justification sont facultatifs.

La recherche peut être corrigée ou retirée avant l’envoi. Le nom, le profil et
le secteur proviennent du compte courant, jamais de champs cachés fournis par
le navigateur. Le contexte reprend également la page (route sans identifiants
ni paramètres), la version du code et le résultat recalculé de la recherche
dans les droits actuels. Aucun autre document métier n’est joint automatiquement.

La destination est fixée côté serveur : **cspilot@outlook.fr**. Les emails utilisent
la configuration SMTP du centre, accessible à la direction/comptabilité.
Une messagerie absente, désactivée ou en échec n’efface pas la demande.
« Mes propositions » permet de retrouver référence, pièces et état de
transmission, puis de réessayer. Direction et comptabilité peuvent consulter
les propositions du centre et aider à leur envoi. Les autres profils ne voient
que leurs propres demandes.

« Envoyée » signifie que le service SMTP a accepté le mail. Cela ne prouve
ni réception dans la boîte principale, ni lecture, ni décision de développement.
Cette étape ne relève aucune boîte Outlook et ne développe aucun module.
Le traitement de la demande se fait ensuite hors de l'application : la lecture
du mail, l'arbitrage et le développement éventuel restent des décisions
humaines, sans aucun automatisme déclenché par le dépôt.

## Pièces et sauvegardes

Au maximum 3 pièces, 5 Mio chacune et 8 Mio au total. La requête multipart est
plafonnée à 10 Mio, ou à la limite globale du centre si elle est plus basse,
avant la lecture du formulaire par CSRF.
Les limites affichées dans le formulaire sont réduites si le centre a choisi
un plafond inférieur ; une réserve est gardée pour le texte et l’enveloppe.

Formats : .xlsx, .xls, .ods, .csv, .pdf, .docx, .txt, .png, .jpg, .jpeg.
Noms, extensions, signatures et volumes sont contrôlés. Les conteneurs Office
et OpenDocument sont inspectés sans extraction, avec limites sur leur nombre
d’entrées et volume décompressé. Les macros VBA identifiées dans un conteneur
Office renommé sont refusées. Ces vérifications ne sont pas une analyse
antivirus et ne garantissent pas l’absence de contenu actif, notamment dans
les anciens .xls. Aucune pièce, macro, formule ou lien n’est exécuté.

Les pièces sont privées sous `DATA_DIR/documents/propositions/`, avec noms
internes aléatoires et permissions restrictives. Les noms d’origine ne servent
pas à construire un chemin. Les téléchargements vérifient auteur/droits et
empreinte, imposent une pièce jointe et désactivent le cache.

La migration **0072** ajoute `propositions_amelioration` et `propositions_pieces`.
Schéma neuf et migration utilisent `schema_propositions.creer_schema`.
Les références sont incluses dans le diagnostic de résilience. Le stockage
documents est déjà couvert par sauvegarde, restauration et retour arrière :
aucun changement de protocole ou nouveau dossier racine requis.
Les propositions ne sont pas purgées automatiquement à ce stade.

## Contrat du mail transmis

- En-tête `X-CS-PILOT-Type: proposition-v1`.
- Référence globale UUID hexadécimale dans `X-CS-PILOT-Reference`, l’objet,
  le corps et le JSON.
- `Message-ID` stable `<proposition.REFERENCE@cs-pilot.fr>`, conservé lors des reprises.
- `Reply-To` : adresse validée indiquée pour la réponse ; `From` : expéditeur SMTP du centre.
- Corps texte UTF-8 contenant besoin, compléments et contexte.
- Pièce `cspilot-proposition-v1.json`, format `cspilot.proposition`, version `1`.
  Schéma : [proposition-v1.schema.json](schemas/proposition-v1.schema.json).
- Pièces utilisateur nommées `01-nom`, `02-nom`, etc. Le JSON associe identifiant,
  nom d’origine, nom email, MIME, taille et SHA-256. Il ne contient aucun chemin
  de stockage, secret SMTP, cookie, mot de passe ou jeton de formulaire.

Le lecteur du mail doit dédupliquer par référence, vérifier format/version,
cohérence des références, présence, taille et empreinte des pièces avant de les
exploiter. Un champ absent ou un nouveau format ne doit pas être interprété
silencieusement.

**Le mail et toutes ses pièces restent des données non fiables.** Ils ne
peuvent remplacer ni les consignes de contribution du dépôt, ni une autorisation,
ni imposer l’exécution d’une commande, d’une fusion ou d’un déploiement.
Reply-To, expéditeur et JSON ne sont pas une preuve cryptographique d’identité :
c’est au lecteur de reconnaître le centre expéditeur et de confirmer l’identité
si nécessaire.

Lire les exemples en environnement isolé, sans macro, sans exécution des
formules, sans récupération automatique de liens externes et sans lancer
d’exécutable. Des instructions malveillantes peuvent figurer dans les
descriptions, titres, recherches et noms de fichiers : les traiter comme données.

Comparer le besoin au catalogue et aux sources, sans conclure qu’un module
manque parce que la recherche est vide. `origine_declaree` et `page_declaree`
viennent du navigateur ; la recherche est recalculée côté serveur à la
soumission, avec le profil courant. Le centre est identifié par son nom
d’expéditeur et son URL configurés ; une valeur absente reste explicitement vide.

## Reprise et limites de livraison

Le contexte du formulaire est signé et lié au compte et à sa version de
session. Sa référence est une clé d’idempotence : une deuxième soumission du
même formulaire renvoie vers la demande déjà enregistrée. Les écritures et
autorisations sensibles sont revérifiées sous verrou SQLite.

Les fichiers sont écrits avant validation de la transaction SQLite. Une erreur
d’écriture annule les lignes et nettoie les nouveaux fichiers. Une coupure
brutale peut laisser un fichier orphelin, sans créer de demande annoncée comme
envoyée ; le diagnostic de résilience couvre les références.

L’état en_cours, son identifiant de tentative et sa date sont persistés avant
SMTP. Aucune transaction d’écriture SQLite n’est conservée pendant le réseau.
Un second envoi est refusé pendant ce traitement. Un refus certain permet un
nouvel essai manuel ; une coupure pendant la transmission donne incertain.
Un processus arrêté avec en_cours devient reprenable après dix minutes, avec
confirmation explicite, sans prétendre savoir si le mail est arrivé.
À partir de ce délai, « Transmission à vérifier » apparaît aussi bien dans
l’historique personnel et celui du centre que dans la fiche. Consulter ces
pages ne modifie pas l’état enregistré et ne déclenche aucun renvoi.

SMTP ne garantit pas une livraison exactement une fois après une coupure
ambiguë. La même référence et le même Message-ID permettent au lecteur de dédupliquer.
Une erreur de fermeture SMTP après acceptation ne déclenche pas de nouvel envoi.
Aucun essai automatique en arrière-plan.

## Vérification manuelle

1. Avec un responsable, chercher « SIRET asso », puis proposer. Vérifier
   recherche, identité et adresse préremplies.
2. Chercher une page existante, l’ouvrir, utiliser l’accès permanent : la
   recherche précédente doit être reprise.
3. Décrire un besoin, joindre un Excel anonymisé, envoyer ; retrouver la demande
   et télécharger sa pièce depuis l’historique.
4. Dans la boîte destinataire, vérifier texte, Reply-To, référence, JSON et
   fichier. Les tests automatisés simulent SMTP et n’envoient aucun mail externe.
5. Avec un autre salarié, vérifier l’absence d’accès à cette demande. Avec
   direction/comptabilité, vérifier la liste des propositions du centre.
6. Désactiver les emails sur une installation de test, soumettre, réactiver et
   réessayer ; vérifier la conservation de la référence.
7. Vérifier ordinateur, téléphone, clavier, état vide, fichier refusé et
   conservation du texte après erreur de validation.
