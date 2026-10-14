/* Flask/SQLite/CSRF réels, aucun appel extérieur ; dépendances déjà installées. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
(async () => {
  const captures = fs.mkdtempSync(path.join(os.tmpdir(), 'budget-suivi-captures-'));
  const server = spawn(process.env.PYTHON || 'python', ['tests/budget_suivi_live_server.py'], {cwd:path.resolve(__dirname,'..')});
  let browser, errors = '';
  server.stderr.on('data', c => {errors = (errors+c).slice(-4000);});
  try {
    const base = await new Promise((resolve,reject) => {
      const timer = setTimeout(() => reject(Error('Démarrage trop long')),30000);
      let buffer='';
      server.stdout.on('data', c => {buffer+=c; const m=buffer.match(/RECETTE_URL=(http:\/\/127\.0\.0\.1:\d+)/); if(m){clearTimeout(timer);resolve(m[1]);}});
      server.once('exit', c => {clearTimeout(timer);reject(Error('Serveur arrêté '+c+' '+errors));});
    });
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium'});
    for (const [name,width,height,annee] of [['desktop',1440,1000,2027],['mobile',390,844,2028]]) {
      const context=await browser.newContext({viewport:{width,height}, reducedMotion:'reduce'});
      await context.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():r.abort());
      const page=await context.newPage();
      const jsErrors=[];page.on('pageerror',e=>jsErrors.push(e.message));
      await page.goto(base+'/login');
      await page.locator('#login').fill('recette');
      await page.locator('#password').fill('Recette-locale-2026!');
      await page.locator('button[type=submit]').click();
      await page.waitForURL(u=>!u.pathname.endsWith('/login'));
      await page.evaluate(async()=>{await fetch('/api/interface/basculer',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({actif:true})});});
      await page.goto(base+'/budget/suivi?annee=2030');
      assert.match(await page.locator('#initial-app').innerText(),/Figez d’abord/);
      await page.goto(base+'/budget/gel?annee=2030');
      assert.equal(await page.getByRole('button',{name:'Figer une nouvelle version annuelle'}).isDisabled(),true);
      await page.goto(base+'/budget/gel?annee='+annee);
      await page.locator('#motif').fill('Vote synthétique du CA');
      await page.locator('[name=confirme]').check();
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.screenshot({animations:'disabled',path:path.join(captures,name+'-gel.png'),fullPage:true});
      await page.getByRole('button',{name:'Figer une nouvelle version annuelle'}).click();
      await page.waitForURL(u=>u.pathname==='/budget/suivi');
      assert.match(await page.locator('#initial-app').innerText(),/800.00/);
      await page.locator('#nouveau-libelle').fill('Énergie, projection révisée');
      await page.locator('#nouveau-compte').fill('606100');
      await page.locator('#nouveau-montant').fill('1500');
      await page.locator('#nouveau-lien').selectOption(annee+':1:606100');
      await page.getByRole('button',{name:'Ajouter l’ajustement',exact:true}).click();
      assert.match(await page.locator('#initial-app').innerText(),/-300.00/);
      await page.locator('#nouveau-libelle').fill('Montant à préciser');
      await page.locator('#nouveau-compte').fill('606100');
      await page.getByRole('button',{name:'Ajouter l’ajustement',exact:true}).click();
      assert.match(await page.locator('#initial-app').innerText(),/courant est provisoire/);
      const first=page.locator('article').first();
      await first.getByText('Modifier cet ajustement',{exact:true}).click();
      await first.locator('[name=montant]').fill('1600');
      await first.getByRole('button',{name:'Enregistrer la révision'}).click();
      assert.match(await page.locator('#initial-app').innerText(),/-400.00/);
      await page.getByRole('button',{name:'Créer un instantané daté et ses PDF'}).click();
      const link=page.getByRole('link',{name:'PDF synthèse',exact:true}).first();
      const pdf=await context.request.get(base + await link.getAttribute('href'));
      assert.equal(pdf.status(),200); assert.ok((await pdf.body()).subarray(0,4).toString()==='%PDF');
      // Erreur serveur conservant les champs d'un nouvel ajustement.
      await page.locator('#nouveau-libelle').fill('Saisie à conserver');
      await page.locator('#nouveau-compte').fill('799999');
      await page.getByRole('button',{name:'Ajouter l’ajustement',exact:true}).click();
      assert.equal(await page.locator('#nouveau-libelle').inputValue(),'Saisie à conserver');
      assert.match(await page.locator('#initial-app').innerText(),/classe 6/);
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.screenshot({animations:'disabled',path:path.join(captures,name+'-suivi.png'),fullPage:true});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      assert.deepEqual(jsErrors,[]);
      // Interface classique, même parcours.
      await page.evaluate(async()=>{await fetch('/api/interface/basculer',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({actif:false})});});
      await page.goto(base+'/budget/suivi?annee='+annee);
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.screenshot({animations:'disabled',path:path.join(captures,name+'-classique.png'),fullPage:true});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      await context.close();
    }
    console.log('Recette lot 2 desktop/mobile, flux/classique, CSRF, PDF : OK. Captures '+captures);
  } finally {if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
