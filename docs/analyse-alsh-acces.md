# Accès à l’analyse ALSH

## Responsable du secteur Enfance

Un compte actif de profil **responsable**, rattaché au secteur nommé
**Enfance**, dispose de :

- **Financier → Analyse ALSH** dans le menu classique et dans la carte ;
- la barre intelligente, avec `analyse alsh`, `alsh` ou `saisie NOÉ` ;
- la consultation des tableaux, indicateurs, graphiques et tarifs calculés ;
- l’onglet **Saisie NOÉ**, avec enregistrement des heures de présence et du
  nombre d’enfants par année, période et tranche d’âge.

Le nom du secteur est comparé exactement après retrait des espaces de bord et
normalisation de la casse. `ENFANCE` convient ; `Petite Enfance`, `Enfance
jeunesse` ou un autre secteur de type `accueil_loisirs` ne conviennent pas.
Un rattachement hiérarchique à un salarié de ce secteur n’accorde pas ce droit.
Le secteur se configure par les gestionnaires dans **Gestion des secteurs**,
et le rattachement du responsable dans sa fiche utilisateur.

## Configuration et analytique

Le responsable ne peut pas modifier les affectations analytiques, tranches
d’âge, périodes ou répartition globale des quotients. L’onglet
**Configuration** est absent ; les API associées refusent aussi les appels
directs. Les pourcentages utilisés pour le tarif optimal sont consultables
mais désactivés. La configuration et les droits existants de la direction et
de la comptabilité restent inchangés.

L’analyse reste celle de l’ensemble des ALSH configurés : aucune subdivision
par secteur n’existe dans les tables de ce module. Le détail des charges du
responsable est toutefois limité aux codes configurés pour les périodes et
tranches actives de l’année demandée. Modifier un paramètre d’URL ne donne
pas accès aux charges d’un autre code ou à la liste générale des codes FEC.

Les autres responsables, salariés et prestataires n’accèdent ni à la page ni
aux API ALSH. Aucun droit sur les imports, bilans généraux ou autres fonctions
comptables n’est ajouté par ce changement.

## Sessions et données

`alsh_acces.droits_alsh` lit le compte actif et son secteur en base, sans cache
de droits ni confiance dans un profil/secteur fourni par le navigateur. Un
changement de profil, de secteur, du nom du secteur ou d’activation prend effet
à la requête suivante. Une saisie NOÉ recontrôle la session et le droit dans
la transaction d’écriture, afin de refuser un droit retiré entre les deux
contrôles. CSRF reste actif.

Les heures doivent être finies et non négatives, le nombre d’enfants non
négatif ; seules des périodes/tranches actives existantes peuvent recevoir
une saisie. Une saisie NOÉ ne modifie pas les affectations analytiques.

Aucun changement de schéma, migration, dépendance ou traitement des données
existantes n’est nécessaire.

## Vérifications reproductibles

Sur données temporaires et avec les dépendances déjà disponibles :

```sh
pytest tests/test_alsh_acces.py tests/test_alsh.py tests/test_acces_routes_sensibles.py tests/test_search_palette.py tests/test_search_engine.py tests/test_interface_flux.py tests/test_perimetres_sessions.py -q
python scripts/validate_feature_catalogue.py
git diff --check
```

Parcours Chromium, avec `@playwright/test` existant accessible à Node :

```sh
python tests/alsh_acces_browser_server.py
node tests/alsh_acces_browser_checks.cjs
```

Le serveur crée une base éphémère et des comptes fictifs sur `127.0.0.1:5057`.
CSRF demeure activé ; aucun mail ou service métier réel n’est utilisé. Les
preuves vont dans `/tmp/cspilot-alsh-acces-browser-results`, ou le dossier
`CSPILOT_BROWSER_OUTPUT`. Les tests distinguent ordinateur, viewport étroit
et téléphone (User-Agent compris), lecture, détail des charges, saisie NOÉ
relue après rechargement et refus des modifications analytiques.

Les graphiques et cartes passent sur une seule colonne sur petit écran ; les
tableaux conservent leur défilement horizontal interne. La touche Échap ferme
le détail des charges sans ouvrir simultanément la vue d’ensemble du flux.
Relancer le serveur éphémère entre deux campagnes pour repartir de données
neuves et ne pas cumuler les connexions soumises à la limite de sécurité.
