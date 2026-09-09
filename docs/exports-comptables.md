# Exports comptables : contenu conservé et suivi après export

## Parcours utilisateur

1. Importer la facture PDF, avec ou sans extraction IA. La facture est « à traiter ».
2. Générer une proposition d'écritures. La facture devient « traitée » ; ses lignes sont en **brouillon**. « Traitée » signifie que les écritures ont été générées, pas qu'elles ont été approuvées, exportées ou importées dans AIGA.
3. Vérifier et éventuellement modifier les lignes. Leur validation manuelle les rend **validées**. Une modification ultérieure avant export crée une nouvelle révision et remet la ligne en brouillon ; une ancienne page ne peut plus la valider ou l'exporter.
4. Dans **Exportation des écritures**, sélectionner toutes les lignes validées de chaque facture concernée. Le serveur contrôle les droits actuels, le contenu affiché, les sources, l'absence d'export précédent et l'équilibre de chaque pièce.
5. Télécharger le fichier TXT. Les lignes deviennent **exportées** et un lot conserve le fichier exact, les lignes et leurs versions, l'auteur, la date UTC, le nombre de lignes et les totaux.
6. Consulter le lot depuis la page Exportation, les écritures ou le détail de la facture. Les valeurs présentées sont celles du fichier conservé, même si les renseignements courants du fournisseur ont changé.

Le circuit d'approbation de la facture (en attente / approuvée, responsable du secteur ou direction, avec les accès déjà existants) reste indépendant de la validation comptable. Aucune approbation préalable n'est ajoutée comme condition d'export.

**Exportée par CS PILOT ne signifie pas importée dans AIGA.** Aucun accusé d'import AIGA n'existe dans le parcours actuel.

## Règles métier validées pour cette phase

Les règles suivantes et la conservation **facture + PDF + écritures + historique + fichier exporté original** ont été confirmées par Cyril lors de la revue de ce chantier.

| Sujet | Règle validée |
|---|---|
| Équilibre | Chaque facture constitue une pièce complète et équilibrée. Le lot l'est donc aussi. La ventilation analytique peut produire plusieurs débits pour une même facture. |
| Export partiel | Refus d'une partie des lignes d'une facture, même si cette sélection est équilibrée. Plusieurs factures complètes peuvent être exportées ensemble. |
| Approbation facture | Circuit indépendant, comportement existant conservé : aucune approbation préalable n'est exigée pour l'export comptable. |
| Correction après export | Écritures et export immuables. Une anomalie peut être signalée, motivée et tracée, sans correction comptable automatique. Le futur processus sera défini séparément selon le fonctionnement d'AIGA. |

Dans l'usage actuel précisé par Cyril, ce module est une aide à la saisie des factures. Les autres modules utilisent les imports AIGA BI/FEC ; ce chantier ne remplace pas ces données par les propositions d'écritures de CS PILOT.

Le signalement de correction **n'est pas une correction comptable exécutée** : il ne crée pas de nouvelle ligne exportable, ne marque pas le lot « corrigé » et ne réécrit pas l'histoire. L'export initial reste identifiable.

Les montants sont contrôlés au centime, sans tolérance d'équilibre ni arrondi silencieux : valeurs finies, non négatives et au plus deux décimales ; un seul côté débit ou crédit positif par ligne. Les montants invalides doivent être corrigés avant validation/export. Les colonnes ne peuvent pas contenir de tabulation, retour à la ligne ou caractère de contrôle, qui introduiraient une colonne ou une ligne supplémentaire dans le TXT.

## Après export : conservation, archivage et nouveau téléchargement

Une tentative de modification d'une ligne exportée est refusée et tracée. La suppression physique de sa facture est aussi refusée, y compris si seules certaines de ses lignes avaient été exportées historiquement.

La comptabilité et la direction peuvent **archiver la facture avec un motif** depuis son détail. Le PDF, les écritures et les historiques sont conservés. La facture sort des listes actives et des relances ; elle reste accessible par « Voir les factures archivées », la recherche et les liens des lots. Les informations d'approbation ne sont ni fabriquées ni effacées. Les factures jamais exportées restent supprimables, même si leurs lignes étaient validées ; un événement de suppression indépendant reste conservé.

Les archives d'export, anciennes et nouvelles, ne sont plus supprimables depuis l'application. Un fichier ancien peut être la seule trace conservée de son contenu.

Un nouvel export d'une ligne déjà exportée est refusé. Pour récupérer un fichier perdu, ouvrir son lot puis confirmer **Télécharger à nouveau le même fichier**. L'action est tracée comme nouveau téléchargement ; elle ne crée pas un nouveau lot et ne remet aucune ligne dans la file d'export. Vérifier dans AIGA avant tout nouvel import. Le lien GET historique reste compatible et ses téléchargements sont désormais tracés.

Si la réponse réseau est interrompue après un export réussi, retrouver le lot dans les archives et utiliser cette action. L'enregistrement du lot établit que le fichier a été produit et conservé ; il n'établit pas sa réception sur le poste ni son import dans AIGA.

## Preuve et atomicité (maintenance)

La table `archives_export` existante devient le lot explicite, sans second objet concurrent :

- `preuve_version=1` : fichier binaire UTF-8 exact, empreinte SHA-256, format `aiga-txt-v1`, auteur enregistré (identifiant et nom à cette date), date, nombre de lignes et totaux en centimes ;
- `export_lignes` : position dans le fichier, identifiants écriture/source, révision, valeurs source et neuf colonnes réellement émises ; unicité de l'écriture exportée ;
- `comptabilite_evenements` : événements indépendants des cascades de suppression, avec copie du nom de l'acteur ;
- `ecritures_comptables.revision` : incrémentée lors d'un changement de contenu, avec retour automatique en brouillon ;
- références de formulaire signées : acteur, identifiant d'écriture, contenu, source, révision et état.

Les neuf colonnes restent celles du format existant : journal `AC`, date `JJMMAAAA`, compte/code auxiliaire, libellé majuscule, référence facture, débit, crédit, analytique, échéance `JJMMAAAA`. Il n'existe pas de colonne site ni de colonne tiers séparée dans ce format ; aucune n'est inventée. Le compte/code auxiliaire et la source fournisseur sont conservés explicitement.

L'export prend `BEGIN IMMEDIATE`, recontrôle la session et le rôle actuels, puis toute la sélection. Un vrai fichier temporaire est écrit et relu, ses octets sont vérifiés et le temporaire est fermé **avant** d'enregistrer le lot. Le fichier définitif est le BLOB conservé dans SQLite, dans le même commit que les lignes et leurs états. Il n'existe donc pas de fichier externe définitif à renommer après commit, ni de cache à réparer pour télécharger un lot.

Une panne de création, écriture, lecture ou fermeture du temporaire, d'enregistrement SQL ou de commit annule l'opération. Les réponses de succès ne sont produites qu'après commit. La concurrence d'écriture est sérialisée ; deux exports des mêmes lignes ne créent qu'un lot. Les protections SQL empêchent modification/suppression des preuves, des lignes exportées et des sources/historiques nécessaires, indépendamment du bouton utilisé. Elles n'ont aucune prétention à protéger contre un administrateur modifiant directement le schéma ou remplaçant la base.

`ConnexionFiches`, les contrôles mensuels, la préparation de paie et les autres migrations restent inchangés. Les helpers n'effectuent aucun commit.

La génération IA ne détient pas le verrou SQL pendant l'appel distant. Son contexte source est lu dans une transaction cohérente ; au retour, les droits, les identifiants attendus, le contenu et l'absence d'écritures préexistantes sont revérifiés sous verrou. Une réponse tardive ou portant sur une autre facture ne peut pas écraser ou compléter silencieusement une facture déjà traitée.

## Migration 0069 et ancien historique

La migration et `init_db()` appliquent le même schéma idempotent. Aucun fichier métier n'est lu lors de la migration.

- Les anciennes lignes `exportee` sont identifiées par `export_historique=1`. Leurs montants, statuts et dates sont conservés.
- Les anciennes archives ont `preuve_version=0`, leurs références de fichier et métadonnées d'origine restent intactes. Aucun BLOB, total ou lien aux écritures courantes n'est inventé.
- L'interface indique : **Export historique antérieur au nouveau système — contenu exact non garanti par CS PILOT.**
- Le schéma ancien ne liait pas une archive à ses lignes. Un nom de fichier et une date ne suffisent pas pour reconstituer ce lien de façon fiable. Les anciens fichiers restent téléchargeables par leur référence existante, s'ils sont présents. S'ils ont disparu, CS PILOT le signale sans reconstruire leur contenu.
- Une facture historiquement partiellement exportée reste consultable, archivable et peut faire l'objet d'un signalement. Son reliquat ne devient pas automatiquement une nouvelle pièce exportable ; son traitement relève du futur processus de correction, défini séparément.
- Les nouvelles révisions commencent à 1 sur le contenu courant. Cela ne prétend pas identifier la version d'un ancien fichier.

Aucune reconnexion globale n'est nécessaire. Recharger les pages d'écritures et d'export ouvertes avant la migration pour obtenir leurs nouvelles références. La migration ne réinitialise aucun état RH. Le retour arrière doit passer par une sauvegarde préalable cohérente ; `downgrade` refuse la destruction silencieuse des nouvelles preuves.

Les nouveaux TXT augmentent la taille de la base, avec leurs lignes détaillées. Leur conservation bénéficie de la sauvegarde SQL existante. Ce chantier ne modifie pas la stratégie de sauvegarde des anciens fichiers ou des PDF source.

## Limites volontaires

Pas de simulation de l'import AIGA, de contrepassation ou de nouvelle écriture corrective sans décision métier. Pas de reconstruction de sources supprimées historiquement, de réparation automatique d'anciens exports partiels ou de rapprochement fondé sur une date approximative. Pas de refonte des dashboards : seuls les filtres nécessaires à l'archivage sont adaptés. Sauvegardes, autres audits, paie et règles d'équipe restent hors périmètre.
