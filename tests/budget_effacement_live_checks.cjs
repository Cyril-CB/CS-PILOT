/* Recette de l'effacement groupé sur Flask/SQLite synthétiques, avec CSRF réel.
 * PYTHON=/chemin/vers/python node tests/budget_effacement_live_checks.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'budget-effacement-captures-'));

(async () => {
    const server = spawn(process.env.PYTHON || 'python', ['tests/budget_initial_live_server.py'], {cwd:root});
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
        browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium'});
        for (const [name, width, height, year] of [['desktop',1440,1000,2027], ['mobile',390,844,2028]]) {
            const context = await browser.newContext({viewport:{width,height}});
            await context.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());
            const page = await context.newPage();
            const errors = [];
            const dialogs = [];
            page.on('pageerror', error => errors.push(error.message));
            let cancel = false;
            page.on('dialog', dialog => {
                dialogs.push(dialog.message());
                return cancel ? dialog.dismiss() : dialog.accept();
            });
            await page.goto(base + '/login');
            await page.locator('#login').fill('recette');
            await page.locator('#password').fill('Recette-locale-2026!');
            await page.locator('button[type=submit]').click();
            await page.waitForURL(url => !url.pathname.endsWith('/login'));
            for (const typ of ['initial', 'actualise']) {
                await page.goto(base + '/budget-previsionnel?annee='+year+'&secteur_id=1');
                await page.waitForFunction(() => !budgetFetching);
                await page.locator('#typeBudget').selectOption(typ);
                await page.waitForFunction(() => !budgetFetching);
                await page.evaluate(async ({year,typ}) => {
                    const scope = {type_budget:typ,annee:year,secteur_id:1};
                    const send = async (action,data) => {
                        const response = await fetch('/api/budget-previsionnel/'+action, {method:'POST',
                            headers:{'Content-Type':'application/json'},body:JSON.stringify({...scope,...data})});
                        if (!response.ok) throw new Error(await response.text());
                    };
                    for (const compte_num of ['606100','706100']) await send('ajouter-compte',{compte_num});
                    const state = await (await fetch('/api/budget-previsionnel/donnees?type_budget='+typ+'&annee='+year+'&secteur_id=1')).json();
                    await send('save-lines',{reference_budget:state.reference_budget,lignes:[
                        {compte_num:'606100',valeur_def:100,valeur_temp:120,commentaire:'Commentaire conservé'},
                        {compte_num:'706100',valeur_def:null,valeur_temp:150,commentaire:'Résidu masqué'}]});
                }, {year,typ});
                // Recharger via les filtres conserve le type sélectionné.
                await page.evaluate(() => chargerBudget());
                await page.waitForFunction(() => !budgetFetching);
                const button = page.locator('#budgetEffacerMontants');
                await button.focus();
                assert(await button.evaluate(el => el === document.activeElement));
                await button.hover();
                const box = await button.boundingBox();
                assert(box.x >= 0 && box.x + box.width <= width, 'Bouton visible dans la largeur');
                // Le panneau de paramètres possède aussi des saisies non enregistrées.
                await page.locator('#budgetParametres summary').click();
                await page.locator('#budgetReferenceComplete').check();
                await button.click();
                assert.match(dialogs.at(-1), /paramètres non enregistrés/);
                assert(await page.locator('#budgetReferenceComplete').isChecked());
                await page.locator('#budgetReferenceComplete').uncheck();
                await page.locator('#budgetParametres summary').click();
                // Les saisies non enregistrées sont conservées, sans confirmation destructive.
                await page.locator('[data-bp-comment-compte="606100"]').fill('Commentaire non enregistré');
                await button.click();
                assert.match(dialogs.at(-1), /Enregistrez ou annulez/);
                assert.equal(await page.locator('[data-bp-comment-compte="606100"]').inputValue(), 'Commentaire non enregistré');
                await page.locator('#budgetSaveSaisies').click();
                await page.waitForFunction(() => !budgetSaving && !budgetFetching);
                let requests = 0;
                const count = request => {if (request.url().endsWith('/effacer-montants')) requests++;};
                page.on('request', count);
                cancel = true;
                await button.click();
                assert.equal(requests, 0);
                assert.match(dialogs.at(-1), new RegExp('exercice ' + year));
                assert(dialogs.at(-1).includes('Pilote synthétique'));
                assert(dialogs.at(-1).includes(typ === 'initial' ? 'budget initial' : 'budget actualisé'));
                assert.equal(await page.locator('[data-bp-def-compte="606100"]').inputValue(), '100');
                assert.equal(await page.locator('#budgetEffacementEtat').textContent(), '');
                cancel = false;
                // Échec réseau avant écriture : aucune réussite, montants inchangés.
                await page.route('**/effacer-montants', route => route.abort('failed'));
                await button.click();
                await page.waitForFunction(() => !budgetSaving);
                assert.match(dialogs.at(-1), /Enregistrement non confirmé/);
                assert.equal(await page.locator('#budgetEffacementEtat').textContent(), '');
                assert.equal(await page.locator('[data-bp-def-compte="606100"]').inputValue(), '100');
                await page.screenshot({path:path.join(output,name+'-'+typ+'-erreur.png'),fullPage:true});
                await page.unroute('**/effacer-montants');
                // Suspendre la requête permet de vérifier l'état avant commit et les doubles clics.
                let release;
                const pending = new Promise(resolve => {release = resolve;});
                await page.route('**/effacer-montants', async route => {await pending; await route.continue();});
                const before = requests;
                await page.evaluate(() => {effacerMontantsBudget(); effacerMontantsBudget();});
                await page.waitForFunction(() => budgetSaving);
                assert(await button.isDisabled());
                assert(await page.locator('#secteurBudget').isDisabled());
                assert(await page.locator('#budgetReferenceComplete').isDisabled());
                assert.equal(await page.locator('#budgetEffacementEtat').textContent(), '');
                await page.screenshot({path:path.join(output,name+'-'+typ+'-enregistrement.png'),fullPage:true});
                release();
                await page.waitForFunction(() => !budgetSaving && !budgetFetching);
                assert.equal(requests - before, 1);
                assert.match(await page.locator('#budgetEffacementEtat').textContent(), /effacés et enregistrés/);
                for (const code of ['606100','706100']) assert.equal(await page.locator('[data-bp-def-compte="'+code+'"]').inputValue(), '');
                assert.equal(await page.locator('[data-bp-comment-compte="606100"]').inputValue(), 'Commentaire non enregistré');
                assert.equal(await page.locator('[data-bp-comment-compte="706100"]').inputValue(), 'Résidu masqué');
                await page.screenshot({path:path.join(output,name+'-'+typ+'-succes.png'),fullPage:true});
                await page.unroute('**/effacer-montants');
                // Rechargement et commentaire seul : aucun temporaire calculé ne revient en base.
                await page.evaluate(() => chargerBudget());
                await page.waitForFunction(() => !budgetFetching);
                await page.locator('[data-bp-comment-compte="606100"]').fill('Après effacement et rechargement');
                await page.locator('#budgetSaveSaisies').click();
                await page.waitForFunction(() => !budgetSaving && !budgetFetching);
                assert(await page.evaluate(() => currentRows.every(r => r.def === null && r.temp_saisie === null)));
                page.off('request', count);
            }
            assert.deepEqual(errors, []);
            await context.close();
        }
        console.log('Effacement groupé : Flask/SQLite/CSRF, initial/actualisé, annulation, saisies, erreurs, double clic, rechargement, ordinateur/mobile : OK. Captures : '+output);
    } finally {
        if (browser) await browser.close();
        server.kill('SIGTERM');
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
