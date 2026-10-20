/* Shared standalone / WordPress renderer. No credentials or third-party scripts. */
(() => {
'use strict';
const root = document.getElementById('maritime-living');
if (!root || root.dataset.initialized) return;
root.dataset.initialized = 'true';
const $ = id => root.querySelector('#' + id);
const regions = ['Black Sea', 'Red Sea', 'Strait of Hormuz'];
let feedMeta = {};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = value => { try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password ? u.href : null; } catch { return null; } };
const stamp = value => { const n = typeof value === 'string' ? Date.parse(value) : NaN; return Number.isFinite(n) ? n : 0; };
const attackTime = i => stamp(i.date_utc);
const date = value => stamp(value) ? new Date(stamp(value)).toLocaleDateString('en-GB', {day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'}) : 'Date not established';
const validCount = n => Number.isSafeInteger(n) && n >= 0;
const links = sources => (Array.isArray(sources) ? sources : []).flatMap(s => {const url = safeURL(typeof s === 'string' ? s : s?.url);return url ? [{url,source:typeof s === 'string' ? new URL(url).hostname : s.source || new URL(url).hostname}] : [];});
const sourceHTML = sources => [...new Map(links(sources).map(s => [s.url,s])).values()].map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer nofollow">${esc(s.source)} ↗</a>`).join('');
const confirmedCasualties = i => {const c=i.casualties;return c && typeof c === 'object' && c.status==='confirmed' && validCount(c.deaths) && links(c.sources).length ? c : null;};
let all = [], visible = [], limit = 16;
const media = window.matchMedia('(prefers-reduced-motion: reduce)');
let motionPreference = true;
try { motionPreference = localStorage.getItem('maritime-atlas-motion') !== 'off'; } catch {}
let motion = !media.matches && motionPreference;
let routeLength = 0, routeCurrent = null, routeTarget = 0, frame = 0, previousFrame = 0;
let rootVisible = true;
let heroVisible = true, heroDistance = 0, lastCurrent = null;
const hero = root.querySelector('.hero');
const observer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
 entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add('is-visible', 'reveal'); observer.unobserve(entry.target); } });
}, {threshold: .08}) : null;
const reveal = () => root.querySelectorAll('.impact-heading, .stat, .update, .record-heading, .method-grid article, .incident-card, .featured').forEach(el => {
 if (el.hidden || el.classList.contains('motion-reveal')) return;
 el.classList.add('motion-reveal');
 el.style.setProperty('--reveal-delay', `${Math.min([...el.parentElement.children].indexOf(el), 3) * 75}ms`);
 if (motion && observer) observer.observe(el); else el.classList.add('is-visible', 'reveal');
});
function applyMotion() {
 motion = !media.matches && motionPreference;
 root.dataset.motion = motion ? 'full' : 'reduced';
 root.classList.add('motion-ready');
 root.classList.toggle('motion-reduced', !motion);
 const toggle = $('motion-toggle');
 if (toggle) {
  toggle.setAttribute('aria-pressed', String(motion)); toggle.setAttribute('aria-label', 'Animations');
  toggle.disabled = media.matches; toggle.title = media.matches ? 'Reduced motion is enabled in your system settings' : 'Control decorative animations';
  const label=toggle.querySelector('.motion-label'), icon=toggle.querySelector('.motion-icon');
  if(label)label.textContent=motion?'Pause motion':'Play motion'; else toggle.textContent=motion?'Pause motion':'Play motion';
  if(icon)icon.textContent=motion?'Ⅱ':'▶';
 }
 if (!motion) root.querySelectorAll('.motion-reveal').forEach(el => el.classList.add('is-visible', 'reveal'));
 routeCurrent = null;
 scrollRoute(); scheduleFrame();
}
$('motion-toggle')?.addEventListener('click', () => {
 if(media.matches)return;
 motionPreference = !motionPreference;
 try { localStorage.setItem('maritime-atlas-motion', motionPreference ? 'on' : 'off'); } catch {}
 applyMotion();
});
if (media.addEventListener) media.addEventListener('change', applyMotion);
else if (media.addListener) media.addListener(applyMotion);
if ('IntersectionObserver' in window && hero) {
 new IntersectionObserver(entries => { heroVisible = entries[0].isIntersecting; root.dataset.heroVisible = String(heroVisible); scheduleFrame(); }).observe(hero);
}
function updatePause(){const paused=document.hidden||!rootVisible;root.dataset.motionPaused=String(paused);root.classList.toggle('motion-paused',paused);previousFrame=0;scheduleFrame();}
if('IntersectionObserver' in window)new IntersectionObserver(entries=>{rootVisible=entries[0].isIntersecting;updatePause();}).observe(root);
document.addEventListener('visibilitychange', updatePause);
function animateCount(id, count) {
 const el = $(id); if (!el) return;
 const final = count.toLocaleString('en');
 el.textContent = final;
 el.setAttribute('aria-label', final);
 if (!motion || count === 0 || el.dataset.counted) return;
 el.dataset.counted = 'true';
 // Animate a visual duplicate, keeping the true value stable for assistive technology.
 const visual = document.createElement('span'); visual.setAttribute('aria-hidden', 'true');
 const accessible = document.createElement('span'); accessible.className = 'count-accessible'; accessible.style.cssText = 'position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap'; accessible.textContent = final;
 el.replaceChildren(accessible, visual);
 const start = performance.now();
 const tick = now => {
  const t = motion ? Math.min(1, (now - start) / 1000) : 1;
  visual.textContent = Math.round(count * (1 - Math.pow(1 - t, 3))).toLocaleString('en');
  if (t < 1) requestAnimationFrame(tick); else el.textContent = final;
 };
 requestAnimationFrame(tick);
}
function updateNotes(i) {return (Array.isArray(i.updates) ? i.updates : []).filter(u => u && typeof u.text === 'string' && stamp(u.at)).sort((a,b)=>stamp(b.at)-stamp(a.at));}
function stats() {
 animateCount('total', all.length);

 const known = new Map();all.forEach(i=>{const key=i.imo ? `imo:${i.imo}` : i.vessel_name ? `name:${String(i.vessel_name).trim().toUpperCase()}` : null;if(key)known.set(key,i);});
 animateCount('vessels', known.size);

 $('unidentified').textContent='Distinct named vessels in the reviewed record.';
 const casualties=all.map(confirmedCasualties).filter(Boolean);
 const deaths=casualties.reduce((n,c)=>n+c.deaths,0), complete=all.length>0&&casualties.length===all.length;
 $('deaths').textContent=complete?deaths.toLocaleString('en'):deaths>0?`≥${deaths.toLocaleString('en')}`:'Pending';
 $('death-note').textContent=complete?'Sourced casualty counts available for every displayed incident.':`${casualties.length} of ${all.length} incidents have confirmed casualty counts. The overall toll is still being established.`;
 const nations=new Map();casualties.forEach(c=>(Array.isArray(c.nationalities)?c.nationalities:[]).forEach(n=>{if(n.status==='confirmed'&&typeof n.nationality==='string'&&n.nationality.trim()&&validCount(n.deaths)&&n.deaths>0&&links(n.sources).length)nations.set(n.nationality.trim(),(nations.get(n.nationality.trim())||0)+n.deaths);}));
 $('nationalities').textContent=nations.size || (casualties.length===all.length && all.length>0 && casualties.every(c=>c.deaths===0) ? '0' : 'Pending');
 $('deaths').classList.toggle('unavailable', !complete&&deaths===0);
 $('nationalities').classList.toggle('unavailable', !nations.size);
 $('nationality-note').textContent=nations.size ? [...nations].map(([n,count])=>`${n}: ${count}`).join(' · ') : 'Nationality totals await explicit source confirmation.';
 const types=new Map();known.forEach(i=>{const t=typeof i.vessel_type==='string'&&i.vessel_type.trim()?i.vessel_type:'Type not established';types.set(t,(types.get(t)||0)+1);});
 $('breakdown').innerHTML=[...types].sort((a,b)=>b[1]-a[1]).map(([type,n])=>`<span class="type-chip">${esc(type)} <b>${n}</b></span>`).join('');
 const dates=all.map(attackTime).filter(Boolean);
 const updated=all.map(i=>stamp(i.last_updated)).filter(Boolean);
 $('scope').textContent=all.length?`Available attack dates: ${dates.length?date(new Date(Math.min(...dates)).toISOString()):'unknown'} onward · Latest record change: ${updated.length?date(new Date(Math.max(...updated)).toISOString()):'unknown'} · Reviewed incidents only`:'Evidence review in progress · Only reviewed, named incidents enter this record.';
 const recent=all.flatMap(i=>{const notes=updateNotes(i);return notes.length?notes.map(note=>({incident:i,note,at:note.at})):[{incident:i,note:null,at:i.verification?.checked_at||i.last_updated}];}).sort((a,b)=>stamp(b.at)-stamp(a.at)).slice(0,3);
 $('updates').innerHTML=recent.length?recent.map(({incident:i,note,at})=>`<article class="update"><time>${esc(date(at))}</time><a href="#incident-${esc(i.id)}" data-record="${esc(i.id)}">${esc(i.vessel_name)} ↗</a><p>${esc(note?.text||i.summary)}</p>${note?`<div class="sources">${sourceHTML(note.sources)}</div>`:''}</article>`).join(''):'<p class="muted">No record updates available.</p>';
}
function ship(type='') {
 const t=type.toLowerCase();
 if(t.includes('tug'))return `<svg class="ship" viewBox="0 0 380 130" role="img" aria-label="Illustrated tug vessel"><path fill="currentColor" d="M82 90h219l-18 24H111L82 90Z"/><path fill="currentColor" d="M133 88V57h49v31Zm-7-36V40h64v12Zm20-17V23h8v12Z"/><g fill="var(--paper)"><path d="M137 60h10v9h-10zm14 0h10v9h-10zm14 0h10v9h-10Z"/></g><g fill="none" stroke="currentColor" stroke-width="3"><path d="M205 88V77h44v11m-22-11V65m-15 2h30M106 92v12m13-12v14m151-14v14m13-14v11M70 119h245"/><circle cx="227" cy="70" r="8"/></g></svg>`;

 const deck=t.includes('container')?'<g fill="currentColor" opacity=".65"><path d="M110 65h35v20h-35zm39 0h35v20h-35zm39 0h35v20h-35zm39 0h35v20h-35zm-117-24h35v20h-35zm39 0h35v20h-35zm39 0h35v20h-35z"/></g>':t.includes('tanker')?'<g fill="none" stroke="currentColor" stroke-width="2"><path d="M105 81V69h170v12M120 69V58m40 11V58m40 11V58m40 11V58"/><path d="M115 81h32m7 0h32m7 0h32m7 0h32"/></g>':'<g fill="none" stroke="currentColor" stroke-width="2"><path d="M106 81h43V69h-43zm50 0h43V69h-43zm50 0h43V69h-43zM130 69V36l45 16m30 17V36l45 16"/></g>';
 return `<svg class="ship" viewBox="0 0 380 130" role="img" aria-label="Illustrated merchant vessel"><path fill="currentColor" d="M35 87h291l23-14-16 38H68L35 87Z"/><path fill="currentColor" d="M65 86V56h30v30Zm6-34V40h15v12Z"/><path fill="none" stroke="currentColor" stroke-width="2" d="M77 40V22m-8 9h16M21 117h338"/>${deck}<g fill="var(--paper)"><path d="M70 61h6v5h-6zm10 0h6v5h-6z"/></g></svg>`;
}
function card(i) {
 const d=attackTime(i), c=confirmedCasualties(i), notes=updateNotes(i);
 const image=i.image&&safeURL(i.image.url)&&safeURL(i.image.source_url)&&i.image.credit;
 const meta=[i.vessel_type,i.imo?`IMO ${i.imo}`:null,i.location_text].filter(Boolean).map(esc).join(' · ');
 const sourceCount=links(i.sources).length;
 const nations=c&&Array.isArray(c.nationalities)?c.nationalities.filter(n=>n.status==='confirmed'&&validCount(n.deaths)&&links(n.sources).length):[];
 return `<article class="incident" id="incident-${esc(i.id)}"><div class="date-label"><strong>${new Date(d).toLocaleDateString('en-GB',{day:'2-digit',month:'short',timeZone:'UTC'})}</strong>${new Date(d).getUTCFullYear()}${i.date_approx?' · approx.':''}<span>INCIDENT DATE</span></div><div class="incident-card"><div class="card-top"><span>${esc(i.region_group||i.region)}</span><span class="badge">✓ SOURCE CHECKED</span></div><div class="incident-main"><div><h3>${esc(i.vessel_name)}</h3><div class="vessel-meta">${meta}</div></div><div class="vessel-art" aria-hidden="true">${ship(i.vessel_type)}<span class="illustration-label">VESSEL ILLUSTRATION</span></div></div><p class="incident-summary">${esc(i.summary)}</p>${image?`<figure><img src="${esc(safeURL(i.image.url))}" alt="${esc(i.image.alt||'Sourced image associated with this incident')}" loading="lazy" referrerpolicy="no-referrer"><figcaption>Image: <a href="${esc(safeURL(i.image.source_url))}" target="_blank" rel="noopener noreferrer">${esc(i.image.credit)}</a></figcaption></figure>`:''}<div class="factline">${c?`<div><span>Confirmed deaths / </span><b>${c.deaths}</b></div>`:''}${nations.length?`<div><span>Nationalities / </span><b>${nations.map(n=>`${esc(n.nationality)} (${n.deaths})`).join(', ')}</b></div>`:''}<div><span>Evidence checked / </span><b>${esc(date(i.verification?.checked_at))}</b></div></div>${i.conflicting?'<p class="notice">Accounts differ on some details. See the evidence notes.</p>':''}<details><summary>Read the evidence · ${sourceCount} source links ＋</summary>${i.date_note?`<p><b>Date context:</b> ${esc(i.date_note)}</p>`:''}<p>${esc(i.verification?.note||i.verification?.notes||'Incident identity, date and account reviewed against the linked sources. Each casualty claim requires separate confirmation.')}</p><div class="sources">${sourceHTML(i.sources)}</div>${c?`<p>Confirmed deaths: ${c.deaths}.</p><div class="sources">${sourceHTML(c.sources)}</div>`:'<p>A confirmed casualty total has not yet been established for this incident.</p>'}${nations.map(n=>`<p>${esc(n.nationality)}: ${n.deaths} confirmed deaths.</p><div class="sources">${sourceHTML(n.sources)}</div>`).join('')}${notes.length?`<h4>How the record developed</h4>${notes.map(u=>`<div class="revision"><time>${esc(date(u.at))}</time><p>${esc(u.text)}</p><div class="sources">${sourceHTML(u.sources)}</div></div>`).join('')}`:''}</details></div></article>`;
}
function drawRoute() {
 const journey=root.querySelector('.journey'), svg=$('journey-route'), nodes=[...root.querySelectorAll('.date-label')];
 if(!nodes.length){svg.style.display='none';return;}svg.style.display='';
 const box=journey.getBoundingClientRect(), width=journey.clientWidth, height=journey.clientHeight;
 svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
 const points=nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.right-box.left+(width<400?12.5:width<700?23:32),y:r.top-box.top+(width<400?27.5:32)};});
 let d=`M ${points[0].x} 0 L ${points[0].x} ${points[0].y}`;
 points.slice(1).forEach((p,i)=>{const q=points[i], bend=(width<400?7:width<700?13:24)*(i%2?-1:1);d+=` C ${q.x+bend} ${q.y+(p.y-q.y)*.35}, ${p.x+bend} ${q.y+(p.y-q.y)*.65}, ${p.x} ${p.y}`;});
 d+=` L ${points.at(-1).x} ${height}`;
 $('route-base').setAttribute('d',d);$('route-progress').setAttribute('d',d);routeLength=$('route-progress').getTotalLength();scrollRoute();
}
function scheduleFrame() {
 if (!frame && !document.hidden && rootVisible) frame = requestAnimationFrame(animateFrame);
}
function scrollRoute(){
 const journey=root.querySelector('.journey'), path=$('route-progress');
 if (journey && path?.getAttribute('d')) {
  const box=journey.getBoundingClientRect();
  routeTarget=Math.max(0,Math.min(1,(innerHeight*.6-box.top)/Math.max(1,box.height)));
  if (routeCurrent === null || !motion) routeCurrent=routeTarget;
 }
 const scrollMax = document.documentElement.scrollHeight - innerHeight;
 const progress = $('reading-progress-fill') || root.querySelector('.reading-progress span');
 if(progress) progress.style.transform=`scaleX(${scrollMax>0?Math.max(0,Math.min(1,scrollY/scrollMax)):0})`;
 const cards=[...root.querySelectorAll('.incident')];
 let current=null, distance=Infinity;
 cards.forEach(el=>{const rect=el.getBoundingClientRect();const d=Math.abs(rect.top-innerHeight*.4);if(rect.bottom>0&&rect.top<innerHeight&&d<distance){current=el;distance=d;}});
 if(current!==lastCurrent){lastCurrent?.classList.remove('is-current');current?.classList.add('is-current');lastCurrent=current;}
 scheduleFrame();
}
function animateFrame(now){
 frame=0;
 if(document.hidden||!rootVisible)return;
 const dt=previousFrame?Math.min(48,now-previousFrame):16;previousFrame=now;
 const path=$('route-progress'), vessel=$('route-vessel');
 let settling=false;
 if(path?.getAttribute('d')&&routeLength){
  if(routeCurrent===null)routeCurrent=routeTarget;
  const delta=routeTarget-routeCurrent;
  settling=motion&&Math.abs(delta)>.00005;
  routeCurrent=settling?routeCurrent+delta*(1-Math.exp(-dt/110)):routeTarget;
  const travelled=(motion?routeCurrent:1)*routeLength;
  path.style.strokeDasharray=`${travelled} ${routeLength}`;
  if(vessel){
   const p=path.getPointAtLength(travelled),q=path.getPointAtLength(Math.max(0,travelled-2));
   vessel.style.display=motion?'':'none';
   vessel.setAttribute('transform',`translate(${p.x},${p.y}) rotate(${Math.atan2(p.y-q.y,p.x-q.x)*180/Math.PI+90})`);
  }
  const wake=$('route-wake');
  if(wake){wake.setAttribute('d',path.getAttribute('d'));wake.style.strokeDasharray=`${Math.min(travelled,65)} ${routeLength}`;wake.style.strokeDashoffset=String(-Math.max(0,travelled-65));}
 }
 const heroPath=$('hero-route-path') || root.querySelector('.hero-map svg path:first-of-type'), heroVessel=$('hero-vessel');
 if(motion&&heroVisible&&heroPath&&heroVessel){
  const length=heroPath.getTotalLength();
  if(length){
   heroDistance=(heroDistance+dt*.035)%length;
   const p=heroPath.getPointAtLength(heroDistance),q=heroPath.getPointAtLength(Math.min(length,heroDistance+1));
   heroVessel.setAttribute('transform',`translate(${p.x} ${p.y}) rotate(${Math.atan2(q.y-p.y,q.x-p.x)*180/Math.PI})`);
   const trail=$('hero-trail');if(trail){trail.setAttribute('d',heroPath.getAttribute('d'));trail.style.strokeDasharray=`${Math.min(heroDistance,100)} ${length}`;trail.style.strokeDashoffset=String(-Math.max(0,heroDistance-100));}
  }
 }
 if(settling||(motion&&heroVisible&&heroVessel))scheduleFrame();
}
let layoutFrame=0;
function scheduleLayout(){if(!layoutFrame)layoutFrame=requestAnimationFrame(()=>{layoutFrame=0;fitMap();drawRoute();});}
window.addEventListener('scroll',scrollRoute,{passive:true});
window.addEventListener('resize',scheduleLayout);
root.addEventListener('toggle',scheduleLayout,true);
root.addEventListener('load',scheduleLayout,true);
if(document.fonts)document.fonts.ready.then(scheduleLayout);
if('ResizeObserver' in window)new ResizeObserver(scheduleLayout).observe(root.querySelector('.journey'));
applyMotion();

function render() {
 const query=$('search').value.toLowerCase().trim();
 visible=all.filter(i=>(!$('region').value||(i.region_group || i.region)===$('region').value)&&(!$('status').value||i.vessel_type===$('status').value)&&(!query||[i.vessel_name,i.imo,i.location_text].some(v=>String(v||'').toLowerCase().includes(query))));
 $('result-count').textContent=`${visible.length} reviewed incident records · Hero totals cover all three regions.`;
 if(observer)root.querySelectorAll('#timeline .motion-reveal').forEach(el=>observer.unobserve(el));
 $('timeline').innerHTML=visible.length?visible.slice(0,limit).map(card).join(''):'<p class="empty">No records match these filters. Try another region, evidence level or vessel name.</p>';
 $('timeline').setAttribute('aria-busy','false');$('more').hidden=visible.length<=limit; requestAnimationFrame(drawRoute);
 reveal();
}
function syncMap(region) {
 root.querySelectorAll('.map-choice').forEach(button => {
  const selected=(button.dataset.region||'')===region;
  button.classList.toggle('is-selected',selected);
  button.setAttribute('aria-pressed',String(selected));
 });
 root.querySelectorAll('.map-region').forEach(area => area.classList.toggle('is-selected',Boolean(region)&&area.dataset.region===region));
}
root.querySelectorAll('.map-choice').forEach(button=>button.addEventListener('click',()=>{
 const region=button.dataset.region||'';
 if(region&&!regions.includes(region))return;
 $('region').value=region;limit=16;syncMap(region);render();
}));
syncMap($('region').value);
$('filters').addEventListener('submit',e=>e.preventDefault());
['region','status'].forEach(id=>$(id).addEventListener('change',()=>{limit=16;syncMap($('region').value);render();}));
$('search').addEventListener('input',()=>{limit=16;render();});
$('filters').addEventListener('reset',()=>{setTimeout(()=>{limit=16;syncMap($('region').value);render();},0);});
$('more').addEventListener('click',()=>{const firstNew=visible[limit]?.id;limit+=16;render();if(firstNew)root.querySelector(`#incident-${CSS.escape(firstNew)}`)?.scrollIntoView({behavior:motion?'smooth':'auto',block:'start'});});
function navigateRecord(e) {const a=e.target.closest('[data-record]');if(!a)return;const index=all.findIndex(i=>i.id===a.dataset.record);if(index<0)return;e.preventDefault();$('region').value='';$('status').value='';$('search').value='';limit=Math.max(16,index+1);syncMap('');render();root.querySelector(`#incident-${CSS.escape(a.dataset.record)}`)?.scrollIntoView({behavior:motion?'smooth':'auto',block:'start'});}
$('updates').addEventListener('click',navigateRecord);
$('featured').addEventListener('click',navigateRecord);
function fitMap() {
 const mount = $('hero-map-mount'), svg = mount?.querySelector('svg');
 if (svg) {
  const compact = mount.clientWidth < 520;
  mount.classList.toggle('map-compact', compact);
  svg.setAttribute('viewBox', compact ? '330 0 510 600' : '0 0 1100 600');
 }
}
async function loadMap() {
 const mount = $('hero-map-mount');
 if (!mount) return;
 try {
  const base = new URL(root.dataset.feed || 'living-incidents.json', document.baseURI);
  const response = await fetch(new URL('maritime-map.svg', base), {cache: 'no-cache'});
  if (!response.ok) throw new Error('Map unavailable');
  const parsed = new DOMParser().parseFromString(await response.text(), 'image/svg+xml');
  const svg = parsed.documentElement;
  if (svg.localName !== 'svg' || parsed.querySelector('parsererror')) throw new Error('Map unavailable');
  mount.replaceChildren(document.importNode(svg, true));
  syncMap($('region').value);
  scheduleLayout();
 } catch {
  mount.querySelector('.map-loading').textContent = 'The map is temporarily unavailable. Region filters below remain available.';
 }
}
async function load(){
 try{
  const response=await fetch(root.dataset.feed||'living-incidents.json',{cache:'no-cache'});if(!response.ok)throw new Error('Feed request failed');
  const data=await response.json();const records=Array.isArray(data)?data:data.incidents;if(!Array.isArray(records))throw new Error('Invalid incident feed');
  feedMeta=data.review||{}; const seen=new Set();all=records.filter(i=>i&&typeof i.id==='string'&&!seen.has(i.id)&&seen.add(i.id)&&regions.includes(i.region_group || i.region)&&i.verification?.status==='verified'&&stamp(i.verification.checked_at)&&typeof i.vessel_name==='string'&&i.vessel_name.trim()&&attackTime(i)&&links(i.sources).length&&!i.merged_into).sort((a,b)=>attackTime(b)-attackTime(a)||String(b.id).localeCompare(String(a.id)));
  $('status').innerHTML='<option value="">All vessel types</option>'+[...new Set(all.map(i=>i.vessel_type).filter(Boolean))].sort().map(t=>`<option>${esc(t)}</option>`).join('');
  stats();render();
  if(all.length){const i=all[0];$('featured').hidden=false;$('featured').innerHTML=`<div><span class="eyebrow">MOST RECENT REVIEWED INCIDENT / ${esc(date(i.date_utc))}</span><h2>${esc(i.vessel_name)} <em>↗</em></h2><p>${esc(i.summary)}</p><a href="#incident-${esc(i.id)}" data-record="${esc(i.id)}">${esc(i.location_text||i.region_group||i.region)} · Open the evidence ↓</a></div><div class="featured-art">${ship(i.vessel_type)}<span class="illustration-label">VESSEL ILLUSTRATION · NOT AN INCIDENT PHOTOGRAPH</span></div>`;}
  reveal();
  if(!all.length){$('timeline').innerHTML='<div class="empty"><strong>The record begins with evidence.</strong><p>Reports are being checked for vessel identity, incident date and original supporting sources. Reviewed incidents will appear here; unverified reports are excluded from public totals.</p></div>';$('total').textContent='0';}

 }catch{
  $('scope').textContent='The shared incident feed could not be loaded.';$('result-count').textContent='Records temporarily unavailable.';$('timeline').setAttribute('aria-busy','false');$('timeline').innerHTML='<div class="empty">We could not load the record. No figures are displayed until the source data is available.<button type="button" id="retry">Try again</button></div>';$('updates').innerHTML='<p class="muted">Updates temporarily unavailable.</p>';$('retry').addEventListener('click',load);
 }
}
loadMap();
load();
})();
