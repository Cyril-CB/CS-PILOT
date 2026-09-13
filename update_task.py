"""Garde de processus pour les commandes de mise à jour, sans dépendance tierce."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from update_protocol import verrou_exclusif


def main():
    arguments = sys.argv[1:]
    verrou = None
    if arguments[0] == '--donnees':
        verrou = verrou_exclusif(Path(os.environ['CSPILOT_UPDATE_DIR']) / 'worker.lock')
        arguments = arguments[1:]
    options = {'pass_fds': (verrou.fileno(),)} if verrou and os.name == 'posix' else {}
    commande = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, **options)

    def surveiller():
        # stdin est un pipe dont le superviseur est le seul écrivain. EOF couvre
        # aussi SIGKILL, sans dépendre d'un PID réutilisable ou d'un heartbeat.
        while os.read(sys.stdin.fileno(), 4096):
            pass
        if os.name == 'posix':
            os.killpg(os.getpgrp(), signal.SIGKILL)
        else:
            subprocess.run(['taskkill', '/PID', str(commande.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            os._exit(1)

    threading.Thread(target=surveiller, daemon=True).start()
    try:
        return commande.wait()
    finally:
        if verrou:
            verrou.close()


if __name__ == '__main__':
    raise SystemExit(main())
