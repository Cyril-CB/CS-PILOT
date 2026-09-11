"""Commandes d'exploitation explicites ; aucune action réseau ou service système."""
import argparse
import getpass
import json
import os
from pathlib import Path
import stat

from resilience import (ErreurResilience, _configuration, sauvegarder, restaurer,
                        diagnostiquer, verifier_parametres, ouvrir_lecture)


def lire_secret(fichier):
    p = Path(fichier)
    if p.is_symlink() or not p.is_file() or (os.name == 'posix' and stat.S_IMODE(p.stat().st_mode) & 0o077):
        raise ErreurResilience('Le fichier secret doit être privé (permissions 600), sans lien symbolique.')
    return p.read_text(encoding='utf-8').rstrip('\r\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Résilience CS PILOT — voir docs/resilience.md')
    commandes = parser.add_subparsers(dest='commande', required=True)
    for nom in ('sauvegarder', 'restaurer', 'diagnostic', 'migrer'):
        cmd = commandes.add_parser(nom)
        if nom != 'restaurer':
            cmd.add_argument('--data-dir', required=True, type=Path)
            cmd.add_argument('--cle-fichier', help='SECRET_KEY effective, si absente de la configuration')
        if nom in ('sauvegarder', 'migrer'):
            cmd.add_argument('--application-arretee', action='store_true')
        if nom in ('sauvegarder', 'restaurer'):
            cmd.add_argument('--archive', required=True, type=Path)
            cmd.add_argument('--phrase-fichier', help='Phrase de sauvegarde dans un fichier privé ; sinon saisie masquée')
        if nom == 'restaurer':
            cmd.add_argument('--destination', required=True, type=Path)
            cmd.add_argument('--nouvelle-cle-fichier', help='Rechiffrer les paramètres avec cette clé privée')
        if nom == 'migrer':
            cmd.add_argument('--version', help='Une version précise ; sinon toutes les migrations en attente')
            cmd.add_argument('--reprise-historique', action='store_true',
                             help='Après diagnostic isolé : autoriser la reprise d’un ancien échec potentiellement partiel')
    args = parser.parse_args(argv)
    try:
        if args.commande in ('sauvegarder', 'migrer') and not args.application_arretee:
            raise ErreurResilience('Arrêtez les processus écrivains puis indiquez --application-arretee.')
        if args.commande in ('sauvegarder', 'restaurer'):
            phrase = lire_secret(args.phrase_fichier) if args.phrase_fichier else getpass.getpass('Phrase de sauvegarde : ')
            if args.commande == 'sauvegarder' and not args.phrase_fichier:
                if getpass.getpass('Confirmez la phrase : ') != phrase:
                    raise ErreurResilience('Les phrases diffèrent.')
        if args.commande != 'restaurer':
            cle = lire_secret(args.cle_fichier) if args.cle_fichier else None
            config = _configuration(args.data_dir, cle)
            cle = config['SECRET_KEY']
        if args.commande == 'sauvegarder':
            resultat = sauvegarder(args.data_dir, args.archive, phrase, arret_confirme=True, secret_key=cle)
        elif args.commande == 'restaurer':
            nouvelle = lire_secret(args.nouvelle_cle_fichier) if args.nouvelle_cle_fichier else None
            resultat = restaurer(args.archive, args.destination, phrase, nouvelle_cle=nouvelle)
        elif args.commande == 'diagnostic':
            resultat = diagnostiquer(args.data_dir, cle)
        else:
            if args.reprise_historique and not args.version:
                raise ErreurResilience('Précisez la version dont la reprise historique a été vérifiée.')
            import database
            database.DATA_DIR = str(args.data_dir.resolve())
            database.DATABASE = str(args.data_dir.resolve() / 'cspilot.db')
            # Ne pas importer app : ni logs métier, ni routes, ni connexion à un
            # service. Le contexte minimal sert aux migrations de paramètres.
            from flask import Flask
            from contextlib import closing
            from migration_manager import appliquer_migration, appliquer_toutes_en_attente, get_statut_complet
            with closing(ouvrir_lecture(database.DATABASE)) as conn:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='app_settings'").fetchone():
                    verifier_parametres(conn, cle)
            app = Flask('migration_hors_ligne')
            app.secret_key = cle
            with app.app_context():
                if args.version:
                    resultats = [(args.version, *appliquer_migration(args.version, getpass.getuser(),
                                                                  reprise_historique=args.reprise_historique))]
                else:
                    resultats = appliquer_toutes_en_attente(getpass.getuser())
                resultat = {'ok': all(r[1] for r in resultats) and get_statut_complet()['a_jour'],
                            'resultats': resultats, 'statut': get_statut_complet()}
        print(json.dumps(resultat, ensure_ascii=False, indent=2))
        return 0 if resultat['ok'] else 2
    except ErreurResilience as erreur:
        print(json.dumps({'ok': False, 'erreur': str(erreur)}, ensure_ascii=False))
        return 2
    except Exception as erreur:
        print(json.dumps({'ok': False, 'erreur': 'Opération interrompue : vérifiez les fichiers, droits et le schéma.',
                          'type': type(erreur).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
