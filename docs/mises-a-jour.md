# Mises à jour de CS PILOT

## Pour le centre

Un directeur ou un comptable ouvre **Mise à jour**, clique sur **Vérifier les
mises à jour**, puis sur **Installer la mise à jour**. Il prévient les autres
utilisateurs de la courte interruption. Il n'a plus à créer manuellement une
sauvegarde, redémarrer le serveur ou appliquer les migrations dans Administration.

L'écran indique la préparation, la sauvegarde, la migration et la vérification
du démarrage. Fermer l'onglet n'arrête pas l'opération. Pendant l'interruption,
les autres utilisateurs voient une page de maintenance qui se rafraîchit.
Le succès n'est annoncé qu'après démarrage du nouveau processus et contrôle HTTP.

Un échec de téléchargement ou de préparation conserve l'application courante.
Un échec après le début des migrations déclenche le rétablissement du code, de
son environnement Python et des données d'avant la mise à jour. Le centre peut
réessayer après avoir consulté le message affiché. Si le rétablissement lui-même
échoue, l'application reste fermée aux écritures et affiche une référence pour
le support. Le terminal reste alors un outil de dépannage exceptionnel.

Les deux dernières versions installées avec succès et leurs sauvegardes de mise
à jour sont conservées automatiquement, ainsi que la version nécessaire au
retour arrière. Les dossiers d'échec restent disponibles pour le diagnostic.
Ces sauvegardes sont locales : maintenir aussi une sauvegarde extérieure au VPS.

## Activation sur une installation existante

Cette évolution n'ajoute aucune migration de schéma. Sur une installation dont
les migrations sont déjà à jour, le bouton de mise à jour antérieur peut installer
ces fichiers, puis effectuer son dernier redémarrage habituel. `lancer.sh`
et `LANCER.bat` lancent ensuite le superviseur. `python app.py` le lance également
hors mode debug et hors exécutable. Aucun nouveau droit sudo n'est nécessaire.

Le premier redémarrage dépend encore de l'ancien mécanisme : si son appel
`sudo systemctl restart cspilot` n'était pas autorisé, le support doit réaliser
ce redémarrage une fois. Les installations qui importent directement `app:app`
avec un serveur WSGI personnalisé, les conteneurs avec plusieurs workers et les
exécutables PyInstaller nécessitent une adaptation initiale. La page détecte
l'absence de superviseur et refuse le remplacement en place au lieu de promettre
une installation automatique qu'elle ne peut pas réaliser.

Pour le VPS utilisant déjà `bash lancer.sh` dans `cspilot.service`, conserver le
service, son utilisateur, sa configuration et le port public. Après installation,
vérifier que la page **Mise à jour** propose l'installation automatique et que
`GET /__cspilot__/mise-a-jour` répond avec `disponible: true`.

Le déploiement du superviseur doit être réalisé sur un schéma sain. Une ancienne
migration en erreur, une clé perdue ou un démarrage déjà bloqué ne sont pas
contournés : suivre le [diagnostic de résilience](resilience.md) avant activation.

## Contrat du déploiement supervisé

- Un superviseur et un processus applicatif par `CSPILOT_DATA_DIR`. Toutes les
  écritures doivent passer par ce processus. Ne pas laisser tourner d'ancien
  worker, de tâche cron ou de second service écrivant dans le même stockage.
- `CSPILOT_DATA_DIR` conserve sa valeur d'origine, même quand le code change de
  dossier. Sans configuration, il correspond au dossier de l'installation.
- La configuration est chargée avec python-dotenv ; l'environnement reste
  prioritaire sur `.env`, notamment pour `SECRET_KEY`. Aucun `source .env`,
  aucune nouvelle clé générée par le moteur de mise à jour.
- Le superviseur garde le port public (`PORT`, défaut 5000). Le processus Flask
  utilise un port temporaire sur `127.0.0.1`, avec un jeton interne renouvelé.
  Les requêtes directes à ce processus sans jeton sont refusées.
- Le frontal Waitress transmet les corps en flux, les cookies multiples,
  téléchargements, en-têtes CSRF et contexte client. La configuration
  `BEHIND_PROXY` conserve son sens : ne l'activer que derrière un proxy de
  confiance et restreindre l'accès direct au port public dans ce cas.
- Le superviseur refuse les nouvelles requêtes pendant la maintenance et attend
  jusqu'à deux minutes la fin des réponses en cours. Si elles ne se terminent
  pas, il annule l'opération et laisse fonctionner la version précédente.
- Les processus sont surveillés par des pipes : la disparition du superviseur
  ferme ces pipes. Le processus applicatif s'arrête et la garde des commandes
  termine leurs descendants. Des verrous de fichiers empêchent deux superviseurs
  ou des processus applicatifs/de maintenance concurrents.
- Le service et les répertoires de données restent privés à leur utilisateur
  d'exploitation. Le superviseur n'effectue aucune élévation de privilèges.

## Installation et point de publication

Le canal des sources reste la branche `main` du dépôt **Cyril-CB/CS-PILOT**.
L'interface vérifie un SHA complet ; la demande signée en session expire après
30 minutes. L'installation télécharge ce SHA exact, même si `main` évolue entre
les deux clics. Le navigateur ne fournit ni URL, ni commande, ni chemin.
Le numéro de `VERSION.txt` est affiché séparément de la révision : une ancienne
release GitHub n'est plus présentée comme la version des sources installées.

Chaque demande crée un répertoire privé :

```
DATA_DIR/.cspilot-updates/
  etat.json                   # version active, phase, version précédente
  demande.json                # une demande exclusive, supprimée à la fin
  service.lock / worker.lock  # verrous détenus par les processus
  releases/<reference>/
    app/                      # sources isolées, REVISION-SOURCES.txt
    venv/                     # dépendances propres à cette version
    sources.zip               # archive du SHA sélectionné
    operations.log            # sortie privée des commandes
    avant.cspbackup           # sauvegarde complète chiffrée
    phrase-secrete            # fichier privé 600 ; ne jamais publier
    donnees-echec/             # données écartées lors d'un retour arrière
    resultat.json             # marqueur autorisant la rétention automatique
```

Le téléchargement est borné à 512 Mio, l'extraction à 2 Gio et 50 000 entrées.
Les traversées, liens, racines multiples et chemins dupliqués sont refusés.
Les données et environnements inclus par erreur dans une archive sont ignorés.
`update-protocol.json` doit correspondre au protocole et aux stockages connus.

La préparation crée un venv séparé, installe `requirements.txt`, vérifie ses
cohérences et compile les sources avant d'interrompre l'application. Le contrôle
d'espace réserve six fois le volume des données plus 3 Gio pour la préparation
et le retour arrière ; il est répété après installation des dépendances.

Après arrêt confirmé du worker, le moteur appelle les CLI de résilience avec
la même configuration effective : sauvegarde complète, puis migrations hors
ligne de la version candidate. Une sauvegarde refusée interdit la migration.
Le moteur ne demande jamais une reprise historique forcée d'une migration.

Le nouveau processus doit passer le contrôle de schéma et des paramètres
chiffrés de `app.py`, un contrôle HTTP privé lié à son PID et une requête réelle
sur `/login`. Ensuite, une seule écriture atomique publie la version active et
la réussite, avant de rouvrir les accès. Une coupure avant cette publication
entraîne une reprise avec les données précédentes ; après publication, aucun
retour arrière automatique ne doit effacer des écritures nouvellement acceptées.

La restauration utilise d'abord un dossier vierge vérifié. Elle ne remplace
jamais `DATA_DIR` lui-même : seules la base, ses WAL/SHM, la configuration, les
cinq stockages et les fichiers de relocalisation sont rétablis. Les données de
l'échec sont conservées. L'opération peut reprendre après une coupure au milieu
des déplacements de fichiers.

Le superviseur reste chargé pendant les mises à jour courantes ; il ne dépend
pas du nouveau Flask pour afficher la maintenance. Au prochain redémarrage du
service, il reprend aussi son propre code et ses dépendances depuis la version
active. Une évolution incompatible du protocole ou une mise à niveau du
superviseur déjà en mémoire relève de l'exploitation et peut nécessiter un
redémarrage ponctuel par le support. Les mises à jour applicatives ordinaires
n'appellent pas systemd.

Après activation, utiliser le bouton pour les déploiements applicatifs. Un
`git pull` dans le dépôt d'origine ne change pas la version isolée sélectionnée
dans le journal ; il ne constitue plus à lui seul un déploiement.

## Diagnostic exceptionnel

Le statut public expose uniquement phase, disponibilité et référence. Les
raisons détaillées accessibles au directeur/comptable restent des messages
contrôlés ; les sorties de commandes, chemins et données restent dans les
fichiers privés. Ne jamais joindre `phrase-secrete`, `.env`, des archives ou des
journaux métier à une issue publique.

En cas d'intervention demandée, le support arrête le service et tous ses
processus avant de manipuler les données. Il conserve `etat.json`, le dossier
de la demande et les données courantes, puis vérifie le journal d'opérations,
l'espace disque, les droits, la clé effective et l'état des migrations.
Les commandes de [résilience hors ligne](resilience.md) restent utilisables sans
importer l'application. Une restauration manuelle se fait vers un nouveau dossier,
avec `avant.cspbackup` et le fichier privé `phrase-secrete`, puis est testée avec
le code et le Python de la version précédente. Ne pas simplement effacer le
journal ni revenir au code ancien sur une base déjà migrée.

Les tests automatisés couvrent les processus réels et le frontal sous Linux,
Python 3.12. Le lanceur Windows et la terminaison d'arbre par `taskkill` demandent
une validation sur Windows avant généralisation à ces postes. Les déploiements
WSGI personnalisés, les stockages externes, changements majeurs de Python et
migrations exigeant une décision humaine restent hors du parcours automatique.
