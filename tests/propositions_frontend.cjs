/* Tests du script livré, sans navigateur ni dépendance JavaScript externe. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/propositions.js'), 'utf8');

function ouvrirPage({user = '1', session = '1', stockage = new Map(), formulaire = false} = {}) {
    const handlers = {}, fenetre = {}, etat = {date: 1000000, envois: []};
    function element() {
        return {listeners: {}, children: [], textContent: '', dataset: {},
            addEventListener(nom, cb) { this.listeners[nom] = cb; },
            appendChild(el) { this.children.push(el); },
            focus() { this.focused = true; }};
    }
    const pont = {dataset: {user, session}, elements: {
        recherche: {value: ''}, origine: {value: ''}},
        submit() { etat.envois.push({recherche: this.elements.recherche.value,
                                    origine: this.elements.origine.value}); }};
    const elements = user ? {'proposition-pont': pont} : {};
    if (formulaire) {
        for (const id of ['proposition-formulaire', 'pieces', 'proposition-pieces-liste',
                          'proposition-envoyer', 'proposition-envoi-info', 'proposition-erreurs']) {
            elements[id] = element();
        }
        elements.pieces.setCustomValidity = function (message) { this.erreur = message; };
    }
    const window = {addEventListener(nom, cb) { fenetre[nom] = cb; }};
    const document = {getElementById(id) { return elements[id] || null; },
        addEventListener(nom, cb) { handlers[nom] = cb; }, createElement: element};
    vm.runInNewContext(source, {window, document, Date: {now: () => etat.date},
        sessionStorage: {get length() { return stockage.size; }, key: i => Array.from(stockage.keys())[i],
                         getItem: k => stockage.get(k), setItem: (k, v) => stockage.set(k, v),
                         removeItem: k => stockage.delete(k)}});
    return {api: window.CSPilotPropositions, etat, elements, handlers, fenetre, stockage};
}

// La recherche survive à l'ouverture d'une autre page de l'onglet.
const depart = ouvrirPage();
depart.api.memoriser('SIRET asso <exemple>', 'sans_resultat');
const arrivee = ouvrirPage({stockage: depart.stockage});
arrivee.api.ouvrir();
assert.deepEqual(arrivee.etat.envois[0], {recherche: 'SIRET asso <exemple>', origine: 'insatisfait'});
arrivee.api.ouvrir('fréquentation crèche', 'sans_resultat');
assert.deepEqual(arrivee.etat.envois[1], {recherche: 'fréquentation crèche', origine: 'sans_resultat'});

// Aucun transfert de la recherche d'un autre compte ou d'une session révoquée.
for (const options of [{user: '2'}, {session: '2'}]) {
    const autre = ouvrirPage({...options, stockage: new Map(depart.stockage)});
    autre.api.ouvrir();
    assert.equal(autre.etat.envois[0].recherche, '');
    assert.equal(autre.stockage.size, 0);
}
const deconnecte = ouvrirPage({user: null, stockage: new Map(depart.stockage)});
assert.equal(deconnecte.stockage.size, 0);
arrivee.etat.date += 31 * 60 * 1000;
arrivee.api.ouvrir();
assert.equal(arrivee.etat.envois[2].recherche, '');

// Un lien de proposition transmet le contexte explicitement choisi.
let empeche = false;
const lien = {dataset: {recherche: '"besoin" & exemple', origine: 'insatisfait'},
    hasAttribute: () => true};
arrivee.handlers.click({target: {closest: () => lien}, preventDefault() { empeche = true; }});
assert.equal(empeche, true);
assert.equal(arrivee.etat.envois.at(-1).recherche, '"besoin" & exemple');

// La liste des noms utilise du texte ; validation des tailles puis retour navigateur.
const form = ouvrirPage({formulaire: true});
form.elements.pieces.files = [{name: '<img src=x onerror=alert(1)>.csv', size: 20}];
form.elements.pieces.listeners.change();
assert.equal(form.elements.pieces.erreur, '');
assert.equal(form.elements['proposition-pieces-liste'].children[0].textContent,
             '<img src=x onerror=alert(1)>.csv · 1 Ko');
form.elements.pieces.files = [{name: 'trop-grand.xlsx', size: 6 * 1024 * 1024}];
form.elements.pieces.listeners.change();
assert.ok(form.elements.pieces.erreur);
form.elements['proposition-formulaire'].listeners.submit();
assert.equal(form.elements['proposition-envoyer'].disabled, true);
form.fenetre.pageshow();
assert.equal(form.elements['proposition-envoyer'].disabled, false);
assert.equal(form.elements['proposition-erreurs'].focused, true);
process.stdout.write('Parcours JavaScript des propositions : OK\n');
