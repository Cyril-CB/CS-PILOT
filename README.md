# CS-PILOT

![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)
![Databse : SQL Lite](https://img.shields.io/badge/sqlite-%2307405e.svg)
![Langage : Python](https://img.shields.io/badge/python-3670A0.svg)

## Description

Application web de gestion du temps de travail des salaries, conçue pour les structures de type associatif ou collectivite. Elle couvre l'ensemble du cycle : planning theorique, saisie des heures, demandes de recuperation, validation hierarchique, preparation de la paie et exports.

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
- Export Excel (openpyxl)

### Gestion des absences
- Suivi des absences par type et par salarie

### Forfait jours
- Calendrier forfait jour
- Tableau de bord dedie

### Notifications par email
- Envoi de notifications via Gmail (SMTP)
- Notifications automatiques sur les demandes de recuperation (creation, validation, refus)
- Relance manuelle des responsables pour les fiches d'heures non validees
- Configuration via l'interface d'administration (identifiants chiffres en base)

### Outils specifiques
- Pesee ALISFA (avec integration IA Claude)
- Assistant RH (avec integration IA Claude)
- Planning enfance

### Administration
- Gestion des utilisateurs (creation, modification, secteurs, responsables hierarchiques)
- Gestion des secteurs
- Gestion des cles API
- Systeme de migration de base de donnees avec suivi des versions
- Sauvegarde et restauration de la base de donnees (avec rotation automatique)
- Page d'administration systeme

### Securite
- Authentification par login/mot de passe
- Migration automatique des anciens hash SHA256 vers werkzeug (bcrypt)
- Cle secrete chargee depuis variable d'environnement
- Protection contre le path traversal sur les sauvegardes
- Validation stricte des noms de fichiers

## Installation

### Prerequis

- Python 3.8 ou superieur
- pip (gestionnaire de paquets Python)

### Mise en place

1. Placer le dossier du projet ou vous le souhaitez (ex: `C:\Apps\Centre-en-Commun`)

2. Installer les dependances :
   ```
   pip install -r requirements.txt
   ```

3. Creer un fichier `.env` a la racine du projet :
   ```
   SECRET_KEY=votre_cle_secrete_generee
   FLASK_DEBUG=0
   ```
   Pour generer une cle secrete :
   ```
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

### Lancement

**Sous Windows** : double-cliquer sur `LANCER.bat`

**En ligne de commande** :
```
python app.py
```

L'application est accessible sur `http://localhost:5000`.

### Acces depuis le reseau local

Sur le PC serveur, relever l'adresse IP (`ipconfig` sous Windows). Depuis les autres postes, acceder a `http://<adresse-ip>:5000`.

## Premiere connexion

Lors du premier acces a l'application (aucun compte existant), un assistant de configuration vous guidera pour creer le compte administrateur initial.

Ce compte sera automatiquement de profil **Directeur** (acces complet). Le mot de passe doit respecter les regles de securite : 8 caracteres minimum, au moins une majuscule, une minuscule et un chiffre (caractere special recommande).

## Structure du projet

```
Centre-en-Commun/
├── app.py                     # Point d'entree Flask
├── database.py                # Gestion de la base SQLite
├── backup_db.py               # Sauvegarde / restauration
├── migration_manager.py       # Systeme de migrations
├── utils.py                   # Utilitaires (decorateurs, chiffrement)
├── requirements.txt           # Dependances Python
├── LANCER.bat                 # Script de lancement Windows
├── .env                       # Variables d'environnement (non versionne)
│
├── blueprints/                # Modules fonctionnels Flask
│   ├── auth.py                # Authentification
│   ├── dashboard.py           # Tableau de bord
│   ├── saisie.py              # Saisie des heures
│   ├── planning.py            # Planning theorique
│   ├── validation.py          # Validation mensuelle
│   ├── recup.py               # Demandes de recuperation
│   ├── suivi.py               # Suivi et anomalies
│   ├── exports.py             # Exports Excel/PDF
│   ├── admin.py               # Gestion des utilisateurs
│   ├── administration.py      # Administration systeme
│   ├── backup.py              # Sauvegardes
│   ├── absences.py            # Gestion des absences
│   ├── variables_paie.py      # Variables de paie
│   ├── infos_salaries.py      # Informations salaries
│   ├── prepa_paie.py          # Preparation de la paie
│   ├── forfait.py             # Forfait jours
│   ├── mon_equipe.py          # Vue equipe hebdomadaire
│   ├── planning_enfance.py    # Planning enfance
│   ├── pesee_alisfa.py        # Pesee ALISFA (IA)
│   ├── assistant_rh.py        # Assistant RH (IA)
│   ├── api_keys.py            # Gestion des cles API
│   └── notifications.py       # Notifications email
│
├── migrations/                # Fichiers de migration SQL
├── templates/                 # Templates HTML (Jinja2)
├── static/                    # CSS, images
└── tests/                     # Tests pytest
```

## Configuration

| Variable | Description | Defaut |
|---|---|---|
| `SECRET_KEY` | Cle secrete Flask pour les sessions | cle de developpement |
| `FLASK_DEBUG` | Mode debug (`1` = actif, `0` = inactif) | `0` |

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

Le numero de version suit le format `2.XXXX` ou `XXXX` correspond a la derniere migration de base de donnees appliquee. La version est calculee automatiquement et affichee sur la page Administration et dans le pied de page.

---

**Developpe avec** : Python, Flask, SQLite
