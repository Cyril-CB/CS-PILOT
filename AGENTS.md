# AGENTS.md — Guide de contribution à CS PILOT

Ce fichier s'applique à l'ensemble du dépôt. Il est destiné aux agents de
développement qui modifient CS PILOT. Lisez-le avant toute intervention, puis
consultez `README.md`, `SECURITY.md` et les fichiers proches du code concerné.

## 1. Comprendre le produit

CS PILOT est une application web Flask monolithique de gestion RH, du temps,
de la paie, de la comptabilité et d'activités associatives. Les données RH et
financières sont sensibles : privilégiez les changements minimaux, explicites,
rétrocompatibles et couverts par des tests.

- Langue de l'interface, des messages et de la documentation utilisateur :
  **français**.
- Backend : Python/Flask, blueprints et SQLite.
- Frontend : templates Jinja2, CSS et JavaScript sans étape de compilation.
- Point d'entrée : `app.py` (configuration Flask et enregistrement des
  blueprints).
- Accès aux données et schéma initial : `database.py`.
- Extensions Flask partagées : `extensions.py`.
- Logique transversale : `utils.py` et les modules `*_engine.py` ou
  `*_metrics.py`.
- Modules métier HTTP : `blueprints/`.
- Vues : `templates/`; ressources : `static/`.
- Évolutions du schéma : `migrations/`.
- Tests : `tests/`, avec les fixtures communes dans `tests/conftest.py`.

Avant de coder, recherchez les routes, tables, templates, tests et fonctions
qui participent déjà au parcours concerné. Un même concept peut traverser
plusieurs modules (par exemple saisie des heures, paie, prévention, exports et
tableaux de bord).

## 2. Installation et commandes utiles

Depuis la racine du dépôt :

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

L'application locale est servie sur `http://localhost:5000`. Si nécessaire,
définissez une clé de développement non sensible :

```bash
export SECRET_KEY="cle-locale-uniquement"
```

Commandes de validation :

```bash
pytest                             # suite complète
pytest tests/test_<module>.py       # fichier ciblé
pytest tests/test_<module>.py -k nom_du_test
python -m compileall -q app.py blueprints migrations tests
```

Commencez par les tests ciblés, puis lancez la suite complète avant de livrer.
N'ajoutez pas de nouvel outil de formatage ou de lint sans demande explicite :
le dépôt n'en configure actuellement aucun.

## 3. Méthode de travail attendue

1. Vérifiez `git status` et ne supprimez ni ne réécrivez les changements déjà
   présents sans rapport avec la tâche.
2. Identifiez le comportement existant et ses tests avant de proposer une
   nouvelle abstraction.
3. Réalisez la plus petite modification cohérente possible ; évitez les
   refactorings opportunistes.
4. Ajoutez ou adaptez les tests dans le même changement. Pour un correctif,
   écrivez un test qui échoue avant le correctif et réussit après.
5. Contrôlez les parcours pour chaque profil impacté : `salarie`,
   `responsable`, `comptable`, `directeur` et `prestataire`.
6. Si l'interface change, vérifiez au minimum le rendu ordinateur et mobile,
   les libellés français, les états vides et les messages d'erreur.
7. Résumez clairement les fichiers modifiés et les commandes réellement
   exécutées ; ne prétendez jamais qu'un test non lancé a réussi.

## 4. Conventions Python et Flask

- Respectez le style du fichier environnant : quatre espaces, `snake_case`,
  constantes en `MAJUSCULES` et docstrings utiles. Conservez les accents dans
  les textes métier.
- N'entourez jamais les imports d'un `try/except`. Pour éviter un cycle
  d'import réel, préférez un import local commenté et limité à la fonction qui
  en a besoin.
- Un nouveau domaine HTTP doit vivre dans un blueprint. Enregistrez tout
  nouveau blueprint dans `app.py` et utilisez `url_for()` plutôt que des URL
  codées en dur.
- Protégez les routes avec `login_required` et une autorisation métier
  explicite. Une entrée de menu masquée ne constitue **pas** un contrôle
  d'accès.
- Ne faites jamais confiance aux identifiants, profils, noms de fichiers,
  dates ou montants reçus du navigateur. Validez-les côté serveur et vérifiez
  que l'utilisateur peut agir sur la ressource visée.
- Utilisez `flash()` avec un message français actionnable, puis le schéma
  Post/Redirect/Get pour les formulaires classiques.
- Gardez les calculs métier déterministes hors des fonctions de route lorsque
  cela facilite leur réutilisation et leurs tests.
- Ne changez pas silencieusement les règles de temps, congés, validation,
  paie ou comptabilité. Documentez les arrondis, bornes, fuseaux horaires et
  effets sur les compteurs.

## 5. SQLite et migrations

- Utilisez toujours des paramètres SQLite (`?`) pour les valeurs. Ne composez
  du SQL avec une f-string que pour un nom de table/colonne issu d'une liste
  fermée contrôlée par le code.
- Ouvrez la connexion avec `get_db()`, regroupez les écritures liées dans une
  transaction, faites un seul `commit()` après succès et fermez toute connexion
  ouverte par la fonction. Ne commitez pas à l'intérieur d'un helper si son
  appelant doit garantir l'atomicité.
- Toute évolution de schéma doit fonctionner à la fois pour :
  1. une installation neuve créée par `database.init_db()` ;
  2. une base existante mise à niveau par `migration_manager.py`.
- Ajoutez donc le schéma final/idempotent dans `database.py` **et** une migration
  numérotée `XXXX_description.py` dans `migrations/`. Prenez le prochain numéro
  disponible ; ne renumérotez et ne modifiez pas l'historique déjà livré.
- Une migration expose `NOM`, `DESCRIPTION`, `upgrade(conn)` et
  `downgrade(conn)`. `upgrade` doit être idempotente autant que SQLite le
  permet et préserver les données existantes.
- Ajoutez la version à `ALL_MIGRATION_VERSIONS` quand elle est incluse dans le
  schéma des installations neuves. Testez explicitement une base neuve et, si
  la migration transforme des données, un état antérieur représentatif.
- Ne versionnez jamais `*.db`, `.env`, sauvegardes, logs ou documents métier.

## 6. Templates, JavaScript et CSS

- Réutilisez le template de base, les macros, composants et classes CSS
  existants avant d'introduire une nouvelle variante.
- Jinja échappe le contenu par défaut : n'ajoutez `|safe` que pour du HTML
  généré et assaini de manière fiable.
- Tous les formulaires mutatifs doivent conserver la protection CSRF. Les
  appels `fetch` mutatifs doivent transmettre le jeton selon le mécanisme déjà
  utilisé dans le dépôt.
- Le serveur reste la source de vérité : une validation JavaScript améliore
  l'expérience, mais ne remplace pas la validation Python.
- Préservez l'accessibilité : `label` associés, navigation clavier, focus
  visible, boutons avec type explicite et informations qui ne dépendent pas de
  la couleur seule.
- Préservez la compatibilité mobile. Évitez les largeurs fixes et vérifiez les
  tableaux, modales et actions principales sur une petite largeur.
- Ne modifiez pas les fichiers tiers de `static/js/vendor/`. Si une dépendance
  doit évoluer, ajoutez la version officielle minifiée et documentez sa source
  et sa version.

## 7. Sécurité et confidentialité

- Ne lisez, n'affichez, ne commitez et ne journalisez aucun secret ni donnée
  réelle (`.env`, clés API, mots de passe, base locale, documents RH, factures).
- Ne désactivez pas CSRF, le rate limiting, les cookies sécurisés ou les
  contrôles d'autorisation pour contourner un test.
- Pour les mots de passe, utilisez les helpers Werkzeug existants ; ne créez
  pas de nouvel algorithme de hachage.
- Pour les fichiers téléversés, contrôlez extension, taille et nom, utilisez
  un nom sûr, empêchez le path traversal et stockez-les sous `DATA_DIR` via les
  helpers existants.
- Échappez les sorties utilisateur, paramétrez le SQL et évitez de révéler une
  exception, un chemin local ou une configuration sensible dans la réponse
  HTTP.
- Toute modification touchant authentification, permissions, uploads,
  sauvegardes, exports ou IA doit inclure des tests négatifs (non connecté,
  mauvais profil, entrée invalide ou ressource appartenant à autrui).

## 8. Stratégie de tests

- Utilisez les fixtures existantes (`client`, `auth_client`, `resp_client`,
  `comptable_client`, `admin_client`, `db`, `sample_users`) avant d'en créer.
- Les tests disposent d'une base SQLite temporaire et désactivent CSRF et le
  rate limiter. Ne reproduisez jamais ces réglages dans le code de production.
- Pour une route, testez le statut ou la redirection, l'effet en base et le
  message/rendu utile. Pour un calcul, privilégiez des tests unitaires purs et
  couvrez limites, valeurs nulles et cas incohérents.
- Les tests doivent être déterministes : dates explicites, aucune dépendance au
  réseau, à l'ordre d'exécution, à une base locale ou à l'heure réelle sauf si
  celle-ci est injectée/figée.
- Simulez les appels externes (SMTP, fournisseurs IA, HTTP et système de
  fichiers lorsque pertinent). N'utilisez jamais une vraie clé ou un service
  payant dans les tests.
- Ne relâchez pas une assertion existante uniquement pour faire passer un
  changement ; vérifiez d'abord si le comportement métier attendu a réellement
  évolué.

## 9. Fichiers générés et périmètre documentaire

Ne modifiez pas ou ne versionnez pas les artefacts d'exécution : `.env`, bases
SQLite et fichiers WAL, `backups/`, `documents/`, `logs/`, contrats générés,
caches Python et environnements virtuels. Le PDF de convention collective à la
racine est une référence documentaire : ne le remplacez pas sans demande
explicite.

Mettez à jour `README.md` ou `docs/` lorsqu'une commande, une configuration ou
un parcours utilisateur change. Ne changez `VERSION.txt` que si la tâche ou le
processus de livraison l'exige ; une modification fonctionnelle ordinaire ne
justifie pas à elle seule une hausse de version.

## 10. Critères de fin

Une intervention est terminée lorsque le comportement demandé est implémenté,
les autorisations et cas d'erreur sont couverts, les données existantes restent
compatibles, les tests ciblés et la suite pertinente passent, la documentation
est cohérente et `git diff` ne contient ni artefact ni modification étrangère à
la tâche.
