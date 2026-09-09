# Fiches mensuelles : signatures et réouverture

Une signature approuve le contenu précis de la fiche affichée. Si ce contenu
change avant le verrouillage, les anciennes approbations restent dans
l'historique mais une nouvelle signature est nécessaire. Une fiche verrouillée
conserve ses journées, ses totaux et ses soldes, y compris dans le PDF.

## Parcours utilisateur

Le salarié, le responsable et la direction conservent leurs droits habituels.
Le serveur refuse une signature tant que le mois n'est pas terminé ou que des
journées attendues restent à renseigner. Les repos planifiés, jours fériés,
limites inclusives et interruptions de contrat gardent leurs règles existantes.
Une ancienne saisie manuelle reste visible même hors contrat.

Le circuit est obligatoirement **Salarié → Responsable → Direction**.
Chaque étape approuve la même version métier. Le salarié utilise **Valider ma
fiche** après lecture. Sans son accord courant, aucune approbation responsable
ou direction n'est possible, y compris par POST manuel. La direction verrouille
uniquement après les deux accords précédents.

Un responsable qui valide sa propre fiche enregistre deux approbations :
**salarié** et **responsable**, sur la même version, avec le même acteur et le
même horodatage. Deux événements identifient ces qualités. Cette règle remplace
l'ancienne dispense sur sa fiche personnelle, y compris sans secteur configuré.
Un directeur également responsable applicable peut de même enregistrer les
approbations **responsable** et **direction** en une action, après l'accord du
salarié. Il n'y a jamais de signature générique valant implicitement deux rôles.

Pour les autres personnes, le périmètre reste **même secteur OU rattachement
direct** (`est_dans_equipe_responsable`). La fonction textuelle d'un utilisateur
n'ajoute aucun droit : les profils et rattachements existants restent l'autorité.
La fiche personnelle d'un directeur conserve le traitement existant (forfait
jour dans l'interface) ; aucun pouvoir supplémentaire d'auto-clôture n'est créé.

Si personne n'est habilité à l'étape responsable, la fiche attend cette étape.
La relance signale l'absence de responsable applicable ; la direction doit faire
vérifier le rattachement habituel. Aucun contournement ni nouveau remplaçant
n'est introduit. Ce cas est couvert avec des données fictives ; aucune donnée
RH de production n'a été consultée pour déduire une nouvelle règle.

Si le contenu change après un ou deux accords, les approbations antérieures
restent tracées mais deviennent obsolètes. Le circuit repart du salarié.
Une page restée ouverte sur un contenu périmé doit être relue avant de signer.

Pour corriger une fiche verrouillée, la direction doit d'abord utiliser
**Déverrouiller** et saisir un motif. Cette action conserve l'historique et
retire les approbations actives. Après réouverture, les trois approbations du nouveau circuit
doivent être recueillies à nouveau, même si le contenu reste identique. Être directeur ne dispense jamais de cette
réouverture explicite.

Une correction portant sur plusieurs mois est annulée entièrement si elle
affecte l'un de leurs contenus verrouillés. Le message précise la première
fiche à réouvrir. Cela s'applique aussi aux effets sur les soldes reportés :
une correction d'heures antérieures, du solde initial ou des heures
supplémentaires payées peut nécessiter la réouverture des mois suivants.
Préparer ces corrections avant le verrouillage évite de multiplier les
nouvelles signatures. Les autres variables de paie ne sont pas bloquées si
elles ne changent aucune valeur de la fiche.

Le fil d'actions garde son périmètre M−1. Une fiche ouverte plus ancienne reste
accessible par la navigation mensuelle et la vue d'ensemble des validations.

## Choix de conception

1. **Version métier.** Un instantané JSON conserve les journées, leur contexte
   utile, l'identité affichée, la complétude, les absences et les totaux/soldes.
   Un numéro croissant identifie chaque contenu successif d'un salarié/mois.
2. **Modification pertinente.** Une empreinte SHA-256 déterministe compare ce
   contenu. Une modification sans effet sur ce contenu ne crée pas de version.
   Les horodatages ne servent pas à départager deux opérations : des opérations
   dans la même seconde sont correctement distinguées.
3. **Signature.** Chaque rôle conserve le nom, la date et la référence de
   l'instantané approuvé. Le formulaire transmet également l'empreinte du
   contenu présenté ; elle est vérifiée côté serveur.
4. **Obsolescence.** Une signature dont la référence diffère de la version
   courante ne participe plus au verrouillage. Les anciens accords et les
   changements sont conservés dans les événements de la fiche.
5. **Verrouillage.** Complétude, référence affichée, signatures et verrouillage
   sont vérifiés et écrits dans une transaction SQLite `BEGIN IMMEDIATE`.
   La lecture de la page et celle du PDF utilisent chacune une transaction
   cohérente. Une fiche verrouillée est rendue depuis son instantané.
6. **Historique existant.** La migration conserve les noms, dates et verrous.
   Elle fige le contenu constaté lors de la reprise sans prétendre reconstituer
   le contenu au jour des anciennes signatures.

Un simple timestamp ne prouve pas les valeurs approuvées et peut confondre
deux changements simultanés. Un hash seul ne permet pas de relire le contenu
ancien. L'instantané, son empreinte et sa référence donnent cette preuve
locale sans ajouter de service ni changer la base de données.

## Sources couvertes et point de contrôle

| Sources | Effet pris en compte |
| --- | --- |
| Heures réelles, déclarations conformes, pauses et commentaires | Journées, heures, écarts, complétude |
| Planning, historique de validité, alternance | Horaires et heures théoriques, déclarations conformes |
| Périodes scolaires/vacances, jours fériés | Planning applicable et jours attendus |
| Contrats | Présence attendue, bornes et interruptions |
| Absences ajoutées, modifiées, supprimées, y compris sur plusieurs mois | Contexte d'absence et heures projetées |
| Congés et récupérations approuvés, dont récupérations partielles | Absences/heures créées et état de la demande dans la même transaction |
| Solde initial, heures antérieures, HS payées déduites | Soldes affichés, y compris reports sur les mois suivants |
| Nom et prénom | Identité conservée dans la fiche |

`fiches_contenu.py` fournit le calcul commun à l'écran, aux contrôles et au
PDF. `fiches_versions.py` gère les instantanés et les événements.
`get_db()` retourne `ConnexionFiches` : des triggers SQLite enregistrent les
salariés affectés par les écritures, puis `commit()` contrôle leurs fiches
déjà signées. Un contenu verrouillé différent provoque un rollback de toute
la transaction, y compris compteurs, demandes et journal. Les fichiers liés
à une absence ou un contrat ne sont supprimés qu'après un commit réussi.
Le nettoyage refuse les chemins sortant du dossier des pièces. Un fichier
absent est accepté ; un échec disque (droits, verrou Windows) est journalisé
séparément et ne transforme pas une suppression SQL réussie en erreur métier.
La pièce résiduelle peut nécessiter un nettoyage manuel ; aucune relance
automatique du nettoyage n'est ajoutée. La même règle préserve le message
initial lorsqu'un justificatif nouvellement téléversé doit être retiré après
le refus d'une modification de fiche verrouillée.

Les producteurs métier doivent toujours utiliser `get_db()`, conserver
l'isolation transactionnelle par défaut et appeler `conn.commit()` une seule
fois après leurs écritures liées. Les curseurs, `executemany` et les blocs
`with conn` sont couverts. Un `COMMIT` SQL direct est refusé. Ne pas introduire
de connexion brute, d'autocommit ou de transaction externe via un savepoint
pour une écriture métier : ces chemins n'offrent pas ce contrat de contrôle.
Une nouvelle source de calcul doit être ajoutée au suivi dans
`fiches_versions.py` et `fiches_db.py`, avec un test de rollback.

La protection concerne les chemins applicatifs. Les sauvegardes/restaurations
et les modifications manuelles de SQLite sont des opérations d'exploitation,
pas un moyen de corriger une fiche métier. Les instantanés sont un historique
applicatif ; ils ne constituent pas un scellement cryptographique indépendant
d'un administrateur ayant accès à la base.

## Migration 0065

La migration `0065_versions_fiches_mensuelles.py` et `init_db()` appellent le
même schéma idempotent. Ils ajoutent `fiches_versions`, `fiches_evenements`,
les quatre références de version dans `validations`, et la file de recalcul
avec ses triggers. Les valeurs d'heures et les signatures existantes ne sont
pas réécrites. Relancer la migration ne duplique pas les reprises.

Les fiches historiques verrouillées restent verrouillées ; leur écran et
leur PDF signalent que le contenu exact des anciennes signatures n'est pas
vérifiable. Les fiches ouvertes conservent leurs anciennes signatures dans
l'historique, mais nécessitent de nouvelles approbations pour être verrouillées.
Il n'est pas possible de réparer rétroactivement la preuve d'une signature
antérieure à cette évolution.

Pour une future mise en service :

1. Arrêter les écritures et effectuer une sauvegarde complète selon la
   procédure d'exploitation habituelle.
2. Tester cette mise à niveau sur une copie représentative de la base à jour
   des migrations précédentes. Vérifier les volumes et le temps de reprise :
   les soldes historiques sont recalculés pour chaque fiche existante.
3. Appliquer le code et la migration 0065 par le circuit habituel, puis
   vérifier une fiche historique verrouillée et une fiche ouverte signée.
4. Vérifier l'état de migration dans l'administration et prévenir les
   utilisateurs concernés par les nouvelles signatures nécessaires.

La migration démarre une transaction si l'appelant n'en a pas déjà une et
ne commite pas elle-même. Un échec permet le rollback du schéma et de la
reprise. Il n'existe pas de downgrade destructif automatique : un retour
nécessite la sauvegarde précédente et le code correspondant.

## Migration 0067 : circuit applicable et date de bascule

`validations.circuit_version` rend le circuit explicite :

| État lors de la première application du schéma 0067 | Circuit et effet |
| --- | --- |
| Fiche déjà verrouillée | `1` : verrou, noms, dates et références de versions conservés intégralement |
| Fiche ouverte, même partiellement approuvée | `2` : retour à l'étape salarié ; anciennes références d'approbation retirées, noms/dates et événements conservés |
| Nouvelle fiche | `2` par défaut |
| Fiche historique réouverte explicitement | Nouveau circuit `2`, avec l'ancien circuit tracé dans l'événement de réouverture |

La bascule correspond au premier démarrage de ce code via `init_db()` ou à
l'application de la migration 0067 par le gestionnaire, selon lequel intervient
en premier. Il ne s'agit pas d'une date de mois choisie a posteriori. Un événement
`bascule_circuit` conserve la date effective, les anciennes approbations et le
circuit attribué. L'existence de la colonne empêche une seconde bascule : un
nouveau verrou en circuit 2 ne devient pas historique au redémarrage.

Cette migration ne recalcule pas les instantanés créés par 0065, ne modifie pas
leurs versions et ne fabrique aucune signature salarié. Les fiches ouvertes
repartent volontairement du salarié : on ne peut pas supposer que leurs anciens
accords avaient respecté le nouvel ordre. L'opération est transactionnelle et
idempotente, commune à la base neuve et à la base existante. Aucun changement de
session ni reconnexion spécifique n'est nécessaire ; les pages ouvertes avant
la bascule doivent être relues. Pas de downgrade destructif automatique.

Pour la mise en service future : arrêter les écritures, sauvegarder selon la
procédure habituelle, appliquer sur une copie représentative, puis installer
le code et appliquer les migrations par le circuit habituel. Vérifier le
maintien d'un verrou ancien et le retour au salarié d'une fiche ouverte. Cette
PR ne déclenche ni déploiement ni migration sur la production.

## Confirmation des anciennes fiches verrouillées

Ces fiches restent valablement clôturées selon le **circuit historique :
Responsable → Direction**. L'absence d'accord salarié ne constitue pas une
anomalie. Le salarié peut ouvrir **Confirmer mes anciennes fiches verrouillées**,
lire le contenu figé puis confirmer aujourd'hui ce contenu. La direction dispose
d'une liste distincte et d'une action **Inviter le salarié à confirmer**.

La confirmation est un événement `confirmation_historique`, rôle `salarie`, avec
son véritable auteur, sa véritable date et l'identifiant exact de l'instantané
verrouillé. Elle ne remplit pas rétroactivement `validation_salarie`, ne participe
pas au verrouillage d'origine et ne modifie ni contenu, ni version, ni signatures,
ni date de clôture. La référence et l'empreinte sont vérifiées avec la propriété
de la fiche dans une transaction. Une répétition ne crée aucun doublon.

Le PDF lit toujours l'instantané verrouillé. Il peut ajouter une mention datée
**a posteriori**, séparée des signatures initiales. Pour les fiches antérieures
au versionnement 0065, la limite de preuve d'origine reste affichée : le salarié
confirme l'état figé lors de cette reprise, sans reconstitution impossible.

Une confirmation déjà acquise sur l'instantané courant ne produit pas de rappel.
Après confirmation tardive, les invitations salarié et direction disparaissent.
Les anciens verrous restent exclus des relances et des blocages du mois courant.

## Actions, relances et historique

Les actions normales gardent le périmètre M−1 ; les autres mois restent
consultables depuis la navigation et la vue d'ensemble. Les confirmations
historiques souhaitées regroupent tous les mois verrouillés historiques.
Le responsable ne reçoit une action que lorsque le salarié a approuvé la version
courante. La direction voit successivement l'attente salarié, l'attente responsable
et sa propre action finale. La comptabilité conserve sa visibilité de suivi.

La relance groupée vise l'acteur de l'étape courante : salarié, responsable ou
direction. La relance individuelle responsable reste limitée à son périmètre et
aux fiches effectivement à son étape. Les réglages et le consentement email
existants restent respectés. Les invitations historiques sont distinctes et
n'envoient jamais de rappel responsable/direction pour un verrou déjà acquis.

L'historique distingue les trois rôles d'approbation, l'obsolescence des accords,
les changements de contenu, le verrouillage, la réouverture motivée, la bascule
de circuit et la confirmation salarié tardive. Les anciennes confirmations
ne satisfont jamais une étape du circuit après réouverture.

## Vérifications avant fusion

`tests/test_circuit_fiches.py` couvre T1–T6, les refus sans écriture, la migration,
les doubles rôles, les références invalides et les accès à autrui, les relances,
les actions, le PDF figé, les sessions révoquées, CSRF et les opérations concurrentes.
Les tests de versions continuent de vérifier les sources indirectes de modification,
les périodes de contrat, les refus de modification verrouillée et le rollback.
Les anciens scénarios d'ordre libre sont remplacés par le nouvel ordre métier.

```sh
pytest tests/test_circuit_fiches.py tests/test_fiches_versions.py tests/test_validation.py
pytest tests/test_equipe_responsable.py tests/test_perimetres_sessions.py tests/test_dashboard_actions.py
pytest
python -m compileall -q app.py blueprints migrations tests fiches_*.py
git diff --check
```

À vérifier en navigateur ordinateur et mobile sur un environnement accessible :
le parcours salarié → responsable → direction ; la double approbation personnelle ;
la réouverture motivée ; la consultation et confirmation d'un ancien instantané,
avec disparition des invitations et séparation des dates dans le PDF.

Contrôle du 9 septembre 2026 : le navigateur distant refuse le serveur local
(`ERR_BLOCKED_BY_CLIENT`). Le rendu visuel ordinateur/mobile reste à vérifier
sur l'environnement de recette ; les parcours HTTP, le HTML utile et les PDF
sont contrôlés par les tests. Aucun déploiement n'a été effectué pour cette
vérification.
