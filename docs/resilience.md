# Sauvegarde, restauration et reprise après mise à jour

Cette procédure concerne les données applicatives de CS PILOT. Elle complète la
sauvegarde infrastructure OVH ; elle ne pilote ni le VPS, ni les snapshots.
**Ne jamais commencer un exercice de restauration sur la production.**

## Stratégie retenue

| Protection | Rôle | Limites / contrôle attendu |
| --- | --- | --- |
| Sauvegarde complète OVH quotidienne, historique 7 jours (configuration déclarée par l’exploitant) | Perte du VPS, retour à un état quotidien | Garanties SQLite/WAL, volumes inclus, durée et intégrité : **à confirmer par test de restauration OVH** |
| Snapshot OVH manuel avant grosse mise à jour | Retour au point immédiatement précédent | Pas d’intégration automatique ; ne remplace pas l’historique quotidien |
| Export applicatif complet chiffré | Reconstruction des données, migration de serveur, copie indépendante et vérifiable | Arrêter tous les écrivains ; conserver le code correspondant et la phrase secrète hors du VPS |
| Copies ponctuelles de la page Sauvegardes | Extraction SQLite et ZIP du seul dossier `documents/` | Partielles, non chiffrées, produites séparément ; ne permettent pas seules une reconstruction |
| Exercice périodique isolé | Vérifier qu’une sauvegarde se restaure réellement | Conserver date, sauvegarde testée, résultat, anomalies et durées |

La rotation existante conserve 20 copies SQLite et 20 ZIP documentaires. L’export
complet n’ajoute **aucune rotation ni suppression automatique**. Définir la
conservation et la copie hors machine avec l’exploitant, sans multiplier les
archives complètes sans objectif. Ne pas mettre les exports complets dans un
dossier servi par le serveur web.

## Inventaire de reconstruction

`DATA_DIR` est le dossier des données. Par défaut : dossier du projet en mode
script, emplacement utilisateur en mode exécutable. `CSPILOT_DATA_DIR` permet de
le fixer explicitement, indépendamment du code ; il doit être défini **avant**
le lancement. Le nom de la base est `cspilot.db`.

| Élément | Contenu et références | Criticité | Export complet |
| --- | --- | --- | --- |
| SQLite | Utilisateurs, droits/session_version, contrats, saisies, absences/récupérations et provenance, budgets, paramètres | Historique métier irremplaçable ; certains imports seraient recréables avec effort | Copie intégrale via API SQLite backup, WAL pris en compte |
| Preuves dans SQLite | `fiches_versions`, validations, événements/réouvertures, préparation de paie et empreintes ; `archives_export.contenu`, SHA-256, `export_lignes`, événements et historique des factures | Historique métier irremplaçable | Conservées sans nettoyage, recalcul, nouvelle signature ni régénération d’export |
| `documents/` | `documents_salaries.fichier_path`, `contrats.fichier_path`, `absences.justificatif_path` | Historique métier irremplaçable | Tous les fichiers et sous-dossiers |
| `documents/subventions/` | `subventions.justificatif_path`, `subventions_sous_elements.document_path` | Historique métier irremplaçable | Inclus dans `documents/` |
| `factures/` | PDF originaux, `factures.fichier_path` historiquement absolu | Historique métier irremplaçable | Tous les fichiers ; correspondance de chemins pour changement de serveur |
| `modeles_contrats/` | Modèles DOCX personnalisés | Recréable avec effort, original à conserver | Tous les fichiers |
| `contrats_generes/` | DOCX effectivement produits, `contrats_generes.fichier_path` | Historique métier à conserver ; une nouvelle génération peut différer | Tous les fichiers présents ; ne reconstitue pas des versions déjà supprimées |
| `exports/` | Anciens fichiers référencés par `archives_export.fichier_path` | Historique irremplaçable lorsqu’il s’agit du fichier d’époque | Tous les fichiers ; les nouveaux exports exacts résident dans SQLite |
| `.env`, configuration effective | `SECRET_KEY`, `APP_TIMEZONE`, `BEHIND_PROXY`, `PORT`, `FLASK_DEBUG`, `MAX_UPLOAD_MO` ; autres valeurs du `.env` | Secrets/configuration nécessaires au démarrage | Configuration sérialisée **à l’intérieur de l’enveloppe chiffrée** ; environnement prioritaire comme au démarrage |
| `app_settings` | Paramètres applicatifs, SMTP, mots de passe et clés API chiffrés | Secret nécessaire à la restauration : `SECRET_KEY` | Valeurs incluses dans SQLite ; déchiffrement intégral vérifié |
| Code, migrations, templates, assets, `requirements.txt`, référence convention collective | Version applicative et dépendances | Reconstructible depuis Git à la révision archivée, si les sources restent disponibles | Révision Git et empreinte des dépendances dans le manifeste ; **code à conserver séparément** |
| Configuration VPS | OS, paquets système, service de démarrage, chemins, propriétaire, reverse proxy, TLS, DNS, éventuels volumes et tâches | Recréable avec effort ; secrets d’exploitation à conserver séparément | Hors export applicatif ; inventaire réel à compléter par l’exploitant |
| `.git`, environnement virtuel, caches, fichiers temporaires | Construction/exécution | Reconstructible | Exclus |
| `logs/`, `backups/` | Diagnostic opérationnel, copies précédentes | Utiles à l’investigation ; pas la source des preuves métier | Exclus de l’export complet, pas de sauvegarde récursive des sauvegardes |

Les PDF mensuels et exports non archivés sont généralement calculés à la demande.
Un PDF de fiche verrouillée doit toujours utiliser son instantané SQLite. Un
fichier d’export comptable historique ne doit jamais être remplacé par une
régénération sous prétexte qu’il pourrait être recalculé.

## Créer un export applicatif complet

Prérequis : code correspondant disponible, dépendances installées, espace libre,
phrase secrète conservée séparément (gestionnaire de mots de passe recommandé),
répertoire d’archives privé. Les exemples utilisent des chemins fictifs à adapter.

1. Vérifier la sauvegarde quotidienne ; conserver la version du code et les
   éventuelles modifications locales. Une révision Git seule ne restitue pas
   un arbre modifié non commité.
2. Arrêter CS PILOT, tous ses workers, tâches planifiées, scripts d’import et
   autres écrivains. Empêcher leur redémarrage automatique pendant l’opération.
   Le nom du service dépend de l’installation, il n’est pas deviné par CS PILOT.
3. Lancer, depuis le code de l’application :

```bash
python resilience_cli.py diagnostic --data-dir /srv/cspilot-donnees
python resilience_cli.py sauvegarder --data-dir /srv/cspilot-donnees --archive /srv/archives-privees/avant-maj.cspbackup --application-arretee
```

La phrase est demandée sans affichage ni passage sur la ligne de commande. Pour
une exécution automatisée, `--phrase-fichier /chemin/prive/phrase` accepte un
fichier privé, permissions `600`, sans lien symbolique. `--cle-fichier` permet de
fournir la `SECRET_KEY` effective lorsqu’elle n’est pas disponible dans le `.env`
ou l’environnement du processus d’exploitation. Ne pas écrire une clé dans les
arguments, journaux ou captures d’écran.

Le verrou SQLite `BEGIN IMMEDIATE` empêche une nouvelle écriture DB pendant la
copie. Il **ne suffit pas** à arrêter un téléchargement ou une écriture disque
déjà engagée : l’arrêt de tous les écrivains est obligatoire. Le programme
contrôle aussi l’inventaire avant/après la copie et refuse un changement détecté.
L’option `--application-arretee` est une déclaration de l’opérateur, pas une
détection du service ni une garantie contre un autre programme écrivant les fichiers.

L’archive contient SQLite, les cinq stockages, la configuration protégée, une
correspondance des chemins et un manifeste de SHA-256/tailles. Les orphelins sont
inclus et signalés, jamais supprimés. Une référence manquante, une preuve altérée
ou une clé indéchiffrable fait échouer l’export complet : aucun fichier final
n’est publié. Pour conserver une installation endommagée aux fins d’expertise,
garder sa copie/snapshot isolé ; ne pas la qualifier de sauvegarde vérifiée.

L’enveloppe utilise AES-256-GCM, sel/nonce aléatoires, dérivation Scrypt
(`N=131072`, `r=8`, `p=1`) et authentification de l’en-tête. Minimum 16 caractères
pour la phrase ; choisir une phrase longue et imprévisible. Lecture par blocs,
limite 32 Gio par archive et 32 Gio décompressés. Les fichiers de travail sont
dans un répertoire privé `700`, l’archive finale en `600`. Prévoir environ la base
copiée + le ZIP + l’archive chiffrée en espace temporaire ; la restauration demande
le ZIP déchiffré + les fichiers restaurés. Aucun stockage chiffré n’est déchiffrable
si la phrase de sauvegarde est perdue.

La copie SQLite s’appuie sur [l’API backup Python](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).
Le ZIP n’est jamais ouvert avant la validation complète du tag [GCM](https://cryptography.io/en/48.0.1/hazmat/primitives/symmetric-encryption/#cryptography.hazmat.primitives.ciphers.modes.GCM).

## Restaurer dans un emplacement vierge

Sur un environnement isolé, avec sorties SMTP/API/réseau de production bloquées
**avant le premier démarrage**, installer le code et ses dépendances, puis :

```bash
python resilience_cli.py restaurer --archive /srv/archives-privees/avant-maj.cspbackup --destination /srv/restauration-test
python resilience_cli.py diagnostic --data-dir /srv/restauration-test
```

La destination doit être inexistante. Une installation déjà présente n’est jamais
écrasée. L’archive est authentifiée, ses chemins/tailles/hash contrôlés, puis la
base et ses références vérifiées dans une zone privée avant publication du dossier.
Une erreur ne publie pas de destination partielle. Le programme ne démarre pas
l’application et n’applique pas de migrations automatiquement.

Le manifeste d’origine reste conservé ; `restauration-rapport.json` indique la
restauration et l’éventuel rechiffrement. Le manifeste décrit le contenu d’origine :
en cas de rechiffrement, l’empreinte du fichier DB restauré peut changer, mais les
preuves RH/comptables et leur contenu restent identiques.

`restauration-chemins.json` relie les anciennes références absolues aux fichiers
restaurés sous `DATA_DIR`. **Le conserver avec les données** : factures et exports
historiques utilisent cette correspondance, même si le serveur source existe
encore. Les valeurs d’historique dans SQLite ne sont pas réécrites. Une nouvelle
sauvegarde d’une installation restaurée conserve ces correspondances.

Si le rapport signale seulement des migrations en attente, les données sont
restaurées, mais la commande sort avec le code `2` et `ok: false` : ne pas ouvrir
les accès. Employer d’abord le code correspondant à la sauvegarde ou vérifier la
mise à niveau sur cette copie. Ne jamais faire tourner un ancien code contre un
schéma plus récent sans compatibilité démontrée.

Après diagnostic et validation fonctionnelle :

```bash
export CSPILOT_DATA_DIR=/srv/restauration-test
python app.py
```

Adapter propriétaire, service, port, proxy et certificat dans la configuration
d’exploitation. `.env` est lu par `python-dotenv` ; **ne jamais l’exécuter avec
`source`**. Un `SECRET_KEY` déjà exporté dans le shell ou le service prend priorité
sur le fichier : vérifier que c’est la bonne clé. Le démarrage normal par `app.py`
contrôle les migrations et le déchiffrement avant de servir des requêtes. Pour
une autre entrée WSGI, exécuter ces contrôles explicitement avant d’activer le service.

### Changer de SECRET_KEY

Conserver la clé d’origine est le comportement par défaut. Elle dérive la clé
Fernet de **tous** les `app_settings`, y compris les paramètres non secrets en
apparence. La changer sans rechiffrement rendrait ces valeurs illisibles.

```bash
python resilience_cli.py restaurer --archive /srv/archives-privees/avant-maj.cspbackup --destination /srv/restauration-test --nouvelle-cle-fichier /chemin/prive/nouvelle-cle
```

Tous les paramètres sont déchiffrés avant la première modification, puis
rechiffrés dans une transaction. Un seul paramètre illisible annule l’opération.
La nouvelle clé est écrite dans le `.env` privé de la destination. Les clés ne sont
jamais affichées. Les sessions signées avec l’ancienne clé deviennent invalides :
**reconnexion nécessaire**. Après un retour temporel de production, recommander
également une nouvelle clé avec rechiffrement pour empêcher la réutilisation de
sessions dont les révocations postérieures au point restauré auraient été perdues.

## Diagnostic automatisé et contrôle fonctionnel

`diagnostic` est en lecture seule et retourne du JSON, code `0` si tout est bon,
code `2` sinon. Il contrôle :

- `PRAGMA integrity_check`, toutes les tables attendues à la version (y compris
  CSE, budgets et trésorerie), migrations en attente/en erreur/inconnues ;
- références documentaires manquantes, par table et identifiant ; fichiers
  orphelins présents (signalement sans suppression) ;
- SHA-256 des BLOB d’export et des instantanés, JSON et dates des instantanés ;
- clés étrangères de la base et déchiffrement des paramètres.

Cela ne prouve pas toute la cohérence métier ni la configuration réseau du VPS.
Compléter avec : démarrage, connexion direction/salarié, téléchargement document,
contrat et justificatif, facture PDF, PDF d’une fiche verrouillée, dates/versions/
signatures/historique, état de préparation de paie et retéléchargement d’un export
avec **le même SHA-256**. Ne pas envoyer de relance, e-mail ou requête IA réelle.
Les tests automatisés réalisent ce parcours avec des données fictives et les
connexions sortantes interdites.

Le catalogue `resilience.TABLES_REQUISES` couvre les 107 tables du schéma actuel
(avec `schema_migrations` contrôlée séparément). Un test compare ce catalogue
au schéma neuf et à chaque étape des migrations : toute future table doit y être
ajoutée avec sa version d'introduction. Une table attendue absente interdit
l'export complet et la restauration, même si l'archive est authentique. Une
ancienne sauvegarde n'est pas tenue de contenir les modules apparus ensuite.

## Migrations : états et reprise

Seul `schema_migrations.statut = 'ok'` compte comme appliqué. Une erreur reste
en attente ; même une erreur dont le fichier manque empêche l’état « à jour ».
Toute version enregistrée mais inconnue du code installé empêche aussi l'état
« à jour », le démarrage et l'application des migrations, y compris avec
`--reprise-historique`. L'administration et le statut CLI l'identifient dans
`inconnues`. Cela protège notamment d'un retour à un ancien code contre une
base déjà mise à niveau : remettre le code compatible ou restaurer un ensemble
code/données cohérent. Ne jamais supprimer les lignes de migration pour passer
ce contrôle.
Le nombre de migrations appliquées exclut les erreurs. Les tentatives sont
conservées dans `schema_migrations_tentatives` ; les anciennes dates d’échec
connues sont reprises, sans affirmer qu’un rollback avait eu lieu.

Chaque migration s’exécute sous `BEGIN IMMEDIATE` : schéma, données, ligne de
succès et tentative réussie forment **un seul commit**. Les `commit()` internes
des anciennes migrations sont neutralisés uniquement dans ce contexte ; les
contrôles métier de la connexion s’exécutent au commit final. Une erreur rollbacke
DDL et données avant d’enregistrer l’échec. Un arrêt brutal du processus laisse
SQLite annuler la transaction ; sans succès durable, la migration reste en attente.
Il n’y a pas de faux état « en cours » durable à réinitialiser manuellement.

L’ordre est contrôlé sous le verrou ; deux processus ne peuvent pas appliquer
deux fois la même version. Un échec ancien peut contenir des effets déjà commités :
**il n’est pas rejoué automatiquement**. Après diagnostic sur une copie isolée,
soit restaurer le point préalable, soit vérifier l’idempotence et utiliser la
reprise explicite d’une seule version.

```bash
python resilience_cli.py migrer --data-dir /srv/cspilot-donnees --application-arretee
# Uniquement après diagnostic d'un ancien échec et répétition isolée réussie :
python resilience_cli.py migrer --data-dir /srv/cspilot-donnees --application-arretee --version 0070 --reprise-historique
```

Un code de sortie non nul interdit la remise en service. Ne pas marquer une
migration réussie à la main pour faire disparaître son erreur. Les erreurs
nouvelles exposent leur type et le résultat du rollback, sans recopier les valeurs
sensibles d’une exception.

La migration **0071** crée le journal et corrige les écarts de schéma constatés :
`contrats.temps_hebdo`, `plan_comptable_general`, nullabilité de
`prepa_paie_statut.traite` et FK de `subventions.action_budget_id`. Les deux tables
qui nécessitent une reconstruction conservent valeurs, identifiants, séquences,
index et triggers. Un NULL incompatible ou une colonne personnalisée inconnue
fait échouer la transaction au lieu d’être corrigé arbitrairement. Aucun ancien
fichier de migration n’est modifié. Les versions 0041–0060 figurent désormais dans
le catalogue des installations neuves. Un redémarrage n’exécute plus la réparation
historique `init_db()` sur une base existante : passer par le gestionnaire.

## Mise à jour importante : checklist

1. Identifier les versions avant/après et les migrations prévues ; vérifier une
   sauvegarde quotidienne récente et lisible, noter sa date réelle.
2. Prévenir les utilisateurs, arrêter les écrivains et leurs redémarrages.
3. Demander manuellement le snapshot OVH ; attendre son achèvement et noter son
   identifiant, sans supposer qu’une demande suffit à le rendre exploitable.
4. Créer l’export applicatif complet vérifié ; conserver phrase et code précédent
   séparément. Copier l’archive hors de la machine suivant la politique choisie.
5. Mettre le code à jour, installer les dépendances, appliquer les migrations
   hors ligne. Vérifier le code de sortie et le diagnostic.
6. Tester les parcours de contrôle, puis seulement rouvrir les accès.
7. Conserver le snapshot pendant la période de surveillance ; décider de sa
   suppression selon la politique OVH, jamais automatiquement depuis CS PILOT.

## Scénarios de reprise

| Incident | Conduite et pertes possibles |
| --- | --- |
| S1 — suppression/modification à 15 h | Restaurer la sauvegarde nocturne **à côté**, vérifier la donnée recherchée et extraire sélectivement les éléments nécessaires. Une restauration globale ferait perdre les écritures valides intervenues depuis la nuit. Réintégrer par un parcours métier contrôlé ; ne pas fusionner les lignes SQLite ni inventer signatures/provenances. Pas de fusion automatique dans ce lot. |
| S2 — perte totale du VPS | Créer un VPS isolé ; réinstaller OS/service/proxy/TLS et code correspondant ; restaurer OVH ou l’export applicatif ; récupérer les secrets ; contrôler DB/fichiers/preuves/auth ; ouvrir les accès seulement après validation. DNS et droits système nécessitent l’inventaire d’exploitation. |
| S3 — mise à jour ratée | Garder les accès arrêtés ; conserver copie et journaux de l’état en échec ; diagnostic du statut et de l’intégrité. Si cette migration a été annulée intégralement, corriger et retester sa reprise. Des migrations précédentes du lot peuvent avoir réussi : un rollback du code seul n’annule pas le schéma. Si nécessaire, restaurer code **et** données/fichiers du point préalable ou le snapshot, d’abord isolément. |
| S4 — base corrompue | Arrêter les écritures ; conserver l’état endommagé pour expertise ; chercher la dernière sauvegarde dont `integrity_check` et les contrôles fonctionnels passent. Restaurer séparément, mesurer l’intervalle perdu, puis basculer. Ne pas considérer une récupération SQLite partielle comme une restitution complète des preuves. |
| S5 — mauvaise migration découverte J+2 | Préserver l’état actuel et ses opérations valides ; explorer les points OVH quotidiens des 7 jours et les exports applicatifs antérieurs. Restaurer le point précédant le problème avec son code. Comparer les deux jours d’activité et définir la reprise sélective avec le métier. Le snapshot immédiat n’est pas la seule source ; éviter un retour global aveugle. |

Une restauration J−3 rend l’état **de J−3**, documents compris. Les nouveaux IDs,
modifications, révocations et fichiers créés après sont absents. L’exercice de
test vérifie que cet état ancien ne dépend plus du stockage source récent.

## RPO et RTO

Le **RPO** est la quantité de travail potentiellement perdue. L’objectif déclaré
avec une sauvegarde OVH quotidienne est **théoriquement ≤ 24 h** si les sauvegardes
réussissent et se restaurent. Ce n’est pas une garantie observée. Si le dernier
point valide est plus ancien, la perte augmente ; l’historique de 7 jours borne
également les retours possibles. Le lot applicatif ne change pas cette fréquence.

Le **RTO** est le temps de remise en service. Aucun engagement métier n’est fixé.
Noter séparément : création du VPS/environnement, transfert, restauration,
migrations, contrôles et réouverture. Les secondes mesurées sur de petites données
fictives dans cet audit ne représentent ni un transfert OVH ni le volume réel.

## Exercice OVH manuel sans risque pour la production

1. Dans OVH, choisir une sauvegarde quotidienne complète (et, lors d’un autre
   exercice, un snapshot pré-mise à jour). Noter date et périmètre des volumes.
2. Restaurer sur **un nouveau VPS de test**, réseau isolé, sans modifier le DNS ni
   remplacer/disconnecter le VPS de production. Avant tout boot applicatif,
   bloquer les sorties SMTP/API et l’accès aux services de production, neutraliser
   service automatique, workers et tâches planifiées dans la copie.
3. Vérifier que tous les disques/dossiers attendus et la configuration sont
   présents. Conserver ensemble les fichiers SQLite/WAL/SHM issus du même point
   avant ouverture ; ne pas jeter le WAL d’une simple copie disque.
4. Sur la copie, lancer `diagnostic`, puis l’application avec le code correspondant.
   Vérifier les parcours listés plus haut, la date des dernières données, les
   signatures/versions, les PDF et SHA-256 comptables ; tester quelques documents
   répartis sur les cinq stockages. Ne jamais employer des services sortants réels.
5. Noter anomalies et temps de chaque étape, RPO constaté sur ce point, périmètre
   réellement récupéré et résultat. C’est cet exercice qui peut confirmer les
   garanties infrastructure ; il n’a pas été réalisé depuis ce dépôt.
6. Arrêter et supprimer **uniquement** le VPS de test, ses volumes et copies
   sensibles après conservation du rapport sans données métier. Vérifier les
   identifiants pour ne supprimer ni production ni sauvegarde d’origine.
