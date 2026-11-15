(function () {
    'use strict';
    const root = document.getElementById('assistantPage');
    if (!root || !root.querySelector('#assistantForm')) return;
    const byId = id => root.querySelector('#' + id);
    let state = null, busy = false, mutating = false, editing = null, generation = 0;
    const model = byId('assistantModele');
    const question = byId('assistantQuestion');
    const csrf = document.querySelector('meta[name="csrf-token"]');

    async function api(url, method, body) {
        const response = await fetch(url, {
            method: method || 'GET', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf ? csrf.content : ''},
            body: body === undefined ? undefined : JSON.stringify(body)
        });
        if (response.redirected) throw new Error('Votre session a expiré. Rechargez la page.');
        let data;
        try { data = await response.json(); }
        catch (_) { throw new Error('La réponse est indisponible. Rechargez la page.'); }
        if (!response.ok) throw new Error(data.error || 'La demande a échoué. Réessayez.');
        return data;
    }
    function error(message) {
        byId('assistantErreur').hidden = !message;
        byId('assistantErreur').textContent = message || '';
    }
    function controls() {
        const locked = busy || mutating || !state || state.en_cours || !model;
        byId('assistantEnvoyer').disabled = !!locked;
        question.disabled = !!locked;
        if (model) model.disabled = busy || mutating;
        root.querySelectorAll('#assistantMemoireForm button, #assistantMemoires button, #assistantNouveau, #assistantToutOublier')
            .forEach(el => { el.disabled = mutating || !state; });
        byId('assistantActualiser').disabled = busy || mutating;
        byId('assistantStatut').textContent = mutating ? 'Mise à jour de votre espace…' : busy || (state && state.en_cours)
            ? 'Préparation de la réponse… Vous pouvez actualiser ou recommencer une conversation.'
            : state ? state.restant + ' demande(s) disponible(s) aujourd’hui · 30 maximum' : 'Chargement de votre espace…';
    }
    function button(label, onClick) {
        const el = document.createElement('button');
        el.type = 'button'; el.className = 'btn btn-secondary btn-sm';
        el.textContent = label; el.addEventListener('click', onClick); return el;
    }
    function render(data) {
        state = data;
        byId('assistantNotice').textContent = data.notice || '';
        byId('assistantNotice').hidden = !data.notice;
        const messages = byId('assistantMessages');
        messages.replaceChildren();
        data.messages.forEach(message => {
            const article = document.createElement('article'); article.className = 'assistant-message';
            const role = document.createElement('strong'); role.textContent = message.role === 'user' ? 'Vous' : 'Assistant';
            const text = document.createElement('p'); text.textContent = message.texte;
            article.append(role, text);
            if (message.sources && message.sources.length) {
                const sources = document.createElement('div'); sources.className = 'assistant-sources';
                message.sources.forEach(source => {
                    // Les sources sont produites par les outils du serveur.
                    // Vérification supplémentaire côté navigateur pour les liens.
                    const url = new URL(source.url, location.origin);
                    if (url.origin !== location.origin || !source.url.startsWith('/') || source.url.startsWith('//')) return;
                    const link = document.createElement('a'); link.className = 'btn btn-secondary btn-sm';
                    link.href = source.url; link.textContent = source.id + ' · ' + source.titre;
                    sources.appendChild(link);
                });
                article.appendChild(sources);
            }
            messages.appendChild(article);
        });
        byId('assistantVide').hidden = data.messages.length > 0;
        byId('assistantResume').textContent = data.resume || 'Aucun résumé pour le moment.';
        byId('assistantMemoireCompteur').textContent = data.memoires.length + ' / 30';
        const memories = byId('assistantMemoires'); memories.replaceChildren();
        data.memoires.forEach(note => {
            const article = document.createElement('div'); article.className = 'assistant-souvenir';
            const text = document.createElement('p'); text.textContent = note.texte;
            const label = document.createElement('small');
            label.textContent = note.categorie === 'preference' ? 'Préférence personnelle' : 'Sujet suivi · jusqu’au ' + new Date(note.expire_le * 1000).toLocaleDateString('fr-FR');
            const actions = document.createElement('div'); actions.className = 'assistant-exemples';
            actions.append(button('Modifier', () => {
                editing = note.id;
                byId('assistantMemoireEdition').textContent = 'Modifier ce souvenir';
                byId('assistantMemoireTexte').value = note.texte;
                byId('assistantMemoireCategorie').value = note.categorie;
                byId('assistantMemoireAnnuler').hidden = false;
                byId('assistantMemoireTexte').focus();
            }), button('Oublier', async () => {
                if (!confirm('Oublier ce souvenir et réinitialiser le dialogue qui pourrait le contenir ?')) return;
                await mutation(root.dataset.memoires + '/' + note.id, 'DELETE');
            }));
            article.append(text, label, actions); memories.appendChild(article);
        });
        controls();
    }
    function cancelEdit() {
        editing = null; byId('assistantMemoireForm').reset();
        byId('assistantMemoireEdition').textContent = 'Ajouter un souvenir';
        byId('assistantMemoireAnnuler').hidden = true;
    }
    async function mutation(url, method, body) {
        if (mutating) return;
        const operation = ++generation;
        mutating = true; busy = false; error(''); controls();
        try {
            const data = await api(url, method, body);
            if (operation !== generation) return;
            render(data); cancelEdit();
        } catch (e) { if (operation === generation) error(e.message); }
        finally { mutating = false; controls(); }
    }
    function requestId() {
        if (crypto.randomUUID) return crypto.randomUUID();
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
        const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
        return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) + '-' + hex.slice(16, 20) + '-' + hex.slice(20);
    }
    byId('assistantForm').addEventListener('submit', async e => {
        e.preventDefault();
        if (busy || mutating || !model || !question.value.trim()) return;
        const message = question.value.trim(), turn = ++generation;
        busy = true; error(''); controls();
        try {
            const data = await api(root.dataset.message, 'POST', {message, model: model.value, request_id: requestId()});
            if (turn !== generation) return;
            question.value = ''; render(data);
        } catch (err) { if (turn === generation) error(err.message); }
        finally { if (turn === generation) { busy = false; controls(); if (!question.disabled) question.focus(); } }
    });
    byId('assistantMemoireForm').addEventListener('submit', async e => {
        e.preventDefault();
        const text = byId('assistantMemoireTexte').value.trim();
        if (!text) return;
        await mutation(root.dataset.memoires + (editing ? '/' + editing : ''), editing ? 'PUT' : 'POST',
                       {texte: text, categorie: byId('assistantMemoireCategorie').value});
    });
    byId('assistantMemoireAnnuler').addEventListener('click', cancelEdit);
    byId('assistantNouveau').addEventListener('click', async () => {
        if (!confirm('Recommencer la conversation ? Vos souvenirs personnels seront conservés.')) return;
        await mutation(root.dataset.oublier, 'POST', {tout: false});
    });
    byId('assistantToutOublier').addEventListener('click', async () => {
        if (!confirm('Effacer toute la conversation et tous vos souvenirs ? Une réponse en cours sera annulée.')) return;
        await mutation(root.dataset.oublier, 'POST', {tout: true});
    });
    byId('assistantActualiser').addEventListener('click', async () => {
        if (busy) return;
        error(''); try { render(await api(root.dataset.etat)); } catch (e) { error(e.message); }
    });
    root.querySelectorAll('[data-assistant-question]').forEach(el => el.addEventListener('click', () => {
        if (question.disabled) return;
        question.value = el.dataset.assistantQuestion; question.focus();
    }));
    controls();
    api(root.dataset.etat).then(render).catch(e => error(e.message));
})();
