// Real local UI flow; synthetic material and no external model calls.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const root = process.env.STUDY_URL || 'http://127.0.0.1:18773';
  const output = 'data/word-ui-check'; fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce'});
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const created = await context.request.post(root + '/api/courses', {data: {name: '本地Word整理验收'}});
    assert.equal(created.status(), 201);
    const course = await created.json();
    const uploaded = await context.request.post(`${root}/api/courses/${course.id}/documents`, {multipart: {
      file: {name: '合成进程资料.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        buffer: fs.readFileSync('data/exam-word-acceptance/ui-material.docx')}, document_type: 'notes'
    }});
    assert.equal(uploaded.status(), 201);
    await page.goto(root);
    await page.waitForFunction(() => window.studyAuth?.ready);
    assert.equal(await page.locator('.nav-item').count(), 2);
    assert.equal(await page.locator('.nav-item[data-view="exams"], .nav-item[data-view="learning"]').count(), 0);
    await page.locator('#course').selectOption(course.id);
    await page.locator('.document').waitFor();
    await page.locator('#question').fill('根据这进程这部分的知识点出一张试卷');
    await page.locator('#ask-button').click();
    await page.locator('#generated-artifacts button').first().waitFor();
    await page.locator('#result-export .export-offer').waitFor();
    for (const [label, name] of [['题目与答案', 'qa'], ['知识重点', 'knowledge']]) {
      const pending = page.waitForEvent('download');
      await page.locator('#result-export button').filter({hasText: label}).click();
      const download = await pending;
      assert.equal(await download.failure(), null);
      assert.ok(download.suggestedFilename().endsWith('.docx'));
      await download.saveAs(`${output}/${name}.docx`);
      assert.equal(fs.readFileSync(`${output}/${name}.docx`).subarray(0, 2).toString(), 'PK');
    }
    await page.locator('#result-export button').filter({hasText: '暂不整理'}).click();
    assert.equal(await page.locator('#result-export .export-offer').isVisible(), false);
    await page.locator('#generated-artifacts button').first().click();
    await page.locator('#artifact-preview').waitFor();
    assert.equal(await page.locator('#artifact-content .question-item').count(), 5);
    assert.ok(await page.locator('#artifact-downloads .export-offer').isVisible());
    assert.ok((await page.locator('#artifact-downloads .export-offer').boundingBox()).height < 250);
    await page.locator('#artifact-content button').filter({hasText: '查看这题的教材 / 课件依据'}).first().click();
    assert.ok(await page.locator('#relation-content .source').count());
    await page.locator('#relation-dialog button[aria-label="关闭学习关联"]').click();
    await page.locator('#result').scrollIntoViewIfNeeded();
    await page.screenshot({path: output + '/desktop.png', fullPage: true, animations: 'disabled'});
    for (const width of [390, 320]) {
      await page.setViewportSize({width, height: 844});
      await page.locator('#artifact-downloads').scrollIntoViewIfNeeded();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({path: `${output}/mobile-${width}.png`, animations: 'disabled'});
    }
    await page.goto(root + '/#learning');
    await page.waitForFunction(() => location.hash === '#study');
    assert.deepEqual(errors, []);
    const report = {navigation_items: 2, natural_exam_request: true, five_questions: true,
      optional_export_offer: true, qa_word_download: true, knowledge_word_download: true,
      dismiss_offer: true, source_preview: true, mobile_no_overflow: true, errors};
    fs.writeFileSync(output + '/report.json', JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
