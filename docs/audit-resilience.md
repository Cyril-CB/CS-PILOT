# Audit B4 / B10 — résultats du 11 septembre 2026

Base auditée sans modification initiale : `main`, commit
`f297bca0884a89f83b05469a745200f791ab3560` (après fusion de la PR 254).
Toutes les manipulations ont utilisé des bases et fichiers fictifs isolés.
Aucun VPS, secret, document métier ou backup de production n’a été consulté.

## Constats sur main

**B4 confirmé pour le mécanisme intégré.** `creer_sauvegarde()` utilisait déjà
l’API SQLite backup, adaptée au WAL. En revanche, le ZIP ne couvrait que
`documents/`, dans une opération distincte de la copie DB. Il manquait les
factures, modèles de contrats, contrats générés, anciens exports et configuration
nécessaire au déchiffrement. La restauration web remplaçait la base en service,
sans restaurer les documents du même point. Le secours avant réinitialisation
était une copie brute `.db` ignorant le WAL ; son échec était ignoré.

Cela ne démontre **pas** que la production était dépourvue de protection :
l’exploitant déclare une sauvegarde complète OVH quotidienne et sept jours
d’historique. Son périmètre et sa restauration n’ont pas été observés.

**B10 reproduit exactement.** Avec une migration fictive levant une exception :

| Observation avant correction | Résultat |
| --- | --- |
| État enregistré | `erreur` |
| Migrations en attente | `0` |
| `a_jour` | `true` |
| Relance après correction de la cause | `UNIQUE constraint failed: schema_migrations.version` |
| Donnée issue de la relance | Persistée malgré l’annonce d’échec, car commit antérieur au journal |

Les migrations anciennes comportent de nombreux `conn.commit()` internes. Les
migrations récentes 0065, 0067, 0068 et 0069 préparent une transaction, mais le
gestionnaire séparait encore leur commit du journal de succès. 0066 et 0070
dépendaient de la transaction de l’appelant.

`init_db()` laissait 20 migrations (0041–0060) en attente alors que leur schéma
était présent. La comparaison réelle avec une base construite à partir de 0001
puis toutes les migrations a identifié quatre écarts : table
`plan_comptable_general`, colonne `contrats.temps_hebdo`, nullabilité de
`prepa_paie_statut.traite`, FK de `subventions.action_budget_id`.

## Scripts VPS historiques

Les scripts `scripts/migration/export-data.sh`, `import-data.sh`,
`reencrypt_settings.py` et `docs/migration-vps.md` ont été retrouvés dans
l’historique Git, notamment au commit `cf90b40`. Ils ne sont pas présents dans
le `main` audité et n’ont pas été exécutés.

Le dernier export historique connaissait les cinq répertoires et copiait toute
la base : les nouveaux BLOB auraient donc été transportés. Cela ne suffisait pas
à garantir la reprise : arrêt facultatif, copie des fichiers après la DB, clé
ancienne placée en clair dans le tar non chiffré, priorité `.env`/environnement
différente du démarrage, extraction tar non contrôlée, chemins absolus non
relocalisés, copie de secours DB brute, rechiffrement via arguments et erreurs
ignorées, message final d’import possible malgré un échec de migration.

Ils ne sont pas réactivés. Les nouvelles commandes documentées remplacent ce
besoin d’export/restauration applicatif sans piloter de service système.

## Solution livrée

- Export **des données applicatives** complet chiffré : SQLite/WAL, cinq
  répertoires, configuration effective et correspondances de chemins ; manifeste
  avec tailles, SHA-256, versions Python/SQLite, révision Git et dépendances.
- Arrêt des écrivains exigé ; contrôle d’inventaire avant/après ; refus des
  données incohérentes, tables de preuves absentes, liens et volumes non restaurables.
- Restauration authentifiée dans une destination inexistante, sans écrasement,
  démarrage, migration automatique ni nettoyage de preuves.
- Conservation des chemins historiques en DB ; relocalisation explicite des
  factures et anciens exports, même si la source reste joignable.
- Conservation de la `SECRET_KEY` ou rechiffrement complet transactionnel, sans
  exposer de clé dans les arguments/rapports ; mauvaise clé détectée au démarrage.
- Migrations atomiques avec journal de tentatives, ordre et concurrence contrôlés,
  reprise sûre des échecs rollbackés et reprise historique explicite après diagnostic.
- Migration 0071 de convergence ; catalogue neuf corrigé. Les anciens fichiers
  de migration et `VERSION.txt` restent inchangés.
- Copies ponctuelles clairement identifiées dans l’interface ; restauration à
  chaud désactivée ; secours SQLite avant réinitialisation vérifié et obligatoire.

L’inventaire détaillé, la classification de criticité et les commandes sont dans
[la procédure d’exploitation](resilience.md). Le code exact, ses éventuelles
modifications locales et la configuration du VPS restent à conserver séparément.

## Restauration réellement testée

La source fictive comprend utilisateurs, contrat/PDF, document salarié,
justificatif et absence, récupération, fiche complète approuvée par salarié,
responsable et direction puis verrouillée, préparation de paie vérifiée, facture
PDF, écritures équilibrées, ancien fichier exporté et nouvel export BLOB,
paramètres SMTP/API chiffrés, subventions et annexes, modèle et contrat généré.
Un orphelin est présent pour vérifier sa conservation.

La sauvegarde est restaurée ailleurs. Toutes les tables, identifiants, séquences
et valeurs sont comparés à la source, ainsi que tous les fichiers métier. La
source devient ensuite inaccessible. Un **nouveau processus** démarre avec la
configuration restaurée ; il vérifie les migrations et le déchiffrement, se
connecte avec la protection CSRF réelle, télécharge les documents/facture/ancien
export et retélécharge le BLOB comptable avec **le même SHA-256**. Le texte du PDF
mensuel verrouillé est identique. Les connexions réseau sortantes sont interdites.

Le rechiffrement avec une nouvelle clé est testé réellement : seul
`app_settings` change, toutes les autres tables sont identiques, la nouvelle clé
relit le secret fictif et l’ancienne échoue. Un paramètre illisible interdit tout
rechiffrement partiel. Un service ayant gardé une autre clé refuse de démarrer.

Le scénario J−3 ajoute un nouveau document puis supprime le fichier actuel après
la sauvegarde. La restauration retrouve toutes les données et le document de
J−3, sans le fichier postérieur et sans dépendance au stockage source.

## Mesure observée, RPO et RTO

Sur ce petit jeu synthétique : archive chiffrée **36 034 octets**, base restaurée
**843 776 octets**.

| Étape mesurée | Durée |
| --- | ---: |
| Authentification de l’archive, restauration et diagnostics | 0,312 s |
| Nouveau processus, démarrage, authentification, documents, PDF et export | 0,842 s |

Création/transfert d’un VPS et restauration OVH : **non mesurés**. Aucune migration
n’était nécessaire pour cette archive récente. Les migrations sont exercées
séparément par les tests. Ces durées ne sont **pas un engagement de RTO**.
Le RPO OVH déclaré reste théoriquement **≤ 24 heures**, à confirmer sur un point
réellement restauré. Aucun RPO de production n’a été mesuré.

## Tests ajoutés et résultats

40 scénarios supplémentaires : 23 dans `test_resilience.py`, 14 dans
`test_migrations_resilience.py`, 3 dans `test_backup.py`. Le test existant de
restauration web valide désormais le refus sans effet d’un remplacement à chaud.

Couverture principale : T1–T9, WAL non checkpointé, comparaison de toutes les
preuves, archive modifiée, phrase incorrecte, destination préexistante, chemin
hostile, référence retirée de l’archive, fichier manquant, clé absente/différente,
refus du rechiffrement partiel, changement de fichiers pendant copie, archive
trop volumineuse, sauvegarde après restauration, erreur sans fichier de migration,
syntaxe de migration invalide, double exécution concurrente, COMMIT/ROLLBACK SQL,
ancien échec partiel, arrêt brutal réel par `os._exit`, conservation des lignes et
triggers des anciens schémas, refus d’un faux état « à jour » en administration,
collision de noms de sauvegarde et réinitialisation annulée sans secours.

| Vérification exécutée | Résultat |
| --- | --- |
| Régressions sur main avant correctif | 3 échecs attendus, 1 succès ; B10 reproduit séparément |
| Tests ciblés sauvegarde, migrations, DB, documents, factures/exports, versions/circuit, administration/droits | **366 réussis**, 73,36 s |
| Derniers tests sauvegarde/restauration, migrations et accès après relecture | **96 réussis**, 30,15 s |
| Suite complète finale | **2 138 réussis**, 252,05 s |
| `compileall` et `git diff --check` | Vérifiés lors de la préparation de la PR |
| CodeQL | Contrôle GitHub attaché à la PR ; statut final indiqué dans sa description |

La première campagne complète a été interrompue par l’environnement d’exécution.
Le résultat ci-dessus correspond à une nouvelle campagne terminée avec code 0.

## Fichiers modifiés et raison

| Fichier(s) | Raison |
| --- | --- |
| `resilience.py` | Export chiffré, restauration vérifiée, diagnostic et rechiffrement |
| `resilience_cli.py` | Commandes hors ligne, saisie protégée et codes de sortie |
| `stockage_restaure.py` | Correspondances des chemins absolus historiques |
| `blueprints/factures.py`, `blueprints/exportation.py` | Téléchargement/nettoyage dans le stockage restauré, sans modifier les preuves |
| `fiches_db.py` | Transaction de migration avec commit final contrôlé, y compris pour les anciens scripts |
| `migration_manager.py` | États, journal de tentatives, ordre, échecs et reprise |
| `database.py`, `schema_resilience.py`, `migrations/0071_resilience.py` | Convergence neuf/migré, initialisation atomique, dossier des données et démarrage explicite |
| `app.py`, `lancer.sh` | Vérifications avant service ; configuration dotenv non exécutée comme du shell |
| `backup_db.py`, `blueprints/administration.py` | Copies WAL vérifiées, permissions, collisions, restauration hors ligne et secours obligatoire |
| `templates/backup.html`, `templates/administration.html` | Périmètre explicite et échecs/tentatives visibles |
| Trois fichiers de tests cités ci-dessus | Régressions B4/B10 et protections négatives |
| `README.md`, `docs/resilience.md`, présent rapport | Exploitation, scénarios S1–S5, inventaire, checklist snapshot et exercice OVH |

## Relecture et limites

La relecture a notamment corrigé la reconstruction de table avec triggers
dépendants, la comparaison des valeurs par noms de colonnes, les collisions qui
pouvaient supprimer une copie préexistante, le risque d’un export dépassant les
limites de son restaurateur, et le faux succès possible si une table de preuves
avait disparu. Les références absolues, l’accès persistant au serveur source et
la conservation des preuves ont été testés explicitement.

Le navigateur cloud refuse l’aperçu local : `net::ERR_BLOCKED_BY_CLIENT`.
Les pages ont été rendues et vérifiées par les tests HTTP, mais le contrôle
visuel ordinateur/mobile reste à réaliser. Aucune protection réseau n’a été
contournée pour accéder à cet aperçu.

Restent hors périmètre : restauration/snapshot OVH réel, configuration des
services/disques/DNS/TLS, fusion automatique de deux états SQLite, correction
comptable automatique, politique de rétention métier et SLA. L’arrêt de tous les
écrivains et la conservation externe de la phrase/code demeurent des obligations
d’exploitation. Les répertoires de travail privés peuvent devoir être examinés
après un arrêt brutal du processus ; ne pas les publier ni les traiter comme des
archives chiffrées finales.

La mise à niveau nécessite un arrêt, la migration 0071 et les contrôles avant
redémarrage. Cette migration ne change pas la clé ni les sessions ; un
rechiffrement avec nouvelle clé lors d’une restauration impose une reconnexion.
Les cinq scénarios de reprise, la checklist pré-mise à jour et les six étapes du
test OVH isolé figurent dans [la procédure](resilience.md).
