"""Enregistrement commun aux imports de factures, dans la transaction appelante."""
from datetime import date
import re
import unicodedata

from assistant_pdf import copier_piece
from database import DATA_DIR
from pathlib import Path


def _nom(texte):
    texte = unicodedata.normalize('NFKD', str(texte or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'-+', '-', re.sub(r'[^a-zA-Z0-9_-]', '-', texte)).strip('-')[:100]


def enregistrer_import(conn, source, nom_original, info, user_id, fichiers_crees,
                       secteur_id=None, direction=False):
    """Crée fournisseur si nécessaire, facture, historique et copie PDF ; sans commit."""
    nom = info.get('fournisseur')
    fournisseur_id = None
    if nom:
        row = conn.execute('''SELECT id FROM fournisseurs WHERE LOWER(nom)=LOWER(?)
            OR LOWER(alias1)=LOWER(?) OR LOWER(alias2)=LOWER(?)''', (nom,) * 3).fetchone()
        fournisseur_id = row['id'] if row else conn.execute(
            'INSERT INTO fournisseurs(nom) VALUES (?)', (nom,)).lastrowid
    date_facture = info.get('date_facture') or date.today().isoformat()
    # Les champs extraits ne peuvent pas devenir un chemin de fichier.
    nom_pdf = f"{_nom(date_facture)}_FACTURE_{_nom(nom) or 'Inconnu'}_{_nom(info.get('numero_facture')) or 'SANS-NUM'}.pdf"
    fichier = copier_piece(source, Path(DATA_DIR) / 'factures', nom_pdf, fichiers_crees)
    fid = conn.execute('''INSERT INTO factures
        (fournisseur_id,numero_facture,date_facture,date_echeance,montant_ttc,description,
         fichier_path,fichier_nom,fichier_original,created_by,secteur_id,assigned_direction)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (fournisseur_id, info.get('numero_facture'), date_facture, info.get('date_echeance'),
         info.get('montant_ttc'), info.get('description'), str(fichier), fichier.name,
         nom_original, user_id, secteur_id, int(direction))).lastrowid
    conn.execute('''INSERT INTO facture_historique(facture_id,action,details,user_id)
        VALUES (?,'Création','Facture importée',?)''', (fid, user_id))
    if secteur_id or direction:
        conn.execute('''INSERT INTO facture_historique(facture_id,action,details,user_id)
            VALUES (?,'Assignation',?,?)''',
            (fid, 'Assignée à la direction' if direction else f'Secteur {secteur_id}', user_id))
    return fid
