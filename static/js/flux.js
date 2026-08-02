/* Interface sans menu : clavier, barre intelligente et vue d'ensemble.
 *
 * Trois comportements, tous pilotés par le clavier :
 * - une touche imprimable, n'importe où, ouvre la barre et s'y inscrit ;
 * - Ctrl/⌘ + K ouvre la barre vide ;
 * - Échap ouvre la vue d'ensemble (et la referme).
 *
 * La recherche garde le moteur existant : la barre propose d'abord les zones
 * et les pages (ce qui remplace le menu), et « Rechercher … » envoie la requête
 * à /api/search, dont le verdict est traité comme avant (redirect / choices /
 * none).
 */
(function () {
    'use strict';

    var socle = document.getElementById('flxSocle');
    if (!socle) return;

    var CARTE = {zones: [], directs: []};
    try {
        CARTE = JSON.parse(socle.getAttribute('data-carte') || '{}') || {};
    } catch (e) { /* carte illisible : la vue d'ensemble restera vide */ }
    CARTE.zones = CARTE.zones || [];
    CARTE.directs = CARTE.directs || [];

    var INITIALES = socle.getAttribute('data-initiales') || '?';
    /* La recherche métier n'est ouverte qu'aux profils que /api/search accepte.
       Pour les autres, la barre reste un moyen d'aller à une page — proposer
       « Rechercher » leur renverrait un « Accès non autorisé ». */
    var RECHERCHE_GLOBALE = socle.getAttribute('data-recherche-globale') === '1';
    var URL_ACCUEIL = socle.getAttribute('data-accueil') || '/accueil';

    var champ = document.getElementById('flxChamp');
    var barre = document.getElementById('flxBarre');
    var palette = null;      // élément DOM de la palette ouverte
    var ensemble = null;     // élément DOM de la vue d'ensemble ouverte
    var selection = 0;
    var resultats = [];

    /* ── Utilitaires ──────────────────────────────────────────────────── */

    function ech(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(s == null ? '' : String(s)));
        return d.innerHTML;
    }

    /* Comparaison insensible aux accents et à la casse : « échéance » doit se
       trouver en tapant « echeance ». */
    function pliable(s) {
        return String(s == null ? '' : s)
            .toLowerCase()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '');
    }

    function toast(message) {
        var t = document.createElement('div');
        t.className = 'flx-toast';
        t.textContent = message;
        document.body.appendChild(t);
        setTimeout(function () { t.remove(); }, 2600);
    }

    /* Lieux fréquentés : alimente la barre du bas, sans rien demander. */
    function usage() {
        try { return JSON.parse(localStorage.getItem('flx_usage') || '{}') || {}; }
        catch (e) { return {}; }
    }
    function noterUsage(id) {
        try {
            var u = usage();
            u[id] = (u[id] || 0) + 1;
            localStorage.setItem('flx_usage', JSON.stringify(u));
        } catch (e) { /* stockage indisponible : le sillage restera vide */ }
    }

    function groupes() { return CARTE.zones.concat(CARTE.directs); }

    /* ── Palette : construction des propositions ──────────────────────── */

    function propositionsVides() {
        var liste = [];
        var u = usage();
        var frequents = groupes()
            .filter(function (g) { return (u[g.id] || 0) > 0; })
            .sort(function (a, b) { return (u[b.id] || 0) - (u[a.id] || 0); })
            .slice(0, 3);
        if (frequents.length) {
            frequents.forEach(function (g, i) {
                liste.push({
                    entete: i === 0 ? 'Vos lieux' : null,
                    icone: g.icone, titre: g.nom,
                    sous: g.pages.length + ' page(s)',
                    url: g.pages[0].lien, zone: g.id
                });
            });
        }
        groupes().slice(0, 6).forEach(function (g, i) {
            liste.push({
                entete: i === 0 ? 'Zones' : null,
                icone: g.icone, titre: g.nom, sous: g.description,
                url: g.pages[0].lien, zone: g.id
            });
        });
        liste.push({
            entete: 'Explorer', icone: '⊕', titre: "Voir tout l'espace",
            sous: inventaire(),
            action: 'ensemble'
        });
        return liste;
    }

    function nbPages() {
        return groupes().reduce(function (n, g) { return n + g.pages.length; }, 0);
    }

    /* « 8 zones · 3 accès directs · 58 pages » : le décompte dit ce que la
       carte montre, les deux cercles ayant des rôles différents. */
    function inventaire() {
        var t = [CARTE.zones.length + ' zone' + (CARTE.zones.length > 1 ? 's' : '')];
        if (CARTE.directs.length) {
            t.push(CARTE.directs.length + ' accès direct' + (CARTE.directs.length > 1 ? 's' : ''));
        }
        t.push(nbPages() + ' pages');
        return t.join(' · ');
    }

    function propositions(q) {
        if (!q) return propositionsVides();
        var qp = pliable(q);
        var liste = [];

        var zones = groupes().filter(function (g) {
            return pliable(g.nom + ' ' + g.mots + ' ' + g.description).indexOf(qp) !== -1;
        });
        zones.forEach(function (g, i) {
            liste.push({
                entete: i === 0 ? 'Zones' : null,
                icone: g.icone, titre: g.nom, sous: g.description,
                url: g.pages[0].lien, zone: g.id
            });
        });

        /* Les pages se cherchent par leur propre nom, pas par les mots-clés de
           leur zone : sans cela, « facture » ferait remonter les onze pages de
           la zone Validations, dont les mots-clés contiennent « facture ». La
           zone, elle, reste proposée juste au-dessus. */
        var parNom = [], parZone = [];
        groupes().forEach(function (g) {
            var zoneMatch = pliable(g.nom).indexOf(qp) !== -1;
            g.pages.forEach(function (p) {
                var item = {icone: g.icone, titre: p.label,
                            sous: 'Page · ' + g.nom, url: p.lien, zone: g.id};
                if (pliable(p.label).indexOf(qp) !== -1) parNom.push(item);
                else if (zoneMatch) parZone.push(item);
            });
        });
        /* Une page qui porte le mot cherché passe avant celles qui ne font que
           partager sa zone : « facture » propose Factures avant Fournisseurs. */
        parNom.concat(parZone).slice(0, 8).forEach(function (p, i) {
            liste.push(Object.assign({entete: i === 0 ? 'Pages' : null}, p));
        });

        if (RECHERCHE_GLOBALE) {
            liste.push({
                entete: 'Rechercher', icone: '⌕', titre: 'Rechercher « ' + q + ' »',
                sous: 'Fournisseur, salarié, facture, budget…', action: 'recherche'
            });
        }
        return liste;
    }

    /* ── Palette : rendu ──────────────────────────────────────────────── */

    function ouvrirPalette(valeurInitiale) {
        if (!palette) {
            var voile = document.createElement('div');
            voile.className = 'flx-voile';
            voile.addEventListener('click', fermerPalette);

            palette = document.createElement('div');
            palette.className = 'flx-palette';
            palette.innerHTML =
                '<div class="flx-palette-corps" id="flxPaletteCorps"></div>' +
                '<div class="flx-palette-pied"><span>↑↓ parcourir · ↵ ouvrir</span>' +
                "<span>Échap : vue d'ensemble</span></div>";
            palette._voile = voile;
            document.body.appendChild(voile);
            document.body.appendChild(palette);
            if (barre) barre.classList.add('flx-ouverte');
        }
        if (typeof valeurInitiale === 'string' && champ) champ.value = valeurInitiale;
        selection = 0;
        rendrePalette();
        if (champ) champ.focus();
    }

    function fermerPalette() {
        if (!palette) return;
        if (palette._voile) palette._voile.remove();
        palette.remove();
        palette = null;
        if (barre) barre.classList.remove('flx-ouverte');
        if (champ) { champ.value = ''; champ.blur(); }
    }

    function rendrePalette() {
        if (!palette) return;
        resultats = propositions(champ ? champ.value.trim() : '');
        if (selection >= resultats.length) selection = Math.max(0, resultats.length - 1);
        var corps = palette.querySelector('#flxPaletteCorps');
        if (!resultats.length) {
            corps.innerHTML = '<div class="flx-palette-vide">Aucune page ne correspond. ' +
                'Essayez « congés », « facture », « salle »' +
                (RECHERCHE_GLOBALE ? '' : ' — ou ouvrez la vue d\'ensemble avec Échap') +
                '.</div>';
            return;
        }
        corps.innerHTML = resultats.map(function (r, i) {
            return (r.entete ? '<div class="flx-palette-groupe">' + ech(r.entete) + '</div>' : '') +
                '<button type="button" class="flx-res' + (i === selection ? ' flx-res-actif' : '') +
                '" data-i="' + i + '">' +
                '<span class="flx-res-icone">' + ech(r.icone) + '</span>' +
                '<span class="flx-res-corps">' +
                '<span class="flx-res-titre">' + ech(r.titre) + '</span>' +
                '<span class="flx-res-sous">' + ech(r.sous) + '</span></span>' +
                '<span class="flx-res-fleche">↵</span></button>';
        }).join('');
        corps.querySelectorAll('.flx-res').forEach(function (b) {
            b.addEventListener('click', function () { executer(resultats[+b.dataset.i]); });
            b.addEventListener('mouseenter', function () {
                selection = +b.dataset.i;
                corps.querySelectorAll('.flx-res').forEach(function (x) {
                    x.classList.toggle('flx-res-actif', +x.dataset.i === selection);
                });
            });
        });
        var actif = corps.querySelector('.flx-res-actif');
        if (actif && actif.scrollIntoView) actif.scrollIntoView({block: 'nearest'});
    }

    function executer(r) {
        if (!r) return;
        if (r.action === 'ensemble') { fermerPalette(); ouvrirEnsemble(); return; }
        if (r.action === 'recherche') { lancerRecherche(); return; }
        if (r.zone) noterUsage(r.zone);
        window.location = r.url;
    }

    /* Recherche intelligente : le moteur existant, inchangé. */
    function lancerRecherche() {
        var q = champ ? champ.value.trim() : '';
        if (!q) return;
        var corps = palette && palette.querySelector('#flxPaletteCorps');
        if (corps) corps.innerHTML = '<div class="flx-palette-vide">Recherche…</div>';
        fetch('/api/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query: q})
        }).then(function (r) { return r.json(); })
          .then(function (v) { rendreVerdict(v, corps); })
          .catch(function () {
              if (corps) corps.innerHTML = '<div class="flx-palette-vide">Erreur de recherche.</div>';
          });
    }

    function rendreVerdict(v, corps) {
        if (!corps) return;
        if (v.type === 'redirect') {
            corps.innerHTML = '<div class="flx-palette-vide">Ouverture : ' + ech(v.label) + '…</div>';
            window.location = v.url;
            return;
        }
        if (v.type === 'choices') {
            corps.innerHTML = '<div class="flx-palette-groupe">' + ech(v.prompt) + '</div>' +
                (v.options || []).map(function (o) {
                    return '<a class="flx-res" href="' + ech(o.url) + '">' +
                        '<span class="flx-res-icone">→</span>' +
                        '<span class="flx-res-corps">' +
                        '<span class="flx-res-titre">' + ech(o.label) + '</span>' +
                        (o.sous_titre ? '<span class="flx-res-sous">' + ech(o.sous_titre) + '</span>' : '') +
                        '</span></a>';
                }).join('');
            return;
        }
        var h = '<div class="flx-palette-vide">' + ech(v.message) + '</div>';
        if (v.exemples && v.exemples.length) {
            h += '<div class="flx-palette-groupe">Essayez</div>' + v.exemples.map(function (e) {
                return '<button type="button" class="flx-res" data-ex="' + ech(e) + '">' +
                    '<span class="flx-res-icone">⌕</span>' +
                    '<span class="flx-res-corps"><span class="flx-res-titre">' + ech(e) +
                    '</span></span></button>';
            }).join('');
        }
        corps.innerHTML = h;
        corps.querySelectorAll('[data-ex]').forEach(function (b) {
            b.addEventListener('click', function () {
                if (champ) champ.value = b.dataset.ex;
                lancerRecherche();
            });
        });
    }

    /* ── Vue d'ensemble : géométrie ───────────────────────────────────── */

    var latch = null;        // zone dépliée
    var tEntree = null, tSortie = null, cible = null, cam = null;

    function ouvrirEnsemble() {
        if (ensemble) return;
        fermerPalette();
        ensemble = document.createElement('div');
        ensemble.className = 'flx-ensemble';
        ensemble.innerHTML =
            '<div class="flx-ensemble-fond" id="flxEnsFond"></div>' +
            '<div class="flx-ensemble-entete">' +
            '<div class="flx-ensemble-sur">Vue d\'ensemble</div>' +
            '<div class="flx-ensemble-titre" id="flxEnsTitre"></div>' +
            '<div class="flx-ensemble-sous" id="flxEnsSous"></div></div>' +
            '<div class="flx-anneau-carte" id="flxAnneauCarte"></div>' +
            '<div class="flx-ensemble-pied" id="flxEnsPied"></div>';
        document.body.appendChild(ensemble);
        ensemble.querySelector('#flxEnsFond').addEventListener('click', function () {
            if (latch) { latch = null; dessinerEnsemble(); } else { fermerEnsemble(); }
        });
        ensemble.addEventListener('mousemove', survolerEspace);
        ensemble.addEventListener('mouseleave', function () {
            annulerEntree(); maintenir();
            if (latch) { latch = null; dessinerEnsemble(); }
        });
        window.addEventListener('resize', dessinerEnsemble);
        latch = null;
        dessinerEnsemble(true);
        /* L'entrée en cascade ne joue qu'à l'ouverture : la classe est retirée
           une fois posée, pour que déplier une zone reste instantané. */
        setTimeout(function () {
            if (ensemble) ensemble.classList.remove('flx-ensemble-anime');
        }, 1100);
    }

    function fermerEnsemble() {
        if (!ensemble) return;
        window.removeEventListener('resize', dessinerEnsemble);
        ensemble.remove();
        ensemble = null;
        latch = null;
        cam = null;
    }

    function maintenir() { clearTimeout(tSortie); tSortie = null; }
    function annulerEntree() { clearTimeout(tEntree); tEntree = null; cible = null; }

    /* Acquisition au survol : il faut s'attarder sur une zone pour la déplier,
       la traverser ne déclenche rien. Une fois dépliée, elle le reste tant
       qu'aucune autre zone n'est franchement plus proche. */
    function survolerEspace(ev) {
        if (!cam) return;
        var cx = ev.clientX, cy = ev.clientY;

        if (latch) {
            var a = cam.actif;
            if (!a) return;
            var d = Math.hypot(cx - a.ex, cy - a.ey);
            if (d < a.halo) { maintenir(); return; }
            var dAutre = Infinity;
            cam.noeuds.forEach(function (n) {
                if (n.id === latch) return;
                dAutre = Math.min(dAutre, Math.hypot(cx - n.ex, cy - n.ey));
            });
            if (dAutre > d * 0.92) { maintenir(); return; }
            if (!tSortie) {
                tSortie = setTimeout(function () {
                    tSortie = null; latch = null; dessinerEnsemble();
                }, 420);
            }
            return;
        }

        var plus = null, dMin = Infinity;
        cam.noeuds.forEach(function (n) {
            var d = Math.hypot(cx - n.ex, cy - n.ey);
            if (d < dMin) { dMin = d; plus = n; }
        });
        if (!plus || dMin > (plus.r + 40) * cam.k) { annulerEntree(); return; }
        if (cible === plus.id) return;
        annulerEntree();
        cible = plus.id;
        tEntree = setTimeout(function () {
            tEntree = null; cible = null; maintenir();
            latch = plus.id;
            dessinerEnsemble();
        }, 280);
    }

    function dessinerEnsemble(entree) {
        if (!ensemble) return;
        /* `entree === true` et non `entree` : cette fonction sert aussi de
           gestionnaire de `resize`, qui lui passe un UIEvent — toujours vrai.
           Sans ce test strict, un redimensionnement après l'ouverture
           réarmerait l'animation d'entrée sans que rien ne la retire, et
           déplier une zone rejouerait la cascade au lieu d'être instantané.
           Le gestionnaire garde volontairement cette référence, pour que
           `removeEventListener` puisse le retirer à la fermeture. */
        if (entree === true) ensemble.classList.add('flx-ensemble-anime');
        var W = window.innerWidth, H = window.innerHeight;
        var HAUT = H < 640 ? 116 : 162, BAS = H < 640 ? 56 : 84;
        var dGrand = 68, dPetit = 56;
        var RO = 332, RI = 178, RS = 150;

        var ajuste = function (dec) {
            return Math.max(0.45, Math.min(1, (H - HAUT - BAS) / (2 * (RO + dec)),
                                           (W - 56) / (2 * (RO + 78))));
        };
        var k = ajuste((dGrand + 10 + 34) / 2);
        k = ajuste((dGrand + 10 + 38 / k) / 2);
        var decNoeud = (dGrand + 10 + 38 / k) / 2;
        var centreY = (HAUT + (H - BAS)) / 2 - H / 2;
        var etire = Math.max(1, Math.min(1.55, ((W - 96) / 2) / ((RO + 84) * k)));

        function pos(rayon, i, n, depart) {
            var ang = ((i + depart) / n) * Math.PI * 2 - Math.PI / 2;
            var x = Math.cos(ang) * rayon * etire, y = Math.sin(ang) * rayon;
            return {x: x, y: y, deg: Math.atan2(y, x) * 180 / Math.PI,
                    dist: Math.hypot(x, y), corde: (2 * Math.PI * rayon) / n};
        }

        /* Cercle intérieur : les zones thématiques. Cercle extérieur : les
           pages qu'on ouvre en accès direct. */
        var places = [];
        var zones = CARTE.zones, directs = CARTE.directs;
        if (!zones.length || !directs.length) {
            var tous = zones.concat(directs);
            tous.forEach(function (g, i) {
                places.push(Object.assign({g: g, interieur: true}, pos(RO, i, tous.length, 0)));
            });
        } else {
            zones.forEach(function (g, i) {
                places.push(Object.assign({g: g, interieur: true}, pos(RI, i, zones.length, 0)));
            });
            directs.forEach(function (g, i) {
                places.push(Object.assign({g: g, interieur: false}, pos(RO, i, directs.length, 0.5)));
            });
        }

        var actif = places.filter(function (p) { return p.g.id === latch; })[0] || null;
        var S = k * (actif ? 1.13 : 1);
        var derive = actif ? 0.3 : 0;
        var TX = -derive * S * (actif ? actif.x : 0);
        var TY = centreY - derive * S * (actif ? actif.y : 0);

        cam = {
            k: k,
            noeuds: places.map(function (p) {
                return {id: p.g.id, r: (p.interieur ? dGrand : dPetit) / 2,
                        ex: W / 2 + k * p.x, ey: H / 2 + centreY + k * p.y};
            }),
            actif: actif ? {
                ex: W / 2 + TX + S * actif.x, ey: H / 2 + TY + S * actif.y,
                halo: (dGrand / 2 + Math.max(RS, 138 / S) + 84) * S
            } : null
        };

        var T = function (px) { return (px / S) + 'px'; };
        var carte = ensemble.querySelector('#flxAnneauCarte');
        carte.style.transform = 'translate(' + TX + 'px, ' + TY + 'px) scale(' + S + ')';
        carte.innerHTML = '';

        places.forEach(function (p) {
            var r = document.createElement('div');
            r.className = 'flx-rayon';
            r.style.animationDelay = (90 + places.indexOf(p) * 45) + 'ms';
            r.style.width = Math.max(16, p.dist - (p.interieur ? dGrand : dPetit) / 2 - 10) + 'px';
            r.style.transform = 'rotate(' + p.deg + 'deg)';
            r.style.opacity = (actif && actif.g.id !== p.g.id) ? '0.15' : '1';
            carte.appendChild(r);
        });

        var centre = document.createElement('div');
        centre.className = 'flx-centre';
        centre.innerHTML = '<div class="flx-centre-disque">' + ech(INITIALES) + '</div>';
        centre.querySelector('.flx-centre-disque').style.opacity = actif ? '0.3' : '1';
        carte.appendChild(centre);

        places.forEach(function (p) {
            var ici = actif && actif.g.id === p.g.id;
            var taille = p.interieur ? dGrand : dPetit;
            var larg = Math.max(76, Math.min(p.corde - 12, 150 / S));

            var n = document.createElement('button');
            n.type = 'button';
            n.className = 'flx-noeud' + (p.interieur ? ' flx-noeud-chaud' : '') +
                          (ici ? ' flx-noeud-ouvert' : '');
            n.style.left = (p.x - larg / 2) + 'px';
            n.style.top = (p.y - decNoeud) + 'px';
            n.style.width = larg + 'px';
            n.style.opacity = actif ? (ici ? '1' : '0.32') : '1';
            n.style.pointerEvents = (actif && !ici) ? 'none' : 'auto';
            n.style.animationDelay = (120 + places.indexOf(p) * 45) + 'ms';
            n.innerHTML =
                '<span class="flx-noeud-disque" style="width:' + taille + 'px;height:' + taille + 'px">' +
                ech(p.g.icone) +
                (p.g.pages.length > 1 ? '<span class="flx-pastille-compte" style="top:' + T(-6) +
                    ';right:' + T(-6) + ';min-width:' + T(19) + ';height:' + T(19) +
                    ';padding:0 ' + T(5) + ';font-size:' + T(10.5) + '">' + p.g.pages.length + '</span>' : '') +
                '</span>' +
                '<span class="flx-noeud-nom" style="font-size:' + T(13.5) +
                ';opacity:' + (actif ? 0 : 1) + '">' + ech(p.g.nom) + '</span>';
            n.addEventListener('click', function (ev) {
                ev.stopPropagation();
                annulerEntree();
                if (p.g.pages.length === 1 || latch === p.g.id) {
                    noterUsage(p.g.id);
                    window.location = p.g.pages[0].lien;
                } else {
                    latch = p.g.id;
                    dessinerEnsemble();
                }
            });
            n.addEventListener('mousemove', function (ev) {
                if (ici) { ev.stopPropagation(); maintenir(); }
            });
            carte.appendChild(n);

            if (!ici) return;

            /* Les pages de la zone dépliée, en couronne autour d'elle. */
            var rs = Math.max(RS, 138 / S);
            var nb = p.g.pages.length;
            var largeSat = Math.max(80, Math.min((2 * Math.PI * rs) / nb - 10, 138 / S));
            p.g.pages.forEach(function (page, j) {
                var ang = (j / nb) * Math.PI * 2 - Math.PI / 2 + 0.42;
                var sx = p.x + Math.cos(ang) * rs, sy = p.y + Math.sin(ang) * rs;
                var s = document.createElement('a');
                s.className = 'flx-satellite';
                s.href = page.lien;
                s.style.left = (sx - largeSat / 2) + 'px';
                s.style.top = (sy - 40) + 'px';
                s.style.width = largeSat + 'px';
                s.innerHTML =
                    '<span class="flx-satellite-disque" style="font-size:' + T(11) + '">' +
                    ech(p.g.icone) + '</span>' +
                    '<span class="flx-satellite-nom" style="font-size:' + T(12.5) + '">' +
                    ech(page.label) + '</span>';
                s.addEventListener('click', function () { noterUsage(p.g.id); });
                s.addEventListener('mousemove', function (ev) { ev.stopPropagation(); maintenir(); });
                carte.appendChild(s);
            });
        });

        ensemble.querySelector('#flxEnsTitre').textContent =
            actif ? actif.g.nom : "Tout l'espace, en un geste — puis il disparaît.";
        ensemble.querySelector('#flxEnsSous').textContent =
            actif ? actif.g.description
                  : inventaire() + " · approchez-vous d'une zone, son contenu apparaît";
        ensemble.querySelector('#flxEnsPied').textContent =
            actif ? 'Cliquez une page pour y entrer · éloignez-vous pour revenir à la carte'
                  : 'Échap ou clic dans le vide pour refermer';
    }

    /* ── Clavier ──────────────────────────────────────────────────────── */

    function dansUnChamp(el) {
        if (!el) return false;
        var t = (el.tagName || '').toUpperCase();
        return t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || el.isContentEditable;
    }

    document.addEventListener('keydown', function (e) {
        if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            ouvrirPalette('');
            return;
        }

        if (e.key === 'Escape') {
            if (palette) { e.preventDefault(); fermerPalette(); return; }
            if (ensemble) {
                e.preventDefault();
                if (latch) { latch = null; dessinerEnsemble(); } else { fermerEnsemble(); }
                return;
            }
            // Sur une page où Échap sert déjà (fenêtre modale ouverte), on ne
            // vole pas la touche : les modales du reste de l'application posent
            // leur propre écouteur et sont visibles à ce moment-là.
            if (document.querySelector('.modal-overlay[style*="flex"]')) return;
            e.preventDefault();
            ouvrirEnsemble();
            return;
        }

        if (palette) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selection = (selection + 1) % Math.max(resultats.length, 1);
                rendrePalette();
                return;
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                selection = (selection - 1 + resultats.length) % Math.max(resultats.length, 1);
                rendrePalette();
                return;
            }
            if (e.key === 'Enter') {
                e.preventDefault();
                executer(resultats[selection]);
                return;
            }
            return;
        }

        // Le cœur du dispositif : taper, n'importe où, remplit la barre.
        if (!dansUnChamp(e.target) && !e.metaKey && !e.ctrlKey && !e.altKey &&
            e.key.length === 1 && /\S/.test(e.key)) {
            e.preventDefault();
            ouvrirPalette(e.key);
        }
    });

    if (champ) {
        champ.addEventListener('input', function () {
            if (!palette) { ouvrirPalette(champ.value); return; }
            selection = 0;
            rendrePalette();
        });
        champ.addEventListener('focus', function () { if (!palette) ouvrirPalette(champ.value); });
    }
    if (barre) {
        barre.addEventListener('click', function () { if (champ) champ.focus(); });
    }

    document.querySelectorAll('[data-flx-ensemble]').forEach(function (b) {
        b.addEventListener('click', function (e) { e.preventDefault(); ouvrirEnsemble(); });
    });

    /* Mémorise la zone visitée, pour alimenter la barre du bas. */
    var zoneCourante = socle.getAttribute('data-zone');
    if (zoneCourante) noterUsage(zoneCourante);

    /* Sillage : les trois zones les plus ouvertes, plus celle où l'on se trouve
       si elle n'y figure pas encore. Le raccourci se forme par l'usage, sans
       rien demander à personne. */
    (function () {
        var hote = document.getElementById('flxSillage');
        if (!hote) return;
        var u = usage();
        var frequents = groupes()
            .filter(function (g) { return (u[g.id] || 0) > 0; })
            .sort(function (a, b) { return (u[b.id] || 0) - (u[a.id] || 0); })
            .slice(0, 3);
        if (zoneCourante && !frequents.some(function (g) { return g.id === zoneCourante; })) {
            groupes().forEach(function (g) { if (g.id === zoneCourante) frequents.push(g); });
        }
        hote.innerHTML = frequents.map(function (g) {
            var actif = g.id === zoneCourante ? ' flx-actif' : '';
            return '<a class="flx-pied-lien' + actif + '" href="' + ech(g.pages[0].lien) +
                '" title="Ouvert ' + (u[g.id] || 0) + ' fois">' + ech(g.nom) + '</a>';
        }).join('');
    })();

    window.flxToast = toast;
})();
