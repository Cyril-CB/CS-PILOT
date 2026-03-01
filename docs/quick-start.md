# Guide de démarrage rapide — CS-PILOT

Ce guide vous accompagne pas à pas depuis l'installation jusqu'à la première utilisation opérationnelle de CS-PILOT.

---

## Table des matières

1. [Prérequis](#1-prérequis)
2. [Installation sur le serveur](#2-installation-sur-le-serveur)
3. [Créer le fichier `.env`](#3-créer-le-fichier-env)
4. [Lancer l'application](#4-lancer-lapplication)
5. [Créer le compte directeur](#5-créer-le-compte-directeur)
6. [Premiers paramètres](#6-premiers-paramètres)
7. [Créer un salarié](#7-créer-un-salarié)
8. [Fiche salarié](#8-fiche-salarié)

---

## 1. Prérequis

| Élément | Version minimale |
|---|---|
| Python | 3.8 |
| pip | inclus avec Python 3.8+ |
| Système | Windows 10/11, Ubuntu 20.04+, Debian 11+ |

> **Réseau local** : les autres postes accèdent à l'application via `http://<IP-du-serveur>:5000`. Le PC qui héberge l'application doit rester allumé pendant les heures d'utilisation.

---

## 2. Installation sur le serveur

### 2.1 Installer Python

**Sous Windows**

1. Rendez-vous sur [https://www.python.org/downloads/](https://www.python.org/downloads/) et téléchargez la dernière version 3.x.
2. Lancez l'installateur. **Cochez impérativement « Add Python to PATH »** avant de cliquer sur *Install Now*.
3. Vérifiez l'installation dans une invite de commande :
   ```
   python --version
   ```

**Sous Linux (Debian / Ubuntu)**

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

Vérification :
```bash
python3 --version
```

---

### 2.2 Télécharger et préparer l'application

1. Copiez le dossier du projet sur le serveur (par exemple `C:\Apps\CS-PILOT` sous Windows ou `/opt/cs-pilot` sous Linux).
2. Ouvrez un terminal dans ce dossier.

**Créer un environnement virtuel (recommandé)**

```bash
# Linux / macOS
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

**Installer les dépendances**

```bash
pip install -r requirements.txt
```

> Si vous obtenez des erreurs de droits sous Linux, ajoutez `--user` ou utilisez `sudo` uniquement si nécessaire.

---

## 3. Créer le fichier `.env`

À la racine du projet, créez un fichier nommé **`.env`** (sans extension). Ce fichier contient les variables de configuration sensibles et ne doit **jamais** être partagé ni versionné.

**Contenu minimal :**

```
SECRET_KEY=votre_cle_secrete_generee
```

**Générer une clé secrète :**

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copiez la valeur affichée et remplacez `votre_cle_secrete_generee`.

**Option proxy / HTTPS** — si l'application est accessible derrière un reverse proxy (Nginx, Cloudflare Tunnel, ngrok…), ajoutez :

```
BEHIND_PROXY=true
```

> En développement local, `BEHIND_PROXY` n'est pas nécessaire.

---

## 4. Lancer l'application

### Sous Windows

Double-cliquez sur **`LANCER.bat`** à la racine du projet.

La fenêtre de console affiche les messages de démarrage. L'application est accessible sur :
```
http://localhost:5000
```

### Sous Linux

```bash
chmod +x lancer.sh
./lancer.sh
```

### En ligne de commande (toutes plateformes)

```bash
# Avec l'environnement virtuel activé
python app.py        # Linux/macOS
python app.py        # Windows
```

### Accès depuis d'autres postes du réseau

1. Relevez l'adresse IP du serveur :
   - Windows : `ipconfig` (cherchez *Adresse IPv4*)
   - Linux : `ip a` ou `hostname -I`
2. Depuis les autres postes, ouvrez un navigateur et accédez à :
   ```
   http://<adresse-ip-du-serveur>:5000
   ```

> **Pour arrêter l'application** : appuyez sur `Ctrl+C` dans la fenêtre de console.

---

## 5. Créer le compte directeur

Lors du **premier accès** (aucun compte existant), l'application vous redirige automatiquement vers la page de configuration initiale.

1. Ouvrez `http://localhost:5000` dans un navigateur.
2. Remplissez le formulaire :
   - **Nom** et **Prénom**
   - **Identifiant de connexion** (login, en minuscules sans espace recommandé)
   - **Mot de passe** : respectez les règles de sécurité — *8 caractères minimum, au moins une majuscule, une minuscule et un chiffre* (caractère spécial recommandé)
   - **Confirmer le mot de passe**
3. Cliquez sur **Créer le compte administrateur**.

Le compte est automatiquement créé avec le profil **Directeur** (accès complet à toutes les fonctionnalités).

4. Connectez-vous avec les identifiants que vous venez de créer.

> Ce formulaire n'est accessible qu'une seule fois. Une fois le premier compte créé, il n'est plus affiché.

---

## 6. Premiers paramètres

Une fois connecté en tant que directeur, configurez les paramètres de base avant de créer les salariés.

### 6.1 Créer les secteurs

Les secteurs organisent les salariés en équipes ou services.

1. Menu **Administration RH** > **Gestion des secteurs** (`/gestion_secteurs`)
2. Cliquez sur **Ajouter un secteur**
3. Renseignez :
   - **Nom** du secteur (ex : *Petite Enfance*, *Accueil de Loisirs*, *Direction*)
   - **Description** (optionnel)
   - **Type de secteur** (optionnel)
4. Cliquez sur **Ajouter**

Répétez l'opération pour chaque secteur de votre structure.

> Les secteurs doivent être créés **avant** les salariés, car chaque salarié est rattaché à un secteur.

---

### 6.2 Saisir les dates de vacances scolaires

Ces périodes influencent le planning théorique des salariés.

1. Menu **Administration RH** > **Vacances scolaires** (`/gestion_vacances`)
2. Pour chaque période de vacances :
   - **Nom** (ex : *Vacances de Toussaint 2025*, *Vacances d'été 2026*)
   - **Date de début** et **Date de fin**
3. Cliquez sur **Ajouter la période**

> Pensez à saisir les vacances sur au moins l'année scolaire en cours et la suivante.

---

### 6.3 Saisir les jours fériés

1. Menu **Administration RH** > **Jours fériés** (`/gestion_jours_feries`)
2. Pour chaque jour férié :
   - **Date**
   - **Libellé** (ex : *14 juillet*, *Toussaint*)
3. Cliquez sur **Ajouter**

**Jours fériés légaux français (exemple pour 2025) :**

| Date | Libellé |
|---|---|
| 01/01/2025 | Jour de l'An |
| 21/04/2025 | Lundi de Pâques |
| 01/05/2025 | Fête du Travail |
| 08/05/2025 | Victoire 1945 |
| 29/05/2025 | Ascension |
| 09/06/2025 | Lundi de Pentecôte |
| 14/07/2025 | Fête Nationale |
| 15/08/2025 | Assomption |
| 01/11/2025 | Toussaint |
| 11/11/2025 | Armistice |
| 25/12/2025 | Noël |

---

### 6.4 Configurer les clés API (Intelligence artificielle)

Les clés API sont nécessaires pour utiliser la **Pesée ALISFA** et l'**Assistant RH** (fonctionnalités IA).

1. Menu **Administration** > **Clés API** (`/gestion_cles_api`)
2. Choisissez votre fournisseur d'IA :
   - **OpenAI** (clé commençant par `sk-`) — [platform.openai.com](https://platform.openai.com)
   - **Anthropic / Claude** (clé commençant par `sk-ant-`) — [console.anthropic.com](https://console.anthropic.com)
   - **Groq** (clé commençant par `gsk_`) — [console.groq.com](https://console.groq.com) *(accès gratuit disponible)*
3. Collez votre clé API dans le champ correspondant.
4. Sélectionnez le **modèle** à utiliser.
5. Cliquez sur **Enregistrer**.

> Les clés API sont chiffrées avant d'être stockées en base de données. Elles ne sont **jamais** visibles en clair après enregistrement.

---

### 6.5 Configurer les notifications email (optionnel)

L'application peut envoyer des emails automatiques (validation de récupération, relances...) via un compte Gmail.

1. Créez un **mot de passe d'application** Google :
   - Connectez-vous sur [myaccount.google.com](https://myaccount.google.com) > **Sécurité**
   - Activez la **Vérification en 2 étapes** si ce n'est pas fait
   - Recherchez **Mots de passe des applications**, créez-en un nommé `CS-PILOT`
   - Notez le code à 16 caractères généré
2. Dans CS-PILOT, menu **Administration** > **Notifications email** (`/configuration_email`)
3. Remplissez :
   - **Adresse email** : votre adresse Gmail
   - **Mot de passe d'application** : le code à 16 caractères (sans espaces)
   - **Serveur SMTP** : `smtp.gmail.com` *(pré-rempli)*
   - **Port** : `587` *(pré-rempli)*
4. Cliquez sur **Enregistrer**, puis **Envoyer un email de test** pour vérifier.

---

## 7. Créer un salarié

1. Menu **Administration RH** > **Gestion des utilisateurs** (`/gestion_users`)
2. Cliquez sur **Créer un utilisateur**
3. Remplissez la fiche :

| Champ | Description |
|---|---|
| **Nom** | Nom de famille |
| **Prénom** | Prénom |
| **Identifiant** | Login de connexion (unique, sans espace) |
| **Mot de passe** | Respecter les règles : 8 car. min., majuscule, minuscule, chiffre |
| **Profil** | `salarie`, `responsable`, `comptable`, `directeur` ou `prestataire paie` |
| **Secteur** | Secteur d'appartenance (créé à l'étape 6.1) |
| **Responsable** | Responsable hiérarchique (pour le circuit de validation) |
| **Date d'entrée** | Date d'embauche |
| **Solde initial** | Solde de récupération en heures à la création du compte |
| **Congés payés** | CP acquis, à prendre, déjà pris |
| **Congés conventionnels** | Solde initial des congés conventionnels |

4. Cliquez sur **Créer l'utilisateur**.

> **Profils disponibles :**
> - `salarie` : saisit ses heures, consulte son solde, fait des demandes de récup
> - `responsable` : valide les heures de son équipe, accès à la vue « Mon équipe »
> - `comptable` : accès aux exports, préparation de paie, administration RH
> - `directeur` : administration complète, validation finale
> - `prestataire paie` : accès dédié à la préparation de paie uniquement

---

## 8. Fiche salarié

La fiche salarié centralise les informations administratives, les contrats et les documents RH.

**Accès** : Menu **RH & Paie** > **Infos Salariés** (`/infos_salaries`)

### 8.1 Mettre à jour l'adresse email

L'adresse email est indispensable pour recevoir les notifications.

1. Sélectionnez le salarié dans la liste déroulante.
2. Dans la section **Email**, saisissez l'adresse.
3. Cliquez sur **Mettre à jour l'email**.

---

### 8.2 Ajouter un contrat

1. Dans la fiche du salarié, section **Contrats**, cliquez sur **Ajouter un contrat**.
2. Renseignez :
   - **Type de contrat** : `CDI`, `CDD`, `CEE` ou `Autre`
   - **Date de début**
   - **Date de fin** *(obligatoire pour CDD et CEE)*
   - **Poste / intitulé**
   - **Temps de travail** (ex : *35h*, *28h*, *80%*)
   - **Document** (PDF ou image, optionnel) — le fichier contrat scanné
3. Cliquez sur **Enregistrer le contrat**.

Les contrats sont listés par ordre chronologique décroissant.

---

### 8.3 Déposer des documents RH

Les documents suivants peuvent être associés à chaque salarié :

| Type | Format accepté |
|---|---|
| Fiche de renseignement | PDF |
| Carte d'identité (recto) | PDF, JPG, PNG |
| Carte d'identité (verso) | PDF, JPG, PNG |
| Carte vitale | PDF, JPG, PNG |
| Diplôme | PDF |
| Autre document 1 | PDF |
| Autre document 2 | PDF |

Pour chaque type de document :
1. Cliquez sur **Choisir un fichier** en face du type souhaité.
2. Sélectionnez le fichier sur votre ordinateur.
3. Cliquez sur **Téléverser**.

Les fichiers sont renommés automatiquement selon le format `TYPE-DOCUMENT_Nom_Prenom.ext` et stockés dans le dossier `documents/` du projet.

> Un document déjà déposé peut être **téléchargé** (icône 📥) ou **supprimé** (icône 🗑️).

---

## Résumé de la séquence de démarrage

```
1. Installer Python ──────────────────────────────────── python --version
2. Copier le projet et installer les dépendances ─────── pip install -r requirements.txt
3. Créer le fichier .env avec SECRET_KEY
4. Lancer l'application ──────────────────────────────── ./lancer.sh  ou  LANCER.bat
5. Ouvrir http://localhost:5000
6. Créer le compte directeur (formulaire affiché automatiquement)
7. Se connecter
8. Créer les secteurs ────────────────────────────────── /gestion_secteurs
9. Saisir les vacances scolaires ─────────────────────── /gestion_vacances
10. Saisir les jours fériés ──────────────────────────── /gestion_jours_feries
11. Configurer les clés API (si usage de l'IA) ────────── /gestion_cles_api
12. Configurer les notifications email (optionnel) ────── /configuration_email
13. Créer les salariés ───────────────────────────────── /creer_user
14. Compléter les fiches salariés ────────────────────── /infos_salaries
```

---

## Dépannage rapide

| Problème | Solution |
|---|---|
| `python` non reconnu | Vérifier que Python est dans le PATH ; relancer le terminal |
| `pip install` échoue | Essayer `pip install --upgrade pip` puis réessayer |
| Page blanche ou erreur 500 | Vérifier la console ; s'assurer que le fichier `.env` existe avec `SECRET_KEY` |
| Impossible de se connecter depuis un autre poste | Vérifier que le pare-feu autorise le port 5000 ; utiliser `http://` (pas `https://`) |
| Mot de passe oublié | Un directeur peut réinitialiser le mot de passe via **Gestion des utilisateurs** |
| Erreur de base de données | Aller sur `/administration` pour vérifier et appliquer les migrations manquantes |

---

*Pour aller plus loin, consultez le [README](../README.md) et le fichier [SECURITY.md](../SECURITY.md).*
