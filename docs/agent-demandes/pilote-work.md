# Pilote de développement dans Work

## Contrats versionnés

- Entrée du formulaire : `proposition-v1.schema.json`.
- Grille et seuils : `grille-v1.json`.
- Calibration initiale : `calibration-v1.json` (15 cas synthétiques).
- Compte rendu privé : `decision-v1.schema.json`.
- Consignes d'une exécution : `prompt-work.md`.
- Évolution du périmètre par mail : `evolutions-v1.json` (8 scénarios de calibration).
- Critères de fin et preuves par jalon : `definition-termine-v1.json`.
- Moteur déterministe : `scripts/triage_agent.py`. Il contrôle une évaluation
  déjà faite ; il ne comprend pas le mail et ne prouve pas les justifications.

```bash
python scripts/triage_agent.py --calibration docs/agent-demandes/calibration-v1.json
python scripts/triage_agent.py --evaluation /chemin/prive/evaluation.json
pytest tests/test_triage_agent.py
python scripts/validate_feature_catalogue.py
```

Les poids privilégient la valeur et le réemploi. La fréquence pèse moins pour
ne pas éliminer les besoins annuels de financement. Le seuil initial de 70
n'est pas une estimation de rentabilité. Documenter les notes plausibles mais
non confirmées ; un score proche du seuil mérite une relecture lors de la
calibration. Une information facultative vide n'impose pas une clarification.

## Paramétrage

Le pilote utilise les connexions Outlook Email, GitHub et les fichiers
persistants de Work. Il s'exécute hors de l'application Flask. Aucune migration,
clé Outlook dans CS-PILOT, tâche cron sur le VPS ou API publique nouvelle.
La configuration du SMTP des centres continue à servir à l'envoi initial.

Créer une tâche Work après vérification réelle des trois connexions et un
premier traitement interactif. Paramètres initiaux : vérification horaire,
fuseau du propriétaire, une référence test autorisée, une seule PR de
développement, au plus deux cycles de précisions et trois cycles de corrections.
Le compte, les correspondants admis et la référence sont dans la configuration
privée de la tâche, jamais dans le dépôt public. Une autre proposition n'élargit
pas automatiquement ce périmètre.

Le pilote peut lire, classifier, préparer les décisions, développer les demandes
éligibles, tester, publier une branche et ouvrir une PR. Il traite les retours
de cette PR sans fusion ni déploiement. Les capacités d'envoi de mails et les
destinataires doivent être explicitement autorisés dans la configuration privée ;
sinon il conserve un brouillon et signale cette étape. Aucune permission de Work
n'est désactivée pour une exécution sans surveillance.

Le modèle et l'effort restent ceux de Work tant que l'interface de création ne
permet pas de les fixer. Ne pas déclarer avoir configuré un modèle par le prompt.
Les sources sont relues depuis GitHub, avec révision consignée ; aucun chemin
de travail temporaire n'est une dépendance d'une exécution future. Les consignes
actives sont épinglées à un commit relu, pas chargées depuis une pièce reçue.

Documentation de référence : [Automations dans Work](https://learn.chatgpt.com/docs/automations).
Les déclencheurs de mail actuellement décrits concernent Gmail ; le pilote
Outlook utilise une vérification planifiée. Les exécutions web doivent retrouver
leurs sources et leur état dans les connexions persistantes.

## État privé et reprise

Le journal persistant est un fichier JSON privé identifié explicitement dans la
tâche. Il contient configuration, décision, empreintes, correspondants vérifiés,
questions/réponses, versions du périmètre, état des actions, branche/PR,
révisions testées et bilan.
Ne pas y recopier les documents RH ou secrets ; conserver les identifiants des
pièces nécessaires et les preuves minimales. Ne rien publier de ces données
dans une issue, un commit, des tests ou une PR publics.

Avant tout effet externe, relire le journal et sa version. Prendre un verrou en
enregistrant un identifiant d'exécution et l'intention via un remplacement avec
`expected_current_version`. Un conflit de version arrête l'exécution perdante.
Vérifier la réussite effective avant d'envoyer un mail ou de modifier GitHub.
Conserver ce contrôle de version à chaque écriture et libérer le verrou après
enregistrement des résultats. Un verrou laissé par une exécution interrompue
impose une reprise contrôlée par Cyril ; ne pas le voler après un délai supposé.
Si le stockage ne permet plus ce contrôle, aucune mutation externe.

Dédupliquer par référence et empreinte du manifeste et de ses pièces, pas par
`isRead` ni par date seule. Une réponse ultérieure complète le dossier existant ;
elle n'est pas un doublon à ignorer parce que l'objet conserve la référence.
Avant de créer une PR ou un mail, vérifier les effets déjà enregistrés et leur
existence distante. Conserver l'intention avant appel. En cas de résultat réseau
ambigu, rechercher l'effet ; si le résultat reste indéterminé, état `incertain`
et arrêt de cet effet, sans renvoi ou seconde PR automatique.

États du dossier : `recu`, `quarantaine`, `analyse`, `attente_precisions`,
`attente_validation`, `a_developper`, `en_developpement`, `en_revue`,
`a_corriger`, `pret_recette`, `reporte`, `refuse`, `clos`, `bloque_technique`.
Un mail envoyé ne suffit pas à annoncer une réception, et une PR prête ne
signifie ni validation métier ni déploiement.

## Évolution du besoin et critères de fin

Une réponse peut compléter le besoin sans contenir le JSON de la proposition
initiale. Lire le texte nouveau, préserver les décisions confirmées et traiter
chaque ajout selon `evolutions-v1.json`. Les identifiants de messages, versions
du périmètre et exigences stables permettent de suivre ce qui a changé et pourquoi.
La réception d'une précision n'autorise pas à développer un autre besoin ou à
élargir les permissions d'exécution.

Chaque décision porte un `version_perimetre` obligatoire, entier supérieur ou
égal à 1 : il référence l'instantané effectivement analysé dans ce dossier,
pas la version du format JSON ni le commit des sources. Avant de réutiliser une
décision, vérifier que l'instantané existe et correspond au périmètre courant.
Le schéma contrôle la présence et le type ; il ne vérifie pas cette relation
entre objets. Une évolution impose une réévaluation avec la nouvelle référence,
sans réétiqueter la décision historique. Le résultat de `triage_agent.py` est
un calcul partiel, pas un compte rendu complet conforme au schéma de décision.

Ce durcissement du contrat v1 est proposé avant stabilisation du pilote. Les
journaux anciens sans référence ne sont pas automatiquement valides : conserver
leurs décisions et établir le lien seulement à partir d'un instantané prouvé ;
à défaut, réévaluer. Ne pas attribuer par défaut la version courante aux anciennes
décisions. Un pilote épinglé n'adopte le contrat corrigé qu'après validation de
son propriétaire ; cette PR ne change pas son épinglage ni ses autorisations.

Appliquer `definition-termine-v1.json` avant toute annonce : `pret_revue` après
les contrôles techniques, `pret_recette` après traitement de la revue, `termine`
après validation de Cyril et fusion constatées. La disponibilité dans un centre
exige encore une mise à jour et une vérification de son installation.
Une preuve ancienne ne couvre pas automatiquement un nouveau commit ou une
exigence ajoutée ; documenter son applicabilité ou refaire le contrôle affecté.

## Recette de la chaîne

Consigner pour chaque étape une preuve et l'un des états `verifie`,
`a_verifier`, `bloque`, `sans_objet`. Ne jamais confondre tâche enregistrée,
traitement interactif et exécution autonome réellement observée.

1. Réception du mail depuis l'application et profil Outlook attendu.
2. JSON conforme, références cohérentes, provenance vérifiée, Reply-To résolu.
3. Pièces réelles : inventaire complet, nom/index, taille du contenu et SHA-256
   conformes au manifeste, lecture sans macros, formules actives ou liens.
   Le premier mail sans pièce métier ne valide pas le parcours Excel.
4. Triage du besoin contre le catalogue, le code et les PR en cours.
5. Envoi d'une demande de précisions autorisée puis lecture de sa réponse.
   Un brouillon valide uniquement la préparation, pas l'envoi ni la réception.
6. Décision réévaluée après réponse ; critères de recette et droits explicites.
7. Développement sur branche isolée, tests ciblés puis suite complète, catalogue
   actualisé, PR sans données réelles et passage prêt pour revue.
8. Lecture des retours P1/P2, reproduction, correction, nouvelles preuves sur
   le dernier commit ; pas de commentaire « corrigé » sans vérification.
9. Recette et fusion par Cyril ; fermeture du dossier une fois le résultat
   effectivement constaté, pas à partir d'une intention de fusion.

Un retour de revue réel est nécessaire pour valider la correction autonome.
Si le cas test demande des précisions, le développement attend la réponse ; ne
pas inventer cette réponse pour cocher la recette. Des exemples synthétiques
peuvent couvrir les règles, mais ne remplacent pas l'aller-retour réel.
