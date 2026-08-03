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

**Sur téléphone, tout le monde garde le menu latéral.** L'interface sans menu
suppose un écran large : une barre fixe en haut, une autre en bas, une vue
d'ensemble en anneau. Le menu historique, lui, est déjà responsive avec son
bouton hamburger. La détection se fait sur l'agent utilisateur
(`interface_flux.est_telephone()`), la largeur d'écran n'étant pas connue du
serveur : le marqueur normalisé `Mobi` couvre Chrome Android comme Safari iOS.
Une tablette n'en porte pas — un iPad récent annonce même un Safari de bureau —
et garde donc l'interface sans menu. Le même compte suit ainsi son appareil,
sans rien avoir à régler.

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

### La règle du fil : on nomme, on ne compte pas

**Le fil ne porte aucune donnée informative fixe.** Chaque carte attend une
décision, signale un risque réel ou annonce une échéance — sinon elle n'est
pas construite. C'est ce qui le sépare d'un tableau de bord d'indicateurs : un
compteur qui affiche la même chose tous les jours n'apprend rien et use
l'attention de son lecteur.

D'où la forme de toutes les familles de `dashboard_actions.py` :

- **au plus deux cartes nommées** (`MAX_CARTES_NOMMEES`), puis une ligne
  discrète « et N autres ». « 30 fiches à valider » décourage et n'indique pas
  par où commencer ; « Fiche à valider — Marie Dupont, juillet » se traite.
  Traiter la première fait remonter la suivante ;
- **un tri qui dit par où commencer.** Les fiches sont classées par solde
  d'heures décroissant : plus le solde est élevé, plus il pèse sur le compteur
  de récupération, et plus la validation tarde à venir ;
- **rien quand il n'y a rien.** Aucune famille ne produit de carte à zéro.

Une carte **dit ce qu'elle attend, elle ne juge pas**. La fiche de Marie
Dupont attend une validation : c'est tout ce que la carte annonce. Le solde y
figure comme un fait, jamais comme un verdict — le fil n'est pas un détecteur
d'anomalies, et une fiche chargée n'en est pas une. (Rappel métier utile ici :
les heures supplémentaires se **récupèrent**, elles ne se paient pas, sauf
pour un CDD.)

Chaque constructeur décide seul de son public et s'isole des autres : une
famille en panne (table absente, base verrouillée) est journalisée et ignorée,
le reste du fil tient.

Deux exceptions assumées à la règle du nommage. Les **tâches du planificateur**
restent agrégées (« 3 tâches prévues aujourd'hui ») : le planificateur est
déjà l'écran qui détaille et réordonne, le fil ne fait qu'y conduire. Le
**rappel de préparation de paie** est daté plutôt que déclenché par un état :
il paraît le 20 (`JOUR_RAPPEL_PAIE`) parce que le geste attendu — prévenir la
comptabilité des mises à pied et licenciements — se fait hors de
l'application, qui ne peut rien en constater. Son bouton « C'est fait » est
donc déclaratif, et n'éteint le rappel que pour celui qui l'a signalé :
chacun ne répond que de son périmètre.

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

L'ouverture est animée : le voile apparaît en 0,42 s et les zones se posent en
cascade depuis le haut, décalées de 45 ms chacune. La classe
`flx-ensemble-anime` porte cette entrée et est retirée une fois posée, pour que
déplier une zone reste instantané. Le réglage système « animations réduites »
est respecté.

## Le clavier

| Touche | Effet |
| --- | --- |
| n'importe quelle lettre | ouvre la barre intelligente et s'y inscrit |
| `Ctrl` / `⌘` + `K` | ouvre la barre vide |
| `↑` `↓` | parcourt les propositions |
| `↵` | ouvre la proposition sélectionnée |
| `Échap` | ferme la barre, sinon ouvre la vue d'ensemble |

La barre fusionne deux sources dans une seule liste classée :

1. **La navigation locale** — zones et pages, filtrées par les droits du
   lecteur. C'est ce qui remplace le menu, et cela vaut pour **tous** les
   profils de l'interface sans menu. Personne ne se retrouve donc sans menu
   *et* sans barre.
2. **La recherche métier** — elle route directement vers un enregistrement :
   une facture par son numéro, une fiche fournisseur, un budget, la fiche temps
   d'un salarié… Il n'y a plus de ligne intermédiaire « Rechercher… ».

Une page exacte passe avant une zone générale. Une zone n'ouvre jamais sa
première page arbitrairement : elle déplie sa constellation. Le dernier choix
est toujours **« Voir tout l'espace »**, même si aucun résultat précis n'a été
trouvé. Accents, singulier/pluriel, formulations conversationnelles et fautes
proches sont normalisés par `search_palette.py`.

Quand la requête **nomme** une page — son libellé exact, une de ses
`expressions`, ou son début — cette page passe devant l'interprétation du
moteur. « congés à valider » désigne la page de validation, là où le moteur n'y
voit que le mot-clé « congé » et proposerait les absences. Le résultat du moteur
reste offert, une ligne plus bas. Un enregistrement précis, lui, n'est jamais
concurrencé : aucune page ne porte le nom d'une facture ou d'un salarié.

## La richesse du dictionnaire, mesurée

Le vocabulaire est la première cause de déception d'une barre de recherche : une
requête qui ne trouve rien se lit comme une panne. `tests/test_search_dictionnaire.py`
en fait donc une propriété mesurée, pas une impression. Il fait passer un corpus
de **142 formulations telles qu'un utilisateur les tape** — mot unique, pluriel,
phrase parlée, jargon du secteur, abréviation, faute de frappe — et vérifie où
atterrit chacune. La comparaison porte sur le chemin d'arrivée : la page
« Compte de résultat & bilan » de la carte et le résultat « Compte de résultat
2026 » du moteur ouvrent le même écran et comptent tous deux comme une réussite.

État actuel : **98 % des requêtes mènent en première proposition, 100 % dans les
trois premières, aucune ne reste sans réponse.** Le test verrouille des seuils
un peu plus bas (92 % et 98 %) pour qu'une page nouvelle ne fasse pas tomber la
suite avant d'avoir reçu son vocabulaire.

Pour enrichir le dictionnaire, la boucle est toujours la même :

1. relever dans le journal de recherche (Sécurité → Barre intelligente) les
   termes restés **sans résultat** — c'est exactement ce pour quoi il existe ;
2. les ajouter au corpus du test, avec la page qu'ils devraient atteindre ;
3. compléter `mots=` ou `expressions=` de cette page dans `navigation.py`
   jusqu'à ce que le test repasse.

Les mots qui ne portent que la formulation (« qui », « est », « pas », « au »…)
n'ont pas à être déclarés page par page : ils sont écartés une fois pour toutes
dans `search_palette._MOTS_CONVERSATION`.

La recherche métier est ouverte à la **direction, à la comptabilité et aux
responsables**. Pour ces derniers, le moteur limite les salariés à leur équipe,
les secteurs à leur secteur, les factures à ce secteur et les subventions à
leurs attributions. Une seconde barrière supprime toute destination absente de
leur carte. Les salariés délégués conservent uniquement la navigation locale.

`POST /api/search/suggestions` calcule la liste unifiée sans journaliser chaque
frappe. Le journal de recherche (Sécurité → Barre intelligente) est alimenté aux
deux extrémités de l'usage, et une seule fois par recherche :

- le résultat métier **effectivement choisi** repasse par `POST /api/search`,
  comme avant ;
- la recherche **restée vaine** est signalée à la fermeture de la barre, par un
  dernier appel aux suggestions portant `journal: true`. Le serveur revérifie
  que la palette ne proposait rien d'autre que « Voir tout l'espace » : ce
  chemin ne peut enregistrer que des échecs.

Ce sont justement les requêtes sans réponse qui font vivre le dictionnaire du
moteur ; les perdre reviendrait à ne plus voir que ce qui marche déjà. Une
saisie de moins de trois caractères n'est pas tracée : la barre s'ouvrant à la
première touche frappée, un appui accidentel suivi d'Échap n'apprend rien.

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
- `mots=` ajoute le vocabulaire propre à la page ; `expressions=` déclare les
  formulations qui doivent la désigner sans ambiguïté. Les mots de la zone
  servent à proposer son exploration, pas toutes ses pages.

Les droits reproduisent ceux du menu latéral historique : ce fichier réorganise
la présentation, il n'ouvre aucun accès. Les routes gardent leur propre
contrôle. Un test (`test_tous_les_endpoints_de_la_carte_existent`) vérifie que
chaque entrée pointe vers une route réelle.

Pour ajouter un flux d'information à une page, écrire un constructeur dans
`flux_infos.py` et l'inscrire dans `CONSTRUCTEURS` sous son endpoint.

### Les pages de réponse ne sont pas dans la carte

Certaines pages n'existent que pour répondre à une intention formulée dans la
barre intelligente : « contrats de mai » ouvre la liste des contrats du mois,
« salariés sans contrat » ouvre celle des dossiers incomplets. Elles ne
figurent **ni au menu latéral ni dans la carte** — les y mettre chargerait la
navigation d'écrans que personne ne parcourt.

Le risque est alors qu'on ignore leur existence. La réponse n'est pas de les
ajouter au menu, mais de les faire s'annoncer : un bandeau de `flux_infos.py`
sur la page où l'on peut agir, qui ne paraît que lorsqu'il y a lieu. Les
salariés sans aucun contrat s'affichent ainsi en tête d'Infos Salariés — et
disparaissent dès que les dossiers sont complets.

## La place gagnée revient au contenu

Sans menu latéral, les 260 px qu'il occupait doivent revenir au contenu, pas à
des marges. Deux largeurs coexistent donc :

- les **pages ordinaires** (tableaux, listes) montent à 1500 px, au-delà du
  plafond classique de 1400 px qui incluait la sidebar. Sur un portable de
  1440 px, la largeur utile passe de 1180 à 1440 px ;
- les **deux pages de lecture** — le fil et Mon espace — gardent les 880 px du
  modèle, où une ligne trop longue nuirait à la lecture. Elles se reconnaissent
  à la classe `flx-lecture` posée sur `<body>` par `base.html`.

Un test vérifie que la classe n'est posée que sur ces deux pages.

## La règle qui gouverne cartes et bandeaux

**Ne jamais proposer ce que le lecteur ne peut ni ouvrir ni conclure, et ne
jamais compter plus que la destination n'affiche.** Concrètement :

- une carte du fil ou de l'horizon n'est construite que pour les profils que sa
  page de destination accepte — pas de carte de subvention pour un salarié
  délégué, pas de retour d'absence pour un responsable (la page Absences lui
  est fermée) ;
- un bandeau reprend le filtre de la page qu'il annonce — le compteur de
  factures à approuver applique le même prédicat que la page d'approbation
  (secteur renseigné ou assignation à la direction), les factures encore non
  assignées étant signalées à part, vers la page Factures ;
- un bandeau reprend aussi son cadrage — un responsable ne compte que les
  fiches de son équipe, comme la vue d'ensemble le fait pour lui ;
- un bandeau ne recompte pas le tableau qu'il précède. La page Subventions ne
  signale que les étapes échues : annoncer « 100 étapes encore ouvertes » au
  dessus des mêmes cent lignes n'apprenait rien et repoussait la liste vers le
  bas. Un total sans retard, sans échéance ni décision à prendre n'est pas une
  information.

Ces règles sont vérifiées par des tests dédiés dans
`tests/test_interface_flux.py` : un écart entre un compteur et sa destination
fait tomber la suite.

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
