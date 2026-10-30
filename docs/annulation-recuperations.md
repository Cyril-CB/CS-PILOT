# Annuler ou remplacer une récupération validée

## Arrêt maladie ou accident du travail

La comptabilité et la direction saisissent l’absence dans **Absences**. Les récupérations
validées sont annulées uniquement sur les dates couvertes par l’arrêt. Une récupération
de trois jours dont le deuxième devient un arrêt reste appliquée le premier et le
troisième jour. Une récupération horaire sur une journée couverte est entièrement
retirée sur cette journée : le formulaire d’absence ne gère pas d’arrêt à l’heure.

Les autres motifs d’absence ne remplacent pas automatiquement une récupération.
Une autre absence déjà présente reste bloquante ; aucun cumul n’est introduit.

## Le salarié a finalement travaillé

Dans **Historique des demandes**, la comptabilité ou la direction ouvre **Annuler une
récupération**, choisit les dates et indique un motif obligatoire. Les heures réelles
peuvent ensuite être saisies par le circuit habituel. Le salarié et le responsable
ne peuvent pas annuler eux-mêmes une récupération validée.

L’annulation retire la ligne de récupération, sans inventer d’horaires travaillés.
Le compteur existant se recalcule à partir du calendrier : aucun second crédit manuel
n’est ajouté. Un arrêt remplace la récupération par une absence conforme au planning.
La demande initiale, ses dates, son volume et ses validations sont conservés ; elle
devient `annulee` seulement lorsque tous ses jours sont annulés, sinon reste `validee`.
Les listes affichent les dates annulées, les heures correspondantes, le motif et
l’auteur. Les totaux maintenus tiennent compte de ces retraits ; la durée affichée
dans la colonne initiale reste celle de la demande originale.

## Sécurité, historique et corrections

- Seuls `comptable` et `directeur` agissent, en POST protégé par CSRF, après contrôle
  de session courant. Le contrôle reste côté serveur.
- Le retrait et le remplacement sont atomiques avec la demande, le calendrier et
  l’historique. Un second envoi de la même annulation ne crédite rien une seconde fois.
- Un mois verrouillé doit être réouvert par la direction avec motif, via le circuit
  existant. Les signatures et préparations de paie suivent les contrôles existants.
- Une projection structurée doit correspondre à son contenu mémorisé. Pour une ancienne
  récupération sans preuve, seul le commentaire exact et le bon type de saisie sont
  reconnus. Une origine ambiguë ou plusieurs récupérations historiques superposées
  sont refusées : aucune saisie manuelle ni autre absence n’est effacée.
- Retirer l’arrêt ultérieurement ne réactive pas une récupération annulée : la trace
  reste conservée. Une éventuelle nouvelle récupération suit une nouvelle demande.

La migration additive `0082` crée `recup_annulations` sans reconstituer ni modifier les
demandes anciennes. Les heures datées enregistrées sont celles de la récupération
partielle ou du planning applicable lors de l’annulation ; le compteur demeure celui
du calendrier. Installation neuve et migration utilisent le même helper de schéma.
La table est incluse dans le catalogue de résilience. Aucun document métier n’est créé.
