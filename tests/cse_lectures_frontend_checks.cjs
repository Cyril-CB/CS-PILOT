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
    const appels = [];
    const focalisable = () => ({focusCount: 0, focus() {
        this.focusCount += 1;
        document.activeElement = this;
    }});
    const fermeture = focalisable();
    const contenuModal = focalisable();
    const boutonLu = Object.assign(focalisable(), {
        disabled: false,
        getAttribute(name) { return name === 'data-read-url' ? '/cse/messages/1/lire' : null; }
    });
    const erreur = {hidden: true};
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
    // La bannière ne porte plus d'URL d'enregistrement : elle ouvre seulement la modale.
    const trigger = {
        hidden: false,
        focusCount: 0,
        attributes: {},
        getAttribute() { return null; },
        setAttribute(name, value) { this.attributes[name] = value; },
        focus() { this.focusCount += 1; document.activeElement = this; }
    };
    const document = {
        activeElement: null,
        getElementById(id) {
            if (id === 'cseMessageModal') return modal;
            if (id === 'cseLectureErreur') return erreur;
            return null;
        },
        querySelector(selector) { return selector === '.main-content' ? contenu : null; },
        addEventListener(name, callback) { handlers[name] = callback; }
    };
    const fetch = (url, options) => {
        appels.push({url, options});
        return Promise.resolve({ok});
    };
    const context = {document, fetch};
    vm.runInNewContext(match[1], context);
    return {api: context, appels, boutonLu, contenu, erreur, fermeture, handlers, modal, trigger, document};
}

const attendre = () => new Promise(resolve => setImmediate(resolve));

(async function () {
    const succes = ouvrirPage(true);
    succes.api.cseOpenMessage(succes.trigger);
    assert.equal(succes.modal.style.display, 'flex');
    assert.equal(succes.fermeture.focusCount, 1);

    // Ouvrir le message ne l'enregistre plus comme lu.
    await attendre();
    assert.equal(succes.appels.length, 0, 'aucun appel serveur à la simple ouverture');
    assert.equal(succes.trigger.hidden, false, 'la bannière reste visible tant que rien n’est confirmé');

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

    // Fermer sans confirmer laisse la bannière et rend le focus à celle-ci.
    succes.api.cseCloseMessage();
    assert.equal(succes.modal.style.display, 'none');
    assert.equal(succes.trigger.hidden, false);
    assert.equal(succes.trigger.focusCount, 1);

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
    assert.equal(succes.trigger.hidden, false, 'Échap n’enregistre aucune lecture');

    // Le bouton explicite enregistre la lecture, masque la bannière et ferme la modale.
    succes.api.cseOpenMessage(succes.trigger);
    succes.api.cseMarquerLu(succes.boutonLu);
    assert.equal(succes.boutonLu.disabled, true, 'le bouton est neutralisé pendant l’appel');
    assert.equal(succes.appels.length, 1);
    assert.equal(succes.appels[0].url, '/cse/messages/1/lire');
    assert.equal(succes.appels[0].options.method, 'POST');
    await attendre();
    assert.equal(succes.trigger.hidden, true);
    assert.equal(succes.trigger.attributes['aria-hidden'], 'true');
    assert.equal(succes.modal.style.display, 'none');
    assert.equal(succes.contenu.focusCount, 2, 'le focus revient dans la page, pas sur la bannière masquée');

    // Une réponse HTTP en erreur conserve la bannière et permet une nouvelle tentative.
    const echec = ouvrirPage(false);
    echec.api.cseOpenMessage(echec.trigger);
    echec.api.cseMarquerLu(echec.boutonLu);
    await attendre();
    assert.equal(echec.trigger.hidden, false);
    assert.equal(echec.modal.style.display, 'flex', 'la modale reste ouverte pour réessayer');
    assert.equal(echec.boutonLu.disabled, false);
    assert.equal(echec.erreur.hidden, false);
    echec.api.cseOpenMessage(echec.trigger);
    assert.equal(echec.erreur.hidden, true, 'le message d’erreur ne survit pas à une réouverture');
    echec.api.cseCloseMessage();
    assert.equal(echec.trigger.focusCount, 1);
    assert.equal(echec.contenu.focusCount, 0);

    // Un clic sur le chatbot ou un focus programmatique ne doit pas sortir
    // du dialogue, même sans appui sur Tab. Après fermeture, il reste libre.
    const chatbot = ouvrirPage(false);
    const champChat = {};
    const donnerFocusChat = () => {
        chatbot.document.activeElement = champChat;
        if (chatbot.handlers.focusin) chatbot.handlers.focusin({target: champChat});
    };
    chatbot.api.cseOpenMessage(chatbot.trigger);
    donnerFocusChat();
    assert.equal(chatbot.document.activeElement, chatbot.fermeture,
        'le focus externe doit revenir immédiatement dans la modale');
    chatbot.boutonLu.focus();
    chatbot.handlers.focusin({target: chatbot.boutonLu});
    assert.equal(chatbot.document.activeElement, chatbot.boutonLu);
    chatbot.api.cseCloseMessage();
    donnerFocusChat();
    assert.equal(chatbot.document.activeElement, champChat);

    process.stdout.write('Parcours JavaScript des lectures CSE : OK\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
