/* Shared standalone / WordPress renderer. No credentials or third-party scripts. */
(() => {
'use strict';
const root = document.getElementById('maritime-living');
if (!root || root.dataset.initialized) return;
root.dataset.initialized = 'true';
const $ = id => root.querySelector('#' + id);
const regions = ['Black Sea', 'Red Sea', 'Strait of Hormuz'];
const statuses = ['confirmed', 'reported', 'claimed'];
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
const motion = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const observer = motion && 'IntersectionObserver' in window ? new IntersectionObserver(entries => {entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('reveal');observer.unobserve(entry.target);}});},{threshold:.05}) : null;
function updateNotes(i) {return (Array.isArray(i.updates) ? i.updates : []).filter(u => u && typeof u.text === 'string' && stamp(u.at)).sort((a,b)=>stamp(b.at)-stamp(a.at));}
function stats() {
 $('total').textContent = all.length.toLocaleString('en');
 $('statuses').textContent = statuses.map(s=>`${all.filter(i=>i.status===s).length} ${s}`).join(' · ');
 const known = new Map();all.forEach(i=>{const key=i.imo ? `imo:${i.imo}` : i.vessel_name ? `name:${String(i.vessel_name).trim().toUpperCase()}` : null;if(key)known.set(key,i);});
 $('vessels').textContent=known.size.toLocaleString('en');
 const unknown=all.filter(i=>!i.imo&&!i.vessel_name).length;
 $('unidentified').textContent=`Distinct IMO or vessel names; ${unknown} records have no identity. Names can change.`;
 const casualties=all.map(confirmedCasualties).filter(Boolean);
 $('deaths').textContent=casualties.length ? casualties.reduce((n,c)=>n+c.deaths,0).toLocaleString('en') : 'Unavailable';
 $('death-note').textContent=`${casualties.length} of ${all.length} records have structured confirmed death counts. ${casualties.length<all.length?'Total is incomplete.':'Recorded counts only.'}`;
 const nations=new Map();casualties.forEach(c=>(Array.isArray(c.nationalities)?c.nationalities:[]).forEach(n=>{if(n.status==='confirmed'&&typeof n.nationality==='string'&&n.nationality.trim()&&validCount(n.deaths)&&n.deaths>0&&links(n.sources).length)nations.set(n.nationality.trim(),(nations.get(n.nationality.trim())||0)+n.deaths);}));
 $('nationalities').textContent=nations.size || 'Unavailable';
 $('deaths').classList.toggle('unavailable', !casualties.length);
 $('nationalities').classList.toggle('unavailable', !nations.size);
 $('nationality-note').textContent=nations.size ? [...nations].map(([n,count])=>`${n}: ${count}`).join(' · ') : 'No structured confirmed nationality counts available.';
 const types=new Map();known.forEach(i=>{const t=typeof i.vessel_type==='string'&&i.vessel_type.trim()?i.vessel_type:'Type not established';types.set(t,(types.get(t)||0)+1);});
 $('breakdown').innerHTML=[...types].sort((a,b)=>b[1]-a[1]).map(([type,n])=>`<span class="type-chip">${esc(type)} <b>${n}</b></span>`).join('');
 const dates=all.map(attackTime).filter(Boolean);
 const updated=all.map(i=>stamp(i.last_updated)).filter(Boolean);
 $('scope').textContent=all.length?`Available attack dates: ${dates.length?date(new Date(Math.min(...dates)).toISOString()):'unknown'} onward · Latest record change: ${updated.length?date(new Date(Math.max(...updated)).toISOString()):'unknown'} · UTC`:'No documented records in the selected scope.';
 const recent=all.flatMap(i=>{const notes=updateNotes(i);return notes.length?notes.map(note=>({incident:i,note,at:note.at})):[{incident:i,note:null,at:i.last_updated}];}).sort((a,b)=>stamp(b.at)-stamp(a.at)).slice(0,3);
 $('updates').innerHTML=recent.length?recent.map(({incident:i,note,at})=>`<article class="update"><time>${esc(date(at))}</time><a href="#incident-${esc(i.id)}" data-record="${esc(i.id)}">${esc(i.vessel_name||'Unidentified vessel')} ↗</a><p>${esc(note?.text||'Record updated. A description of the change has not been supplied; see the current account and linked sources.')}</p>${note?`<div class="sources">${sourceHTML(note.sources)}</div>`:''}</article>`).join(''):'<p class="muted">No record updates available.</p>';
}
function card(i) {
 const d=attackTime(i), c=confirmedCasualties(i), notes=updateNotes(i);
 const casualtyText=typeof i.casualties_text==='string'?i.casualties_text:typeof i.casualties==='string'?i.casualties:null;
 const image=i.image&&safeURL(i.image.url)&&safeURL(i.image.source_url)&&i.image.credit;
 const meta=[i.vessel_type||'Vessel type not established',i.imo?`IMO ${i.imo}`:null,i.location_text||i.region].filter(Boolean).map(esc).join(' · ');
 const sourceCount=links(i.sources).length;
 return `<article class="incident" id="incident-${esc(i.id)}"><div class="date-label">${d?`<strong>${new Date(d).toLocaleDateString('en-GB',{day:'2-digit',month:'short',timeZone:'UTC'})}</strong>${new Date(d).getUTCFullYear()}${i.date_approx?' · approx.':''}`:'Date unknown'}</div><div class="incident-card"><div class="card-top"><span>${esc(i.region)} / ${esc(i.id)}</span><span class="badge ${esc(i.status)}">${esc(i.status)}</span></div><h3>${esc(i.vessel_name||'Unidentified vessel')}</h3><div class="vessel-meta">${meta}</div><p class="incident-summary">${esc(i.summary||'An account has not yet been supplied.')}</p>${image?`<figure><img src="${esc(safeURL(i.image.url))}" alt="${esc(i.image.alt||'Sourced image associated with this incident')}" loading="lazy" referrerpolicy="no-referrer"><figcaption>Image: <a href="${esc(safeURL(i.image.source_url))}" target="_blank" rel="noopener noreferrer">${esc(i.image.credit)}</a></figcaption></figure>`:''}<div class="factline"><div><span>Attack / </span><b>${esc(i.attack_type||'Not established')}</b></div><div><span>Confirmed deaths / </span><b>${c?c.deaths:'Not established'}</b></div><div><span>Record updated / </span><b>${esc(date(i.last_updated))}</b></div></div>${i.conflicting?'<p class="notice">Conflicting accounts are recorded. Details may change.</p>':''}<details><summary>Evidence & developing account · ${sourceCount} source links</summary>${casualtyText?`<p><b>Casualty account as reported:</b> ${esc(casualtyText)}</p><p>Reported text is not used to calculate death or nationality totals.</p>`:''}${c?`<p>Structured confirmed death count: ${c.deaths}.</p><div class="sources">${sourceHTML(c.sources)}</div>`:'<p>No structured, sourced confirmed death count is available. This does not establish that there were no casualties.</p>'}${c&&Array.isArray(c.nationalities)?c.nationalities.filter(n=>n.status==='confirmed'&&validCount(n.deaths)&&links(n.sources).length).map(n=>`<p>${esc(n.nationality)}: ${n.deaths} confirmed deaths</p><div class="sources">${sourceHTML(n.sources)}</div>`).join(''):''}<p>Incident sources. Links may repeat a shared original report.</p><div class="sources">${sourceHTML(i.sources)||'No usable source links supplied.'}</div>${notes.length?`<h4>Recorded revisions</h4>${notes.map(u=>`<div class="revision"><time>${esc(date(u.at))}</time><p>${esc(u.text)}</p><div class="sources">${sourceHTML(u.sources)}</div></div>`).join('')}`:'<p>No explicit revision notes have been supplied for this record.</p>'}</details></div></article>`;
}
function render() {
 const query=$('search').value.toLowerCase().trim();
 visible=all.filter(i=>(!$('region').value||(i.region_group || i.region)===$('region').value)&&(!$('status').value||i.status===$('status').value)&&(!query||[i.vessel_name,i.imo,i.location_text].some(v=>String(v||'').toLowerCase().includes(query))));
 $('result-count').textContent=`${visible.length} matching records · Hero totals cover all three regions and all available dates.`;
 $('timeline').innerHTML=visible.length?visible.slice(0,limit).map(card).join(''):'<p class="empty">No records match these filters. Try another region, evidence level or vessel name.</p>';
 $('timeline').setAttribute('aria-busy','false');$('more').hidden=visible.length<=limit;
 if(observer)root.querySelectorAll('.incident').forEach(el=>observer.observe(el));
}
$('filters').addEventListener('submit',e=>e.preventDefault());
['region','status'].forEach(id=>$(id).addEventListener('change',()=>{limit=16;render();}));
$('search').addEventListener('input',()=>{limit=16;render();});
$('filters').addEventListener('reset',()=>{setTimeout(()=>{limit=16;render();},0);});
$('more').addEventListener('click',()=>{const firstNew=visible[limit]?.id;limit+=16;render();if(firstNew)root.querySelector(`#incident-${CSS.escape(firstNew)}`)?.scrollIntoView({behavior:motion?'smooth':'auto',block:'start'});});
$('updates').addEventListener('click',e=>{const a=e.target.closest('[data-record]');if(!a)return;const index=all.findIndex(i=>i.id===a.dataset.record);if(index<0)return;e.preventDefault();$('filters').reset();$('region').value='';$('status').value='';$('search').value='';limit=Math.max(16,index+1);render();root.querySelector(`#incident-${CSS.escape(a.dataset.record)}`)?.scrollIntoView({behavior:motion?'smooth':'auto',block:'start'});});
async function load(){
 try{
  const response=await fetch(root.dataset.feed||'living-incidents.json',{cache:'no-cache'});if(!response.ok)throw new Error('Feed request failed');
  const data=await response.json();const records=Array.isArray(data)?data:data.incidents;if(!Array.isArray(records))throw new Error('Invalid incident feed');
  const seen=new Set();all=records.filter(i=>i&&typeof i.id==='string'&&!seen.has(i.id)&&seen.add(i.id)&&regions.includes(i.region_group || i.region)&&i.vessel_category==='merchant'&&statuses.includes(i.status)&&!i.merged_into).sort((a,b)=>attackTime(b)-attackTime(a)||String(b.id).localeCompare(String(a.id)));
  stats();render();
 }catch{
  $('scope').textContent='The shared incident feed could not be loaded.';$('result-count').textContent='Records temporarily unavailable.';$('timeline').setAttribute('aria-busy','false');$('timeline').innerHTML='<div class="empty">We could not load the record. No figures are displayed until the source data is available.<button type="button" id="retry">Try again</button></div>';$('updates').innerHTML='<p class="muted">Updates temporarily unavailable.</p>';$('retry').addEventListener('click',load);
 }
}
load();
})();
