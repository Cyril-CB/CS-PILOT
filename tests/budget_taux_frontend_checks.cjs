// Contrôles JavaScript sans navigateur : node tests/budget_taux_frontend_checks.cjs
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const template = fs.readFileSync(path.join(__dirname, '../templates/budget_previsionnel.html'), 'utf8');
const source = template.split('<script>')[1].split('</script>')[0]
  .replace("{{ 'true' if profil == 'responsable' else 'false' }}", 'false')
  .replace("{{ 'true' if profil in ['directeur', 'comptable'] else 'false' }}", 'true');
assert(!source.includes('{{'));
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {value:'', innerHTML:'', textContent:'', disabled:false,
    style:{}, classList:{add(){}, remove(){}}, removeAttribute(){}, listeners:{},
    querySelectorAll(){return []}, addEventListener(name, handler){this.listeners[name] = handler}});
  return nodes.get(id);
}
const context = vm.createContext({console, alert(){}, fetch(){return new Promise(()=>{})},
  document:{getElementById:element, querySelectorAll(){return []}, addEventListener(){}, body:{appendChild(){}}}});
vm.runInContext(source, context);
const clone = v => JSON.parse(JSON.stringify(v));
const ctx = {defaults:{salaire_socle:24000, valeur_point:0},
  employes:[{id:1, nom:'Fictif', prenom:'Test', temps_hebdo:35, pesee:0, anciennete:0,
    competence:0, maintien:0, mois_debut:1, mois_fin:12, type_contrat:'CDI'}],
  mercredis_dates:['2026-01-07','2026-07-01'], vacances_dates:[],
  last_real_month:6, montant_reel:12000,
  budget_charges:{brut_base:'641100', comptes:['645100','645200','646100','647100','648100'],
    charges_reelles:5500, bruts:[{compte_num:'641100',N:12000},
      {compte_num:'641200',mode:'manuel',def:3600,N:1200}]}};
let st = context.defaultPaieState(ctx);
assert.equal(st.utiliser_taux_charges, false);
assert.equal(st.employes[1].taux_charges, '');
assert.equal(context.computeChargesPaie(st, ctx, {}, 'initial'), null);
st = context.mergePaieState({utiliser_taux_charges:true, taux_charges_cee:0,
  employes:{1:{taux_charges:40}}}, ctx);
assert.equal(st.taux_charges_cee, 0);
const calcul = (state=st, cx=ctx, typ='initial') => context.computeChargesPaie(state, cx, context.computePaieJS(state,cx,typ),typ);
assert.equal(calcul().total, 11040);
assert.equal(calcul(st,ctx,'actualise').total, 11260);
assert.equal(calcul().compte, '645100');
const avecAjout = clone(st);
avecAjout.ajouts = [{type:'cdi',temps_hebdo:17.5,mois_embauche:1,taux_charges:20}];
assert.equal(calcul(avecAjout).total, 13200);
const avecCee = clone(st);
Object.assign(avecCee,{forfait_cee:100,cee_mercredi:2,taux_charges_cee:15});
const cee = calcul(avecCee);
assert(Math.abs(cee.taux_moyen - (9600+400*.15)/24400) < 1e-12);
assert.equal(cee.total, Number((28000 * (9600+400*.15)/24400).toFixed(2)));
avecCee.fermetures[0] = {debut:'2026-01-01',fin:'2026-06-30'};
assert.equal(calcul(avecCee).total, Number((27800 * (9600+200*.15)/24200).toFixed(2)));
const proportion = clone(ctx);
Object.assign(proportion.budget_charges.bruts[1], {mode:'proportionnel',taux:.1});
assert.equal(calcul(st,proportion).total, 10560);
assert.equal(calcul(st,proportion,'actualise').total, 10780);
const petitsMontants = clone(st), petitContexte = clone(proportion);
petitsMontants.salaire_socle = 5.35;
petitsMontants.employes[1].taux_charges = 100;
petitContexte.budget_charges.bruts[1].taux = .5;
assert.equal(calcul(petitsMontants,petitContexte).total, 8.02);
const decembre = clone(ctx);
decembre.last_real_month = 12;
const sansTaux = clone(st);
sansTaux.employes[1].taux_charges = '';
assert.equal(calcul(sansTaux,decembre,'actualise').total, 5500);
assert(calcul(sansTaux).erreur);
for (const taux of [-1,101,'nan','inf']) {
  sansTaux.employes[1].taux_charges = taux;
  assert(calcul(sansTaux).erreur);
}
sansTaux.employes[1].taux_charges = 0;
assert.equal(calcul(sansTaux).total, 0);
const incomplet = clone(ctx);
incomplet.budget_charges.bruts[1].def = null;
assert(calcul(st,incomplet).erreur);
incomplet.budget_charges.comptes = ['646100'];
assert(calcul(st,incomplet).erreur.includes('645'));
// Arrondis de Python (binaire pour les bruts, décimal pour les reports).
for (const [n,brut,montant] of [[2.675,2.67,2.68],[1.005,1,1],[.125,.12,.12],
  [.375,.38,.38],[-.125,-.12,-.12],[1.015,1.01,1.02],[1e-8,0,0],[1.00000001e9,1.00000001e9,1.00000001e9]]) {
  assert.equal(context.paieArrondiBrut(n),brut);
  assert.equal(context.paieArrondiMontant(n),montant);
}
const partiel = clone(ctx);
partiel.employes[0].mois_debut = partiel.employes[0].mois_fin = 7;
partiel.employes[0].mois_ratios = {7:7/31};
partiel.budget_charges.bruts[1].def = 0;
assert.equal(calcul(st,partiel).total, 180.64); // 451,61 × 40 %.

// Rendu et interaction réels du template, avec un DOM minimal simulé.
context.paieSim = {state:st, context:ctx, ctx:{type_budget:'initial'}, compte:'641100'};
ctx.employes[0].nom = '"><img src=x onerror=alert(1)>';
context.renderPaieSimulator();
context.recomputePaie();
const html = element('paieSimBody').innerHTML;
assert(html.includes('T%Ch.'));
assert(html.includes('id="paieUtiliserTaux" type="checkbox" checked'));
assert(html.includes('Taux de charges CEE (%)'));
assert(!html.includes('<img'));
assert(html.includes('&lt;img'));
assert.equal(element('paieReporter').disabled,false);
st.employes[1].taux_charges = '';
context.recomputePaie();
assert.equal(element('paieReporter').disabled,true);
assert(element('paieChargesResume').innerHTML.includes('role="alert"'));
element('paieUtiliserTaux').checked = false;
element('paieUtiliserTaux').listeners.change.call(element('paieUtiliserTaux'));
assert.equal(st.utiliser_taux_charges,false);
assert.equal(element('paieReporter').disabled,false);
assert.equal(element('paieChargesResume').innerHTML,'');
// Une valeur invalide cesse aussi de bloquer le report dès que l'option est décochée.
st.employes[1].taux_charges = 101;
element('paieUtiliserTaux').checked = true;
element('paieUtiliserTaux').listeners.change.call(element('paieUtiliserTaux'));
assert.equal(element('paieReporter').disabled,true);
element('paieUtiliserTaux').checked = false;
element('paieUtiliserTaux').listeners.change.call(element('paieUtiliserTaux'));
assert.equal(element('paieReporter').disabled,false);
assert.equal(element('paieChargesResume').innerHTML,'');
console.log('Budget taux JS : pondération, CEE, tous les 641, réalisé, arrondis, saisies et erreurs : OK.');
