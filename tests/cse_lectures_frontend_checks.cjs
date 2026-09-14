/* Contrôles du parcours JavaScript CSE, sans navigateur ni dépendance externe. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../templates/base.html'), 'utf8');
const match = template.match(/<script>\s*(var cseMessageTrigger = null;[\s\S]*?)<\/script>/);
assert.ok(match, 'script de lecture CSE introuvable');

function ouvrirPage(ok) {
    const handlers = {};
    const focalisable = () => ({focusCount: 0, focus() {
        this.focusCount += 1;
        document.activeElement = this;
    }});
    const fermeture = focalisable();
    const boutonLu = focalisable();
    const contenuModal = focalisable();
    const modal = {
        style: {display: 'none'},
        querySelector(selector) {
            return selector === '.modal-close' ? fermeture : contenuModal;
        },
        querySelectorAll() { return [fermeture, boutonLu]; },
        contains(element) { return [fermeture, boutonLu, contenuModal].includes(element); }
    };
    const contenu = {
        focusCount: 0,
        attributes: {},
        setAttribute(name, value) { this.attributes[name] = value; },
        removeAttribute(name) { delete this.attributes[name]; },
        focus() { this.focusCount += 1; document.activeElement = this; },
        addEventListener() {}
    };
    const trigger = {
        hidden: false,
        focusCount: 0,
        attributes: {},
        getAttribute(name) { return name === 'data-read-url' ? '/cse/messages/1/lire' : null; },
        setAttribute(name, value) { this.attributes[name] = value; },
        focus() { this.focusCount += 1; document.activeElement = this; }
    };
    const document = {
        activeElement: null,
        getElementById(id) { return id === 'cseMessageModal' ? modal : null; },
        querySelector(selector) { return selector === '.main-content' ? contenu : null; },
        addEventListener(name, callback) { handlers[name] = callback; }
    };
    const context = {document, fetch: () => Promise.resolve({ok})};
    vm.runInNewContext(match[1], context);
    return {api: context, boutonLu, contenu, fermeture, handlers, modal, trigger};
}

(async function () {
    const succes = ouvrirPage(true);
    succes.api.cseOpenMessage(succes.trigger);
    assert.equal(succes.modal.style.display, 'flex');
    assert.equal(succes.fermeture.focusCount, 1);

    // Tab et Maj+Tab restent dans la fenêtre tant qu'elle est ouverte.
    let tabEmpeche = 0;
    succes.boutonLu.focus();
    succes.handlers.keydown({key: 'Tab', shiftKey: false,
        preventDefault() { tabEmpeche += 1; }});
    assert.equal(tabEmpeche, 1);
    assert.equal(succes.fermeture.focusCount, 2);
    succes.handlers.keydown({key: 'Tab', shiftKey: true,
        preventDefault() { tabEmpeche += 1; }});
    assert.equal(tabEmpeche, 2);
    assert.equal(succes.boutonLu.focusCount, 2);
    succes.contenu.focus();
    succes.handlers.keydown({key: 'Tab', shiftKey: false,
        preventDefault() { tabEmpeche += 1; }});
    assert.equal(tabEmpeche, 3);
    assert.equal(succes.fermeture.focusCount, 3);

    await new Promise(resolve => setImmediate(resolve));
    assert.equal(succes.trigger.hidden, true);
    assert.equal(succes.trigger.attributes['aria-hidden'], 'true');
    succes.api.cseCloseMessage();
    assert.equal(succes.modal.style.display, 'none');
    assert.equal(succes.trigger.focusCount, 0);
    assert.equal(succes.contenu.focusCount, 2);

    // Échap ne concerne cette modale que lorsqu'elle est réellement ouverte.
    let empeche = 0;
    let arrete = 0;
    succes.handlers.keydown({key: 'Escape', preventDefault() { empeche += 1; },
        stopImmediatePropagation() { arrete += 1; }});
    assert.equal(empeche, 0);
    assert.equal(arrete, 0);
    succes.api.cseOpenMessage(succes.trigger);
    succes.handlers.keydown({key: 'Escape', preventDefault() { empeche += 1; },
        stopImmediatePropagation() { arrete += 1; }});
    assert.equal(empeche, 1);
    assert.equal(arrete, 1);
    assert.equal(succes.modal.style.display, 'none');

    // Une réponse HTTP en erreur conserve la bannière et permet une nouvelle tentative.
    const echec = ouvrirPage(false);
    echec.api.cseOpenMessage(echec.trigger);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(echec.trigger.hidden, false);
    echec.api.cseCloseMessage();
    assert.equal(echec.trigger.focusCount, 1);
    assert.equal(echec.contenu.focusCount, 0);

    process.stdout.write('Parcours JavaScript des lectures CSE : OK\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
