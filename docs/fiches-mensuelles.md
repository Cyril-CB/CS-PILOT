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

Le responsable et la direction peuvent signer dans les deux ordres. Le
verrouillage exige leurs approbations du même contenu. Un directeur également
responsable du salarié signe les deux rôles en une action. Pour la fiche
personnelle d'un responsable, l'approbation de la direction suffit toujours.
La signature du salarié reste facultative pour le verrouillage, conformément
à la règle existante ; une ancienne signature facultative n'est pas affichée
comme une approbation actuelle.

Si quelqu'un modifie la fiche ouverte, l'interface indique les anciennes
signatures et demande une nouvelle approbation. Les actions des responsables
et de la direction tiennent compte de cet état. Une page restée ouverte avant
une modification doit être relue avant de pouvoir signer.

Pour corriger une fiche verrouillée, la direction doit d'abord utiliser
**Déverrouiller** et saisir un motif. Cette action conserve l'historique et
retire les approbations actives. Après correction, les signatures nécessaires
doivent être recueillies à nouveau. Être directeur ne dispense jamais de cette
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

## Vérifications avant fusion

Les tests d'intégration de `tests/test_fiches_versions.py` exercent les vrais
calculs et la base SQLite : signatures périmées, ordres de signature, rôles,
contrats, refus de POST incomplet, mutations indirectes, absence multi-mois,
congé approuvé, réouverture motivée, rollback complet, concurrence,
migration relançable/interrompue et contenu PDF.

Les fixtures existantes de signatures ont été adaptées pour envoyer la
référence réellement affichée. Celles du dashboard modifient désormais le
contenu métier au lieu de déduire l'obsolescence d'une date de journal.
Un ancien test d'autorisation signait une fiche vide : il renseigne maintenant
les heures afin de continuer à tester l'autorisation avec une fiche complète.

Commandes à exécuter avec les dépendances du projet et des données fictives :

```sh
pytest tests/test_fiches_versions.py tests/test_validation.py tests/test_equipe_responsable.py
pytest
python -m compileall -q app.py blueprints migrations tests fiches_*.py
git diff --check
```

Compléter sur un environnement navigateur accessible, en ordinateur et mobile :

1. Responsable signe → l'action disparaît → salarié modifie → l'action revient
   → direction signe sans clôturer sur l'ancien accord → responsable signe à
   nouveau → verrouillage. Vérifier en base que les deux références requises
   égalent `version_courante_id` et que le contenu PDF correspond à l'instantané.
2. Fiche verrouillée → modifier rétroactivement le planning ou créer une
   absence → refus lisible et base inchangée → direction réouvre avec motif
   → modification acceptée → nouvelles signatures → nouveau verrouillage.
   Vérifier les événements de réouverture, signatures et verrouillage.

Lors du contrôle du 5 septembre 2026, le navigateur distant a refusé l'accès
au serveur local (`ERR_BLOCKED_BY_CLIENT`). Ces deux parcours visuels restent
à effectuer ; les parcours HTTP automatisés et leurs assertions en base sont
couverts. Aucun déploiement n'a été effectué pour contourner cette limite.
