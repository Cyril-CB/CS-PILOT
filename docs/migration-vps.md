# Migration de CS-PILOT d'un VPS à un autre

Ce guide décrit la procédure complète pour déplacer une installation CS-PILOT
d'un serveur (VPS source — ex. le serveur de test actuel) vers un nouveau
serveur (VPS cible — ex. celui du centre), **avec toutes les données** : base
de données et documents uploadés.

L'application est mono-instance : un fichier SQLite (`cspilot.db`) + un dossier
`documents/`. La migration consiste donc à transférer ces deux éléments puis à
remonter le service. Deux scripts automatisent l'export/import des données ;
la reconstruction du service systemd et du reverse proxy Nginx est décrite
ci-dessous (à faire à la main sur le nouveau serveur).

> **Note sur le `SECRET_KEY`** : cette procédure **génère une nouvelle clé** sur
> le serveur cible. Le `.env` de la source n'est volontairement pas copié. Les
> sessions actives de l'ancien serveur seront donc invalidées : les utilisateurs
> devront simplement se reconnecter. C'est sans impact sur les données.

---

## Vue d'ensemble

| Étape | Où | Commande / Action |
|------|-----|-------------------|
| 1 | Cible | Préparer le VPS (Python, git, dépendances) |
| 2 | Source | Exporter les données → archive `.tar.gz` |
| 3 | — | Transférer l'archive (scp/rsync) + vérifier le SHA-256 |
| 4 | Cible | Importer les données |
| 5 | Cible | Reconstruire le service systemd |
| 6 | Cible | Reconstruire Nginx + HTTPS |
| 7 | Cible | Vérifier la migration |
| 8 | — | Basculer le DNS, puis rollback possible |

---

## 1. Préparer le VPS cible

Pré-requis à installer :

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git sqlite3 rsync
```

Récupérer le code et préparer l'environnement :

```bash
cd /opt                       # ou le répertoire de déploiement de votre choix
sudo git clone https://github.com/cyril-cb/cs-pilot.git
sudo chown -R "$USER" cs-pilot
cd cs-pilot
./lancer.sh                   # crée venv/ + installe les dépendances + génère un .env
```

Au premier lancement, `lancer.sh` crée le `venv`, installe les dépendances et
**génère automatiquement un `.env` avec un nouveau `SECRET_KEY`**. Une fois que
l'application affiche qu'elle écoute sur le port 5000, arrêtez-la avec `Ctrl+C` :
les données seront importées à l'étape 4.

---

## 2. Exporter les données depuis le VPS source

Sur le serveur **actuel**, depuis le dossier du projet :

```bash
cd /chemin/vers/cs-pilot
./scripts/migration/export-data.sh
```

Le script :
- effectue une **copie cohérente** de la base (API backup SQLite — indispensable
  car la base tourne en mode WAL, un simple `cp` n'est pas fiable) ;
- copie l'intégralité du dossier `documents/` ;
- produit `cspilot-migration-AAAAMMJJ-HHMMSS.tar.gz` et affiche sa taille et son
  empreinte **SHA-256**.

Option pour un instantané parfaitement figé (courte interruption de service) :

```bash
./scripts/migration/export-data.sh --stop-service
```

Cette option arrête le service `cspilot` le temps de la copie puis le relance.

---

## 3. Transférer l'archive

Depuis le VPS source (ou votre poste) :

```bash
scp cspilot-migration-*.tar.gz user@NOUVEAU_VPS:~/
```

Vérifier que l'empreinte est identique des deux côtés :

```bash
# Sur la source
sha256sum cspilot-migration-*.tar.gz
# Sur la cible
sha256sum ~/cspilot-migration-*.tar.gz
```

Les deux empreintes doivent correspondre avant de continuer.

---

## 4. Importer les données sur le VPS cible

```bash
cd /opt/cs-pilot
./scripts/migration/import-data.sh ~/cspilot-migration-AAAAMMJJ-HHMMSS.tar.gz
```

Le script :
- **sauvegarde** toute base/documents déjà présents (dans `backups/`, horodaté) ;
- restaure `cspilot.db` et `documents/` ;
- conserve le `.env` (et son nouveau `SECRET_KEY`) déjà généré à l'étape 1 ;
- **rejoue les migrations de schéma en attente** si le code de la cible est plus
  récent que celui de la source, puis affiche la version du schéma.

---

## 5. Reconstruire le service systemd

Le code attend un service nommé **`cspilot`** (utilisé notamment par la mise à
jour automatique : `blueprints/mise_a_jour.py` lance `systemctl restart cspilot`).
Créez `/etc/systemd/system/cspilot.service` :

```ini
[Unit]
Description=CS-PILOT (gestion du temps de travail)
After=network.target

[Service]
Type=simple
User=cspilot
WorkingDirectory=/opt/cs-pilot
ExecStart=/opt/cs-pilot/venv/bin/python /opt/cs-pilot/app.py
Restart=always
RestartSec=3
# Le port et les autres réglages sont lus depuis .env (chargé par app.py).
EnvironmentFile=-/opt/cs-pilot/.env

[Install]
WantedBy=multi-user.target
```

> Adaptez `User=` et `WorkingDirectory=` à votre déploiement. Créez au besoin un
> utilisateur dédié : `sudo useradd -r -s /usr/sbin/nologin cspilot` puis
> `sudo chown -R cspilot /opt/cs-pilot`.

Activer et démarrer :

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cspilot
sudo systemctl status cspilot
```

---

## 6. Reconstruire Nginx + HTTPS

L'application écoute en local sur `127.0.0.1:5000` (Waitress). Placez Nginx en
reverse proxy. `/etc/nginx/sites-available/cspilot` :

```nginx
server {
    listen 80;
    server_name cspilot.votre-domaine.fr;

    client_max_body_size 50M;   # marge pour l'upload de documents

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/cspilot /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Comme l'application tourne derrière un reverse proxy, activez le mode proxy
dans `.env` (cf. `app.py`, gestion de `BEHIND_PROXY` / `ProxyFix` et des cookies
sécurisés) :

```bash
echo "BEHIND_PROXY=true" >> /opt/cs-pilot/.env
sudo systemctl restart cspilot
```

Certificat TLS via Let's Encrypt :

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d cspilot.votre-domaine.fr
```

---

## 7. Vérifier la migration

- **Connexion** : ouvrez l'application et connectez-vous (les comptes existants
  fonctionnent ; seules les sessions sont à refaire à cause du nouveau `SECRET_KEY`).
- **Documents** : ouvrez quelques justificatifs / factures / pièces de subvention
  pour confirmer que les fichiers sont bien présents.
- **Schéma** : dans le panneau **Administration**, vérifiez qu'aucune migration
  n'est en attente et que la version du schéma correspond à la source.
- **Comptage** (optionnel) — comparer la source et la cible :

  ```bash
  sqlite3 cspilot.db "SELECT name FROM sqlite_master WHERE type='table';"
  sqlite3 cspilot.db "SELECT COUNT(*) FROM utilisateurs;"
  ```

---

## 8. Bascule DNS et rollback

1. Une fois la cible validée, faites pointer le nom de domaine vers l'IP du
   nouveau VPS (ou mettez à jour le tunnel/reverse proxy en amont).
2. **Conservez l'archive de migration et l'ancien VPS** quelques jours : en cas
   de problème, il suffit de re-basculer le DNS vers l'ancien serveur.
3. Quand tout est confirmé, vous pouvez décommissionner l'ancien VPS.

---

## Hors périmètre

- **Secrets / SMTP** : les éventuels réglages de notification e-mail sont à
  reconfigurer manuellement sur la cible.
- **Zéro interruption / haute dispo** : non couvert (architecture mono-instance
  SQLite — une courte coupure pendant la bascule est normale).
