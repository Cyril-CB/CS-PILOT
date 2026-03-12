# CS-PILOT

![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)
![Databse : SQL Lite](https://img.shields.io/badge/sqlite-%2307405e.svg)
![Langage : Python](https://img.shields.io/badge/python-3670A0.svg)

## Description

Application web de gestion RH, comptable et operationnelle, conçue pour les structures de type associatif ou collectivite. Elle couvre l'ensemble du cycle RH (planning, heures, paie), la comptabilite analytique, la tresorerie, la gestion des factures et des subventions, ainsi que des outils metier specifiques au secteur (ALSH, contrats, reservations de salles…).

## Fonctionnalites

### Gestion des temps
- Planning theorique par salarie (periodes scolaires / vacances)
- Saisie des heures reelles et heures supplementaires
- Calcul automatique du solde de recuperation
- Calendrier des jours feries et vacances scolaires
- Vue calendrier mensuelle

### Circuit de validation
- Demandes de recuperation avec workflow hierarchique (responsable puis direction)
- Validation mensuelle par responsable et directeur
- Historique complet des demandes et modifications
- Suivi des anomalies

### Multi-profils (5 profils)
- **Salarie** : saisie de ses heures, consultation de son solde, demandes de recup
- **Responsable** : validation equipe, vue "Mon equipe" hebdomadaire par secteur
- **Comptable** : acces aux exports et a la preparation de paie
- **Directeur** : administration complete, validation finale
- **Prestataire paie** : acces dedie a la preparation de paie

### Preparation de la paie
- Module de preparation de paie avec statut par salarie
- Variables de paie configurables
- Informations complementaires salaries
- Generation de contrats de travail a partir de modeles DOCX
- Export Excel (openpyxl)

### Gestion des absences
- Suivi des absences par type et par salarie

### Forfait jours
- Calendrier forfait jour
- Tableau de bord dedie

### Comptabilite & Finances
- Plan comptable general avec import TXT
- Plan comptable analytique avec affectation des comptes aux secteurs et actions
- Saisie et gestion des ecritures comptables avec circuit de validation (Brouillon → Validee → Exportee)
- Generation automatique d'ecritures via IA a partir des factures
- Export des ecritures comptables au format TXT
- Import et analyse des bilans comptables par secteur (compte de resultat detaille, export PDF)
- Regles comptables pour la generation automatique d'ecritures (par type de depense ou fournisseur)
- Trésorerie : import FEC, projection de solde multi-mois, gestion des comptes avec budget N ajustable

### Gestion budgetaire
- Budgets previsionnels par secteur avec repartition par postes de depense
- Suivi des depenses reelles vs. budget par secteur

### Gestion des factures et fournisseurs
- Gestion des factures avec import PDF et extraction IA des informations
- Circuit de validation des factures (responsable / direction)
- Annuaire des fournisseurs avec aliases IA et codes comptables
- Approbation des factures par les responsables

### Subventions et benevoles
- Gestion des dossiers de subventions en kanban (Nouveau → Envoye → Accepte / Refuse)
- Gestion des benevoles avec suivi des heures assignees

### Tableau de bord direction
- Vue d'ensemble effectifs, absences, validations et anomalies
- Demandes de recuperation en attente et top conges cumules

### Reservations de salles
- Gestion des reservations de salles avec recurrences
- Exclusion automatique des vacances et jours feries
- Calendrier visuel des reservations

### Notifications par email
- Envoi de notifications via Gmail (SMTP)
- Notifications automatiques sur les demandes de recuperation (creation, validation, refus)
- Relance manuelle des responsables pour les fiches d'heures non validees
- Configuration via l'interface d'administration (identifiants chiffres en base)

### Outils specifiques
- ALSH : pilotage des Accueils de Loisirs sans Hebergement (tableau de bord croisant donnees comptables et pedagogiques)
- Pesee ALISFA (avec integration IA Claude)
- Assistant RH (avec integration IA Claude)
- Planning enfance

### Administration
- Gestion des utilisateurs (creation, modification, secteurs, responsables hierarchiques)
- Gestion des secteurs
- Gestion des cles API
- Parametres personnels (email, preferences de notifications)
- Systeme de migration de base de donnees avec suivi des versions
- Sauvegarde et restauration de la base de donnees (avec rotation automatique)
- Page d'administration systeme

### Securite
- Authentification par login/mot de passe
- Migration automatique des anciens hash SHA256 vers werkzeug (bcrypt)
- Cle secrete chargee depuis variable d'environnement (generee automatiquement au premier demarrage)
- Protection contre le path traversal sur les sauvegardes
- Validation stricte des noms de fichiers

## Documentation

- **[Guide de démarrage rapide](docs/quick-start.md)** — installation, premier lancement, configuration initiale, création des salariés et de leur fiche RH.

## Installation

### Option 1 : Executable Windows (recommande)

Telechargez le dernier executable `.exe` depuis les releases GitHub. Aucune installation requise : Python, les dependances et les fichiers de l'application sont integres. La base de donnees et les documents sont stockes dans `%LOCALAPPDATA%\cspilot`.

Double-cliquer sur l'executable pour lancer l'application.

### Option 2 : Depuis les sources

#### Prerequis

- Python 3.8 ou superieur
- pip (gestionnaire de paquets Python)

#### Mise en place

1. Placer le dossier du projet ou vous le souhaitez (ex: `C:\Apps\CS-PILOT`)

2. Installer les dependances :
   ```
   pip install -r requirements.txt
   ```

#### Lancement

**Sous Windows** : double-cliquer sur `LANCER.bat`

**En ligne de commande** :
```
python app.py
```

> **Note** : le fichier `.env` (contenant la cle secrete Flask) est genere automatiquement au premier demarrage si absent. Aucune configuration manuelle n'est necessaire.

L'application est accessible sur `http://localhost:5000`.

### Acces depuis le reseau local

Sur le PC serveur, relever l'adresse IP (`ipconfig` sous Windows). Depuis les autres postes, acceder a `http://<adresse-ip>:5000`.

## Premiere connexion

Lors du premier acces a l'application (aucun compte existant), un assistant de configuration vous guidera pour creer le compte administrateur initial.

Ce compte sera automatiquement de profil **Directeur** (acces complet). Le mot de passe doit respecter les regles de securite : 8 caracteres minimum, au moins une majuscule, une minuscule et un chiffre (caractere special recommande).

## Structure du projet

```
CS-PILOT/
├── app.py                     # Point d'entree Flask
├── database.py                # Gestion de la base SQLite
├── backup_db.py               # Sauvegarde / restauration
├── migration_manager.py       # Systeme de migrations
├── utils.py                   # Utilitaires (decorateurs, chiffrement)
├── requirements.txt           # Dependances Python
├── LANCER.bat                 # Script de lancement Windows
│
├── blueprints/                # Modules fonctionnels Flask
│   ├── auth.py                # Authentification
│   ├── dashboard.py           # Tableau de bord salarie
│   ├── dashboard_direction.py # Tableau de bord direction
│   ├── saisie.py              # Saisie des heures
│   ├── planning.py            # Planning theorique
│   ├── validation.py          # Validation mensuelle
│   ├── recup.py               # Demandes de recuperation
│   ├── suivi.py               # Suivi et anomalies
│   ├── exports.py             # Exports Excel/PDF
│   ├── exportation.py         # Export ecritures comptables (TXT)
│   ├── admin.py               # Gestion des utilisateurs
│   ├── administration.py      # Administration systeme
│   ├── backup.py              # Sauvegardes
│   ├── absences.py            # Gestion des absences
│   ├── variables_paie.py      # Variables de paie
│   ├── infos_salaries.py      # Informations salaries
│   ├── prepa_paie.py          # Preparation de la paie
│   ├── generation_contrats.py # Generation de contrats (DOCX)
│   ├── forfait.py             # Forfait jours
│   ├── mon_equipe.py          # Vue equipe hebdomadaire
│   ├── planning_enfance.py    # Planning enfance
│   ├── alsh.py                # Pilotage ALSH
│   ├── pesee_alisfa.py        # Pesee ALISFA (IA)
│   ├── assistant_rh.py        # Assistant RH (IA)
│   ├── tresorerie.py          # Tresorerie (import FEC, projection)
│   ├── comptabilite_analytique.py # Plan comptable analytique
│   ├── plan_comptable_general.py  # Plan comptable general
│   ├── ecritures.py           # Ecritures comptables (IA + validation)
│   ├── regles_comptables.py   # Regles comptables pour l'IA
│   ├── bilan_secteurs.py      # Bilans comptables par secteur
│   ├── budget.py              # Budgets previsionnels par secteur
│   ├── factures.py            # Gestion des factures (import PDF, IA)
│   ├── fournisseurs.py        # Annuaire des fournisseurs
│   ├── subventions.py         # Gestion des subventions (kanban)
│   ├── benevoles.py           # Gestion des benevoles
│   ├── salles.py              # Reservations de salles
│   ├── parametres.py          # Parametres personnels
│   ├── api_keys.py            # Gestion des cles API
│   └── notifications.py       # Notifications email
│
├── migrations/                # Fichiers de migration SQL
├── templates/                 # Templates HTML (Jinja2)
├── static/                    # CSS, JS, images
└── tests/                     # Tests pytest
```

## Configuration

Le fichier `.env` est genere automatiquement au premier demarrage dans le meme dossier que la base de donnees. Vous pouvez l'editer manuellement si besoin.

| Variable | Description | Defaut |
|---|---|---|
| `SECRET_KEY` | Cle secrete Flask pour les sessions (generee automatiquement) | — |
| `BEHIND_PROXY` | Mettre `true` si l'application est derriere un proxy/tunnel (ngrok, Cloudflare…) | `false` |

## Configuration des notifications email (Gmail)

L'application peut envoyer des notifications par email via un compte Gmail. Aucune dependance supplementaire n'est requise (utilisation de la bibliotheque standard Python `smtplib`).

### Etape 1 : Preparer le compte Gmail

1. Connectez-vous au compte Google qui servira d'expediteur
2. Allez sur **myaccount.google.com** > **Securite**
3. Activez la **Verification en 2 etapes** si ce n'est pas deja fait
4. Retournez dans **Securite** > **Mots de passe des applications**
   - Si vous ne voyez pas cette option, cherchez "Mots de passe des applications" dans la barre de recherche du compte Google
5. Creez un nouveau mot de passe d'application :
   - Nom : `CS-PILOT`
   - Copiez le code a 16 caracteres genere (format `xxxx xxxx xxxx xxxx`)

> **Important** : le mot de passe habituel du compte Gmail ne fonctionnera pas. Il faut obligatoirement un mot de passe d'application.

### Etape 2 : Configurer dans CS-PILOT

1. Connectez-vous en tant que **directeur** ou **comptable**
2. Menu **Administration** > **Notifications email**
3. Remplissez les champs :
   - **Adresse email** : l'adresse Gmail (ex: `notifications@gmail.com`)
   - **Mot de passe d'application** : le code a 16 caracteres (sans espaces)
   - **Serveur SMTP** : `smtp.gmail.com` (pre-rempli)
   - **Port** : `587` (pre-rempli)
4. Cliquez sur **Enregistrer la configuration**
5. Cliquez sur **Envoyer un email de test** pour verifier

Les identifiants sont chiffres avant d'etre stockes en base de donnees (meme mecanisme que les cles API).

### Etape 3 : Renseigner les adresses email des utilisateurs

Pour que les notifications fonctionnent, chaque utilisateur concerne doit avoir une adresse email configuree :
- Menu **RH & Paie** > **Infos Salaries** > selectionner un salarie > modifier l'email

### Notifications disponibles

| Notification | Declencheur | Destinataire |
|---|---|---|
| Nouvelle demande de recup | Salarie cree une demande | Responsable du secteur |
| Demande validee par responsable | Responsable valide | Direction |
| Demande validee definitivement | Direction valide | Salarie |
| Demande refusee | Responsable ou direction refuse | Salarie |
| Relance validation fiches | Directeur clique sur "Relancer" | Responsable(s) concerne(s) |

Les 4 premieres notifications sont envoyees automatiquement lors de l'action correspondante. La relance est declenchee manuellement via un bouton sur la page "Vue ensemble validation".

## Depannage

### L'application ne demarre pas
- Verifier Python : `python --version`
- Reinstaller les dependances : `pip install -r requirements.txt --force-reinstall`

### Impossible de se connecter
- Verifier que l'application tourne (messages visibles dans la console)
- Utiliser `http://localhost:5000` (pas https)

### Erreur de base de donnees
- Utiliser la page Administration pour verifier l'etat des migrations
- Restaurer une sauvegarde depuis la page Sauvegardes

## Versionnement

Le numero de version suit le format `1.0.XXXX` ou `XXXX` correspond a la derniere migration de base de donnees appliquee. La version est calculee automatiquement et affichee sur la page Administration et dans le pied de page.

---

**Developpe avec** : Python, Flask, SQLite
