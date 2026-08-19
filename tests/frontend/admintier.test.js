/* 后台「档位控制」：点一下旋钮，究竟发出去了什么。
 *
 * 这一页几乎全是「渲染 + 点一下就发请求」，而发错的代价是真金白银：
 * 键写错（write 而不是 write:pro）会把便宜的那半也一起动了；
 * 档位名发错（读图那家不认 fast）会 400；确认弹窗答「否」却照发，就等于闸形同虚设。
 * 这些错在界面上都看不出来——按钮照样变色。所以断言全部对着请求体。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { bootAdmin } = require('./harness-admin');

const DATA = {
  win: '30d',
  models: { fast: 'ds-flash', pro: 'ds-pro', vision_free: 'glm-flash', vision_pro: 'glm-pro' },
  vision_configured: true,
  global: { text: '', vision: '' },
  groups: [
    {
      key: 'web', name: '应用内 · 用户触发', services: [
        { key: 'write', name: '大作文成文', desc: '取材走快、成文走旗舰', group: 'web', known: true,
          calls: 88, tokens: 1360195,
          text: { override: '', rows: [
            { tier: 'fast', override: '', effective: 'fast', calls: 5, tokens: 33907, failed: 0 },
            { tier: 'pro', override: '', effective: 'pro', calls: 83, tokens: 1326288, failed: 0 }] },
          vision: { override: '', rows: [] } },
        { key: 'docqa', name: '文档识题', desc: '图要看清才抽得准', group: 'web', known: true,
          calls: 12, tokens: 40000,
          text: { override: '', rows: [{ tier: 'fast', override: '', effective: 'fast', calls: 12, tokens: 40000, failed: 0 }] },
          vision: { override: '', rows: [{ tier: 'pro', override: '', effective: 'pro', calls: 4, tokens: 9000, failed: 0 }] } },
        { key: 'marks', name: '划重点', desc: '标考点', group: 'web', known: true, calls: 0, tokens: 0,
          text: { override: '', rows: [{ tier: 'fast', override: '', effective: 'fast', calls: 0, tokens: 0, failed: 0 }] },
          vision: { override: '', rows: [] } },
      ],
    },
    {
      key: 'cron', name: '定时任务 · 后台自动跑', services: [
        { key: 'gen_essays', name: '范文生成（每日）', desc: 'token 大户', group: 'cron', known: true,
          calls: 349, tokens: 2486584,
          text: { override: '', rows: [{ tier: 'pro', override: '', effective: 'pro', calls: 349, tokens: 2486584, failed: 0 }] },
          vision: { override: '', rows: [] } },
      ],
    },
  ],
};

async function boot(t, opts = {}) {
  const h = bootAdmin({
    // 只加载这一页的脚本：别的分栏各自也会自执行 load*()，它们的失败跟本页无关，
    // 却会在测试结束后冒出一堆 unhandledRejection，把真问题埋掉。
    only: ['js/admin-tier.js'],
    fetch: (url, o) => {
      if (url.indexOf('/api/admin/ai/tiers') === 0) {
        if (!o || o.method !== 'POST') return { json: DATA };
        const body = JSON.parse(o.body);
        return { json: opts.post ? opts.post(body) : { ok: true, changed: 1 } };
      }
      return undefined;
    },
  });
  t.after(() => h.close());
  await h.settle();                 // 先让页面自己的启动请求落地
  return h;
}

const posts = (h) => h.calls.filter(c => c.method === 'POST' && c.url.indexOf('/api/admin/ai/tiers') === 0);

test('混档服务拆成两行分别设，单档的就一个旋钮', async (t) => {
  const h = await boot(t);
  await h.run('loadTier()');
  const write = h.$('.srow[data-svc="write"]');
  const keys = [...write.querySelectorAll('.tr-set')].map(x => x.dataset.key);
  assert.deepStrictEqual(keys, ['write:fast', 'write:pro'],
    '两个档位各自一个键——只想降成文那一半时不该动到取材');

  const essays = h.$('.srow[data-svc="gen_essays"]');
  assert.deepStrictEqual([...essays.querySelectorAll('.tr-set')].map(x => x.dataset.key), ['gen_essays'],
    '单档服务用服务级键就够了');
});

test('会读图的服务多一行读图旋钮，不读图的不摆', async (t) => {
  const h = await boot(t);
  await h.run('loadTier()');
  const kinds = (k) => [...h.$(`.srow[data-svc="${k}"]`).querySelectorAll('.tr-set')].map(x => x.dataset.kind);
  assert.deepStrictEqual(kinds('docqa'), ['text', 'vision']);
  assert.deepStrictEqual(kinds('gen_essays'), ['text']);
});

test('窗口内没跑过的服务先收起来，不占版面', async (t) => {
  const h = await boot(t);
  await h.run('loadTier()');
  assert.ok(h.$('.srow[data-svc="marks"]').closest('.tr-idle'), '0 调用的该在折叠区里');
  assert.ok(h.$('.tr-more'), '得有一个展开它的入口');
  h.$('.tr-more').click();
  assert.ok(!h.$('.tr-idle').classList.contains('hidden'), '点了就展开');
});

test('点旗舰那一行的「快速档」→ 只发 write:pro 这一条', async (t) => {
  const h = await boot(t);
  await h.run('loadTier()');
  const seg = h.all('.srow[data-svc="write"] .tr-set').find(x => x.dataset.key === 'write:pro');
  seg.querySelector('[data-v="fast"]').click();
  await h.settle();
  assert.deepStrictEqual(posts(h)[0].body.set, { 'write:pro': 'fast' });
  assert.deepStrictEqual(posts(h)[0].body.vision, {});
});

test('读图那一行发的是读图的档位名，不是文字那套', async (t) => {
  const h = await boot(t);
  await h.run('loadTier()');
  const seg = h.all('.srow[data-svc="docqa"] .tr-set').find(x => x.dataset.kind === 'vision');
  seg.querySelector('[data-v="free"]').click();
  await h.settle();
  const b = posts(h)[0].body;
  assert.deepStrictEqual(b.vision, { 'docqa:pro': 'free' }, '读图用 free，发 fast 会被后端 400');
  assert.deepStrictEqual(b.set, {});
});

test('降档确认：点「确定」才带 confirmed 重发', async (t) => {
  const h = await boot(t, {
    post: (body) => (body.confirmed
      ? { ok: true, changed: 1 }
      : { ok: false, need_confirm: [{ key: 'gen_essays', kind: 'text', why: '范文生成降档会悄悄变差' }] }),
  });
  await h.run('loadTier()');
  h.$('.srow[data-svc="gen_essays"] .tr-set [data-v="fast"]').click();
  await h.settle();
  assert.strictEqual(h.confirms.length, 1, '得弹一次确认');
  assert.ok(h.confirms[0].text.includes('范文生成降档会悄悄变差'), '后果得原样念给人听，别在前端另编一套');
  assert.deepStrictEqual(posts(h).map(p => !!p.body.confirmed), [false, true]);
});

test('降档确认：点「取消」就不发第二次', async (t) => {
  const h = await boot(t, {
    post: (body) => (body.confirmed
      ? { ok: true, changed: 1 }
      : { ok: false, need_confirm: [{ key: 'gen_essays', kind: 'text', why: '会变差' }] }),
  });
  h.answerConfirm(false);
  await h.run('loadTier()');
  h.$('.srow[data-svc="gen_essays"] .tr-set [data-v="fast"]').click();
  await h.settle();
  assert.strictEqual(posts(h).length, 1, '答了「否」还照发，闸就形同虚设');
  assert.strictEqual(h.toasts.length, 0, '没保存就别说保存了');
});

test('批量：省钱档在两家是两个名字，按位置发', async (t) => {
  const h = await boot(t);
  await h.run('loadTier()');
  h.$('.srow[data-svc="docqa"] .tr-ck').click();
  h.$('.srow[data-svc="gen_essays"] .tr-ck').click();
  assert.ok(!h.$('#tr-bulk').classList.contains('hidden'), '选了就该出现批量条');
  assert.ok(h.text('#tr-cnt').includes('2'));
  h.$('#tr-bulk [data-bulk="cheap"]').click();
  await h.settle();
  const b = posts(h)[0].body;
  assert.deepStrictEqual(b.set, { docqa: 'fast', gen_essays: 'fast' });
  assert.deepStrictEqual(b.vision, { docqa: 'free' }, '只有会读图的才发读图那条');
});

test('「恢复默认」发的是空串——那是唯一的清除方式', async (t) => {
  const h = await boot(t);
  await h.run('loadTier()');
  h.$('.srow[data-svc="gen_essays"] .tr-ck').click();
  h.$('#tr-bulk [data-bulk=""]').click();
  await h.settle();
  assert.deepStrictEqual(posts(h)[0].body.set, { gen_essays: '' });
});

test('全站兜底的旋钮发的是 * 这个键', async (t) => {
  const h = await boot(t);
  await h.run('loadTier()');
  h.$('#tr-global .tr-set[data-kind="text"] [data-v="fast"]').click();
  await h.settle();
  assert.deepStrictEqual(posts(h)[0].body.set, { '*': 'fast' });
});
