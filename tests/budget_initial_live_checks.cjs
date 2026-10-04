/* Recette Chromium avec vrai Flask/SQLite, connexion et CSRF actifs.
 * PYTHON=/tmp/cs-pilot-venv/bin/python node tests/budget_initial_live_checks.cjs
 * Aucune API simulée ; aucune requête externe autorisée par ce harnais.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'budget-initial-live-captures-'));

(async () => {
    const server = spawn(process.env.PYTHON || 'python', ['tests/budget_initial_live_server.py'], {cwd: root});
    let serverError = '';
    server.stderr.on('data', chunk => {serverError = (serverError + chunk).slice(-4000);});
    let browser;
    try {
        const base = await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('Démarrage Flask trop long')), 30000);
            let buffer = '';
            server.stdout.on('data', chunk => {
                buffer += chunk;
                const found = buffer.match(/RECETTE_URL=(http:\/\/127\.0\.0\.1:\d+)/);
                if (found) {clearTimeout(timer); resolve(found[1]);}
            });
            server.once('exit', code => {clearTimeout(timer); reject(new Error('Flask arrêté : ' + code + '\n' + serverError));});
        });
        browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium'});
        for (const [name, width, height, year] of [['desktop',1440,1000,2027], ['mobile',390,844,2028]]) {
            const context = await browser.newContext({viewport:{width,height}});
            await context.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());
            const page = await context.newPage();
            const errors = [];
            page.on('pageerror', error => errors.push(error.message));
            let dismissNextDialog = false;
            page.on('dialog', dialog => {
                if (dismissNextDialog) { dismissNextDialog = false; return dialog.dismiss(); }
                return dialog.accept();
            });
            await page.goto(base + '/login');
            await page.locator('#login').fill('recette');
            await page.locator('#password').fill('Recette-locale-2026!');
            await page.locator('button[type=submit]').click();
            await page.waitForURL(url => !url.pathname.endsWith('/login'));
            // Chaque largeur repart du flux, même après la préférence classique
            // enregistrée pendant le parcours précédent du même compte de test.
            assert.ok(await page.evaluate(async () => {
                const response = await fetch('/api/interface/basculer', {
                    method:'POST', headers:{'Content-Type':'application/json',
                        'X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},
                    body:JSON.stringify({actif:true})});
                return response.ok && (await response.json()).actif;
            }));
            // Charges et produits déjà vides : reprise explicite des anciens temporaires.
            const legacyYear = year - 3;
            await page.goto(base + '/budget-previsionnel?annee=' + legacyYear + '&secteur_id=1');
            await page.waitForFunction(() => !budgetFetching);
            await page.evaluate(async year => {
                const scope = {type_budget:'initial',annee:year,secteur_id:1};
                const send = async (action,data) => {
                    const response = await fetch('/api/budget-previsionnel/' + action, {method:'POST',
                        headers:{'Content-Type':'application/json'},body:JSON.stringify({...scope,...data})});
                    if (!response.ok) throw new Error(await response.text());
                };
                for (const compte_num of ['606100','706100']) await send('ajouter-compte',{compte_num});
                const state = await (await fetch('/api/budget-previsionnel/donnees?type_budget=initial&annee='+year+'&secteur_id=1')).json();
                await send('save-lines',{reference_budget:state.reference_budget,lignes:['606100','706100'].map(compte_num =>
                    ({compte_num,valeur_def:null,valeur_temp:1200,commentaire:'Note conservée'}))});
            }, legacyYear);
            await page.reload();
            for (const code of ['606100','706100']) {
                assert.equal(await page.locator('[data-bp-def-compte="'+code+'"]').inputValue(),'');
                await page.locator('[data-effacer-montant="'+code+'"]').click();
            }
            await page.locator('#budgetSaveSaisies').click();
            await page.waitForFunction(() => !budgetFetching && !budgetSaving && !Object.keys(budgetDirty).length);
            await page.reload();
            for (const code of ['606100','706100']) {
                await page.locator('[data-bp-comment-compte="'+code+'"]').fill('Commentaire après effacement et rechargement');
            }
            await page.locator('#budgetSaveSaisies').click();
            await page.waitForFunction(() => !budgetFetching && !budgetSaving && !Object.keys(budgetDirty).length);
            await page.screenshot({path:path.join(output,name+'-effacer-comptes.png'),fullPage:true});
            assert.ok(await page.evaluate(async year => {
                const state = () => fetch('/api/budget-initial-detaille?annee='+year).then(r=>r.json());
                for (const code of ['606100','706100']) {
                    const d = await state();
                    const response = await fetch('/api/budget-initial-detaille/enregistrer',{method:'POST',
                        headers:{'Content-Type':'application/json'},body:JSON.stringify({annee:year,revision:d.revision,
                        action:'ligne',ligne:{donnees:{libelle:'Compte fictif',nature:code[0]==='6'?'depense':'financement',
                        compte:code,secteurs:{'1':'100'},mode:'manuel',annuel:'1200'}}})});
                    if (!response.ok) return false;
                }
                const d = await state();
                if (!d.reports.every(r=>r.possible)) return false;
                const response = await fetch('/api/budget-initial-detaille/reporter',{method:'POST',
                    headers:{'Content-Type':'application/json'},body:JSON.stringify({annee:year,revision:d.revision,reference_report:d.reference_report})});
                return response.ok && (await response.json()).reportes===2;
            },legacyYear));
            // Vraie simulation puis effacement UI : la simulation reste jusqu'à l'abandon confirmé.
            await page.goto(base + '/budget-previsionnel?annee=' + year + '&secteur_id=1');
            await page.waitForFunction(() => !budgetFetching);
            await page.evaluate(async year => {
                const scope = {type_budget:'initial',annee:year,secteur_id:1};
                const send = async (action,data) => {
                    const response = await fetch('/api/budget-previsionnel/' + action, {
                        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...scope,...data})});
                    if (!response.ok) throw new Error(await response.text());
                };
                await send('ajouter-compte',{compte_num:'641100'});
                const state = await (await fetch('/api/budget-previsionnel/donnees?type_budget=initial&annee='+year+'&secteur_id=1')).json();
                await send('paie-simulation',{compte_num:'641100',reference_budget:state.reference_budget,
                    donnees:{salaire_socle:24000,ajouts:[{type:'cdi',pesee:100}]}});
            }, year);
            await page.reload();
            const amountInput = page.locator('[data-bp-def-compte="641100"]');
            await amountInput.waitFor();
            await amountInput.fill('');
            await page.locator('#budgetSaveSaisies').click();
            await page.waitForFunction(() => !budgetFetching && !budgetSaving && !Object.keys(budgetDirty).length);
            assert.equal(await amountInput.inputValue(), '');
            assert.equal(await amountInput.getAttribute('placeholder'), 'Non renseigné');
            const simUrl = base + '/api/budget-previsionnel/paie-simulation?type_budget=initial&annee='+year+'&secteur_id=1';
            assert.equal((await (await context.request.get(simUrl)).json()).found,true);
            await page.reload();
            await page.locator('[data-bp-comment-compte="641100"]').fill('Commentaire paie après effacement');
            await page.locator('#budgetSaveSaisies').click();
            await page.waitForFunction(() => !budgetFetching && !budgetSaving && !Object.keys(budgetDirty).length);
            await page.locator('[data-paie-compte="641100"]').click();
            await page.locator('#paieAbandonner').waitFor();
            await page.screenshot({path:path.join(output,name+'-abandon.png'),fullPage:true});
            dismissNextDialog = true;
            await page.locator('#paieAbandonner').click();
            assert.equal((await (await context.request.get(simUrl)).json()).found,true);
            // Appels rapprochés : la garde empêche une deuxième requête pendant l'abandon.
            let abandons = 0;
            page.on('request', request => {if(request.url().endsWith('/paie-simulation/abandonner')) abandons++;});
            await page.evaluate(() => { abandonnerPaieSimulator(); abandonnerPaieSimulator(); });
            await page.waitForFunction(() => !paieSim && !budgetFetching);
            assert.equal(abandons,1);
            assert.equal((await (await context.request.get(simUrl)).json()).found,false);
            await page.goto(base + '/budget-initial-detaille?annee=' + year);
            await page.getByText('Construction chargée.', {exact:true}).waitFor();
            assert.equal(await page.locator('#bi-report').isDisabled(), true);
            await page.screenshot({path:path.join(output,name+'-vide.png'),fullPage:true});
            await page.locator('#bi-new').focus();
            assert.equal(await page.locator('#bi-new').evaluate(el => el === document.activeElement), true);
            await page.locator('#bi-new').hover();
            await page.screenshot({path:path.join(output,name+'-focus.png')});
            await page.locator('#bi-new').click();
            await page.locator('#bi-f-libelle').fill('Poste vacant synthétique');
            await page.locator('#bi-f-compte').selectOption('641100');
            await page.locator('#bi-f-poste').selectOption('vacant');
            await page.locator('#bi-f-quotite').fill('100');
            await page.locator('#bi-editor button[type=submit]').click();
            await page.getByText('Enregistré et recalculé.', {exact:true}).waitFor();
            assert.equal(await page.locator('#bi-report').isDisabled(), true);
            assert.equal(await page.locator('#bi-note').inputValue(), '');
            const api = '/api/budget-initial-detaille?annee=' + year;
            const state = await (await context.request.get(base + api)).json();
            const id = state.lignes[0].id;
            await page.reload();
            await page.getByText('Construction chargée.', {exact:true}).waitFor();
            await page.locator('#bi-lines button').first().click();
            assert.equal(await page.locator('#bi-f-poste').inputValue(), 'vacant');
            await page.locator('#bi-f-libelle').fill('Poste vacant renommé');
            await page.locator('#bi-f-brut_mensuel').fill('1e-999999');
            await page.locator('#bi-editor button[type=submit]').click();
            await page.getByText('Nombre invalide ou hors limites.', {exact:true}).waitFor();
            assert.equal(await page.locator('#bi-f-brut_mensuel').inputValue(), '1e-999999');
            assert.equal((await (await context.request.get(base + api)).json()).revision, state.revision);
            await page.locator('#bi-f-brut_mensuel').fill('2000');
            await page.locator('#bi-f-brut_verifie').check();
            await page.locator('#bi-f-secteur-1').fill('99');
            await page.locator('#bi-editor button[type=submit]').click();
            await page.getByText('La ventilation sectorielle doit totaliser exactement 100 %.', {exact:true}).waitFor();
            assert.equal(await page.locator('#bi-f-brut_mensuel').inputValue(), '2000');
            await page.screenshot({path:path.join(output,name+'-erreur.png'),fullPage:true});
            assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Débordement global');
            await page.locator('#bi-f-secteur-1').fill('100');
            await page.locator('#bi-editor button[type=submit]').click();
            await page.getByText('Enregistré et recalculé.', {exact:true}).waitFor();
            const complete = await (await context.request.get(base + api)).json();
            assert.equal(complete.lignes[0].id, id);
            assert.equal(complete.calcul.general.charges_annuel, '24000');
            await page.locator('#bi-report').click();
            await page.getByText('1 compte(s) reporté(s). Vérifiez les comptes conservés avant le PDF.', {exact:true}).waitFor();
            await page.screenshot({path:path.join(output,name+'-report.png'),fullPage:true});
            const old = await (await context.request.get(base + '/api/budget-previsionnel/donnees?type_budget=initial&secteur_id=1&annee=' + year)).json();
            assert.equal(old.rows.find(row => row.compte_num === '641100').def, 24000);
            const actualise = await (await context.request.get(base + '/api/budget-previsionnel/donnees?type_budget=actualise&secteur_id=1&annee=2026')).json();
            assert.equal(actualise.rows.find(row => row.compte_num === '606100').def, 55.55);
            const pdf = await context.request.get(base + '/api/budget-previsionnel/export-pdf?type_budget=initial&secteur_id=1&annee=' + year);
            assert.equal(pdf.status(), 200);
            assert.ok((await pdf.body()).subarray(0,4).equals(Buffer.from('%PDF')));
            const switched = await page.evaluate(async () => {
                const response = await fetch('/api/interface/basculer', {
                    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({actif:false})});
                return response.ok;
            });
            assert.ok(switched);
            await page.reload();
            await page.getByText('Construction chargée.', {exact:true}).waitFor();
            assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
            await page.screenshot({path:path.join(output,name+'-classique.png'),fullPage:true});
            // Listes filtrées et copie ALISFA réelle, indépendante des ajustements RH.
            await page.locator('#bi-lines button').first().click();
            const codes = () => page.locator('#bi-f-compte option').evaluateAll(os => os.map(o => o.value).filter(Boolean));
            assert.deepEqual(await codes(), ['641100','641200']);
            await page.locator('#bi-f-nature').selectOption('depense');
            assert.deepEqual(await codes(), ['606100']);
            await page.locator('#bi-f-nature').selectOption('financement');
            assert.deepEqual(await codes(), ['706100']);
            await page.locator('#bi-f-nature').selectOption('salaire');
            await page.locator('#bi-f-compte').selectOption('641100');
            await page.locator('#bi-f-salarie_id').selectOption('2');
            await page.locator('#bi-f-base').selectOption('alisfa');
            await page.waitForFunction(() => document.getElementById('bi-f-pesee').value === '20');
            assert.equal(await page.locator('#bi-f-quotite').inputValue(), '80.0');
            assert.equal(await page.locator('#bi-f-maintien').inputValue(), '0');
            await page.locator('#bi-f-pesee').fill('99');
            await page.locator('#bi-f-base').selectOption('brut');
            await page.locator('#bi-f-quotite').fill('75');
            await page.locator('#bi-f-base').selectOption('alisfa');
            assert.equal(await page.locator('#bi-f-pesee').inputValue(), '99');
            assert.equal(await page.locator('#bi-f-quotite').inputValue(), '75');
            await page.locator('#bi-f-salarie_id').selectOption('1');
            await page.getByText(/Copie budgétaire modifiable/).waitFor();
            await page.waitForFunction(() => document.getElementById('bi-f-socle').value === '23000');
            assert.equal(await page.locator('#bi-f-quotite').inputValue(), '');
            await page.locator('#bi-f-salarie_id').selectOption('2');
            assert.equal(await page.locator('#bi-f-pesee').inputValue(), '99');
            assert.equal(await page.locator('#bi-f-quotite').inputValue(), '75');
            await page.screenshot({path:path.join(output,name+'-alisfa.png'),fullPage:true});
            await page.locator('#bi-editor button[type=submit]').click();
            await page.getByText('Enregistré et recalculé.', {exact:true}).waitFor();
            await page.reload();
            await page.getByText('Construction chargée.', {exact:true}).waitFor();
            await page.locator('#bi-lines button').first().click();
            assert.equal(await page.locator('#bi-f-pesee').inputValue(), '99');
            assert.equal(await page.locator('#bi-f-source').inputValue(), '');
            assert.equal(await page.locator('#bi-f-note').inputValue(), '');
            // Les paramètres ALISFA restent mémorisés même après une sauvegarde en brut.
            await page.locator('#bi-f-base').selectOption('brut');
            await page.locator('#bi-editor button[type=submit]').click();
            await page.getByText('Enregistré et recalculé.', {exact:true}).waitFor();
            await page.reload();
            await page.getByText('Construction chargée.', {exact:true}).waitFor();
            await page.locator('#bi-lines button').first().click();
            await page.locator('#bi-f-base').selectOption('alisfa');
            assert.equal(await page.locator('#bi-f-pesee').inputValue(), '99');
            await page.locator('#bi-cancel').click();
            // Invalider la session par un vrai POST sans CSRF, puis essayer de sauver.
            await page.locator('#bi-lines button').first().click();
            await page.locator('#bi-f-libelle').fill('Saisie à conserver après expiration');
            await context.request.post(base + '/api/budget-initial-detaille/enregistrer', {data:{annee:year}});
            await page.locator('#bi-editor button[type=submit]').click();
            await page.getByText('Votre session a expiré ou est invalide. Conservez vos saisies affichées, puis reconnectez-vous et rechargez la page.', {exact:true}).waitFor();
            assert.equal(await page.locator('#bi-f-libelle').inputValue(), 'Saisie à conserver après expiration');
            assert.deepEqual(errors, []);
            console.log(name + ': connexion, CSRF, vide/incomplet, erreur, reprise/UUID, report, PDF, actualisé 2026, interfaces flux/classique, focus/survol, comptes filtrés, copie ALISFA et ajustements conservés, documents facultatifs et expiration OK');
            await context.close();
        }
        console.log('Captures : ' + output);
    } finally {
        if (browser) await browser.close();
        server.kill('SIGTERM');
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
