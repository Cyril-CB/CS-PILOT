(function () {
    'use strict';
    const root = document.getElementById('assistantPage');
    const form = document.getElementById('assistantDocumentForm');
    if (!root || !form) return;
    const list = document.getElementById('assistantDocuments');
    const errorBox = document.getElementById('assistantDocumentsErreur');
    const status = document.getElementById('assistantDocumentStatut');
    const model = document.getElementById('assistantDocumentModele');
    const csrf = document.querySelector('meta[name="csrf-token"]');
    const labels = {facture:'Facture', convention:'Convention de financement', notification:'Notification de subvention',
        contrat:'Contrat de travail', arret_maladie:'Arrêt maladie', autre:'Autre document'};
    const states = {recu:'À analyser', analyse:'Analyse disponible', precision:'Précisions nécessaires', traite:'Traitement terminé'};
    let busy = false, version = 0;

    function el(tag, text, cls) {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (cls) node.className = cls;
        return node;
    }
    function button(text, callback) {
        const b = el('button', text, 'btn btn-secondary btn-sm');
        b.type = 'button'; b.addEventListener('click', callback); return b;
    }
    function link(text, value) {
        const url = new URL(value, location.origin);
        if (url.origin !== location.origin || !value.startsWith('/') || value.startsWith('//')) return el('span');
        const a = el('a', text, 'btn btn-secondary btn-sm'); a.href = value; return a;
    }
    function error(text) { errorBox.textContent = text || ''; errorBox.hidden = !text; }
    function controls() {
        root.querySelectorAll('.assistant-reception button').forEach(b => { b.disabled = busy; });
        root.querySelectorAll('[data-needs-model]').forEach(b => { b.disabled = busy || !model.value; });
        status.textContent = busy ? 'Traitement en cours… Le PDF déposé reste conservé en cas d’erreur.' : '';
    }
    async function api(url, method, body) {
        const headers = {'X-CSRFToken': csrf ? csrf.content : ''};
        if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
        const response = await fetch(url, {method:method || 'GET', credentials:'same-origin', headers,
            body:body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body)});
        if (response.redirected) throw new Error('Votre session a expiré. Rechargez la page.');
        let data;
        try { data = await response.json(); } catch (_) { throw new Error('Réponse indisponible. Actualisez la boîte de réception.'); }
        if (!response.ok) throw new Error(data.error || 'Le traitement n’a pas abouti.');
        return data;
    }
    async function load(openId) {
        const current = ++version;
        const data = await api(root.dataset.documents);
        if (current !== version) return;
        const opened = new Set(Array.from(list.querySelectorAll('details[open]'), n => n.dataset.id));
        if (openId) opened.add(openId);
        list.replaceChildren();
        if (!data.documents.length) list.append(el('p', 'Aucun document déposé pour le moment.', 'assistant-aide'));
        data.documents.forEach(d => list.append(render(d, opened.has(d.id))));
        controls();
    }
    async function operation(fn) {
        if (busy) return;
        busy = true; error(''); controls();
        let selected;
        try { selected = await fn(); }
        catch (e) { error(e.message); }
        finally {
            try { await load(selected && selected.id); } catch (e) { error(e.message); }
            busy = false; controls(); root.dispatchEvent(new CustomEvent('assistant:quota'));
        }
    }
    function addOption(select, value, text) { const o = el('option', text); o.value = value; select.append(o); }
    function field(q, d, parent) {
        const id = 'document-' + d.id + '-' + q.champ;
        const label = el('label', q.label); label.htmlFor = id; parent.append(label);
        let input;
        if (q.type === 'etapes') {
            const box = el('div'); box.id = id;
            const add = button('Ajouter une échéance', () => {
                const row = el('div', undefined, 'assistant-etape');
                const title = el('input'); title.type = 'text'; title.maxLength = 200; title.required = true;
                title.placeholder = 'Étape à suivre'; title.setAttribute('aria-label', 'Étape à suivre');
                const day = el('input'); day.type = 'date'; day.required = true; day.setAttribute('aria-label', 'Date d’échéance');
                const remove = button('Retirer cette ligne', () => row.remove());
                row.append(title, day, remove); box.append(row);
            });
            parent.append(box, add);
            return () => Array.from(box.querySelectorAll('.assistant-etape'), row => ({
                nom:row.querySelector('input[type=text]').value.trim(), date_echeance:row.querySelector('input[type=date]').value}));
        }
        if (['salarie','salaries','subvention','affectation','contrat'].includes(q.type)) {
            input = el('select');
            if (q.type === 'salaries') { input.multiple = true; input.size = 4; }
            else addOption(input, '', q.type === 'affectation' ? 'Sans affectation' : 'Choisir…');
            if (q.type === 'salarie' || q.type === 'salaries')
                (d.choix.salaries || []).forEach(p => addOption(input, p.id, p.prenom + ' ' + p.nom));
            else if (q.type === 'subvention') {
                (d.choix.subventions || []).forEach(s => addOption(input, s.id, s.nom + ' · ' + (s.annee || 'année non renseignée')));
                addOption(input, 'nouvelle', 'Créer une nouvelle subvention');
            } else if (q.type === 'affectation') (d.choix.affectations || []).forEach(s => addOption(input, s.id, s.nom));
            else ['CDI','CDD','CEE','Autre'].forEach(t => addOption(input, t, t));
        } else {
            input = el('input');
            input.type = q.type === 'confirmation' ? 'checkbox' : q.type === 'date' ? 'date' :
                ['nombre','annee'].includes(q.type) ? 'number' : 'text';
            if (q.type === 'nombre') { input.min = '0'; input.step = '0.01'; }
            if (q.type === 'annee') { input.min = '1900'; input.max = '2200'; input.step = '1'; }
            if (input.type === 'text') input.maxLength = 500;
        }
        input.id = id; input.name = 'assistant_document_' + q.champ;
        input.required = !!q.obligatoire && q.type !== 'affectation';
        if (d.champs[q.champ] != null && input.type !== 'checkbox') input.value = d.champs[q.champ];
        parent.append(input);
        return () => {
            if (q.type === 'confirmation') return input.checked;
            if (q.type === 'salaries') return Array.from(input.selectedOptions, o => Number(o.value));
            if (q.type === 'salarie') return Number(input.value);
            if (q.type === 'subvention') return input.value === 'nouvelle' ? 'nouvelle' : Number(input.value);
            return input.value;
        };
    }
    function render(d, opened) {
        const details = el('details', undefined, 'assistant-document'); details.dataset.id = d.id; details.open = opened;
        const summary = el('summary', d.nom + (d.type ? ' · ' + labels[d.type] : ''));
        summary.append(el('span', d.en_cours ? 'Analyse en cours' : states[d.statut], 'assistant-badge')); details.append(summary);
        if (d.commentaire) details.append(el('p', 'Votre commentaire : ' + d.commentaire, 'assistant-aide'));
        const actions = el('div', undefined, 'assistant-exemples');
        actions.append(link('Télécharger le PDF', d.pdf), button('Poser une question sur ce PDF', () => {
            root.dispatchEvent(new CustomEvent('assistant:document', {detail:{id:d.id, nom:d.nom}}));
            document.getElementById('assistantForm').scrollIntoView({behavior:'smooth', block:'center'});
        }));
        if (!d.analyse) {
            const retry = button('Analyser', () => operation(() => api(root.dataset.documents + '/' + d.id + '/analyser', 'POST', {model:model.value})));
            retry.dataset.needsModel = '1'; actions.append(retry);
        }
        details.append(actions);
        if (d.analyse) {
            details.append(el('h3', d.analyse.titre), el('p', d.analyse.resume));
            if (d.analyse.informations.length) {
                const ul = el('ul'); d.analyse.informations.forEach(v => ul.append(el('li', v))); details.append(ul);
            }
            d.analyse.questions.forEach(q => details.append(el('p', q, 'assistant-aide')));
        }
        if (d.resultat.message && (!d.analyse || d.resultat.message !== d.analyse.resume))
            details.append(el('p', d.resultat.message, 'assistant-notice'));
        if (d.resultat.lien) details.append(link('Ouvrir le module pour la suite', d.resultat.lien));
        if (d.erreur) details.append(el('p', d.erreur, 'assistant-erreur'));
        if (d.analyse && d.statut !== 'traite' && d.autorise) {
            const f = el('form'); f.autocomplete = 'off';
            const readers = new Map();
            d.questions.forEach(q => readers.set(q.champ, field(q, d, f)));
            const submit = el('button', d.questions.length ? 'Répondre et poursuivre le traitement' : 'Reprendre le traitement', 'btn btn-primary btn-sm');
            submit.type = 'submit'; f.append(submit);
            f.addEventListener('submit', e => {
                e.preventDefault(); const answers = {};
                readers.forEach((read, key) => { answers[key] = read(); });
                if (answers.assignees && answers.assignees.length > 2) { error('Choisissez au maximum deux salariés.'); return; }
                operation(() => api(root.dataset.documents + '/' + d.id + '/precisions', 'POST', {revision:d.revision, reponses:answers}));
            });
            details.append(f);
        }
        if (!d.resultat.facture_id && !d.resultat.subvention_id && !d.resultat.contrat_id && d.analyse) {
            const correction = el('details');
            correction.append(el('summary', 'Préciser ou corriger le type de document'));
            const f = el('form'); f.autocomplete = 'off';
            const type = el('select'); type.id = 'document-type-' + d.id;
            const label = el('label', 'Type à réexaminer'); label.htmlFor = type.id;
            addOption(type, '', 'Laisser l’assistant identifier le type');
            Object.entries(labels).forEach(([k,v]) => addOption(type,k,v));
            const note = el('textarea'); note.id = 'document-note-' + d.id; note.maxLength = 2000; note.rows = 2;
            const noteLabel = el('label', 'Précision facultative'); noteLabel.htmlFor = note.id;
            const submit = el('button', 'Réexaminer avec ces précisions', 'btn btn-secondary btn-sm');
            submit.type = 'submit'; submit.dataset.needsModel = '1';
            f.append(label,type,noteLabel,note,submit);
            f.addEventListener('submit', e => {
                e.preventDefault();
                const body = {model:model.value, commentaire:note.value.trim()};
                if (type.value) body.type_document = type.value;
                operation(() => api(root.dataset.documents + '/' + d.id + '/analyser', 'POST', body));
            });
            correction.append(f); details.append(correction);
        }
        return details;
    }
    form.addEventListener('submit', e => {
        e.preventDefault();
        const file = document.getElementById('assistantDocumentFichier').files[0];
        if (!file) return;
        if (!file.name.toLowerCase().endsWith('.pdf') || file.size > 16 * 1024 * 1024) {
            error('Choisissez un PDF numérique original de 16 Mo maximum.'); return;
        }
        operation(async () => {
            const data = await api(root.dataset.documents, 'POST', new FormData(form));
            form.reset(); return data;
        });
    });
    document.getElementById('assistantDocumentsActualiser').addEventListener('click', () => {
        if (!busy) load().catch(e => error(e.message));
    });
    model.addEventListener('change', controls);
    load().catch(e => error(e.message));
})();
