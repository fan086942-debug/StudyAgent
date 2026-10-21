// Isolated UI acceptance; synthetic material and local demo generation only.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const root = process.env.STUDY_URL || 'http://127.0.0.1:18772';
  const output = 'data/workbench-ui-check';
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce'});
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const created = await context.request.post(root + '/api/courses', {data: {name: '统一工作台验收'}});
    assert.equal(created.status(), 201);
    const course = await created.json();
    const uploaded = await context.request.post(`${root}/api/courses/${course.id}/documents`, {multipart: {
      file: {name: '合成层次聚类资料.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        buffer: fs.readFileSync('data/topic-test-fixtures/合成层次聚类资料.docx')}, document_type: 'textbook'
    }});
    assert.equal(uploaded.status(), 201);
    await page.goto(root);
    await page.waitForFunction(() => window.studyAuth?.ready);
    assert.equal(await page.locator('.nav-item').count(), 4);
    assert.equal(await page.locator('.nav-item[data-view="generation"]').count(), 0);
    assert.equal(await page.getByText('保留原文来源，学得更有把握', {exact: true}).count(), 0);
    assert.equal(await page.locator('#view-study #generation-form').count(), 1);
    assert.equal(await page.locator('#generation-settings').getAttribute('open'), null);
    await page.locator('#course').selectOption(course.id);
    await page.locator('.document').waitFor();
    await page.locator('#question').fill('根据层次聚类出两道题目');
    await page.locator('#ask-button').click();
    await page.locator('#generated-artifacts button').first().waitFor();
    await page.locator('#generated-artifacts button').first().click();
    await page.locator('#artifact-preview').waitFor();
    assert.equal(await page.locator('#artifact-content .question-item').count(), 2);
    assert.equal(new URL(page.url()).hash, '#study');
    await page.locator('#artifact-content button').filter({hasText: '查看这题的教材 / 课件依据'}).first().click();
    assert.ok(await page.locator('#relation-content .source').count() > 0);
    await page.locator('#relation-dialog button[aria-label="关闭学习关联"]').click();
    await page.locator('#open-generation-settings').click();
    assert.equal(await page.locator('#open-generation-settings').getAttribute('aria-expanded'), 'true');
    await page.locator('#generation-kind').selectOption('review');
    await page.locator('#generation-topics').fill('层次聚类');
    await page.locator('#generate-button').click();
    await page.locator('#generation-status').filter({hasText: '已生成并保存'}).waitFor();
    await page.locator('#generation-history > summary').click();
    assert.ok(await page.locator('#artifact-history .paper-row').count() >= 2);
    await page.locator('.nav-item[data-view="exams"]').click();
    assert.equal(await page.locator('#study-generation').isVisible(), false);
    await page.goto(root + '/#generation');
    await page.waitForFunction(() => location.hash === '#study');
    assert.equal(await page.locator('#generation-settings').getAttribute('open') !== null, true);
    await page.locator('#generation-settings > summary').click();
    await page.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    await page.screenshot({path: output + '/desktop.png', fullPage: true, animations: 'disabled'});
    for (const width of [390, 320]) {
      await page.setViewportSize({width, height: 844});
      await page.locator('#open-generation-settings').click();
      assert.ok(await page.locator('#generation-kind').isVisible());
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.locator('#study-generation').scrollIntoViewIfNeeded();
      await page.screenshot({path: `${output}/mobile-${width}.png`, animations: 'disabled'});
      await page.locator('#generation-settings > summary').click();
    }
    assert.deepEqual(errors, []);
    const report = {navigation_items: 4, generation_inside_study: true, chat_generation: true,
      configurable_generation: true, saved_results: true, original_sources: true,
      old_generation_link_redirected: true, slogan_removed: true, mobile_widths: [390, 320], errors};
    fs.writeFileSync(output + '/report.json', JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
