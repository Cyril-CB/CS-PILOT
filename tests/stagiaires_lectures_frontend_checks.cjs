// Exécute le script livré, sans prétendre vérifier le rendu d'un navigateur.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../templates/accueil_flux.html'), 'utf8');
const script = source.split('<script>')[1].split('</script>')[0]
    .replace("{{ url_for('stagiaires_bp.lire_annonces') }}", '/stagiaires/annonces/lire');

async function scenario() {
    const listeners = [], requests = [], timeouts = [], timers = [];
    const fields = Object.fromEntries(['flxFaites', 'flxTotal', 'flxResume', 'flxAnneau', 'flxToutFait', 'flxActions']
        .map(id => [id, {textContent: '', style: {setProperty(k,v) {this[k]=v;}}}]));
    let cards = ['one', 'two', 'group'].map(ref => ({
        getAttribute: () => ref,
        classList: {add() {}},
        remove() {cards = cards.filter(c => c !== this);}
    }));
    let mode = 'pending', resolveFetch;
    const context = {
        document: {
            addEventListener: (_, fn) => listeners.push(fn),
            querySelectorAll: () => cards,
            querySelector: () => null,
            getElementById: id => fields[id],
        },
        window: {flxToast() {}}, URLSearchParams,
        setTimeout: fn => timeouts.push(fn),
        setInterval: fn => timers.push(fn),
        fetch: (url, options) => {
            requests.push({url, options});
            if (mode === 'pending') return new Promise(resolve => {resolveFetch=resolve;});
            return Promise.resolve({ok: mode === 'ok', json: () => Promise.resolve({ok: mode === 'ok'})});
        },
    };
    vm.runInNewContext(script, context);
    const event = btn => ({target: {closest: selector => selector === '[data-flx-act]' ? btn : null}});
    const button = (ref, annonces) => ({disabled: false, getAttribute: key => ({
        'data-flx-act':'stagiaire', 'data-flx-ref':ref, 'data-secteur-id':'7',
        'data-annonces':JSON.stringify(annonces),
    })[key]});
    const click = b => listeners.forEach(fn => fn(event(b)));
    const settle = async () => {for(let i=0;i<10;i++) await Promise.resolve(); while(timeouts.length) timeouts.shift()();};
    const first = button('one', [{stagiaire_id: 1, date:'2026-10-06'}]);
    click(first); click(first);
    assert.equal(requests.length, 1, 'double clic ignoré pendant la requête');
    assert.equal(cards.length, 3, 'ne pas masquer avant succès');
    resolveFetch({ok:false, json:()=>Promise.resolve({ok:false})}); await settle();
    assert.equal(first.disabled, false, 'échec réessayable');
    assert.equal(fields.flxFaites.textContent, 0);
    mode='ok'; click(first); await settle();
    assert.equal(fields.flxFaites.textContent, 1); assert.equal(fields.flxTotal.textContent, '/3');
    assert.equal(fields.flxResume.textContent, '2 décisions vous attendent.');
    click(button('two', [{stagiaire_id:2,date:'2026-10-06'}])); await settle();
    const group=[{stagiaire_id:3,date:'2026-10-06'},{stagiaire_id:4,date:'2026-10-06'}];
    click(button('group', group)); await settle();
    assert.deepEqual(JSON.parse(requests.at(-1).options.body), {annonces:group, secteur_id:'7'});
    assert.equal(cards.length,0); assert.equal(fields.flxFaites.textContent,3);
    assert.equal(fields.flxTotal.textContent,'/3'); assert.equal(fields.flxAnneau.style['--p'],'100%');
    assert.equal(fields.flxToutFait.style.display,'');
    assert.equal(fields.flxResume.textContent,'Tout est traité. L’application se tait.');
    console.log('Lecture, lot, double clic, erreur, compteurs et état vide : OK');
}
scenario().catch(e=>{console.error(e);process.exitCode=1;});
