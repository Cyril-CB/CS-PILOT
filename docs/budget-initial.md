# Construire l’initial annuel détaillé — lot 1

Depuis **Budget prévisionnel**, la direction ou la comptabilité ouvre
**Construire l’initial annuel détaillé** et choisit l’année. Cette construction
porte uniquement sur l’initial, en fonctionnement normal. Elle ne reprend pas
automatiquement les budgets ni les simulations déjà enregistrés.

## Commencer par un secteur pilote

1. Enregistrer les hypothèses générales de l’année.
2. Ajouter une ligne par salarié ou poste identifié, y compris vacant. Le nom
   du poste est obligatoire ; la référence à un salarié existant est facultative.
   Une même référence salarié ne peut être utilisée deux fois dans l’année.
3. Renseigner la quotité, la base de rémunération, la source et la justification.
   Ventiler entre les secteurs à **100 % au total**. Un poste vacant conserve son
   identifiant lorsqu’il est complété ou renommé.
4. Ajouter les dépenses, charges et financements, avec leur méthode et leur
   répartition mensuelle. Renseigner explicitement les zéros vérifiés.
5. Examiner **Contrôle et informations manquantes**, puis les calculs expliqués
   et les douze mois du secteur. Lever les marques « à revoir » après contrôle.
6. Comparer les propositions aux montants enregistrés avant le report.

Les détails nominatifs et la ventilation intersectorielle sont réservés à la
direction et à la comptabilité. Les droits des responsables sur le tableau
budgétaire existant restent inchangés.

## Rémunérations

Une seule base est active à la fois ; les autres paramètres restent mémorisés.

- **Brut mensuel vérifié** : montant de base à la quotité indiquée, hors
  compléments listés séparément. Cocher la confirmation après vérification.
  Ce montant n’est pas multiplié une deuxième fois par la quotité.
- **ALISFA** : `((socle annuel + pesée × point) × quotité / 100
  + (ancienneté + compétences) × point) / 12 + maintien mensuel`.
  Les paramètres sont ceux de la construction ; aucune fiche RH n’est modifiée.
- **CEE** : forfait journalier × nombre de jours prévu pour chaque mois,
  conformément à l’activité normale.

Un permanent est prévu sur douze mois. Pour un saisonnier, saisir les fractions
mensuelles d’activité normale de 0 à 1, justifiées dans la note. Ne pas déduire
d’absence imprévisible et ne pas ajouter de remplacement hypothétique.

Le brut de base utilise le **premier compte 641** du secteur. Si les secteurs
partagés utilisent des premiers 641 différents, harmoniser explicitement les
comptes du budget avant de reporter cette construction ; aucune harmonisation
n’est faite automatiquement.

Les compléments ont un nom unique dans la ligne et douze montants sur un autre
641. Une prime incluse dans le brut vérifié ne doit pas être ajoutée à nouveau.
La somme de tous les 641 constitue le brut global, compléments compris.

## Dépenses, financements et charges

Trois méthodes restent disponibles :

| Méthode | Calcul |
|---|---|
| Montant annuel manuel | Montant conservé et ventilé selon douze poids. 1 partout signifie douze parts égales. |
| Projection mensuelle | Somme des douze montants saisis. Aucun réalisé repris. |
| Proportionnel au brut | Brut global mensuel du secteur × numérateur annuel / assiette annuelle de référence. |

Une ligne proportionnelle appartient à un seul secteur à 100 %, afin de ne pas
ventiler deux fois une assiette déjà sectorisée. La référence **2025** est
proposée dans le formulaire, sans présumer qu’elle est complète. Renseigner
source, année, assiette, périmètre et date de vérification, puis confirmer
explicitement l’exercice complet et le périmètre comparable. Le numérateur et
l’assiette annuelle sont conservés ; l’assiette ne peut être nulle pour le ratio.
Il n’existe pas de liaison automatique avec un import comptable dans ce lot.

L’option **Utiliser les taux de charges individuels** applique le taux de chaque
personne à son brut global, compléments compris, puis regroupe les charges sur
le premier 645 de chaque secteur. Prévoir un compte 645 dans la construction
ou dans le tableau existant. Les autres 645–648 de la construction passent à
zéro ; leurs données saisies restent mémorisées. Décocher l’option les rétablit.
Les comptes 63 et hors périmètre gardent leur méthode. Chaque taux doit avoir
sa provenance, y compris un taux nul explicitement vérifié.

## Inconnus, arrondis et contrôles

Vide signifie **inconnu**, jamais zéro. Une donnée requise manquante rend le
montant et les totaux concernés « À compléter » et bloque le report. Source,
justification et marque « à revoir » participent au contrôle de complétude.

Les calculs sont faits sur le serveur avec `Decimal`, arrondi monétaire au
centime (`ROUND_HALF_UP`). Une ventilation répartit les centimes par plus grands
restes ; les ex æquo sont départagés par clé stable. Les douze mois totalisent
exactement l’année et les secteurs totalisent exactement le général, y compris
pour les montants négatifs. Les poids mensuels sont normalisés par leur somme.

Exemple synthétique du secteur pilote : base 2 000 €/mois + complément
100 €/mois = **25 200 € de brut global**. Référence annuelle 48 000 / 120 000
= 40 %, soit **10 080 € de charges**. Autres dépenses manuelles : 1 200 €.
Charges générales : **36 480 €**. Financements : 40 000 €, résultat : **3 520 €**.
Cet exemple est vérifié par les tests autonomes, pas sur les données du centre.

## Rapprochement et report

Le tableau de rapprochement montre le montant initial enregistré, la
construction et la décision par secteur et compte. **Reporter les comptes
autorisés** est une action explicite :

- Un compte sans montant saisi peut recevoir le montant calculé.
- Un compte précédemment reporté par cette construction peut être actualisé
  seulement si ses montants temporaire et définitif sont restés inchangés.
- Une saisie manuelle préexistante, y compris zéro, reste intacte. Un report
  modifié ensuite à la main reste également intact. Les comptes automatiques
  existants et les comptes pilotés par une simulation avec taux sont conservés.
- Les commentaires et simulations ne sont jamais remplacés par cette action.
- Un compte piloté par une simulation de paie ou de prestation de service
  reste protégé, même si son montant est identique au précédent report.
  La protection porte sur le compte, le secteur et l’exercice de l’initial ;
  une simulation de l’actualisé ou d’un autre périmètre ne bloque pas le report.
- La disparition d’une ligne déjà reportée propose explicitement zéro pour
  son ancien compte, si d’autres lignes subsistent et si ce compte est resté
  inchangé. Supprimer toute la construction n’efface jamais l’ancien budget.

Les comptes conservés peuvent donc différer de la construction : ce n’est pas
un report complet. Leur décision est visible avant et après l’action. Contrôler
ces écarts dans le tableau habituel. Le PDF existant utilise ses montants
enregistrés, et non les hypothèses non reportées.

Les révisions servent uniquement à refuser une page périmée. Elles ne sont pas
un gel/versionnement métier. Aucun recalcul n’écrit spontanément dans un budget.

L’ancien actualisé conserve sa colonne comparative **Initial** : après un report
explicite, cette colonne et celle du PDF reflètent les nouveaux montants initiaux,
comme après une saisie dans le tableau habituel. Les montants actualisés,
leurs méthodes, commentaires et simulations ne sont pas modifiés.

Il est possible de commencer par une ligne : les hypothèses générales restent
alors vides, avec les taux individuels désactivés. Les paramètres transversaux
tels que l’inflation sont documentés dans la note d’hypothèses ; ce lot ne propose
pas de coefficient d’inflation appliqué automatiquement aux lignes.

## Migration et périmètre

La migration **0077** crée seulement `budget_initial_hypotheses`,
`budget_initial_lignes` et `budget_initial_reports`, ainsi qu’un index. Elle
est idempotente et partage son schéma avec une installation neuve. Aucune
conversion, copie de données existantes ou réécriture de budget n’est effectuée.
Les nouvelles tables sont déclarées au contrôle de résilience ; les sauvegardes
SQLite les incluent. Un retour arrière demande une sauvegarde cohérente : le
downgrade refuse leur suppression silencieuse.

La suppression d’un secteur ayant reçu un report est refusée, même sans salarié
rattaché, pour conserver l’historique budgétaire et éviter une référence
orpheline dans le diagnostic de sauvegarde. Ce contrôle est réalisé dans la
même transaction que la suppression, sous verrou d’écriture.

UUID et colonnes de liaison nullables préparent les liens futurs ; les routes
ne permettent pas de les activer. Gel versionné, suivi en direct, subventions,
factures, contrats et IJ automatisés restent hors lot 1. Aucun nouvel outil ni
aucune dépendance n’est ajouté.

## Validation technique

Contrôles autonomes, sans Flask :

```bash
python -m unittest tests.test_budget_initial_moteur -v
python scripts/validate_feature_catalogue.py
python -m compileall -q app.py budget_initial.py schema_budget_initial.py blueprints migrations tests
node --check static/js/budget_initial.js
git diff --check
```

Si Playwright et Chromium sont déjà disponibles, le contrôle UI isolé utilise
le template, le JavaScript et les styles livrés, avec des réponses API
synthétiques (aucun serveur Flask ni service externe) :

```bash
node tests/budget_initial_frontend_checks.cjs
```

Il contrôle les largeurs 1440 et 390 pixels, les états vide/erreur, la conservation
des saisies, les modes et le jeton CSRF transmis. Il produit des captures dans
un répertoire temporaire. `CHROMIUM_PATH` désigne un navigateur déjà installé.
Ce contrôle ne remplace pas l’intégration ni le rendu complet dans le shell Flask.

Avec les dépendances déclarées installées, exécuter les tests d’intégration et
de non-régression avant fusion :

```bash
python -m pytest tests/test_budget_initial_routes.py tests/test_budget_initial_moteur.py tests/test_budget.py tests/test_budget_regles.py tests/test_budget_taux_charges.py tests/test_migrations_resilience.py tests/test_resilience.py
python -m pytest
```

Contrôler ensuite le parcours réel sur ordinateur et mobile, avec une base
synthétique : états vide/incomplet/complet, erreur, création/modification d’un
poste vacant, réouverture, report refusé/périmé, comparaison des PDF et
préservation d’un actualisé 2026. Les résultats réellement obtenus et les
contrôles bloqués sont consignés dans la PR.

Un harnais reproductible réalise ce parcours avec Flask et SQLite réels :

```bash
PYTHON=/chemin/vers/venv/bin/python node tests/budget_initial_live_checks.cjs
```

Il crée son propre dossier temporaire et un serveur sur loopback, puis se
connecte avec un compte synthétique. CSRF et les protections de session restent
actifs ; les requêtes externes du navigateur sont bloquées. Il vérifie les états
vide/incomplet/complet, une ventilation refusée sans perte de saisie, le poste
vacant renommé avec UUID conservé, la reprise, le report, le PDF, l’actualisé
2026, les interfaces flux/classique et l’expiration de session. Les captures
desktop/mobile restent dans un dossier temporaire indiqué en sortie.

Les tests Flask vérifient aussi la migration sur un schéma antérieur synthétique
peuplé (y compris simulations, formules, zéro manuel et commentaire), son
idempotence, le contenu textuel des PDF avant/après, le recalcul et l’édition
de l’actualisé. Un PDF n’est pas comparé octet pour octet : les métadonnées de
génération peuvent varier. Un rejet CSRF invalide la session et redirige vers
la connexion selon le contrat global existant ; l’écran conserve la saisie et
explique désormais cette situation.
