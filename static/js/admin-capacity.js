/* 备份与容量 —— 后台「备份容量」分栏。
   全局 $ / esc / toast / adminConfirm 由 admin.html 的内联脚本提供。

   删文件的按钮**故意不做**：手工快照该留哪几个是人的判断（每一个都对应一次
   「万一改坏了要回滚」的时刻），所以只报告 + 给命令，跟内容质检同一条规矩。 */

function cpSize(b) {
  if (!b) return '0';
  if (b >= 1073741824) return (b / 1073741824).toFixed(1) + 'G';
  if (b >= 1048576) return Math.round(b / 1048576) + 'M';
  if (b >= 1024) return Math.round(b / 1024) + 'K';
  return b + 'B';
}

function cpBar(items, total) {
  return `<div class="cp-bar">` + items.map(i =>
    `<i class="${i.cls}" style="width:${total ? Math.max(0.5, i.v * 100 / total) : 0}%" title="${esc(i.label)} ${cpSize(i.v)}"></i>`
  ).join('') + `</div>
    <div class="cp-legend">` + items.map(i =>
    `<span><em class="${i.cls}"></em>${esc(i.label)} <b>${cpSize(i.v)}</b></span>`).join('') + `</div>`;
}

async function loadCapacity() {
  const box = $('#cp-body');
  try {
    const r = await fetch('/api/admin/capacity', { cache: 'no-store' });
    const d = await r.json();
    if (!r.ok) { box.innerHTML = '<p class="ai-tip">读取失败：' + esc(d.error || '') + '</p>'; return; }
    const s = d.states, b = d.backup, sz = d.sizes, dk = d.disk;
    const used = sz.db + sz.uploads + sz.data + b.db_bytes + b.uploads_bytes + d.manual_bytes;

    const snapRows = d.manual_snaps.map(x =>
      `<div class="cp-snap"><span>${esc(x.name)}</span><i>${esc(x.at)}</i><b>${cpSize(x.bytes)}</b></div>`).join('');

    const stuck = d.stuck_tasks.length ? `
      <div class="ql-card warn" style="margin-top:12px;">
        <div class="ql-top"><span class="hl-dot warn"></span><b class="hl-name">卡住的后台任务</b>
          <span class="pill idle">${d.stuck_tasks.length}</span></div>
        <div class="hl-note">还标着 running，但超过 30 分钟没动静。</div>
        <div class="st-recent">${d.stuck_tasks.map(t =>
          `<div><span class="st-t">${esc((t.updated_at || '').slice(5, 16))}</span>
            #${t.id} ${esc(t.kind || '')} · ${esc(t.title || '')} · ${t.progress}/${t.total}</div>`).join('')}</div>
      </div>` : '';

    box.innerHTML = `
      <div class="hl-grid">
        <div class="ql-card ${s.backup}">
          <div class="ql-top"><span class="hl-dot ${s.backup === 'bad' ? 'down' : s.backup}"></span>
            <b class="hl-name">最近备份</b>
            <button class="ubtn" id="cp-run">立即备份</button></div>
          <div class="ql-num"><b>${esc(b.last || '从未备份')}</b></div>
          <div class="hl-note">${b.count} 份快照（最早 ${esc(b.oldest || '—')}），
            最新一份 ${cpSize(b.last_size)}。每天 03:30 自动跑，滚动保留 14 天。
            备份时已做 <code>integrity_check</code>，快照存在即校验通过。</div>
        </div>
        <div class="ql-card ${s.disk}">
          <div class="ql-top"><span class="hl-dot ${s.disk === 'bad' ? 'down' : s.disk}"></span>
            <b class="hl-name">磁盘</b><span class="pill ${s.disk === 'ok' ? 'run' : 'fail'}">${dk.pct}%</span></div>
          <div class="ql-num"><b>${cpSize(dk.free)}</b> 可用 / ${cpSize(dk.total)}</div>
          <div class="hl-note">公考助手一共占 ${cpSize(used)}，其中备份和快照占了大头。</div>
        </div>
      </div>

      <h3 class="st-h">占用构成</h3>
      ${cpBar([
        { label: '数据库', v: sz.db, cls: 'c1' },
        { label: '上传文件', v: sz.uploads, cls: 'c2' },
        { label: '词库数据', v: sz.data, cls: 'c3' },
        { label: '每日备份', v: b.db_bytes, cls: 'c4' },
        { label: '备份镜像', v: b.uploads_bytes, cls: 'c5' },
        { label: '手工快照', v: d.manual_bytes, cls: 'c6' },
      ], used)}

      <h3 class="st-h">手工快照 · ${d.manual_snaps.length} 个 · ${cpSize(d.manual_bytes)}</h3>
      <div class="ai-cfg">
        <p class="ai-tip" style="margin:0 0 10px;">项目根上的 <code>app.db.bak.*</code>，是历次改造前手动留的保命点。
          它们<b>没有保留策略、没人清</b>，是最容易悄悄吃掉几个 G 的地方。
          留哪几个是你的判断，所以这儿只列出来、不给删除按钮。</p>
        <div class="cp-snaps">${snapRows || '<p class="ai-tip" style="margin:0;">没有手工快照。</p>'}</div>
        ${d.manual_snaps.length > 2 ? `<div class="ql-fix" style="margin-top:10px;">
          <code>cd ~/AppStore/apps/gongkao-app &amp;&amp; ls -t app.db.bak.* | tail -n +3 | xargs rm -i</code>
          <button class="ubtn" data-copy="cd ~/AppStore/apps/gongkao-app &amp;&amp; ls -t app.db.bak.* | tail -n +3 | xargs rm -i">复制</button>
        </div><p class="ai-tip" style="margin:6px 0 0;">这条只保留最近 2 个，<code>rm -i</code> 会逐个问你确认。</p>` : ''}
      </div>
      ${stuck}
      <p class="ai-tip" style="margin-top:14px;">目录大小是扫盘算出来的，缓存 5 分钟（上次 ${esc(d.scanned_at)}）。
        近 7 天共 ${d.tasks_7d} 个后台任务。</p>`;
  } catch (e) {
    box.innerHTML = '<p class="ai-tip">读取失败：' + esc(e.message) + '</p>';
  }
}

$('#cp-body').onclick = async (e) => {
  const copy = e.target.closest('[data-copy]');
  if (copy) {
    try {
      await navigator.clipboard.writeText(copy.dataset.copy);
      toast('命令已复制，到终端里跑');
    } catch (_) {
      toast('复制不了，请手动选中', true);
    }
    return;
  }
  if (e.target.id === 'cp-run') {
    if (!await adminConfirm('立刻跑一次备份？\n\n会导出一份数据库快照并同步 uploads，\n库大约 140M，通常几秒到十几秒。', '立即备份')) return;
    toast('备份已启动…');
    try {
      const r = await fetch('/api/admin/services/restart', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ names: ['gongkao-backup.service'] })
      });
      const d = await r.json();
      const v = (d.results || {})['gongkao-backup.service'];
      if (r.ok && v && v.ok) {
        toast('已启动，跑完点刷新看结果');
      } else {
        toast((v && v.msg) || d.error || '启动失败', true);
      }
    } catch (err) { toast(err.message, true); }
  }
};
$('#cp-refresh').onclick = loadCapacity;

loadCapacity();
