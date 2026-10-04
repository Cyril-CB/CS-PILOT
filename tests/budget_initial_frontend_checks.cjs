/* Contrôles UI isolés : vrai Chromium, réponses API synthétiques, sans Flask.
 * node tests/budget_initial_frontend_checks.cjs
 * CHROMIUM_PATH permet de choisir un navigateur déjà installé, sans téléchargement.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {spawnSync} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const python = spawnSync(process.env.PYTHON || 'python', ['-c', `
import json
from budget_initial import serialisable
from tests.test_budget_initial_moteur import lignes, salaire, depense, calcul
data=lignes(salaire(),depense())
for l in data:l['updated_at']='2026-01-10 12:00:00'
print(json.dumps(serialisable({'annee':2026,'revision':2,'hypotheses':{'note':'Pilote synthétique','taux_individuels':False},
'updated_at':'2026-01-10 12:00:00','lignes':data,'secteurs':{'1':'Pilote synthétique','2':'Second synthétique'},
'premiers_641':{'1':'641100'},'calcul':calcul(salaire(),depense()),
'reports':[{'secteur_id':'1','compte':'641100','avant':None,'montant':'24000','possible':True,'motif':''}],
'reference_report':'synthetique'})))
`], {cwd:root, encoding:'utf8'});
assert.equal(python.status, 0, python.stderr);
const fixture = JSON.parse(python.stdout);
const substitutions = {
    "url_for('static', filename='css/budget_initial.css')": '/static/css/budget_initial.css',
    "url_for('static', filename='js/budget_initial.js')": '/static/js/budget_initial.js',
    "url_for('budget_initial_bp.donnees')": '/api/budget-initial-detaille',
    "url_for('budget_initial_bp.sauvegarder')": '/api/budget-initial-detaille/enregistrer',
    "url_for('budget_initial_bp.report')": '/api/budget-initial-detaille/reporter',
    "url_for('budget_bp.budget_previsionnel', annee=annee)": '/budget-previsionnel?annee=2026',
    annee: '2026',
};
let content = fs.readFileSync(path.join(root,'templates/budget_initial.html'),'utf8').split('{% block content %}')[1].split('{% endblock %}')[0];
content = content.replace(/{{\s*(.*?)\s*}}/g, (_,key) => {assert.ok(key in substitutions,key); return substitutions[key];});
const html = '<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="csrf-token" content="synthetic-test-token"><link rel="stylesheet" href="/static/css/style.css"></head><body><div class="main-content"><div class="container">'+content+'</div></div></body></html>';
const output = process.env.BUDGET_UI_OUTPUT || fs.mkdtempSync(path.join(os.tmpdir(),'budget-initial-ui-'));
(async () => {
    const browser = await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium'});
    try {
        for (const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]) {
            const page = await browser.newPage({viewport:{width,height}});
            const errors=[];let lastPost=null, responseStatus=409, reply={error:'Erreur synthétique : ventilation à 99 %.'};
            let current=structuredClone(fixture);
            page.on('pageerror',e=>errors.push(e.message));
            page.on('dialog',d=>d.accept());
            await page.route('http://budget.test/**', async route => {
                const req=route.request(),url=new URL(req.url());
                if(url.pathname.startsWith('/static/')) {
                    const file=path.join(root,url.pathname.slice(1));
                    return route.fulfill({status:200,contentType:file.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(file)});
                }
                if(req.method()==='POST') {
                    lastPost=req.postDataJSON();
                    assert.equal(req.headers()['x-csrftoken'],'synthetic-test-token');
                    return route.fulfill({status:responseStatus,contentType:'application/json',body:JSON.stringify(reply)});
                }
                if(url.pathname==='/api/budget-initial-detaille') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(current)});
                return route.fulfill({status:200,contentType:'text/html',body:html});
            });
            await page.goto('http://budget.test/');
            await page.getByText('Construction chargée.',{exact:true}).waitFor();
            assert.equal(await page.locator('#bi-lines tr').count(),2);
            assert.equal(await page.locator('#bi-report').isEnabled(),true);
            await page.screenshot({path:path.join(output,name+'-totaux.png'),fullPage:true});
            await page.locator('#bi-lines button').first().click();
            assert.equal(await page.locator('#bi-f-brut_mensuel').inputValue(),'2000');
            assert.equal(await page.locator('#bi-brut').isVisible(),true);
            await page.locator('#bi-f-base').selectOption('alisfa');
            assert.equal(await page.locator('#bi-alisfa').isVisible(),true);
            assert.equal(await page.locator('#bi-brut').isVisible(),false);
            await page.locator('#bi-f-base').selectOption('brut');
            await page.locator('#bi-add-complement').click();
            await page.locator('#bi-complements input').nth(0).fill('Prime synthétique');
            await page.locator('#bi-complements input').nth(1).fill('641200');
            await page.locator('#bi-f-secteur-1').fill('99');
            await page.locator('#bi-editor button[type=submit]').click();
            await page.getByText(reply.error,{exact:true}).waitFor();
            assert.equal(lastPost.ligne.id,'0');
            assert.equal(lastPost.ligne.donnees.complements[0].mois.length,12);
            assert.equal(lastPost.ligne.donnees.secteurs['1'],'99');
            assert.equal(await page.locator('#bi-editor').isVisible(),true);
            assert.equal(await page.locator('#bi-f-libelle').isEnabled(),true);
            assert.equal(await page.locator('#bi-f-secteur-1').inputValue(),'99');
            await page.screenshot({path:path.join(output,name+'-erreur.png'),fullPage:true});
            assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Pas de débordement global');
            await page.locator('#bi-cancel').click();
            await page.locator('#bi-note').fill('Hypothèse non enregistrée');
            await page.locator('#bi-new').click();
            assert.equal(await page.locator('#bi-editor').isVisible(),false);
            await page.locator('#bi-cancel-hypotheses').click();
            assert.equal(await page.locator('#bi-note').inputValue(),'Pilote synthétique');
            await page.locator('#bi-new').click();
            await page.locator('#bi-f-nature').selectOption('depense');
            assert.equal(await page.locator('#bi-other').isVisible(),true);
            await page.locator('#bi-f-mode').selectOption('proportionnel');
            assert.equal(await page.locator('#bi-proportional').isVisible(),true);
            assert.equal(await page.locator('#bi-f-ref-annee').inputValue(),'2025');
            await page.locator('#bi-cancel').click();
            responseStatus=200;reply={success:true,reportes:1};
            await page.locator('#bi-report').click();
            await page.getByText('1 compte(s) reporté(s). Vérifiez les comptes conservés avant le PDF.',{exact:true}).waitFor();
            assert.equal(lastPost.reference_report,'synthetique');
            current={...fixture,lignes:[],reports:[],calcul:{...fixture.calcul,complet:false,alertes:[],lignes:[]}};
            await page.reload();
            await page.getByText('La construction est vide.',{exact:true}).waitFor();
            assert.equal(await page.locator('#bi-report').isDisabled(),true);
            assert.deepEqual(errors,[]);
            await page.close();
            console.log(name+': rendu, formulaires, modes, erreur préservée, CSRF, report, état vide OK');
        }
        console.log('Captures synthétiques : '+output);
    } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
