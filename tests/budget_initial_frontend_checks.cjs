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
'comptes':[{'compte_num':c,'libelle':'Synthétique'} for c in ['641100','641200','606100','706100']],
'premiers_641':{'1':'641100'},'calcul':calcul(salaire(),depense()),
'reports':[{'secteur_id':'1','compte':'641100','avant':None,'montant':'24000','possible':True,'motif':''}],
'reference_report':'synthetique'})))
`], {cwd:root, encoding:'utf8'});
assert.equal(python.status, 0, python.stderr);
const fixture = JSON.parse(python.stdout);
fixture.salaries = [1,2].map(id => ({id, prenom:'Test', nom:String(id), actif:true}));
const substitutions = {
    "url_for('static', filename='css/budget_initial.css')": '/static/css/budget_initial.css',
    "url_for('static', filename='js/budget_initial.js')": '/static/js/budget_initial.js',
    "url_for('budget_initial_bp.donnees')": '/api/budget-initial-detaille',
    "url_for('budget_initial_bp.sauvegarder')": '/api/budget-initial-detaille/enregistrer',
    "url_for('budget_initial_bp.report')": '/api/budget-initial-detaille/reporter',
    "url_for('budget_bp.budget_previsionnel', annee=annee)": '/budget-previsionnel?annee=2026',
    "url_for('budget_initial_bp.alisfa')": '/api/budget-initial-detaille/alisfa',
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
            const pendingAlisfa = new Map(), waitingAlisfa = new Map();
            const waitAlisfa = id => pendingAlisfa.has(id) ? Promise.resolve() : new Promise((resolve, reject) => {
                const timer = setTimeout(() => reject(new Error('Requête ALISFA absente : ' + id)), 3000);
                waitingAlisfa.set(id, () => { clearTimeout(timer); resolve(); });
            });
            page.on('pageerror',e=>errors.push(e.message));
            page.on('dialog',d=>d.accept());
            await page.route('http://budget.test/**', async route => {
                const req=route.request(),url=new URL(req.url());
                if(url.pathname.startsWith('/static/')) {
                    const file=path.join(root,url.pathname.slice(1));
                    return route.fulfill({status:200,contentType:file.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(file)});
                }
                if(url.pathname==='/api/budget-initial-detaille/alisfa') {
                    return new Promise(resolve => {
                        const id = url.searchParams.get('salarie_id');
                        pendingAlisfa.set(id, async values => {
                            await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({valeurs:values,message:'Copie synthétique reçue'})});
                            resolve();
                        });
                        waitingAlisfa.get(id)?.();
                    });
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
            await page.locator('#bi-complements select').selectOption('641200');
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
            // Une réponse RH retardée ne doit pas écraser le salarié courant ni une saisie.
            await page.locator('#bi-new').click();
            await page.locator('#bi-f-salarie_id').selectOption('1');
            await page.locator('#bi-f-base').selectOption('alisfa');
            await waitAlisfa('1');
            assert.ok(pendingAlisfa.has('1'));
            const previousPost = lastPost;
            await page.locator('#bi-editor button[type=submit]').click();
            await page.getByText('Attendez la fin du préremplissage ALISFA avant d’enregistrer.', {exact:true}).waitFor();
            assert.equal(lastPost, previousPost);
            await page.locator('#bi-f-salarie_id').selectOption('2');
            await page.locator('#bi-f-pesee').fill('88');
            await waitAlisfa('2');
            await pendingAlisfa.get('2')({pesee:20,quotite:80,socle:23000,point:55,anciennete:6,competence:3,maintien:0});
            await page.getByText('Copie synthétique reçue', {exact:true}).waitFor();
            await pendingAlisfa.get('1')({pesee:1,quotite:100,socle:24000,point:60,anciennete:0,competence:0,maintien:0});
            await page.locator('#bi-f-base').selectOption('brut');
            await page.locator('#bi-f-base').selectOption('alisfa');
            assert.equal(await page.locator('#bi-f-pesee').inputValue(), '88');
            assert.equal(await page.locator('#bi-f-quotite').inputValue(), '80');
            await page.locator('#bi-cancel').click();

            current={...fixture,lignes:[],reports:[],calcul:{...fixture.calcul,complet:false,alertes:[],lignes:[]}};
            await page.reload();
            await page.getByText('La construction est vide.',{exact:true}).waitFor();
            assert.equal(await page.locator('#bi-report').isDisabled(),true);
            assert.deepEqual(errors,[]);
            await page.close();
            console.log(name+': rendu, formulaires, modes, erreur préservée, CSRF, report, copie ALISFA asynchrone, état vide OK');
        }
        console.log('Captures synthétiques : '+output);
    } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
