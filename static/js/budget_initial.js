/* Construction de l'initial : aucune formule métier n'est calculée ici. */
(() => {
    'use strict';
    const root = document.getElementById('initial-app');
    if (!root) return;
    const $ = id => document.getElementById(id);
    const months = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'];
    let state, editing = null, busy = false, dirty = false, hypothesesDirty = false;
    const amount = v => v === null || v === undefined ? 'À compléter' : Number(v).toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' €';
    function element(tag, text, cls) {
        const el = document.createElement(tag);
        if (text !== undefined) el.textContent = text;
        if (cls) el.className = cls;
        return el;
    }
    function status(message, error = false) {
        $('bi-status').textContent = message;
        $('bi-status').className = error ? 'bi-error' : '';
    }
    function input(parent, key, label, value = '', options = null, type = 'text') {
        const wrap = element('label', undefined, 'form-group');
        wrap.append(element('span', label));
        const field = element(options ? 'select' : type === 'textarea' ? 'textarea' : 'input');
        field.id = 'bi-f-' + key;
        if (options) options.forEach(([v, t]) => { const opt = element('option', t); opt.value = v; field.append(opt); });
        else if (type !== 'textarea') field.type = type;
        if (type === 'checkbox') field.checked = value === true;
        else field.value = value ?? '';
        if (type === 'text') field.maxLength = 4000;
        wrap.append(field); parent.append(wrap);
        return field;
    }
    function get(key) { const el = $('bi-f-' + key); return el.type === 'checkbox' ? el.checked : el.value; }
    function monthInputs(id, key, values, fallback = '') {
        $(id).replaceChildren();
        months.forEach((m, i) => { const f = input($(id), key + i, m, values?.[i] ?? fallback); f.inputMode = 'decimal'; });
    }
    const monthValues = key => months.map((_, i) => get(key + i));
    function reference(id, prefix, r = {}) {
        $(id).replaceChildren();
        [['source', 'Source du taux'], ['annee', 'Année complète de référence'], ['assiette', 'Assiette et méthode'], ['perimetre', 'Périmètre comparable'], ['verification', 'Date de vérification']].forEach(([k, label]) => input($(id), prefix + k, label, r[k] ?? (k === 'annee' ? '2025' : ''), null, k === 'verification' ? 'date' : 'text'));
        input($(id), prefix + 'complete_comparable', 'Je confirme une année complète et un périmètre comparable', r.complete_comparable, null, 'checkbox');
        if (prefix === 'ref-') {
            input($(id), prefix + 'numerateur', 'Montant annuel du compte de référence', r.numerateur);
            input($(id), prefix + 'denominateur', 'Brut global annuel de référence (somme des 641)', r.denominateur);
        }
    }
    function readReference(prefix) {
        const r = {};
        ['source', 'annee', 'assiette', 'perimetre', 'verification', 'complete_comparable'].forEach(k => { r[k] = get(prefix + k); });
        if (prefix === 'ref-') ['numerateur', 'denominateur'].forEach(k => { r[k] = get(prefix + k); });
        return r;
    }
    let complementCounter = 0;
    function complement(c = {}) {
        const key = 'comp-' + complementCounter++ + '-';
        const block = element('fieldset'); block.dataset.key = key;
        block.append(element('legend', 'Complément 641'));
        const fields = element('div', undefined, 'bi-grid'); block.append(fields);
        input(fields, key + 'libelle', 'Prime ou complément (nom unique)', c.libelle);
        input(fields, key + 'compte', 'Autre compte 641', c.compte);
        const ms = element('div', undefined, 'bi-months'); block.append(ms);
        months.forEach((m, i) => input(ms, key + i, m, c.mois?.[i]));
        const remove = element('button', 'Retirer ce complément', 'btn btn-secondary btn-sm'); remove.type = 'button';
        remove.addEventListener('click', () => { block.remove(); dirty = true; }); block.append(remove);
        $('bi-complements').append(block);
    }
    function visibility() {
        const salary = get('nature') === 'salaire';
        $('bi-salary').hidden = !salary; $('bi-other').hidden = salary;
        ['brut', 'alisfa', 'cee'].forEach(k => { $('bi-' + k).hidden = get('base') !== k; });
        $('bi-activity').hidden = get('base') === 'cee';
        $('bi-manual').hidden = get('mode') !== 'manuel';
        $('bi-monthly').hidden = get('mode') !== 'mensuel';
        $('bi-proportional').hidden = get('mode') !== 'proportionnel';
    }
    function edit(line = null) {
        if (!state) return;
        if (hypothesesDirty) { status('Enregistrez ou annulez les hypothèses modifiées avant de modifier une ligne.', true); return; }
        if (busy || (dirty && !window.confirm('Abandonner les modifications non enregistrées ?'))) return;
        editing = line?.id || null;
        const d = line?.donnees || {};
        ['bi-common', 'bi-salary-fields', 'bi-brut-fields', 'bi-alisfa-fields', 'bi-cee-fields', 'bi-other-fields', 'bi-secteurs', 'bi-rate', 'bi-notes', 'bi-complements'].forEach(id => $(id).replaceChildren());
        input($('bi-common'), 'libelle', 'Salarié, poste ou libellé', d.libelle);
        input($('bi-common'), 'nature', 'Nature', d.nature || 'salaire', [['salaire','Salarié ou poste'],['depense','Dépense / charge'],['financement','Financement']]);
        input($('bi-common'), 'compte', 'Compte général (premier 641 pour le brut de base)', d.compte);
        Object.entries(state.secteurs).forEach(([id, name]) => input($('bi-secteurs'), 'secteur-' + id, name + ' (%)', d.secteurs?.[id] ?? (Object.keys(state.secteurs).length === 1 ? '100' : '')));
        input($('bi-salary-fields'), 'poste', 'Poste', d.poste || 'occupe', [['occupe','Occupé'],['vacant','Vacant']]);
        input($('bi-salary-fields'), 'salarie_id', 'Salarié facultatif', d.salarie_id || '',
            [['','Poste identifié sans référence salarié'], ...(state.salaries || []).map(s=>[String(s.id),s.prenom+' '+s.nom+(s.actif?'':' (inactif)')])]);
        input($('bi-salary-fields'), 'contrat', 'Activité normale', d.contrat || 'permanent', [['permanent','Permanent · 12 mois'],['saisonnier','Saisonnier'],['cee','CEE']]);
        input($('bi-salary-fields'), 'quotite', 'Quotité (%)', d.quotite);
        input($('bi-salary-fields'), 'base', 'Seule base de rémunération active', d.base || 'brut', [['brut','Brut mensuel vérifié'],['alisfa','Base ALISFA explicable'],['cee','Forfait CEE journalier']]);
        input($('bi-brut-fields'), 'brut_mensuel', 'Brut mensuel de base à la quotité saisie', d.brut_mensuel);
        input($('bi-brut-fields'), 'brut_verifie', 'Brut vérifié, hors compléments ci-dessous', d.brut_verifie, null, 'checkbox');
        [['socle','Socle annuel'],['point','Valeur du point'],['pesee','Pesée'],['anciennete','Points ancienneté'],['competence','Points compétences'],['maintien','Maintien mensuel']].forEach(([k,l]) => input($('bi-alisfa-fields'), k, l, d[k]));
        input($('bi-cee-fields'), 'forfait_cee', 'Forfait CEE par jour', d.forfait_cee);
        monthInputs('bi-cee-months', 'jours-', d.jours_cee);
        monthInputs('bi-activity-months', 'activite-', d.activite, '1');
        (d.complements || []).forEach(complement);
        input($('bi-rate'), 'taux_charges', 'Taux individuel (%)', d.taux_charges);
        reference('bi-rate-reference', 'taux-ref-', d.reference_charges || {});
        input($('bi-other-fields'), 'mode', 'Méthode', d.mode || 'manuel', [['manuel','Montant annuel manuel'],['mensuel','Projection mensuelle'],['proportionnel','Proportionnel au brut global']]);
        input($('bi-other-fields'), 'annuel', 'Montant annuel manuel', d.annuel);
        monthInputs('bi-weights', 'poids-', d.poids, '1');
        monthInputs('bi-monthly-fields', 'mois-', d.mois);
        reference('bi-reference', 'ref-', d.reference || {});
        input($('bi-notes'), 'source', 'Source / document de référence', d.source, null, 'textarea');
        input($('bi-notes'), 'note', 'Justification, période et hypothèses de la ligne', d.note, null, 'textarea');
        input($('bi-notes'), 'a_revoir', 'Ligne à revoir', d.a_revoir, null, 'checkbox');
        ['nature', 'base', 'mode'].forEach(k => $('bi-f-' + k).addEventListener('change', visibility));
        visibility(); dirty = false; $('bi-editor').hidden = false;
        $('bi-editor-title').textContent = editing ? 'Modifier · ' + editing : 'Nouvelle ligne';
        $('bi-f-libelle').focus();
    }
    function readLine() {
        const d = {};
        ['libelle','nature','compte','source','note','a_revoir','mode','annuel','poste','contrat','base','brut_mensuel','brut_verifie','quotite','socle','point','pesee','anciennete','competence','maintien','forfait_cee','taux_charges','salarie_id'].forEach(k => { d[k] = get(k); });
        d.secteurs = {};
        Object.keys(state.secteurs).forEach(id => { const value = get('secteur-' + id); if (value && Number(value.replace(',','.')) !== 0) d.secteurs[id] = value; });
        d.activite = monthValues('activite-'); d.jours_cee = monthValues('jours-'); d.poids = monthValues('poids-'); d.mois = monthValues('mois-');
        d.reference = readReference('ref-'); d.reference_charges = readReference('taux-ref-');
        d.complements = [...$('bi-complements').children].map(b => ({libelle:get(b.dataset.key+'libelle'),compte:get(b.dataset.key+'compte'),mois:monthValues(b.dataset.key)}));
        return {id:editing, donnees:d};
    }
    function row(body, values) { const tr = element('tr'); values.forEach(v => { const td = element('td'); td.append(typeof v === 'string' ? document.createTextNode(v) : v); tr.append(td); }); body.append(tr); }
    function monthlyTable(title, values) {
        const box = element('div'); box.append(element('h3', title));
        const scroll = element('div', undefined, 'bi-scroll'), table = element('table', undefined, 'bi-monthly-table'), head = element('thead'), tr = element('tr');
        ['Nature', ...months, 'Année'].forEach(t => tr.append(element('th',t))); head.append(tr); table.append(head);
        const body = element('tbody');
        [['charges','Charges'],['produits','Produits'],['resultat','Résultat']].forEach(([key,label]) => row(body,[label,...values[key].map(amount),amount(values[key+'_annuel'])]));
        table.append(body); scroll.append(table); box.append(scroll); return box;
    }
    function render() {
        $('bi-note').value = state.hypotheses.note; $('bi-taux').checked = state.hypotheses.taux_individuels;
        $('bi-modification').textContent = state.updated_at ? 'Dernière modification : ' + state.updated_at + ' (UTC).' : 'Aucune construction enregistrée pour cette année.';
        $('bi-lines').replaceChildren();
        state.lignes.forEach(l => {
            const label = element('span',l.donnees.libelle); label.append(element('small',l.id,'bi-id'));
            if (l.updated_at) label.append(element('small','Modifiée le '+l.updated_at+' (UTC)','bi-id'));
            const actions = element('div',undefined,'bi-toolbar');
            const button = element('button','Modifier','btn btn-secondary btn-sm'); button.type='button'; button.addEventListener('click',()=>edit(l)); actions.append(button);
            const remove = element('button','Supprimer','btn btn-secondary btn-sm'); remove.type='button';
            remove.addEventListener('click',()=>{if(dirty||hypothesesDirty){status('Enregistrez ou annulez les saisies en cours avant de supprimer une ligne.',true);return;}if (!busy && window.confirm('Supprimer cette ligne de construction ? Les budgets déjà reportés restent inchangés jusqu’au prochain report contrôlé.')) save('supprimer',l.id);}); actions.append(remove);
            row($('bi-lines'),[label,l.donnees.nature,l.donnees.compte,actions]);
        });
        if (!state.lignes.length) row($('bi-lines'),['Aucune ligne. Ajoutez un salarié, un poste ou une dépense.','','','']);
        $('bi-alerts').replaceChildren();
        state.calcul.alertes.forEach(a=>$('bi-alerts').append(element('li',a.libelle+' : '+a.message)));
        if (!state.calcul.alertes.length) $('bi-alerts').append(element('li',state.lignes.length ? 'Construction complète. Contrôlez les totaux et le rapprochement ci-dessous.' : 'La construction est vide.'));
        $('bi-totals').replaceChildren(monthlyTable('Budget général',state.calcul.general));
        Object.entries(state.calcul.secteurs).forEach(([id,v])=>$('bi-totals').append(monthlyTable(state.secteurs[id],v)));
        $('bi-calculations').replaceChildren();
        state.calcul.lignes.forEach(l=>{ const detail=element('details'); detail.append(element('summary',l.libelle+' · '+l.compte+' · '+amount(l.total))); detail.append(element('p',l.explication)); detail.append(element('p','Source : '+l.source+' · Justification : '+l.note)); const vals=element('p',months.map((m,i)=>m+' : '+amount(l.mois[i])).join(' · ')); detail.append(vals); $('bi-calculations').append(detail); });
        $('bi-reports').replaceChildren();
        state.reports.forEach(p=>row($('bi-reports'),[(state.secteurs[p.secteur_id]||'Secteur supprimé')+' · '+p.compte,amount(p.avant),amount(p.montant),p.motif||(p.retire?'Ancien report retiré : remise à zéro proposée.':'Report autorisé.')]));
        $('bi-report').disabled = !state.calcul.complet || !state.reports.some(p=>p.possible);
    }
    async function load() {
        const r = await fetch(root.dataset.lecture+'?annee='+root.dataset.annee);
        if (!r.ok) { const d=await r.json(); throw new Error(d.error || 'Chargement impossible.'); }
        state = await r.json(); render();
    }
    async function mutate(url, payload) {
        if (busy || !state) return false;
        busy = true; root.setAttribute('aria-busy','true');
        const controls=[...root.querySelectorAll('button,input,textarea,select')];
        const disabled=controls.map(c=>c.disabled); controls.forEach(c=>{c.disabled=true;});
        try {
            const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({annee:Number(root.dataset.annee),revision:state.revision,...payload})});
            const data=await r.json(); if (!r.ok) throw new Error(data.error || 'Enregistrement refusé.');
            await load(); status(data.reportes !== undefined ? data.reportes+' compte(s) reporté(s). Vérifiez les comptes conservés avant le PDF.' : 'Enregistré et recalculé.'); return true;
        } catch(e) { status(e.message || 'Échec de connexion. Vos saisies restent affichées ; rechargez avant de réessayer.',true); return false; }
        finally { busy=false; root.removeAttribute('aria-busy'); controls.forEach((c,i)=>{if(c.isConnected)c.disabled=disabled[i];}); if(state)$('bi-report').disabled=!state.calcul.complet||!state.reports.some(p=>p.possible); }
    }
    async function save(action,value) { const ok=await mutate(root.dataset.sauvegarde,{action,[action]:value}); if(ok){dirty=false;hypothesesDirty=false;$('bi-editor').hidden=true;} }
    $('bi-hypotheses').addEventListener('input',()=>{hypothesesDirty=true;});
    $('bi-cancel-hypotheses').addEventListener('click',()=>{if(!state)return;$('bi-note').value=state.hypotheses.note;$('bi-taux').checked=state.hypotheses.taux_individuels;hypothesesDirty=false;});
    $('bi-editor').addEventListener('input',()=>{dirty=true;});
    $('bi-editor').addEventListener('submit',e=>{e.preventDefault();save('ligne',readLine());});
    $('bi-hypotheses').addEventListener('submit',e=>{e.preventDefault();if(dirty){status('Enregistrez ou annulez la ligne en cours avant les hypothèses.',true);return;} save('hypotheses',{note:$('bi-note').value,taux_individuels:$('bi-taux').checked});});
    $('bi-new').addEventListener('click',()=>edit());
    $('bi-cancel').addEventListener('click',()=>{dirty=false;$('bi-editor').hidden=true;});
    $('bi-add-complement').addEventListener('click',()=>{complement();dirty=true;});
    $('bi-report').addEventListener('click',()=>{if(dirty||hypothesesDirty){status('Enregistrez ou annulez les saisies en cours avant le report.',true);return;}if(window.confirm('Reporter les comptes autorisés selon le rapprochement affiché ? Les autres comptes resteront inchangés.'))mutate(root.dataset.report,{reference_report:state.reference_report});});
    window.addEventListener('beforeunload',e=>{if(dirty||hypothesesDirty){e.preventDefault();e.returnValue='';}});
    load().then(()=>status('Construction chargée.')).catch(e=>status(e.message,true));
})();
