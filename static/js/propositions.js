/* Préparation explicite du formulaire, sans placer la recherche dans une URL. */
(function () {
    'use strict';
    var pont = document.getElementById('proposition-pont');
    var prefixe = 'cspilot-proposition-recherche-';
    var cle = pont ? prefixe + pont.dataset.user + '-' + pont.dataset.session : '';
    try {
        for (var i = sessionStorage.length - 1; i >= 0; i--) {
            var ancienneCle = sessionStorage.key(i);
            if (ancienneCle.indexOf(prefixe) === 0 && ancienneCle !== cle) {
                sessionStorage.removeItem(ancienneCle);
            }
        }
    } catch (e) { /* Pas de contexte réutilisé si le stockage est indisponible. */ }
    if (!pont) return;
    var duree = 30 * 60 * 1000;

    function lire() {
        try {
            var valeur = JSON.parse(sessionStorage.getItem(cle) || 'null');
            if (valeur && typeof valeur.recherche === 'string' && Date.now() - valeur.date < duree) {
                return valeur;
            }
            sessionStorage.removeItem(cle);
        } catch (e) { /* Le formulaire reste accessible sans stockage navigateur. */ }
        return null;
    }

    function memoriser(recherche, origine) {
        if (!recherche) return;
        try {
            sessionStorage.setItem(cle, JSON.stringify({
                recherche: String(recherche).slice(0, 200),
                origine: origine, date: Date.now()
            }));
        } catch (e) { /* Aucune dépendance à sessionStorage pour l'envoi. */ }
    }

    function ouvrir(recherche, origine) {
        var derniere = lire();
        var explicite = typeof recherche === 'string';
        pont.elements.recherche.value = (explicite ? recherche : derniere ? derniere.recherche : '').slice(0, 200);
        pont.elements.origine.value = origine || (explicite || derniere ? 'insatisfait' : 'spontanee');
        pont.submit();
    }

    window.CSPilotPropositions = {memoriser: memoriser, ouvrir: ouvrir};
    lire(); // Effacer un contexte expiré dès l'ouverture d'une page.
    document.addEventListener('click', function (e) {
        var lien = e.target.closest && e.target.closest('[data-proposer-amelioration]');
        if (!lien || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        ouvrir(lien.hasAttribute('data-recherche') ? lien.dataset.recherche : undefined,
               lien.dataset.origine);
    });

    var formulaire = document.getElementById('proposition-formulaire');
    if (!formulaire) return;
    var fichiers = document.getElementById('pieces');
    var liste = document.getElementById('proposition-pieces-liste');
    var maximumFichier = Number(fichiers.dataset.maxFichier) || 5 * 1024 * 1024;
    var maximumTotal = Number(fichiers.dataset.maxTotal) || 8 * 1024 * 1024;
    fichiers.addEventListener('change', function () {
        liste.textContent = '';
        var total = 0;
        var invalides = fichiers.files.length > 3;
        Array.from(fichiers.files).forEach(function (fichier) {
            total += fichier.size;
            invalides = invalides || !fichier.size || fichier.size > maximumFichier;
            var item = document.createElement('li');
            item.textContent = fichier.name + ' · ' + Math.ceil(fichier.size / 1024) + ' Ko';
            liste.appendChild(item);
        });
        fichiers.setCustomValidity(invalides || total > maximumTotal ?
            'Choisissez au maximum 3 fichiers, dans les limites de taille indiquées.' : '');
    });
    formulaire.addEventListener('submit', function () {
        try { sessionStorage.removeItem(cle); } catch (e) { /* Facultatif. */ }
        document.getElementById('proposition-envoyer').disabled = true;
        document.getElementById('proposition-envoi-info').textContent =
            'Enregistrement et transmission en cours…';
    });
    window.addEventListener('pageshow', function () {
        document.getElementById('proposition-envoyer').disabled = false;
        document.getElementById('proposition-envoi-info').textContent = '';
    });
    var erreurs = document.getElementById('proposition-erreurs');
    if (erreurs) erreurs.focus();
})();
