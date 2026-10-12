// Synthetic fixtures and the isolated server only; no writes to the user's library.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs'), assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage(), errors = [], root = 'http://127.0.0.1:8767';
  page.on('pageerror', e => errors.push(e.message));
  try {
    const course = await (await context.request.post(root + '/api/courses', {data: {name: '通用学习 · 隔离验收'}})).json();
    const files = ['人工智能教材.pdf', '搜索算法课件.pptx', '教师复习重点.docx', '关联练习卷.docx'];
    const docs = [];
    for (const name of files) {
      const response = await context.request.post(`${root}/api/courses/${course.id}/documents`, {multipart: {
        file: {name, mimeType: 'application/octet-stream', buffer: fs.readFileSync('data/learning-test-fixtures/' + name)},
        document_type: name === '关联练习卷.docx' ? 'exam' : 'textbook'
      }});
      assert.equal(response.status(), 201); docs.push(await response.json());
    }
    await page.goto(root);
    await page.locator('#course').selectOption(course.id);
    await page.locator('#documents .document').filter({hasText: '搜索算法课件.pptx'}).getByRole('button', {name: '总结知识点', exact: true}).click();
    await page.locator('#generation-status').filter({hasText: '知识点与总结已保存'}).waitFor();
    assert.equal(await page.locator('#artifact-content .question-item').count(), 3);
    assert.equal(await page.locator('#artifact-content .practice-widget').count(), 0);
    await page.locator('#artifact-content button').filter({hasText: '这些知识点有哪些历史题'}).first().click();
    await page.locator('#relation-content .relation-pair').first().waitFor();
    assert.ok((await page.locator('#relation-content').innerText()).includes('匹配知识点：A*'));
    await page.locator('#relation-dialog button[aria-label="关闭学习关联"]').click();
    await page.getByRole('button', {name: '查看已保存的知识点总览 ↗', exact: true}).click();
    await page.locator('#relation-content .question-item').first().waitFor();
    assert.equal(await page.locator('#relation-content .question-item').count(), 3);
    await page.locator('#relation-dialog button[aria-label="关闭学习关联"]').click();
    await page.locator('.nav-item[data-view="exams"]').click();
    await page.locator('#question-keyword').fill('A*');
    await page.locator('#question-search-form button').click();
    await page.locator('#question-list .question-item').first().waitFor();
    await page.locator(`#doc-${docs[0].id}`).check();
    await page.locator('#question-list button').filter({hasText: '定位教材 / 课件依据'}).first().click();
    await page.locator('#relation-content .relation-pair').first().waitFor();
    assert.ok((await page.locator('#relation-content').innerText()).includes('PDF 物理第 1 页'));
    assert.ok((await page.locator('#relation-content').innerText()).includes('人工智能教材.pdf'));
    assert.ok(!(await page.locator('#relation-content').innerText()).includes('搜索算法课件.pptx'));
    await page.screenshot({path: 'docs/screenshots/material-question-links.png', animations: 'disabled'});
    await page.setViewportSize({width: 390, height: 844});
    const widths = await page.evaluate(() => ({view: innerWidth, doc: document.documentElement.scrollWidth,
      dialog: document.querySelector('#relation-dialog').getBoundingClientRect().width}));
    assert.ok(widths.doc <= widths.view && widths.dialog <= widths.view);
    await page.emulateMedia({reducedMotion: 'reduce'});
    assert.equal(await page.locator('.relation-pair').first().evaluate(el => getComputedStyle(el).animationName), 'none');
    await page.screenshot({path: 'docs/screenshots/material-question-links-mobile.png', animations: 'disabled'});
    await page.locator('#relation-content button').filter({hasText: '进入题库练习'}).first().click();
    assert.ok(await page.locator('#view-exams').isVisible());
    assert.deepEqual(errors, []);
    const report = {formats: ['pdf', 'pptx', 'docx'], ppt_summary: true, summary_only: true,
      saved_knowledge_overview: true, material_to_exam: true, exam_to_material: true,
      selected_material_scope: true, real_position_visible: true, practice_navigation: true,
      mobile_no_overflow: true, reduced_motion: true, javascript_errors: errors};
    fs.writeFileSync('docs/evaluation-material-learning-ui.json', JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});
