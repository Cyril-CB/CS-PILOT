// Exécute le JavaScript réellement rendu par Flask, sans dépendance navigateur.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {html, fields} = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {};
for (const [id, attrs] of Object.entries(fields)) {
    nodes[id] = {
        checked: 'checked' in attrs, disabled: 'disabled' in attrs,
        value: attrs.value || '', style: {display: (attrs.style || '').includes('display:none') ? 'none' : ''},
        addEventListener() {},
    };
}
const timeIds = Object.keys(fields).filter(id => fields[id].type === 'time');
const soirIds = ['heure_debut_soir', 'heure_fin_soir'];
nodes['saisie-heures-detail'].querySelectorAll = () => timeIds.map(id => nodes[id]);
nodes['soir-section'].querySelectorAll = () => soirIds.map(id => nodes[id]);
const context = vm.createContext({document: {
    getElementById: id => nodes[id] || null,
    querySelectorAll: () => [], addEventListener() {}, body: {appendChild() {}},
}});
const script = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)]
    .map(match => match[1]).find(source => source.includes('function toggleSoir()'));
assert(script, 'Script de saisie présent');
vm.runInContext(script, context);
const toggle = nodes.toggle_soir;
function assertManual() {
    assert.equal(toggle.disabled, false);
    for (const id of timeIds) assert.equal(nodes[id].disabled, soirIds.includes(id) && !toggle.checked);
    assert.equal(nodes['soir-section'].style.display === 'none', !toggle.checked);
}
function assertWholeDay(mode) {
    assert.equal(toggle.disabled, true, `${mode}: case soir désactivée`);
    assert.equal(toggle.checked, false);
    assert.equal(nodes['soir-section'].style.display, 'none');
    for (const id of timeIds) {
        assert.equal(nodes[id].disabled, true);
        assert.equal(nodes[id].value, '');
    }
    assert.equal(nodes.pause_remuneree.disabled, true);
    const other = mode === 'recup_journee' ? 'declaration_conforme' : 'recup_journee';
    if (nodes[other]) {
        assert.equal(nodes[other].disabled, true);
        assert.equal(nodes[other].checked, false);
    }
}
const handlers = {recup_journee:'toggleRecupJournee', declaration_conforme:'toggleDeclaration'};
// Vérifie d'abord l'état obtenu au chargement, avant toute interaction.
const initialMode = Object.keys(handlers).find(id => nodes[id]?.checked);
if (initialMode) {
    assertWholeDay(initialMode);
    nodes[initialMode].checked = false;
    context[handlers[initialMode]]();
} else {
    assertManual();
    for (const id of soirIds) assert.equal(nodes[id].value, fields[id].value || '');
}
for (const mode of Object.keys(handlers).filter(id => nodes[id])) {
    for (const evening of [false, true]) {
        toggle.checked = evening;
        context.toggleSoir();
        if (evening) nodes.heure_debut_soir.value = '18:00';
        nodes[mode].checked = true;
        context[handlers[mode]]();
        assertWholeDay(mode);
        // Même un appel direct au handler ne doit pas réactiver les horaires.
        toggle.checked = true;
        context.toggleSoir();
        assertWholeDay(mode);
        nodes[mode].checked = false;
        context[handlers[mode]]();
        assertManual();
        toggle.checked = true;
        context.toggleSoir();
        assertManual();
        nodes.heure_debut_soir.value = '18:00';
        toggle.checked = false;
        context.toggleSoir();
        assertManual();
        assert.equal(nodes.heure_debut_soir.value, '');
    }
}
console.log('Transitions saisie / soir / modes journée et chargement initial : OK');
