// 运行前启动隔离的 demo 服务并生成 data/exam-samples 样本。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.STUDY_URL || 'http://127.0.0.1:8000');
    await page.locator('#mode').filter({hasText: '演示模式'}).waitFor();
    await page.locator('#course-name').fill('Phase 2 浏览器验收');
    await page.locator('#course-form button').click();
    await page.locator('#status').filter({hasText: '课程已创建'}).waitFor();
    await page.locator('#document-type').selectOption('textbook');
    await page.locator('#files').setInputFiles(path.resolve('data/samples/人工智能教材.pdf'));
    await page.locator('#upload-button').click();
    await page.locator('#status').filter({hasText: '资料已建立索引'}).waitFor({timeout: 60000});
    await page.locator('#document-type').selectOption('exam');
    await page.locator('#files').setInputFiles(path.resolve('data/exam-samples/2025期末练习卷.docx'));
    await page.locator('#upload-button').click();
    await page.locator('.nav-item[data-view="exams"]').click();
    await page.locator('#papers').filter({hasText: '6 道题'}).waitFor({timeout: 60000});
    await page.locator('#question-search-form button').click();
    await page.locator('#question-list .question-item').nth(5).waitFor();
    await page.locator('.nav-item[data-view="study"]').click();
    await page.locator('#question').fill('解释2025期末第12题');
    await page.locator('#ask-button').click();
    await page.locator('#result').waitFor();
    await page.locator('#trace-panel summary').click();
    const chain = await page.locator('.tool-step strong').allTextContents();
    if (chain.length !== 3 || !chain[2].includes('analyze_question')) throw new Error('expected three-step chain');
    if (!(await page.locator('#answer').innerText()).includes('未调用 LLM')) throw new Error('demo notice missing');
    if (!await page.locator('#sources .source').count()) throw new Error('sources missing');
    await page.locator('.nav-item[data-view="exams"]').click();
    await page.locator('#question-list .question-item button').first().click();
    await page.locator('#answer').filter({hasText: '未生成参考答案'}).waitFor();
    await page.waitForTimeout(500);
    await page.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    fs.mkdirSync('data/screenshots', {recursive: true});
    await page.screenshot({path: 'data/screenshots/phase2-desktop.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('mobile overflow');
    await page.screenshot({path: 'data/screenshots/phase2-mobile.png', fullPage: true});
    if (errors.length) throw new Error(errors.join('\n'));
    console.log(JSON.stringify({questions: 6, chain, direct_analysis: true, javascript_errors: 0, mobile_overflow: false}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
