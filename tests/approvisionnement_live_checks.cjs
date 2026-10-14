/* Vrai Flask/SQLite, sessions et CSRF actifs, ordinateur/mobile, flux/classique.
 * PYTHON=/chemin/venv/bin/python NODE_PATH=/chemin/node_modules node tests/approvisionnement_live_checks.cjs
 * Chromium doit être déjà installé ; aucune requête extérieure n'est autorisée.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'approvisionnement-captures-'));

(async () => {
    // Une base et un limiteur neufs par largeur : les connexions synthétiques
    // ne doivent pas partager artificiellement le quota d'une seule IP.
    if (!process.argv[2]) {
        for (const name of ['desktop','mobile']) {
            await new Promise((resolve,reject) => {
                const child = spawn(process.execPath,[__filename,name],{cwd:root,env:process.env,stdio:'inherit'});
                child.once('error',reject);
                child.once('exit',code => code === 0 ? resolve() : reject(new Error('Recette ' + name + ' : ' + code)));
            });
        }
        return;
    }
    const server = spawn(process.env.PYTHON || 'python', ['tests/approvisionnement_live_server.py'], {cwd: root});
    let stderr = '';
    server.stderr.on('data', data => {stderr = (stderr + data).slice(-6000);});
    let browser;
    let dernierePage;
    try {
        const base = await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('Démarrage Flask trop long')), 30000);
            let buffer = '';
            server.stdout.on('data', data => {
                buffer += data;
                const match = buffer.match(/RECETTE_URL=(http:\/\/127\.0\.0\.1:\d+)/);
                if (match) {clearTimeout(timer); resolve(match[1]);}
            });
            server.once('exit', code => {clearTimeout(timer); reject(new Error('Flask arrêté : ' + code + '\n' + stderr));});
        });
        browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
        for (const [name, width, height, userAgent] of [
            ['desktop', 1440, 1000, 'Mozilla/5.0 Desktop'],
            ['mobile', 390, 844, 'Mozilla/5.0 iPhone Mobile'],
        ].filter(([name]) => name === process.argv[2])) {
            const contexts = [];
            const errors = [];
            const open = async login => {
                const context = await browser.newContext({viewport:{width,height},userAgent});
                contexts.push(context);
                await context.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());
                const page = await context.newPage();
                dernierePage = page;
                page.on('pageerror', error => errors.push(error.message));
                await page.goto(base + '/login');
                await page.locator('#login').fill(login);
                await page.locator('#password').fill('Recette-locale-2026!');
                await page.locator('button[type=submit]').click();
                await page.waitForURL(url => !url.pathname.endsWith('/login'));
                return page;
            };
            const checkWidth = async page => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2), name + ' : débordement horizontal');
            const capture = async (page, suffix) => {
                await page.waitForLoadState('networkidle');
                await checkWidth(page);
                await page.screenshot({path:path.join(output, name + '-' + suffix + '.png'),fullPage:true,animations:'disabled'});
            };
            const admin = await open('direction');
            await admin.goto(base + '/sites');
            assert.equal(await admin.locator('h1').textContent(), 'Sites et commandes');
            await capture(admin,'sites-flux');
            // Configuration réelle d'un site supplémentaire, sans toucher aux scénarios suivants.
            await admin.locator('#nouveau_site').fill('Annexe ' + name);
            await admin.getByRole('button',{name:'Créer le site',exact:true}).click();
            await admin.getByRole('heading',{name:'Annexe ' + name,exact:true}).waitFor({state:'visible'});
            await admin.goto(base + '/produits-entretien/parametres?site_id=1');
            await admin.locator('summary').filter({hasText:'Lavettes roses'}).click();
            await capture(admin,'catalogue');
            const requester = await open('demandeur');
            await requester.goto(base + '/produits-entretien');
            await requester.getByRole('spinbutton',{name:'Quantité — Lessive (bidon)',exact:true}).fill('2');
            await requester.locator('#commentaire').fill('Besoins synthétiques ' + name);
            await capture(requester,'nouvelle-demande');
            await requester.getByRole('button',{name:'Transmettre les besoins de Gribouille',exact:true}).click();
            await requester.getByText('Votre demande a été transmise', {exact:false}).waitFor({state:'visible'});
            const manager = await open('ent1');
            await manager.goto(base + '/produits-entretien');
            await manager.getByRole('heading',{name:'À commander — Cyprian'}).waitFor({state:'visible'});
            await capture(manager,'preparation');
            await manager.getByRole('button',{name:/Marquer ces .* demande\(s\) commandées/}).click();
            const article = manager.locator('article').filter({hasText:'Besoins synthétiques ' + name});
            await article.locator('textarea').fill('Un bidon à récupérer au point habituel.');
            await article.getByRole('button',{name:'Produits reçus — notifier le responsable'}).click();
            await requester.goto(base + '/produits-entretien');
            const notification = requester.locator('.appro-notification').filter({hasText:'Gribouille'});
            assert.equal(await notification.count(),1);
            await capture(requester,'notification');
            await notification.getByRole('button',{name:'J’ai lu',exact:true}).click();
            await notification.waitFor({state:'hidden'});
            assert.equal(await requester.locator('.appro-notification').count(),0);
            await requester.reload();
            assert.equal(await requester.locator('.appro-notification').count(),0);
            // Les deux responsables de fournitures voient des espaces distincts.
            const four1 = await open('four1');
            await four1.goto(base + '/commandes-salaries?site_id=1');
            await four1.getByText('Papier Cyprian synthétique',{exact:true}).waitFor({state:'visible'});
            assert.equal(await four1.getByText('Classeurs Brosses synthétiques',{exact:true}).count(),0);
            await capture(four1,'fournitures-cyprian');
            const four2 = await open('four2');
            await four2.goto(base + '/commandes-salaries?site_id=2');
            await four2.getByText('Classeurs Brosses synthétiques',{exact:true}).waitFor({state:'visible'});
            await capture(four2,'fournitures-brosses');
            // Deux habillages du même écran, avec vrai changement de préférence.
            await admin.evaluate(async () => {
                const response = await fetch('/api/interface/basculer',{method:'POST',
                    headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},
                    body:JSON.stringify({actif:false})});
                if (!response.ok) throw new Error('Changement interface refusé');
            });
            await admin.goto(base + '/sites');
            assert.equal(await admin.locator('body.flx').count(),0);
            await capture(admin,'sites-classique');
            await admin.goto(base + '/produits-entretien');
            await capture(admin,'historique-classique');
            assert.deepEqual(errors,[]);
            for (const context of contexts) await context.close();
        }
        console.log('OK : sites, catalogue, demande, regroupement, réception et lecture ; fournitures séparées ; desktop/mobile, flux/classique, CSRF réel. Captures : ' + output);
    } catch (error) {
        if (dernierePage && !dernierePage.isClosed()) {
            await dernierePage.screenshot({path:path.join(output,'echec.png'),fullPage:true,animations:'disabled'}).catch(() => {});
            console.error('Recette arrêtée sur ' + dernierePage.url() + ' ; capture : ' + output);
        }
        console.error(stderr);
        throw error;
    } finally {
        if (browser) await browser.close();
        server.kill('SIGTERM');
    }
})().catch(error => {console.error(error); process.exitCode=1;});
