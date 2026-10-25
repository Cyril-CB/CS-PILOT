# Messages de la direction aux salariés

## Accès

- **Direction et comptabilité** : menu classique **RH & Paie → Messages de la
  direction**, ou la même page dans la carte de l'interface en flux.
- La barre intelligente reconnaît `message`, `messages`, `info salarié`,
  `infos salariés`, `note de service`, `notes de service`, `note interne`,
  `communication interne`, `communiqué`, `message de la direction`,
  `annonce aux salariés`, `informer les salariés` et `prévenir les salariés`.
  Accents et casse sont normalisés. Les alias exacts déclarés sont prioritaires :
  `infos salariés` propose les communications avant les dossiers RH, qui restent
  accessibles dans les autres résultats et par leur page habituelle.
- Les salariés et responsables lisent les messages sur leur accueil, mais ne
  peuvent ni publier, ni retirer, ni consulter les archives de gestion.
- Les prestataires externes n'ont accès ni à la diffusion ni à la gestion.

## Publication et archivage

Comme pour le CSE, **un seul message de la direction est affiché à la fois** :

1. Saisir un titre facultatif (150 caractères maximum), le contenu obligatoire
   (20 000 caractères maximum) et une date limite, aujourd'hui ou ultérieure.
2. Choisir si le personnel doit également être prévenu par e-mail.
3. Publier : l'auteur est l'utilisateur connecté, jamais une valeur du formulaire.
   Le précédent message de la direction est archivé dans la même transaction.

Le message reste visible **jusqu'à la date limite incluse**, dans le fuseau
applicatif. Dès le lendemain, il n'est plus affiché. Les messages expirés sont
matériellement archivés à l'ouverture de la gestion, sans ajouter de planificateur.
**Retirer ce message** permet de l'archiver immédiatement.

Les archives conservent titre, contenu intégral, auteur, date de publication,
date de validité et date d'archivage. Déplier **Lire le message archivé** pour
retrouver le texte complet. Le texte est échappé, sans HTML interprété.

## Affichage et lecture personnelle

Le bandeau **Message de la direction à lire** apparaît sur les tableaux de bord
des salariés internes et l'accueil en flux. Il peut coexister avec celui du CSE.

- Ouvrir, fermer, cliquer à l'extérieur ou utiliser Échap ne marque pas le message
  comme lu. Le focus reste dans le dialogue pendant son ouverture.
- **J'ai lu et ne souhaite plus voir le message** masque uniquement ce message
  pour l'utilisateur connecté, y compris après reconnexion.
- Un nouveau message réapparaît indépendamment du précédent.
- En cas de refus réseau/serveur ou de réponse non confirmée, le bandeau reste
  affiché et le bouton permet de réessayer. Une réponse HTML de connexion
  n'est pas considérée comme une lecture réussie.

Il ne s'agit pas d'une signature ni d'un accusé de réception juridique. Aucun
tableau nominatif des lecteurs n'est ajouté.

## Notifications e-mail

La case **Prévenir le personnel par e-mail** reprend le comportement CSE :
personnel interne actif, adresse renseignée et consentement individuel vérifié
avec les helpers existants. Le mail s'identifie comme un message de la direction,
et son contenu est échappé. Sans configuration, sans consentement ou en cas
d'erreur d'envoi, la publication reste disponible dans l'application.

## Données et mise à niveau

La migration additive **0080** crée `messages_direction` et
`messages_direction_lectures`. Le même schéma est appelé par `database.init_db()`
pour les installations neuves. Un index unique assure un seul message actif.
Les nouvelles tables sont déclarées dans l'inventaire de `resilience.py`.

Les messages, archives, membres et lectures du CSE ne sont pas modifiés.
Aucune migration n'est appliquée à une base réelle pendant le développement.

## Vérifications reproductibles

Dans un environnement contenant les dépendances déjà définies par le dépôt :

```sh
pytest tests/test_messages_direction.py tests/test_cse.py tests/test_cse_lectures.py tests/test_cse_lectures_frontend.py tests/test_search_palette.py -q
pytest -q
python -m compileall -q app.py blueprints migrations tests schema_messages_direction.py
python scripts/validate_feature_catalogue.py
git diff --check
```

Parcours navigateur facultatif, avec une installation **existante** de
`@playwright/test`/Chromium accessible à Node (aucune dépendance ajoutée au dépôt) :

```sh
# Terminal 1 : base éphémère et cinq profils fictifs, écoute locale uniquement.
python tests/messages_direction_browser_server.py
# Terminal 2 : si nécessaire, NODE_PATH pointe vers les modules déjà installés.
node tests/messages_direction_browser_checks.cjs
```

Le serveur de vérification crée sa propre base temporaire, ne lit pas les données
du centre et conserve CSRF actif. Les mails ne sont pas configurés. Captures et
compte rendu vont dans `/tmp/cspilot-direction-browser-results` (modifiable avec
`CSPILOT_BROWSER_OUTPUT`). Le parcours vérifie ordinateur 1440 px/mobile 390 px,
états vide/actif/archivé, auteur, recherche, publication/remplacement/retrait,
lecture individuelle, persistance après rechargement, focus et erreurs serveur.
