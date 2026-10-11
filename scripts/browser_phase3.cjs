// 对隔离 demo 服务执行；先用 evaluate_generation.make_sample 创建 data/phase3-notes.docx。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1080}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.STUDY_URL || 'http://127.0.0.1:8000');
    await page.locator('#mode').filter({hasText: '演示模式'}).waitFor();
    await page.locator('#course-name').fill('Phase 3 浏览器验收');
    await page.locator('#course-form button').click();
    await page.locator('#status').filter({hasText: '课程已创建'}).waitFor();
    await page.locator('#document-type').selectOption('notes');
    await page.locator('#files').setInputFiles(path.resolve('data/phase3-notes.docx'));
    await page.locator('#upload-button').click();
    await page.locator('#status').filter({hasText: '资料已建立索引'}).waitFor({timeout: 60000});
    await page.locator('.nav-item[data-view="generation"]').click();
    await page.locator('#generation-topics').fill('A* 评价函数');
    await page.locator('#generate-button').click();
    await page.locator('#generation-status').filter({hasText: '已生成并保存'}).waitFor({timeout: 60000});
    await page.locator('#artifact-content h3').filter({hasText: 'A* 评价函数'}).waitFor();
    await page.locator('#generation-kind').selectOption('mock_exam');
    await page.locator('#generate-button').click();
    await page.locator('#generation-status').filter({hasText: '已生成并保存'}).waitFor({timeout: 60000});
    if (await page.locator('#artifact-content .question-item').count() !== 3) throw new Error('question count');
    await page.locator('#artifact-content details summary').first().click();
    await page.locator('#artifact-content details[open]').waitFor();
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('link', {name: '下载题目卷（不附答案）'}).click();
    const download = await downloadEvent;
    const text = fs.readFileSync(await download.path(), 'utf8');
    if (text.includes('## 参考答案与解析') || text.includes('## 来源原文快照')) throw new Error('answer leakage');
    await page.reload();
    await page.locator('.nav-item[data-view="generation"]').click();
    await page.locator('#artifact-history button').nth(1).waitFor();
    await page.locator('#artifact-history button').first().click();
    await page.locator('#artifact-content .question-item').nth(2).waitFor();
    await page.locator('.nav-item[data-view="study"]').click();
    await page.locator('#question').fill('生成 A* 评价函数 复习资料');
    await page.locator('#ask-button').click();
    await page.locator('#generated-artifacts button').waitFor({timeout: 60000});
    await page.locator('#generated-artifacts button').click();
    await page.locator('#artifact-title').filter({hasText: '复习资料'}).waitFor();
    fs.mkdirSync('data/screenshots', {recursive: true});
    await page.screenshot({path: 'data/screenshots/phase3-desktop.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('mobile overflow');
    await page.screenshot({path: 'data/screenshots/phase3-mobile.png', fullPage: true});
    if (errors.length) throw new Error(errors.join('\n'));
    console.log(JSON.stringify({review: true, mock_questions: 3, download: true, persisted: true,
      agent_generation: true, javascript_errors: errors.length, mobile_overflow: false}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
