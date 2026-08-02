# Interface sans menu

Ce document décrit l'accueil « en flux » qui remplace le menu latéral pour une
partie des profils, et explique comment l'ajuster.

## À qui elle s'applique

| Profil | Interface |
| --- | --- |
| Direction | sans menu |
| Comptabilité | sans menu |
| Responsable | sans menu |
| Salarié **porteur d'une délégation** | sans menu |
| Salarié sans délégation | menu latéral habituel |
| Prestataire paie | menu latéral habituel (page unique) |

Les délégations qui font basculer un salarié sont celles qui lui confient des
pages à suivre : suivi des validations et relances, suivi et commande des
fournitures, gestion des bénévoles. La délégation des **récurrences de
réservation de salle** ne compte pas : elle n'ouvre aucune page supplémentaire.

La règle est dans `navigation.est_eligible()`.

Un salarié délégué reste cadré sur ce qui le concerne : il ne valide aucune
demande, donc son fil n'en contient aucune, et l'horizon ne lui montre ni les
contrats ni les absences de l'effectif. Il ne voit que les étapes de
subventions qui lui sont assignées et ses propres tâches planifiées. Le cadrage
est appliqué à la source, dans `dashboard_actions.construire_actions()` et
`flux_accueil.construire_horizon()`, et vaut donc pour tout appelant.

## Les trois écrans

### L'accueil (`/accueil`)

- **Le fil** : uniquement ce qui attend une décision — demandes de congé et de
  récupération à valider, factures à approuver, étapes de subventions échues,
  relances de fiches, alertes de surcharge. Chaque carte porte ses boutons
  d'action : valider, refuser, approuver, marquer comme fait, relancer. La
  carte disparaît une fois traitée et l'anneau de progression avance.
- **« À l'horizon »** : ce qui arrive sans rien demander aujourd'hui, en deux
  lignes à défilement horizontal — *RH* (fins de contrat, retours d'absence
  longue) et *Échéances* (étapes de subventions, tâches du planificateur).

Le fil et l'horizon ne se recouvrent que là où c'est nécessaire. Les **étapes
de subventions** figurent dans le fil quelle que soit leur date : l'horizon ne
les reprend qu'au-delà de `flux_accueil.JOURS_IMMEDIAT` (7 jours), pour ne pas
les afficher deux fois. Les **fins de contrat, retours d'absence et tâches
planifiées** n'apparaissent que dans l'horizon : il démarre donc à aujourd'hui
pour elles, sans quoi elles disparaîtraient au moment précis où elles
deviennent urgentes. L'horizon s'arrête à `JOURS_HORIZON` (120 jours).

Pour la direction et la comptabilité, le fil reprend la file étendue du centre
de contrôle qu'il remplace : factures assignées à la direction, relance des
fiches non validées, surcharges, soldes de congés élevés.

Ce sont les **seuils d'alerte** qui décident de ce qui remonte. Comme ils
façonnent le fil, ils se règlent là où le fil s'affiche : bouton ⚙ à droite de
l'en-tête de l'accueil, réservé à la direction et à la comptabilité. La fenêtre
est le gabarit partagé `_seuils_modal.html`, également inclus par le centre de
contrôle historique — les deux pages règlent donc exactement les mêmes valeurs,
et il n'y a qu'un seul endroit à modifier pour en ajouter une.

### Le nom et la fonction, en haut à droite

Le nom vient de la session ; la **fonction** est celle renseignée sur la fiche
du salarié, dans la section Contrats de « Infos salariés ». Elle se choisit
dans une liste (table `fonctions`, pré-remplie à l'installation) complétable
via « + Ajouter une fonction… » : la fonction créée est affectée au salarié et
proposée ensuite pour tous.

Tant qu'aucune fonction n'est renseignée, l'affichage retombe sur le profil,
précisé par le secteur (« direction · Famille »).

### Mon espace (`/mon-espace`)

Ouvert par le nom, en haut à droite. Compteurs de congés payés, de congés
conventionnels et de récupérations ; dépôt d'une demande (le formulaire poste
sur les routes existantes `/demande_conge` et `/demande_recup`, donc le circuit
de validation et les notifications sont inchangés) ; liste des demandes en
cours. C'est aussi de là qu'on revient au menu classique.

### La vue d'ensemble (touche Échap)

L'application représentée par zones :

- le **cercle intérieur** porte les zones thématiques ; s'attarder sur l'une
  d'elles déplie ses pages en couronne ;
- le **cercle extérieur** porte les accès directs (salles, planificateur,
  administration) ;
- le centre porte les initiales de l'utilisateur.

Échap, ou un clic dans le vide, referme.

## Le clavier

| Touche | Effet |
| --- | --- |
| n'importe quelle lettre | ouvre la barre intelligente et s'y inscrit |
| `Ctrl` / `⌘` + `K` | ouvre la barre vide |
| `↑` `↓` | parcourt les propositions |
| `↵` | ouvre la proposition sélectionnée |
| `Échap` | ferme la barre, sinon ouvre la vue d'ensemble |

La barre propose d'abord les zones et les pages (c'est ce qui remplace le
menu), puis une entrée « Rechercher … » qui envoie la requête au moteur
existant (`POST /api/search`) et en traite le verdict comme auparavant.

## Les autres pages

Elles perdent leur menu et reçoivent, au-dessus de leur contenu habituel :

1. un lien **« Revenir au flux »** ;
2. les **boutons des pages voisines** de leur zone (le sous-menu d'avant) ;
3. un **flux d'information** quand la page s'y prête.

Leur titre, leurs boutons d'action (importer, relancer…) et leur contenu ne
changent pas. Une page qui est déjà un tableau complet — la trésorerie, par
exemple — n'a pas de flux d'information : elle reste telle quelle.

## Ajouter ou déplacer une page

Tout se joue dans `navigation.py` :

- `ZONES` décrit le cercle intérieur, `ACCES_DIRECTS` le cercle extérieur ;
- chaque page est déclarée par `_page(endpoint, label, profils=…)` ;
- `condition=` nomme un drapeau du contexte utilisateur. Avec `profils` vide,
  la condition **suffit** (délégation, appartenance au CSE) ; avec `profils`
  renseignés, elle **restreint** (option d'administration) ;
- `labels=` permet de nommer une même page différemment selon le profil.

Les droits reproduisent ceux du menu latéral historique : ce fichier réorganise
la présentation, il n'ouvre aucun accès. Les routes gardent leur propre
contrôle. Un test (`test_tous_les_endpoints_de_la_carte_existent`) vérifie que
chaque entrée pointe vers une route réelle.

Pour ajouter un flux d'information à une page, écrire un constructeur dans
`flux_infos.py` et l'inscrire dans `CONSTRUCTEURS` sous son endpoint.

## Revenir en arrière

- **Pour tout le centre** : Administration → Options → décocher « Activer
  l'interface sans menu ». `/accueil` et `/mon-espace` redirigent alors vers le
  tableau de bord, et le bouton « Essayer la nouvelle interface » disparaît du
  menu latéral.
- **Pour une personne** : « Mon espace » → « Revenir au menu classique ». Le
  choix est enregistré dans `app_settings` sous la clé
  `interface_sans_menu_user_<id>` et reste réversible.

Les tableaux de bord historiques (`/dashboard_direction`,
`/dashboard_responsable`, `/dashboard_comptable`) restent accessibles par leur
URL dans les deux cas. Ils ne figurent pas dans la carte : l'accueil les
remplace. Rien n'y est pour autant inaccessible — les seuils d'alerte, seul
réglage qui n'existait que là, sont désormais sur l'accueil.

## Tests

`tests/test_interface_flux.py` couvre l'éligibilité, le filtrage de la carte
par profil et par délégation, le rendu des trois écrans, le flux d'information
et la bascule. Les tests qui décrivent le menu latéral historique demandent la
fixture `menu_classique`.
