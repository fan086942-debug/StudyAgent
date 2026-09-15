// 可选网页冒烟验证：需要可用的 Playwright 与 Microsoft Edge。
// PLAYWRIGHT_MODULE 可指定已安装的 Playwright 包路径；不属于后端运行依赖。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8000');
    await page.locator('#mode').filter({ hasText: '演示模式' }).waitFor();
    await page.locator('#course-name').fill('人工智能导论 · 示例课程');
    await page.locator('#course-form button').click();
    await page.locator('#status').filter({ hasText: '课程已创建' }).waitFor();
    const files = ['人工智能教材.pdf', '搜索算法课件.pptx', '教师复习重点.docx'];
    await page.locator('#files').setInputFiles(files.map(name => path.resolve('data/samples', name)));
    await page.locator('#upload-button').click();
    await page.locator('#status').filter({ hasText: '资料已建立索引' }).waitFor({ timeout: 60000 });
    if (await page.locator('.document').count() !== 3) throw new Error('expected 3 documents');
    await page.locator('#question').fill('A* 的 g(n) 表示什么？');
    await page.locator('#ask-button').click();
    await page.locator('#result').waitFor();
    if (await page.locator('.source').count() === 0) throw new Error('expected source cards');
    if (!(await page.locator('#answer').innerText()).includes('未调用 LLM')) throw new Error('mode disclosure missing');
    fs.mkdirSync('data/screenshots', { recursive: true });
    await page.screenshot({ path: 'data/screenshots/desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('mobile overflow');
    await page.screenshot({ path: 'data/screenshots/mobile.png', fullPage: true });
    if (errors.length) throw new Error(errors.join('\n'));
    console.log(JSON.stringify({ browser: 'Edge', documents: 3,
      source_cards: await page.locator('.source').count(), javascript_errors: errors.length,
      mobile_overflow: false, screenshots: 'data/screenshots' }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
