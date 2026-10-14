# Sites physiques, fournitures et produits d’entretien

## Deux modules séparés, une base commune pour les sites

**Commandes salariés** reste le module de demandes de fournitures : description
libre, référence, quantité, prix facultatif et urgence. Il propose désormais une
file par site, par exemple « Commandes Cyprian » et « Commandes Les Brosses ».
Chaque site peut avoir son propre responsable des fournitures.

**Produits d’entretien** est un autre module : catalogue de produits, quantités
par lieu demandeur, regroupement des besoins, suivi de commande et avis de
réception. Le responsable des commandes d’entretien peut être différent du
responsable des fournitures, y compris sur le même site.

Les sites représentent des lieux physiques au sein d’une seule installation.
Ils ne remplacent ni les secteurs analytiques ni les profils utilisateurs et
ne constituent pas une isolation de toute l’application. Cette version applique
les périmètres aux deux modules de commandes seulement. Les anciens
`lieux_travail` des contrats ne sont pas convertis ni modifiés.

## Mise en place

Depuis **Administration → Sites et commandes** (direction ou comptabilité) :

1. Créer les sites souhaités. Aucun nom de site ni salarié réel n’est créé par
   la migration.
2. Pour chaque site, sélectionner les salariés autorisés à demander des
   fournitures. Un salarié peut appartenir à plusieurs sites.
3. Désigner séparément le responsable des fournitures et celui de l’entretien.
   Chaque module possède au plus un responsable par site. Une même personne
   peut gérer plusieurs sites ou les deux modules.
4. Dans **Produits d’entretien → Catalogue et lieux demandeurs**, sélectionner
   le site qui centralise les commandes. Ajouter ses lieux demandeurs et le
   responsable des besoins de chacun. Un responsable de lieu peut être choisi
   sans lui donner l’accès aux fournitures de ce site.
5. Ajouter la liste de départ des 22 produits puis ajuster les conditionnements.
   La liste distingue les lavettes par couleur et les sacs par contenance.
   Unités et catalogue sont propres au site. Les produits existants ne sont
   ni écrasés ni réactivés par un nouveau clic sur la liste de départ.

Un lieu demandeur est un point de besoin desservi par la file de commande du
site choisi. Gribouille et Angle 9 peuvent donc dépendre du même site qui
centralise leurs achats. Ce rattachement ne déplace pas les secteurs RH ou
comptables correspondants.

La création du premier site ferme les nouveaux dépôts dans la file globale :
préparer les appartenances et responsables avant d’annoncer la mise en service.
Un site sans responsable reste accessible à la direction/comptabilité, mais
aucun salarié ne reçoit de mission de traitement automatiquement.

## Parcours entretien

1. Le responsable des besoins choisit son lieu et indique les quantités en
   boîtes, paquets, bidons, etc. Zéro signifie « pas de besoin ». Un commentaire
   est facultatif. La demande est transmise directement, sans validation.
2. Le responsable des commandes voit les demandes de ses sites et les totaux
   à commander par produit/unité. Il passe la commande auprès du fournisseur
   hors application, puis marque les demandes commandées. Le bouton de
   regroupement ne traite que les demandes affichées, pas celles arrivées
   après l’ouverture de la page.
3. À l’arrivée, il choisit **Produits reçus — notifier le responsable** pour
   chaque demande concernée. Une précision de réception permet par exemple de
   signaler un produit manquant. La demande devient **Produits disponibles**.
4. Le responsable courant du lieu reçoit une notification interne, visible sur
   les pages de l’application. Le bouton **J’ai lu** ferme son propre avis.
   Cette action n’atteste pas la récupération des produits.
5. Les personnes organisent la récupération hors application.

Les demandes transmises peuvent être marquées commandées ou annulées ; les
commandées peuvent être reçues ou annulées. Les états disponibles/annulées sont
terminaux. Chaque nouvelle saisie forme une nouvelle demande : les quantités
du mois précédent ne sont pas réutilisées automatiquement.

Ni calendrier, ni transport, ni stock, ni commande fournisseur automatique,
ni facture ou écriture comptable, ni email ne sont gérés par ce module.
La réception est déclarée pour la demande entière : les manquants sont signalés
en commentaire, sans suivi automatique de livraison partielle ou de reliquat.

## Droits et révocation

| Acteur | Fournitures | Entretien |
| --- | --- | --- |
| Salarié interne rattaché à un site | Dépôt sur ses sites, lecture de ses propres demandes | Aucun droit implicite |
| Responsable des besoins d’un lieu | Aucun droit implicite | Saisie et lecture des demandes de ce lieu actif |
| Responsable fournitures d’un site | Dépôt, lecture et traitement de la file de ce site actif | Aucun droit implicite |
| Responsable entretien d’un site | Aucun droit implicite | Lecture/traitement et configuration du catalogue et des lieux de ce site actif |
| Direction/comptabilité | Administration des sites et vue consolidée | Configuration et traitement ; peut saisir en remplacement d’un demandeur |
| Ancien délégataire global des fournitures | Traitement des seules demandes sans site | Aucun droit implicite |
| Prestataire paie | Refusé | Refusé |

Les contrôles sont effectués côté serveur sur le compte actif et les
attributions en base. Les écritures relisent le compte, la délégation, le site
et la ressource sous `BEGIN IMMEDIATE`. Les identifiants fournis par le
navigateur ne permettent pas de changer de périmètre. Retirer un responsable
révoque sa mission dès la requête suivante, sans reconnexion. Il peut conserver
ses autres droits indépendants (demandeur d’un lieu, membre d’un autre site).

Archiver un site ferme les nouvelles demandes et le traitement ; la
direction/comptabilité conserve l’historique, ainsi que chaque salarié pour ses
propres fournitures. Un responsable de site perd la file partagée. Archiver un
lieu ferme sa saisie et sa lecture par le demandeur ; les gestionnaires peuvent
encore clôturer ses demandes. Les produits peuvent être archivés sans
supprimer les lignes historiques.

Le titulaire courant d’un lieu reçoit l’avis de réception, même si une autre
personne avait saisi la demande. Un ancien titulaire ne conserve pas l’accès
par le seul fait d’avoir été demandeur. Un compte inactif ou un lieu archivé
ne reçoit pas d’avis. Les notifications sont internes et ne nécessitent pas
de configuration SMTP.

## Historique et migration 0079

La migration est additive et rejouable. Elle ajoute `site_id` nullable aux
fournitures et les tables des sites, accès et besoins d’entretien. Le schéma
est partagé entre `init_db()` et la migration. La résilience inclut toutes les
nouvelles tables ; aucun fichier métier supplémentaire n’est introduit.

Les fournitures existantes restent **Global / historique**, sans affectation
automatique d’après un secteur ou un salarié. L’ancienne délégation conserve
uniquement cette file. Elle ne donne aucun accès aux files des nouveaux sites.
Sans site configuré, le parcours de fournitures existant continue à fonctionner.
Archiver tous les sites ne rouvre pas les nouveaux dépôts globaux.

Les demandes d’entretien conservent le nom du lieu, les libellés produits et
leurs unités lors de la saisie. Une modification du catalogue ne réécrit pas
l’historique. La transmission possède une clé de rejeu ; une réception répétée
ne réémet pas une notification ni n’efface sa lecture. Statut et notification
sont enregistrés dans la même transaction. Des révisions protègent les
formulaires de configuration, de saisie et de traitement contre les pages
périmées, notamment lorsqu’un conditionnement change avant l’envoi d’un besoin.

Le retour arrière destructif est refusé : restaurer une sauvegarde cohérente
selon la procédure d’exploitation. Aucune migration sur une base réelle n’a
été exécutée pour préparer ce changement.

## Vérification locale

`pytest tests/test_sites_approvisionnement.py` couvre les périmètres positifs et
négatifs, la migration et les accès révoqués, le catalogue, les doubles envois,
le regroupement, les réceptions concurrentes et leur atomicité, CSRF et
l’échappement des textes. `tests/approvisionnement_live_checks.cjs` exerce les
écrans réels dans Chromium sur une base synthétique jetable, sur ordinateur et
mobile, avec sessions et CSRF actifs et sans service extérieur.
