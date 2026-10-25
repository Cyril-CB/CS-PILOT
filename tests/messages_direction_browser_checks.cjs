/* Parcours navigateur sur le serveur éphémère voisin ; Playwright déjà installé. */
const {chromium} = require('@playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = 'http://127.0.0.1:5056';
const out = process.env.CSPILOT_BROWSER_OUTPUT || '/tmp/cspilot-direction-browser-results';
fs.mkdirSync(out, {recursive:true});

(async () => {
    const browser = await chromium.launch({headless:true, args:['--no-sandbox']});
    const errors = [];
    let checks = 0;
    const context = await browser.newContext({viewport:{width:1440,height:1000}, locale:'fr-FR'});
    async function pageFor(ctx, role) {
        const p = await ctx.newPage();
        p.on('pageerror', e => errors.push(e.message));
        await p.goto(base + '/login');
        await p.locator('[name=login]').fill(role);
        await p.locator('[name=password]').fill('Fictif-2026!');
        await Promise.all([p.waitForURL(url => !url.pathname.endsWith('/login')), p.locator('button[type=submit]').click()]);
        return p;
    }
    async function fits(p) {
        assert.ok(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        // Sur mobile, innerWidth peut lui-même s'élargir avec le débordement.
        assert.ok(await p.evaluate(() => document.documentElement.scrollWidth) <= p.viewportSize().width + 1);
        checks++;
    }
    try {
        const page = await pageFor(context, 'directeur');
        await page.goto(base + '/direction/messages');
        assert.ok(await page.getByText("Aucun message n'est actuellement affiché aux salariés.").isVisible());
        await fits(page);
        await page.screenshot({path:path.join(out,'direction-vide-ordinateur.png'),fullPage:true,animations:'disabled'});
        await page.locator('#contenu').fill('Note synthétique\nInformation aux salariés <b>en texte brut</b>.');
        await page.locator('#titre').fill('Note de service de test');
        await page.locator('#date_validite').fill('2999-12-31');
        await page.locator('#notifier_email').uncheck();
        await Promise.all([page.waitForNavigation(), page.getByRole('button',{name:'Publier le message'}).click()]);
        assert.ok(await page.getByText('Le message a été publié.',{exact:true}).isVisible());
        assert.ok(await page.getByText(/publié par Test Directeur/).isVisible());
        await page.reload();
        assert.ok(await page.getByRole('heading',{name:'Note de service de test',exact:true}).isVisible());
        await fits(page);
        await page.screenshot({path:path.join(out,'direction-active-ordinateur.png'),fullPage:true,animations:'disabled'});
        // Palette réellement affichée, y compris l'alias en collision avec les dossiers RH.
        await page.keyboard.press('Control+k');
        const input = page.locator('#flxChamp');
        await input.waitFor({state:'visible'});
        await input.fill('infos salariés');
        const resultat = page.locator('#flxPaletteCorps').getByRole('button',{name:/Messages de la direction/});
        await resultat.waitFor({state:'visible'});
        assert.ok(await resultat.innerText().then(t => t.includes('Messages de la direction')));
        await page.keyboard.press('Escape');
        checks++;

        const staff = await browser.newContext({viewport:{width:1440,height:1000},locale:'fr-FR'});
        const employee = await pageFor(staff, 'salarie');
        const banner = employee.getByRole('button',{name:/Message de la direction à lire/});
        assert.ok(await banner.isVisible());
        assert.ok(await employee.getByRole('button',{name:/Message du CSE à lire/}).isVisible());
        await banner.click();
        const modal = employee.locator('#directionMessageModal');
        await modal.waitFor({state:'visible'});
        assert.ok(await modal.innerText().then(t => t.includes('<b>en texte brut</b>')));
        await employee.locator('.main-content').evaluate(el => {el.tabIndex=-1;el.focus();});
        assert.ok(await modal.evaluate(el => el.contains(document.activeElement)));
        await employee.keyboard.press('Tab');
        assert.ok(await modal.evaluate(el => el.contains(document.activeElement)));
        await employee.keyboard.press('Escape');
        assert.ok(await banner.isVisible());
        await employee.reload();
        assert.ok(await banner.isVisible());
        await banner.click();
        // Un refus serveur ne doit ni masquer la bannière ni perdre le bouton.
        await employee.route('**/direction/messages/*/lire', route => route.fulfill({status:403,contentType:'application/json',body:'{"ok":false}'}));
        await modal.getByRole('button',{name:"J'ai lu et ne souhaite plus voir le message"}).click();
        await employee.locator('#directionLectureErreur').waitFor({state:'visible'});
        assert.ok(await banner.isVisible());
        assert.equal(await modal.getByRole('button',{name:"J'ai lu et ne souhaite plus voir le message"}).isDisabled(),false);
        await employee.unroute('**/direction/messages/*/lire');
        // Une redirection CSRF vers une page HTML 200 n'est pas une confirmation.
        await employee.route('**/direction/messages/*/lire', route => route.fulfill({status:200,contentType:'text/html',body:'<html>Connexion requise</html>'}));
        await modal.getByRole('button',{name:"J'ai lu et ne souhaite plus voir le message"}).click();
        await employee.locator('#directionLectureErreur').waitFor({state:'visible'});
        assert.ok(await banner.isVisible());
        await employee.unroute('**/direction/messages/*/lire');
        await modal.getByRole('button',{name:"J'ai lu et ne souhaite plus voir le message"}).click();
        await banner.waitFor({state:'hidden'});
        await employee.reload();
        assert.equal(await banner.count(),0);
        assert.ok(await employee.getByRole('button',{name:/Message du CSE à lire/}).isVisible());
        checks++;

        const mobile = await browser.newContext({viewport:{width:390,height:844},locale:'fr-FR',isMobile:true,
            userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1'});
        const mp = await pageFor(mobile,'comptable');
        await mp.goto(base + '/direction/messages');
        assert.equal(await mp.locator('a[href="/direction/messages"]').count()>=1,true);
        await fits(mp);
        await mp.screenshot({path:path.join(out,'direction-active-mobile.png'),fullPage:true,animations:'disabled'});
        await mp.goto(base + '/dashboard_comptable');
        await mp.getByRole('button',{name:/Message de la direction à lire/}).click();
        await mp.locator('#directionMessageModal').waitFor({state:'visible'});
        await fits(mp);
        await mp.screenshot({path:path.join(out,'direction-lecture-mobile.png'),animations:'disabled'});
        await mp.keyboard.press('Escape');
        await mp.goto(base + '/direction/messages');
        await mp.locator('#titre').fill('Note de remplacement');
        await mp.locator('#contenu').fill('Remplacement synthétique');
        await mp.locator('#date_validite').fill('2999-12-31');
        await mp.locator('#notifier_email').uncheck();
        await Promise.all([mp.waitForNavigation(),mp.getByRole('button',{name:'Publier le message'}).click()]);
        const archives = mp.locator('.section').filter({has:mp.getByRole('heading',{name:'🗄️ Messages archivés'})});
        await archives.getByText('Lire le message archivé').click();
        assert.ok(await archives.locator('details').getByText(/Information aux salariés/).isVisible());
        assert.ok(await archives.getByText('Test Directeur',{exact:true}).isVisible());
        await fits(mp);
        await mp.screenshot({path:path.join(out,'direction-archives-mobile.png'),fullPage:true,animations:'disabled'});
        mp.on('dialog',dialog=>dialog.accept());
        await Promise.all([mp.waitForNavigation(),mp.getByRole('button',{name:'Retirer ce message'}).click()]);
        assert.ok(await mp.getByText("Aucun message n'est actuellement affiché aux salariés.").isVisible());
        await fits(mp);
        await mp.screenshot({path:path.join(out,'direction-vide-mobile.png'),fullPage:true,animations:'disabled'});

        // Régression P2 : un titre accepté ne doit pas élargir la page, même
        // sans espace ou avec un long paramètre d'URL. Préparation via l'API
        // authentifiée pour isoler le rendu, CSRF actif et sans notification.
        for (const [cas,titre] of [
            ['sans-espaces','A'.repeat(150)],
            ['url','https://exemple.test/?reference='+'a1b2c3d4e5f6'.repeat(9)],
        ]) {
            await page.goto(base + '/direction/messages');
            const csrf = await page.locator('meta[name="csrf-token"]').getAttribute('content');
            const publication = await context.request.post(base + '/direction/messages/creer', {
                form:{titre,contenu:'Message court synthétique pour vérifier le titre.',date_validite:'2999-12-31'},
                headers:{'X-CSRFToken':csrf},
            });
            assert.equal(publication.ok(),true);
            for (const [ecran,p] of [['ordinateur',page],['mobile',mp]]) {
                await p.goto(base + '/direction/messages');
                const heading = p.locator('.direction-messages-page .section h3');
                assert.equal(await heading.innerText(),titre);
                await fits(p);
                assert.ok(await heading.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
                await p.screenshot({path:path.join(out,`direction-titre-${cas}-${ecran}.png`),fullPage:true,animations:'disabled'});
            }
        }
        assert.deepEqual(errors,[]);
        console.log(JSON.stringify({status:'passed',checks,javascriptErrors:errors,screenshots:fs.readdirSync(out)},null,2));
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
