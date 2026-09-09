// Contrôles unitaires JavaScript, sans navigateur : node tests/budget_frontend_checks.cjs
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const template = fs.readFileSync(path.join(__dirname, '../templates/budget_previsionnel.html'), 'utf8');
const source = template.split('<script>')[1].split('</script>')[0]
  .replace("{{ 'true' if profil == 'responsable' else 'false' }}", 'false')
  .replace("{{ 'true' if profil in ['directeur', 'comptable'] else 'false' }}", 'true');
assert(!source.includes('{{'), 'Une nouvelle variable Jinja doit être fournie au test');
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {value:'', textContent:'', innerHTML:'', disabled:false,
    style:{display:'none'}, classList:{remove(){}}, querySelectorAll(){return []}, querySelector(){return null},
    addEventListener(){}, insertAdjacentHTML(_, html){this.innerHTML += html}});
  return nodes.get(id);
}
const fields = [element('tableInput')];
const context = vm.createContext({console, alert(){}, fetch(){return new Promise(()=>{})},
  document:{getElementById:element, querySelectorAll(){return fields}, addEventListener(){}, body:{appendChild(){}}}});
vm.runInContext(source, context);
element('typeBudget').value = 'actualise';
element('anneeBudget').value = '2026';
element('secteurBudget').value = '1';
const data = {parametres:{mois_arrete:6, annee_reference:2025, reference_valide:true},
  annees_reference:[2025], salary_brut_account:'641100', reference_budget:'fictif',
  brut_global:130000, last_month:6, last_month_label:'juin', alertes:[], totaux:{}, rows:[]};
for (const [compte, mode, valeur] of [['641100','base',120000],['641200','manuel',10000],['645100','proportionnel',56400]]) {
  data.rows.push({compte_num:compte, libelle:'Compte fictif', nature:'charges', categorie:'64', is_salary:true,
    mode, def:valeur, temp:valeur, initial:0, 'N':0, 'N-1':0, 'N-2':0,
    taux:mode === 'proportionnel' ? 0.4 : null, reference_brut:120000, reference_montant:48000});
}
context.salaryMeta = data;
context.currentRows = data.rows;
context.renderBudgetTable('budgetTables', data.rows, data, false);
context.renderBudgetParametres(data);
assert(element('budgetTables').innerHTML.includes('Proportionnel au brut'));
assert(element('budgetTables').innerHTML.includes('readonly title="Compte calculé'));
assert(element('budgetParametresContenu').innerHTML.includes('Fin juin'));
assert.equal(context.fmt(null), '—');
assert.equal(context.ecartValue({def:null, initial:100}), null);
const malicious = '2025"><img src=x onerror=alert(1)>';
context.renderBudgetParametres({...data, annees_reference:[malicious]});
assert(!element('budgetParametresContenu').innerHTML.includes('<img'));
assert(element('budgetParametresContenu').innerHTML.includes('&lt;img'));
data.parametres.annee_reference = malicious;
context.renderBudgetTable('budgetTables', data.rows, data, false);
assert(!element('budgetTables').innerHTML.includes('<img'));
assert(element('budgetTables').innerHTML.includes('&lt;img'));
data.parametres.annee_reference = 2025;
element('anneeBudget').value = malicious;
context.renderBudgetTable('budgetTables', data.rows, data, false);
assert(!element('budgetTables').innerHTML.includes('<img'), 'Année du sélecteur injectée dans un en-tête HTML');
element('anneeBudget').value = '2026';
const escaped = context.buildTable([{...data.rows[0], libelle:'<script>danger</script>'}], 'Proposition', 'Budget', false, {annee:2026});
assert(escaped.includes('&lt;script&gt;danger&lt;/script&gt;'));
assert(!escaped.includes('<script>danger</script>'));

// Totaux incomplets au chargement, en consolidation et pendant une saisie.
const partialRows = data.rows.map((r, i) => ({...r, def:[100,null,-10][i], temp:[100,null,-10][i]}));
partialRows.push({...data.rows[0], compte_num:'706100', categorie:'70', nature:'produits', mode:null,
  is_salary:false, def:200, temp:200});
context.currentRows = partialRows;
for (const globalMode of [false, true]) {
  context.renderBudgetTable('budgetTables', partialRows, data, globalMode);
  const table = element('budgetTables').innerHTML;
  const category = table.match(/<tr class="bp-cat-total"><td colspan="2">Total catégorie 64<\/td>(.*?)<\/tr>/)[1];
  assert(category.includes('data-bp-cat-def="64">À compléter</td>'));
  assert(category.includes('data-bp-cat-ecart="64">—</td>'));
  assert.equal(category.match(/À compléter/g).length, 2, 'Proposition et définitif de la catégorie incomplets');
}
const partialTotals = {charges_temp:null, produits_temp:200, resultat_temp:null,
  charges_def:null, produits_def:200, resultat_def:null};
context.renderResult('globalResultat', partialTotals);
context.renderResultFromRows();
assert.equal(element('budgetResultat').innerHTML, element('globalResultat').innerHTML);
assert(element('budgetResultat').innerHTML.includes('Charges À compléter = <strong>À compléter</strong>'));
assert(element('budgetResultat').innerHTML.includes('Produits 200,00 €'));
assert(!element('budgetResultat').innerHTML.includes('110,00'), 'Aucun faux excédent partiel');

const tableRoot = element('budgetTables');
tableRoot.querySelector = selector => ({
  '[data-bp-cat-def="64"]':element('catDef64'),
  '[data-bp-cat-ecart="64"]':element('catEcart64')
}[selector] || null);
context.queueSave('641200', '0', null);
context.updateEcartCell('641200');
assert.equal(element('catDef64').textContent, '90,00');
assert(element('catEcart64').innerHTML.includes('+90,00'));
assert(element('budgetResultat').innerHTML.includes('Charges 90,00 € = <strong>110,00 €</strong>'));
assert(element('budgetResultat').innerHTML.includes('Temporaire : Produits 200,00 € - Charges À compléter'));
context.queueSave('641200', '', null);
context.updateEcartCell('641200');
assert.equal(element('catDef64').textContent, 'À compléter');
assert.equal(element('catEcart64').innerHTML, '—');
assert.equal(element('budgetResultat').innerHTML, element('globalResultat').innerHTML);
partialRows[1].def = 0;
partialRows[1].temp = 0;
context.queueSave('706100', '', null);
context.updateEcartCell('706100');
assert(element('budgetResultat').innerHTML.includes('Définitif : Produits À compléter - Charges 90,00 € = <strong>À compléter</strong>'));
context.currentRows = data.rows;
tableRoot.querySelector = () => null;
(async () => {
  let readBudget;
  context.fetch = (_, options) => options ? Promise.resolve({ok:true, json:() => Promise.resolve({success:true})})
    : new Promise(resolve => {readBudget = resolve});
  context.budgetDirty = {'641100':{compte_num:'641100', valeur_def:120000}};
  await context.budgetPost('/api/budget-previsionnel/save-lines', {lignes:Object.values(context.budgetDirty)});
  assert(context.budgetFetching, 'Le rechargement suivant le POST doit garder le tableau protégé');
  assert(fields[0].disabled);
  assert(element('anneeBudget').disabled);
  readBudget({json:() => Promise.resolve(data)});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(context.budgetFetching, false);
  assert.equal(fields[0].disabled, false);
  assert.equal(Object.keys(context.budgetDirty).length, 0);
  console.log('Budget JS : rendu, modes, valeurs inconnues, échappement HTML et enregistrement asynchrone : OK.');
})().catch(error => {console.error(error); process.exitCode = 1});
