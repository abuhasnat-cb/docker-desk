(function () {
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const statusMarkup = (status) => {
    const symbol = status === 'running' ? '●' : '○';
    return `<span class="status ${escapeHtml(status)}">${symbol} ${escapeHtml(status)}</span>`;
  };
  const size = (bytes) => {
    if (!Number.isFinite(bytes) || bytes < 1024) return `${bytes || 0} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let unit = -1;
    do { value /= 1024; unit += 1; } while (value >= 1024 && unit < units.length - 1);
    return `${value.toFixed(value >= 100 ? 0 : value >= 10 ? 1 : 2)} ${units[unit]}`;
  };

  async function refresh() {
    try {
      const [systemResponse, containersResponse, imagesResponse] = await Promise.all([
        fetch('/api/system'), fetch('/api/containers'), fetch('/api/images')
      ]);
      if (!systemResponse.ok || !containersResponse.ok || !imagesResponse.ok) throw new Error('Docker unavailable');
      const system = await systemResponse.json();
      const containersData = await containersResponse.json();
      const imagesData = await imagesResponse.json();
      $('connection').className = 'connection connected';
      $('connection').innerHTML = '<span aria-hidden="true">●</span><span>connected</span>';
      $('container-count').textContent = system.containers;
      $('running-count').textContent = system.running;
      $('stopped-count').textContent = system.stopped;
      $('image-count').textContent = system.images;
      $('engine-info').textContent = `Docker ${system.docker_version || 'unknown'} · ${system.hostname || 'local engine'}`;

      $('containers').innerHTML = containersData.containers.length
        ? containersData.containers.map((c) => `<div class="row"><span>${escapeHtml(c.name)}</span><span>${escapeHtml(c.image)}</span>${statusMarkup(c.status)}</div>`).join('')
        : '<div class="empty">No containers.</div>';

      $('images').innerHTML = imagesData.images.length
        ? imagesData.images.map((i) => `<div class="row"><span>${escapeHtml(i.tags?.[0] || i.short_id)}</span><span>${size(i.size)}</span><span>${i.container_count}</span></div>`).join('')
        : '<div class="empty">No images.</div>';

      $('projects').innerHTML = containersData.projects.length
        ? containersData.projects.map((p) => `<div class="project"><div class="project-heading"><strong>${escapeHtml(p.name)}</strong><span>${p.running} / ${p.total} running</span></div>${p.containers.map((c) => `<div class="row project-row"><span>${escapeHtml(c.compose_service || c.name)}</span><span>${escapeHtml(c.image)}</span>${statusMarkup(c.status)}</div>`).join('')}</div>`).join('')
        : '<div class="empty">No Compose projects detected.</div>';
    } catch (error) {
      $('connection').className = 'connection disconnected';
      $('connection').innerHTML = '<span aria-hidden="true">×</span><span>Docker unavailable</span>';
      $('engine-info').textContent = 'Docker Engine not connected';
    }
  }

  window.setInterval(refresh, 5000);
})();
