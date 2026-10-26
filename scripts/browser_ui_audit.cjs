/* Run against an isolated local acceptance server. No external model calls. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.UI_AUDIT_URL || 'http://127.0.0.1:18772';
const out = path.resolve('.tmp-ui-desk');
fs.mkdirSync(out, {recursive: true});
function pdf() {
  const stream = 'BT /F1 16 Tf 50 750 Td (A* search: f\(n\) = g\(n\) + h\(n\).) Tj 0 -30 Td (g is path cost. h is estimated remaining cost.) Tj ET';
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`];
  let data = '%PDF-1.4\n', offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(data)); data += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(data);
  data += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(data);
}
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 900}, reducedMotion: 'reduce'});
    const errors = [], cases = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.waitForFunction(() => window.studyAuth?.ready && window.studyDesk);
    const created = await page.request.post(`${base}/api/courses`, {data: {name: `UI 审查验收 ${Date.now()}`}});
    assert.equal(created.status(), 201);
    const course = (await created.json()).id;
    const uploaded = await page.request.post(`${base}/api/courses/${course}/documents`, {multipart: {file: {name: 'search-reference.pdf', mimeType: 'application/pdf', buffer: pdf()}, document_type: 'textbook'}});
    assert.equal(uploaded.status(), 201, await uploaded.text());
    const doc = await uploaded.json();
    await page.evaluate(id => loadCourses(id), course);
    await page.waitForFunction(() => document.querySelector('#pulse-week strong').textContent === '0');
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
      for (const width of [320, 390, 768, 1024, 1366, 1440]) {
        await page.setViewportSize({width, height: width === 1366 ? 768 : 900});
        await page.evaluate(() => window.scrollTo(0, 0));
        const geometry = await page.evaluate(() => {
          const button = document.querySelector('#ask-button').getBoundingClientRect();
          return {overflow: document.documentElement.scrollWidth > innerWidth, sendVisible: button.bottom <= innerHeight && button.top > 0};
        });
        assert.equal(geometry.overflow, false, `${theme}/${width} horizontal overflow`);
        assert.equal(geometry.sendVisible, true, `${theme}/${width} send below fold`);
        await page.screenshot({path: path.join(out, `signed-${theme}-${width}.png`)});
        cases.push({theme, width, state: 'signed-in', ...geometry});
      }
    }
    await page.setViewportSize({width: 1440, height: 900});
    await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });
    // Real local demo answer supplies a saved conversation and verified citation IDs.
    const answer = await page.request.post(`${base}/api/chat`, {data: {course_id: course, question: 'A* search f(n) g(n) h(n)'}});
    assert.equal(answer.status(), 200, await answer.text());
    const result = await answer.json();
    assert.ok(result.sources.length);
    const generated = await page.request.post(base + '/api/generate', {data: {course_id: course, kind: 'review', topics: ['A*']}});
    assert.equal(generated.status(), 201, await generated.text());
    const artifact = await generated.json();
    // Controlled copy exercises the rich reader; this is an explicit UI fixture.
    const rich = {...result, insufficient_evidence: false, answer_basis: 'materials', warning: '原文页码为 PDF 物理页码，请结合教材标注核对。', answer: `## 从评价函数理解 A*\n\nA* 使用 **f(n) = g(n) + h(n)** 评估候选节点。g(n) 是已付出的路径代价，h(n) 是到目标的估计代价。[${result.sources[0].citation_id}]\n\n### 怎样使用这条依据\n\n- 先区分已知代价与估计代价。\n- 回到原页核对适用条件。\n\n> 依据来自你的课程资料，可以随时打开原页。`};
    await page.evaluate(result => renderResult(result), rich);
    assert.equal(await page.evaluate(() => document.activeElement.textContent), '回答与依据');
    assert.equal(await page.locator('.answer').evaluate(node => getComputedStyle(node).fontSize), '16px');
    await page.locator('#answer .inline-citation').first().click();
    assert.equal(await page.locator('#source-drawer').isVisible(), true);
    await page.waitForFunction(() => {const image = document.querySelector('#source-preview img'); return image?.complete && image.naturalWidth > 0;});
    assert.ok((await page.locator('#source-preview a').first().getAttribute('href')).endsWith('#page=1'));
    await page.screenshot({path: path.join(out, 'answer-source-desktop.png')});
    await page.locator('#source-drawer button').first().click();
    assert.equal(await page.locator('#answer .inline-citation').first().evaluate(node => node === document.activeElement), true);
    assert.equal(await page.locator('#result-export .export-offer').getAttribute('open'), null);
    await page.locator('#result-export summary').click();
    await page.locator('#result-export summary').click();
    await page.evaluate(id => openArtifact(id), artifact.id);
    await page.locator('#artifact-downloads summary').click();
    const download = page.waitForEvent('download');
    await page.locator('#artifact-downloads .export-actions button').first().click();
    assert.ok((await download).suggestedFilename().endsWith('.docx'));
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => {document.documentElement.dataset.theme = theme;}, theme);
      for (const width of [390, 768, 1024, 1440]) {
        await page.setViewportSize({width, height: 900});
        await page.evaluate(result => renderResult(result), rich);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({path: path.join(out, `result-${theme}-${width}.png`)});
        if (width === 390) {
          await page.locator('#answer .inline-citation').first().click();
          assert.equal(await page.locator('#source-drawer').evaluate(node => node.matches(':modal')), true);
          await page.keyboard.press('Escape');
        }
        cases.push({theme, width, state: 'result', overflow: false});
      }
    }
    await page.setViewportSize({width: 1440, height: 900});
    await page.evaluate(async () => {document.documentElement.dataset.theme = 'light'; showView('history'); await loadHistory();});
    assert.ok(await page.locator('.history-day').count());
    assert.ok(await page.locator('.history-excerpt').count());
    await page.screenshot({path: path.join(out, 'history-desktop.png')});
    await page.locator('#history-search').fill('this-query-matches-nothing');
    assert.equal(await page.locator('#history-filter-empty').isVisible(), true);
    assert.equal(await page.locator('.history-day').first().isVisible(), false);
    await page.evaluate(() => {showView('study'); $('new-session').click();});
    assert.equal(await page.locator('body').evaluate(node => node.classList.contains('reading-mode')), false);
    await page.locator('#pulse-week').click();
    assert.equal(await page.locator('#view-learning').isVisible(), true);
    await page.evaluate(() => showView('study'));
    await page.setViewportSize({width: 768, height: 900});
    await page.locator('#workspace-library').click();
    assert.equal(await page.locator('#course').isVisible(), true);
    await page.setViewportSize({width: 1440, height: 900});
    await page.locator('#mode').click();
    await page.waitForFunction(() => !$('connection-model').disabled);
    assert.equal(await page.locator('#connection-dialog').isVisible(), true);
    await page.keyboard.press('Escape');
    await page.locator('#question').fill('A* search f(n) g(n) h(n)');
    await page.locator('#ask-button').click();
    await page.waitForFunction(() => !$('ask-button').disabled && !$('result').hidden);
    assert.equal(await page.locator('#question').inputValue(), '');
    assert.equal(await page.locator('body').evaluate(node => node.classList.contains('reading-mode')), true);
    // Guest bootstrap fixture checks layout; real account isolation is covered by pytest.
    await page.route('**/api/auth/me', route => route.fulfill({json: {enabled: true, user: null, registration_enabled: true, setup_required: false}}));
    await page.reload();
    await page.waitForFunction(() => studyAuth.ready && document.body.dataset.auth === 'guest');
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => {document.documentElement.dataset.theme = theme;}, theme);
      for (const width of [320, 390, 768, 1024, 1440]) {
        await page.setViewportSize({width, height: 900});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({path: path.join(out, `guest-${theme}-${width}.png`)});
        cases.push({theme, width, state: 'guest', overflow: false});
      }
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(out, 'verification.json'), JSON.stringify({passed: true, fixture: 'isolated demo API with controlled rich-answer copy', cases, javascript_errors: errors, source_preview: true, pdf_page_link: true, export_download: true, grouped_history: true, focus_restored: true}, null, 2));
    console.log(JSON.stringify({passed: true, cases: cases.length, screenshots: out, javascript_errors: errors}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
