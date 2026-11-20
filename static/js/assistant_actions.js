(function () {
    'use strict';
    const root = document.getElementById('assistantPage');
    const list = document.getElementById('assistantActions');
    if (!root || !list) return;
    const errorBox = document.getElementById('assistantActionsErreur');
    const status = document.getElementById('assistantActionsStatut');
    const csrf = document.querySelector('meta[name="csrf-token"]');
    const base = root.dataset.actions;
    let busy = false, generation = 0, edits = 0;
    const labels = {attente:'À relire', executee:'Création effectuée', abandonnee:'Abandonnée', expiree:'Expirée'};

    function el(tag, text, cls) {
        const n = document.createElement(tag);
        if (text !== undefined) n.textContent = text;
        if (cls) n.className = cls;
        return n;
    }
    function button(text, callback) {
        const b = el('button', text, 'btn btn-secondary btn-sm');
        b.type = 'button'; b.addEventListener('click', callback); return b;
    }
    function edited() { return !!list.querySelector('[data-edite="1"]'); }
    function error(text) { errorBox.textContent = text || ''; errorBox.hidden = !text; }
    function controls() {
        list.querySelectorAll('button,input,select,textarea').forEach(n => { n.disabled = busy; });
        list.querySelectorAll('[data-confirmer]').forEach(b => { b.disabled = busy || b.form.dataset.modifie === '1'; });
        document.getElementById('assistantActionsActualiser').disabled = busy;
    }
    async function api(url, method, body) {
        const r = await fetch(url, {method:method || 'GET', credentials:'same-origin',
            headers:{'Content-Type':'application/json', 'X-CSRFToken':csrf ? csrf.content : ''},
            body:body === undefined ? undefined : JSON.stringify(body)});
        if (r.redirected) throw new Error('Votre session a expiré. Rechargez la page.');
        let d;
        try { d = await r.json(); } catch (_) { throw new Error('Réponse indisponible. Actualisez les propositions.'); }
        if (!r.ok) { const e = new Error(d.error || 'L’action n’a pas abouti.'); e.status = r.status; throw e; }
        return d;
    }
    async function load(force, reveal) {
        if (busy || (edited() && !force)) {
            status.textContent = 'Une mise à jour est disponible. Enregistrez vos modifications puis actualisez les propositions.';
            return;
        }
        const turn = ++generation, previousEdits = edits;
        const previousIds = new Set(Array.from(list.querySelectorAll('.assistant-action'), n => n.id));
        const data = await api(base);
        if (turn !== generation || edits !== previousEdits) return;
        list.replaceChildren();
        data.actions.forEach(a => list.append(render(a)));
        if (!data.actions.length) list.append(el('p', 'Aucune proposition. Demandez un rendez-vous ou une tâche dans la conversation.', 'assistant-aide'));
        status.textContent = ''; controls();
        const added = data.actions.find(a => a.statut === 'attente' && !previousIds.has('action-' + a.id));
        if (reveal && added) document.getElementById('action-' + added.id).scrollIntoView({behavior:'smooth', block:'start'});
    }
    async function operation(a, suffix, method, body) {
        if (busy) return;
        busy = true; ++generation; error(''); status.textContent = 'Mise à jour de la proposition…'; controls();
        try {
            const d = await api(base + '/' + a.id + suffix, method, body);
            document.getElementById('action-' + a.id).replaceWith(render(d));
            status.textContent = d.statut === 'executee' ? 'Création enregistrée. Le lien ouvre votre planificateur.' : '';
        } catch (e) {
            error(e.message); status.textContent = '';
            if (e.status === 409) {
                try { const fresh = await api(base + '/' + a.id); document.getElementById('action-' + a.id).replaceWith(render(fresh)); }
                catch (_) { /* Le message initial reste affiché. */ }
            }
        } finally { busy = false; controls(); }
    }
    function option(select, value, label) { const o = el('option', label); o.value = value; select.append(o); }
    function field(parent, id, name, label, type, value, required) {
        const box = el('div'), l = el('label', label); l.htmlFor = id + '-' + name;
        const n = el(type === 'textarea' ? 'textarea' : type === 'select' ? 'select' : 'input');
        if (n.tagName === 'INPUT') n.type = type;
        n.name = name; n.id = l.htmlFor; n.required = !!required;
        if (type === 'checkbox') n.checked = !!value;
        else if (type !== 'select') n.value = value == null ? '' : value;
        if (type === 'number') { n.min = '5'; n.max = '1440'; n.step = '1'; }
        if (type === 'text' || type === 'textarea') n.maxLength = type === 'text' ? 200 : 2000;
        box.append(l, n); parent.append(box); return n;
    }
    function render(a) {
        const card = el('article', undefined, 'assistant-action'); card.id = 'action-' + a.id;
        const c = a.champs;
        card.append(el('h3', (c.type === 'evenement' ? 'Rendez-vous' : 'Tâche') + ' · ' + (c.titre || 'À compléter')),
                    el('p', labels[a.statut], 'assistant-aide'));
        if (a.statut !== 'attente') {
            if (a.resultat.lien) {
                card.append(el('p', a.resultat.existe ? (a.resultat.non_placee
                    ? 'Tâche créée mais aucun placement complet n’a été trouvé. Consultez le planificateur.'
                    : 'L’élément est créé dans votre planificateur.') : 'L’élément a été créé puis retiré du planificateur. Il ne sera pas recréé automatiquement.'));
                const link = el('a', 'Ouvrir mon planificateur', 'btn btn-secondary btn-sm');
                const url = new URL(a.resultat.lien, location.origin);
                if (url.origin === location.origin && a.resultat.lien.startsWith('/') && !a.resultat.lien.startsWith('//')) {
                    link.href = a.resultat.lien; card.append(link);
                }
            }
            if (a.statut === 'expiree') card.append(el('p', 'Préparez une nouvelle proposition pour relire des informations actuelles.'));
            return card;
        }
        if (a.precision) card.append(el('p', a.precision, 'assistant-notice'));
        a.conflits.forEach(v => card.append(el('p', 'Un créneau est déjà occupé le ' + v.date + ' de ' + v.debut + ' à ' + v.fin + '. Vérifiez ce chevauchement.', 'assistant-notice')));
        const form = el('form'); form.autocomplete = 'off';
        const fields = el('div', undefined, 'assistant-champs');
        field(fields, a.id, 'titre', 'Titre', 'text', c.titre, true);
        field(fields, a.id, 'description', 'Description ou lieu', 'textarea', c.description, false);
        if (c.type === 'evenement') {
            field(fields, a.id, 'date_fixe', 'Date du rendez-vous', 'date', c.date_fixe, true);
            field(fields, a.id, 'heure_debut', 'Heure de début', 'time', c.heure_debut, true);
            field(fields, a.id, 'heure_fin', 'Heure de fin', 'time', c.heure_fin, true);
        } else {
            field(fields, a.id, 'duree_min', 'Durée estimée (minutes)', 'number', c.duree_min, true);
            field(fields, a.id, 'deadline', 'Échéance facultative', 'date', c.deadline, false);
            const pref = field(fields, a.id, 'preference', 'Préférence de placement', 'select');
            [['aucune','Aucune'],['matin','Matin'],['apres_midi','Après-midi']].forEach(([v,l]) => option(pref,v,l)); pref.value = c.preference;
            field(fields, a.id, 'secable', 'Tâche fractionnable', 'checkbox', c.secable);
            field(fields, a.id, 'duree_min_bloc', 'Durée minimale d’un bloc (minutes)', 'number', c.duree_min_bloc, true);
        }
        fields.addEventListener('input', () => { form.dataset.modifie = '1'; form.dataset.edite = '1'; ++edits; controls(); });
        fields.addEventListener('change', () => { form.dataset.modifie = '1'; form.dataset.edite = '1'; ++edits; controls(); });
        form.append(fields);
        const read = () => {
            const v = {type:c.type};
            fields.querySelectorAll('input,select,textarea').forEach(n => {
                v[n.name] = n.type === 'checkbox' ? n.checked : n.type === 'number' ? (n.value ? Number(n.value) : null) : n.value || null;
            });
            return v;
        };
        const save = button('Enregistrer les modifications', () => operation(a, '', 'PUT', {revision:a.revision, champs:read()}));
        form.append(save, el('p', 'Enregistrez vos modifications avant de confirmer la carte actualisée.', 'assistant-aide'));
        const comparisons = [];
        if (c.type === 'tache') {
            const box = el('fieldset'); box.append(el('legend', 'Situer la priorité de cette tâche'));
            if (!a.references.length) box.append(el('p', 'Première tâche en cours : priorité initiale, sans comparaison.'));
            a.references.forEach(r => {
                const s = field(box, a.id, 'reference-' + r.id, 'Par rapport à « ' + r.titre + ' »', 'select', null, true);
                option(s, '', 'Choisir…');
                [['inferieur','Moins prioritaire'],['egal','Au même niveau'],['superieur','Plus prioritaire']].forEach(([v,l]) => option(s,v,l));
                s.addEventListener('change', () => { form.dataset.edite = '1'; ++edits; });
                comparisons.push(() => ({tache_id:r.id, reponse:s.value}));
            });
            form.append(box, el('p', 'Le moteur cherche des créneaux libres sans déplacer vos autres éléments. Utilisez « Replanifier » dans le planificateur pour une réorganisation globale.', 'assistant-aide'));
        } else form.append(el('p', 'Ce rendez-vous fixe sera ajouté à la date et aux horaires affichés, sans déplacer vos autres éléments.', 'assistant-aide'));
        let duplicate = null;
        if (a.similaires.length) {
            form.append(el('p', 'Un élément correspondant existe déjà : ' + a.similaires.map(s => s.titre).join(', ') + '.', 'assistant-notice'));
            duplicate = field(form, a.id, 'distinct', 'Je confirme vouloir créer un élément distinct malgré cette correspondance', 'checkbox', false, true);
        }
        const actions = el('div', undefined, 'assistant-exemples');
        const confirm = el('button', 'Confirmer la création', 'btn btn-primary btn-sm'); confirm.type = 'submit'; confirm.dataset.confirmer = '1';
        actions.append(confirm, button('Abandonner la proposition', () => operation(a, '/abandonner', 'POST', {revision:a.revision})));
        form.append(actions);
        form.addEventListener('submit', e => {
            e.preventDefault();
            if (form.dataset.modifie === '1') { error('Enregistrez les modifications avant de confirmer.'); return; }
            operation(a, '/confirmer', 'POST', {revision:a.revision,
                comparaisons:comparisons.map(f => f()), accepter_doublon:!!(duplicate && duplicate.checked)});
        });
        card.append(form); return card;
    }
    root.addEventListener('assistant:actions', () => { load(false, true).catch(e => error(e.message)); });
    document.getElementById('assistantActionsActualiser').addEventListener('click', () => {
        if (edited() && !confirm('Actualiser les propositions et remplacer les réponses non enregistrées ?')) return;
        load(true).catch(e => error(e.message));
    });
    load().catch(e => error(e.message));
})();
