(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const size = (n) => { if (n == null) return '—'; if (n < 1024) return `${n} B`; const u=['KB','MB','GB','TB']; let v=n, i=-1; do {v/=1024;i++;} while(v>=1024&&i<u.length-1); return `${v.toFixed(v>=100?0:v>=10?1:2)} ${u[i]}`; };
  const pct = n => n == null ? '—' : `${Number(n).toFixed(1)}%`;
  const duration = s => { if (s == null) return '—'; const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60); return `${d?d+'d ':''}${h}h ${m}m`; };
  const portText = maps => (maps||[]).length ? maps.map(p => `${p.host_ip || '0.0.0.0'}:${p.published || '—'} → ${p.container}`).join('<br>') : '—';
  let latest = [];
  let latestImages = [];
  let selectedId = null;
  let imagesOpen = false;
  const IMAGE_PREVIEW = 5;
  try { latest = JSON.parse($('initial-containers').textContent); } catch (e) { latest = []; }
  try { latestImages = JSON.parse($('initial-images').textContent); } catch (e) { latestImages = []; }

  function status(c) { const s=c.status==='running'?'●':'○'; const health=c.health&&c.health!=='healthy'?` · ${c.health}`:''; return `<span class="status ${esc(c.status)}">${s} ${esc(c.status)}${health}</span>`; }
  function renderContainers(list) {
    const q=($('search').value||'').toLowerCase(); const sort=$('sort').value;
    list=list.filter(c => `${c.name} ${c.image} ${c.compose_project||''} ${c.compose_service||''}`.toLowerCase().includes(q));
    list.sort((a,b)=> sort==='cpu' ? (b.stats?.cpu_percent||-1)-(a.stats?.cpu_percent||-1) : sort==='memory' ? (b.stats?.memory_usage||-1)-(a.stats?.memory_usage||-1) : sort==='status' ? a.status.localeCompare(b.status) : a.name.localeCompare(b.name));
    $('containers').innerHTML=list.length?list.map(c=>`<div class="row container-row${c.id===selectedId?' selected':''}" data-container-id="${esc(c.id)}"><span>${esc(c.name)}</span><span>${esc(c.image)}</span>${status(c)}<span>${pct(c.stats?.cpu_percent)}</span><span>${size(c.stats?.memory_usage)}</span><span>${size(c.stats?.network_rx)} / ${size(c.stats?.network_tx)}</span><span class="ports">${esc(c.ports_text||'—')}</span></div>`).join(''):'<div class="empty">No matching containers.</div>';
  }
  function renderProjects(projects) {
    $('projects').innerHTML=projects.length?projects.map(p=>`<div class="project"><div class="project-heading"><strong>${esc(p.name)}</strong><span>${p.running} / ${p.total} running · ${pct(p.resources?.cpu_percent)} CPU · ${size(p.resources?.memory_usage)}</span></div>${p.containers.map(c=>`<div class="row project-row"><span>${esc(c.compose_service||c.name)}</span><span>${esc(c.image)}</span>${status(c)}<span>${pct(c.stats?.cpu_percent)}</span><span>${size(c.stats?.memory_usage)}</span></div>`).join('')}</div>`).join(''):'<div class="empty">No Compose projects detected.</div>';
  }
  function renderImages(images) {
    latestImages=images||[];
    const btn=$('images-toggle');
    if (!latestImages.length) {
      $('images').innerHTML='<div class="empty">No images.</div>';
      btn.hidden=true;
      return;
    }
    const shown=imagesOpen?latestImages:latestImages.slice(0, IMAGE_PREVIEW);
    $('images').innerHTML=shown.map(i=>`<div class="row image-row"><span>${esc(i.tags?.[0]||i.short_id)}</span><span>${size(i.size)}</span><span>${esc(i.age_text||'—')}</span><span class="status ${i.in_use?'running':'exited'}">${esc(i.use_text||'—')}</span><span>${esc(i.used_by_text||'—')}</span></div>`).join('');
    if (latestImages.length<=IMAGE_PREVIEW) { btn.hidden=true; return; }
    btn.hidden=false;
    btn.textContent=imagesOpen?`Show less`:`View all (${latestImages.length})`;
  }
  function renderSystem(s) {
    $('connection').className='connection connected'; $('connection').textContent='● connected'; $('notice').hidden=true;
    $('container-count').textContent=s.containers; $('running-count').textContent=s.running; $('stopped-count').textContent=s.stopped; $('image-count').textContent=s.images;
    $('engine-info').textContent=`Docker ${s.docker_version||'unknown'} · ${s.hostname||'local engine'}`;
    const h=s.host||{}; const m=h.memory||{},d=h.disk,c=h.cpu||{};
    $('ram-used').textContent=size(m.used); $('ram-total').textContent=` / ${size(m.total)}`; $('ram-percent').textContent=pct(m.percent); $('ram-available').textContent=size(m.available);
    $('disk-used').textContent=d?size(d.used):'—'; $('disk-total').textContent=d?` / ${size(d.total)}`:''; $('disk-percent').textContent=d?pct(d.percent):'—'; $('disk-available').textContent=d?size(d.available):'—';
    $('cpu-load').textContent=c.load_1m??'—'; $('cpu-load-percent').textContent=c.load_percent_of_cores!=null?` / ${pct(c.load_percent_of_cores)}`:''; $('cpu-cores').textContent=c.cores??'—';
  }
  function renderDetail(c) {
    const s=c.stats||{};
    $('detail-section').hidden=false;
    $('container-detail').innerHTML=[['name',c.name],['image',c.image],['status',c.status],['uptime',duration(c.uptime_seconds)],['health',c.health],['project',c.compose_project],['service',c.compose_service],['CPU',pct(s.cpu_percent)],['memory',`${size(s.memory_usage)} / ${size(s.memory_limit)} (${pct(s.memory_percent)})`],['network I/O',`${size(s.network_rx)} / ${size(s.network_tx)}`],['block I/O',`${size(s.block_read)} / ${size(s.block_write)}`],['PIDs',s.pids],['restart count',c.restart_count],['ports',portText(c.port_mappings)]].map(([k,v])=>`<div><span>${esc(k)}</span><strong>${k==='ports'?v:esc(v==null||v===''?'—':v)}</strong></div>`).join('');
  }
  function unavailable(){ $('connection').className='connection disconnected'; $('connection').textContent='× Docker unavailable'; $('notice').hidden=false; $('notice').textContent='Unable to connect to Docker Engine. Check Docker and socket permissions.'; }
  async function refresh(){
    const btn=$('refresh');
    btn.disabled=true; btn.textContent='Refreshing…';
    try {
      const r=await fetch('/api/snapshot',{cache:'no-store'});
      const d=await r.json();
      if (!r.ok || !d.connected) throw Error();
      renderSystem(d.system); latest=d.containers||[]; renderContainers(latest); renderProjects(d.projects||[]); renderImages(d.images||[]);
      if (selectedId) {
        const c=latest.find(x=>x.id===selectedId);
        if (c) renderDetail(c); else { selectedId=null; $('detail-section').hidden=true; }
      }
    } catch(e){ unavailable(); }
    finally { btn.disabled=false; btn.textContent='Refresh'; }
  }
  document.addEventListener('click',e=>{
    const row=e.target.closest('.container-row');
    if(!row?.dataset.containerId) return;
    selectedId=row.dataset.containerId;
    document.querySelectorAll('.container-row.selected').forEach(el=>el.classList.remove('selected'));
    row.classList.add('selected');
    const c=latest.find(x=>x.id===selectedId);
    if (c) renderDetail(c);
  });
  $('refresh').addEventListener('click', refresh);
  $('images-toggle').addEventListener('click',()=>{ imagesOpen=!imagesOpen; renderImages(latestImages); });
  $('search').addEventListener('input',()=>renderContainers(latest));
  $('sort').addEventListener('change',()=>renderContainers(latest));
})();
