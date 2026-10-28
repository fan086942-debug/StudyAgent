const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.UI_AUDIT_URL || 'http://127.0.0.1:18772';
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 900}, reducedMotion: 'reduce'});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.waitForFunction(() => window.studyAuth?.ready && window.studyRail);
    async function check(expanded) {
      assert.equal(await page.locator('#desktop-sidebar-toggle').getAttribute('aria-expanded'), String(expanded));
      const geometry = await page.evaluate(() => ({
        sidebar: $('sidebar').getBoundingClientRect().width,
        header: document.querySelector('.header-left').getBoundingClientRect().width,
        main: $('workspace').getBoundingClientRect().left,
        overflow: document.documentElement.scrollWidth > innerWidth,
      }));
      assert.equal(Math.round(geometry.sidebar), expanded ? 220 : 96);
      assert.equal(Math.round(geometry.header), expanded ? 220 : 96);
      assert.ok(geometry.main >= geometry.sidebar);
      assert.equal(geometry.overflow, false);
    }
    fs.mkdirSync('.tmp-ui-desk', {recursive: true});
    for (const width of [1440, 1024, 768]) {
      await page.setViewportSize({width, height: 900});
      await page.evaluate(() => studyRail.expand());
      await check(true);
      await page.locator('#desktop-sidebar-toggle').click();
      await check(false);
      await page.screenshot({path: `.tmp-ui-desk/sidebar-collapsed-${width}.png`});
      await page.reload();
      await page.waitForFunction(() => window.studyAuth?.ready && window.studyRail);
      await check(false);
      await page.locator('#desktop-sidebar-toggle').focus();
      await page.keyboard.press('Enter');
      await check(true);
      await page.screenshot({path: `.tmp-ui-desk/sidebar-expanded-${width}.png`});
      await page.keyboard.press('Space');
      await check(false);
      await page.locator('#workspace-library').click();
      await check(true);
      await page.locator('#desktop-sidebar-toggle').click();
      await check(false);
    }
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('#sidebar-toggle').click();
    assert.equal(await page.locator('#sidebar-toggle').getAttribute('aria-expanded'), 'true');
    assert.equal(await page.locator('#course').isVisible(), true);
    await page.locator('#sidebar-overlay').click({position: {x: 370, y: 150}});
    assert.equal(await page.locator('#sidebar-toggle').getAttribute('aria-expanded'), 'false');
    await page.setViewportSize({width: 768, height: 900});
    await check(false);
    await page.evaluate(() => localStorage.removeItem('study-rail-collapsed'));
    await page.reload();
    await page.waitForFunction(() => window.studyAuth?.ready && window.studyRail);
    await check(false);
    await page.locator('#desktop-sidebar-toggle').click();
    await check(true);
    await page.reload();
    await page.waitForFunction(() => window.studyAuth?.ready && window.studyRail);
    await check(true);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed: true, widths: [1440, 1024, 768, 390], persistence: true, keyboard: true, library_reopen: true, javascript_errors: errors}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
