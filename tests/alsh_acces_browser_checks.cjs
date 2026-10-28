/* Parcours réels sur le serveur voisin, uniquement des données synthétiques. */
const {chromium, devices} = require('@playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = 'http://127.0.0.1:5057';
const out = process.env.CSPILOT_BROWSER_OUTPUT || '/tmp/cspilot-alsh-acces-browser-results';
fs.mkdirSync(out, {recursive:true});

(async () => {
    const browser = await chromium.launch({headless:true, args:['--no-sandbox']});
    const errors = [], checks = [];
    const sessions = new Map();
    async function login(role, phone=false) {
        // Réutiliser le cookie authentique du même compte entre les appareils :
        // cinq connexions au total, en respectant la limite de cinq par minute.
        const storageState = sessions.get(role);
        const context = await browser.newContext(phone
            ? {...devices['iPhone 13'], locale:'fr-FR', timezoneId:'Europe/Paris', storageState}
            : {viewport:{width:1440,height:1000}, locale:'fr-FR', timezoneId:'Europe/Paris', storageState});
        const page = await context.newPage();
        page.setDefaultTimeout(15000);
        page.on('pageerror', error => errors.push(error.message));
        if(storageState){await page.goto(base+'/dashboard');return {context,page};}
        await page.goto(base + '/login');
        await page.locator('[name=login]').fill(role);
        await page.locator('[name=password]').fill('Fictif-ALSH-2026!');
        await Promise.all([page.waitForURL(url=>!url.pathname.endsWith('/login')),
            page.locator('button[type=submit]').click()]);
        sessions.set(role,await context.storageState());
        return {context, page};
    }
    async function read(context, endpoint) {
        const r = await context.request.get(base + endpoint);
        assert.equal(r.status(),200);return r.json();
    }
    async function fits(page) {
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth)<=page.viewportSize().width+1,
            'Débordement horizontal du document');
    }
    async function dashboard(page) {
        await page.locator('#dashboardContent').waitFor({state:'visible'});
        assert.ok((await page.locator('#cartesSommaire').innerText()).length>0);
        assert.equal(await page.locator('#tab-config').count(),0);
        assert.equal(await page.locator('#pane-config').count(),0);
        assert.ok(await page.locator('#qf_0_249').isDisabled());
        assert.ok(await page.getByText('Répartition définie par la comptabilité, consultable sans modification.').isVisible());
    }
    try {
        const manager = await login('comptable');
        const before = {config:await read(manager.context,'/api/alsh/config'),
            codes:await read(manager.context,'/api/alsh/codes?annee=2026')};
        const cell = before.codes.codes.find(c=>c.code1==='ALSH-FICTIF');assert.ok(cell);
        const core = {annee:2026,periode_id:cell.periode_id,tranche_age_id:cell.tranche_age_id};
        for (const phone of [false,true]) {
            const {context,page} = await login('resp_enfance',phone);
            if (!phone) {
                await page.keyboard.press('Control+k');
                await page.locator('#flxChamp').fill('analyse alsh');
                const result = page.locator('#flxPaletteCorps').getByRole('button',{name:/Analyse ALSH/});
                await result.waitFor({state:'visible'});
                await page.screenshot({path:path.join(out,'alsh-recherche-ordinateur.png'),fullPage:true,animations:'disabled'});
                await Promise.all([page.waitForURL('**/analyse-alsh'),result.click()]);
            } else {
                await page.locator('#sidebarToggle').click();
                const section = page.locator('.sidebar-nav .sidebar-section').filter({has:page.getByRole('button',{name:/Financier/})});
                const link = section.getByRole('link',{name:/Analyse ALSH/});
                if(!await link.isVisible())await section.getByRole('button',{name:/Financier/}).click();
                await Promise.all([page.waitForURL('**/analyse-alsh'),link.click()]);
            }
            assert.equal(new URL(page.url()).pathname,'/analyse-alsh');
            await dashboard(page);await fits(page);
            await page.screenshot({path:path.join(out,`alsh-tableau-${phone?'telephone':'ordinateur'}.png`),fullPage:true,animations:'disabled'});
            checks.push(`${phone?'Téléphone/menu':'Ordinateur/palette'} : page, données et configuration interdite`);
            const csrf = await page.locator('meta[name=csrf-token]').getAttribute('content');
            for(const [endpoint,payload] of [
                ['/api/alsh/codes',{...core,code1:'FAMILLE-FICTIF'}],
                ['/api/alsh/tarif-repartition',{tarif_repartition_quotients:[{id:'qf_0_249',pct:99}]}],
            ]) {
                const response = await context.request.post(base+endpoint,{headers:{'X-CSRFToken':csrf},data:payload});
                assert.equal(response.status(),403);
            }
            assert.equal((await context.request.get(base+'/api/alsh/charges-detail?annee=2026&codes=FAMILLE-FICTIF')).status(),403);
            assert.equal((await context.request.get(base+'/api/alsh/codes-disponibles?annee=2026')).status(),403);
            checks.push(`${phone?'Téléphone':'Ordinateur'} : appels directs analytiques refusés`);
            await page.locator('.td-charges-link').filter({hasText:'240,00'}).click();
            await page.locator('#modalChargesContent').waitFor({state:'visible'});
            assert.ok((await page.locator('#modalChargesContent').innerText()).includes('Charges ALSH fictives'));
            assert.ok(!(await page.locator('#modalChargesContent').innerText()).includes('Autres charges fictives'));
            await fits(page);await page.keyboard.press('Escape');
            assert.equal(await page.locator('.flx-ensemble').isVisible(),false);
            checks.push(`${phone?'Téléphone':'Ordinateur'} : détail ALSH chargé sans autres charges`);
            await page.locator('#tab-noe').click();
            const hours = page.locator(`#h_${cell.periode_id}_${cell.tranche_age_id}`);
            const children = page.locator(`#e_${cell.periode_id}_${cell.tranche_age_id}`);
            const value = phone?'654.5':'321.5';
            await hours.fill(value);await children.fill('8');
            const saved = page.waitForEvent('dialog');
            const click = page.getByRole('button',{name:'Enregistrer toutes les saisies'}).click();
            const dialog = await saved;assert.ok(!dialog.message().includes('erreur'));await dialog.accept();await click;
            const noe = await read(context,'/api/alsh/noe?annee=2026');
            assert.equal(noe.noe.find(n=>n.periode_id===cell.periode_id && n.tranche_age_id===cell.tranche_age_id).heures_presence,Number(value));
            await page.reload();await page.locator('#tab-noe').click();await hours.waitFor();
            assert.equal(await hours.inputValue(),value);
            await fits(page);await page.screenshot({path:path.join(out,`alsh-noe-${phone?'telephone':'ordinateur'}.png`),fullPage:true,animations:'disabled'});
            checks.push(`${phone?'Téléphone':'Ordinateur'} : NOÉ enregistré et relu après rechargement`);
            if(!phone){
                await page.setViewportSize({width:390,height:844});
                await page.locator('#tab-dashboard').click();await dashboard(page);await fits(page);
                await page.screenshot({path:path.join(out,'alsh-tableau-viewport-etroit.png'),fullPage:true,animations:'disabled'});
                checks.push('Viewport étroit sans User-Agent téléphone : rendu vérifié');
            }
            await context.close();
        }
        assert.deepEqual(await read(manager.context,'/api/alsh/config'),before.config);
        assert.deepEqual(await read(manager.context,'/api/alsh/codes?annee=2026'),before.codes);
        await manager.page.goto(base+'/analyse-alsh');await manager.page.locator('#tab-config').click();
        await manager.page.locator('#codesBody tr').first().waitFor();
        assert.ok(await manager.page.locator('#nouvelleTrancheInput').isVisible());
        checks.push('Comptabilité : configuration disponible et données analytiques inchangées');
        for(const role of ['resp_famille','salarie','prestataire']){
            const {context,page}=await login(role);
            await page.goto(base+'/analyse-alsh');assert.notEqual(new URL(page.url()).pathname,'/analyse-alsh');
            assert.equal((await context.request.get(base+'/api/alsh/tableau?annee=2026')).status(),403);
            await context.close();
        }
        checks.push('Autres profils et secteurs : page et API refusées');
        assert.deepEqual(errors,[]);
        fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,javascriptErrors:errors},null,2));
        console.log(JSON.stringify({passed:checks.length,checks,javascriptErrors:errors},null,2));
    }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
