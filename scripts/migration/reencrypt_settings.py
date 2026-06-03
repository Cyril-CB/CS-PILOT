#!/usr/bin/env python3
"""
Re-chiffrement des parametres de app_settings lors d'une migration VPS.

Les valeurs de la table `app_settings` (SMTP, cles API, tarifs ALSH, salaire
socle, options d'affichage...) sont chiffrees avec une cle Fernet derivee du
SECRET_KEY (cf. utils._get_fernet : Fernet(base64(sha256(SECRET_KEY)))).

Quand on regenere le SECRET_KEY sur le serveur cible, ces valeurs deviennent
indechiffrables. Ce script dechiffre chaque valeur avec l'ANCIENNE cle puis la
re-chiffre avec la NOUVELLE, de sorte que tous les parametres restent
utilisables sans reconfiguration manuelle.

Usage :
    python reencrypt_settings.py <ancienne_cle> <nouvelle_cle> <chemin_cspilot.db>
"""
import base64
import hashlib
import sqlite3
import sys

from cryptography.fernet import Fernet


def fernet_for(secret_key: str) -> Fernet:
    """Reproduit utils._get_fernet sans dependre du contexte Flask."""
    digest = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2

    old_key, new_key, db_path = sys.argv[1], sys.argv[2], sys.argv[3]

    if not old_key:
        print("[ignore] Ancienne cle absente : aucun re-chiffrement possible.")
        return 0
    if old_key == new_key:
        print("[ok] Ancienne et nouvelle cle identiques : rien a re-chiffrer.")
        return 0

    f_old = fernet_for(old_key)
    f_new = fernet_for(new_key)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    except sqlite3.OperationalError:
        # Table absente : rien a faire (base sans parametres).
        print("[ok] Table app_settings absente : rien a re-chiffrer.")
        conn.close()
        return 0

    migres, deja_ok, ignores = 0, 0, 0
    for row in rows:
        cle, valeur = row["key"], row["value"]
        try:
            clair = f_old.decrypt(valeur.encode())
        except Exception:
            # Pas dechiffrable avec l'ancienne cle : peut-etre deja chiffre avec
            # la nouvelle (re-execution), ou valeur non standard -> on laisse tel quel.
            try:
                f_new.decrypt(valeur.encode())
                deja_ok += 1
            except Exception:
                print(f"  [ignore] '{cle}' indechiffrable, laisse tel quel.")
                ignores += 1
            continue
        conn.execute(
            "UPDATE app_settings SET value = ? WHERE key = ?",
            (f_new.encrypt(clair).decode(), cle),
        )
        migres += 1

    conn.commit()
    conn.close()
    print(f"[ok] Parametres re-chiffres : {migres} | deja a jour : {deja_ok} | ignores : {ignores}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
