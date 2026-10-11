// Read-only UI smoke check against an existing server; rejects all API writes.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const errors = [], writes = [], results = {};
  const output = path.resolve('docs/screenshots');
  fs.mkdirSync(output, {recursive: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1100}});
  await context.route('**/api/**', route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) {
      writes.push(route.request().method());
      return route.abort();
    }
    return route.continue();
  });
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const ready = async () => {
    await page.goto(process.env.STUDY_URL || 'http://127.0.0.1:8000');
    await page.locator('#mode').filter({hasText: /模式/}).waitFor();
    await page.locator('#document-count').filter({hasText: /[1-9]/}).waitFor();
  };
  const selectPalette = async palette => {
    await page.locator('#palette-menu > summary').click();
    await page.locator(`#palette-menu button[data-palette="${palette}"]`).click();
    assert.equal(await page.locator('html').getAttribute('data-palette'), palette);
    assert.equal(await page.locator(`#palette-menu button[data-palette="${palette}"]`).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('#palette-menu').evaluate(el => el.open), false);
  };
  const screenshot = name => page.screenshot({path: path.join(output, `vibrant-${name}.png`), fullPage: true, animations: 'disabled'});
  try {
    await ready();
    for (const palette of ['aurora', 'ocean', 'sunset']) {
      await selectPalette(palette);
      await screenshot(palette);
      await page.locator('#theme-toggle').click();
      assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
      if (palette === 'aurora') await screenshot('dark');
      await page.locator('#theme-toggle').click();
    }
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-palette'), 'sunset');
    await page.locator('#theme-toggle').click();
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
    await page.locator('#theme-toggle').click();
    await selectPalette('aurora');
    results.palette_theme_persistence = true;

    await page.locator('#palette-menu > summary').click();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#palette-menu').evaluate(el => el.open), false);
    await page.locator('#palette-menu > summary').click();
    await page.locator('.hero h1').click();
    assert.equal(await page.locator('#palette-menu').evaluate(el => el.open), false);
    results.palette_dismiss = true;

    const hero = page.locator('.hero');
    await hero.hover({position: {x: 70, y: 55}});
    await page.waitForFunction(() => document.querySelector('.hero').style.getPropertyValue('--parallax-x') !== '');
    await page.mouse.move(1, 1);
    assert.equal(await hero.evaluate(el => el.style.getPropertyValue('--parallax-x')), '');
    const card = page.locator('.capability-card').first();
    await card.hover({position: {x: 35, y: 30}});
    await page.waitForFunction(() => document.querySelector('.capability-card').style.getPropertyValue('--tilt-x') !== '');
    await card.click();
    await page.waitForFunction(() => document.querySelectorAll('.button-pulse').length === 0);
    assert.ok((await page.locator('#question').inputValue()).length > 0);
    results.pointer_and_prompt = true;

    for (const view of ['generation', 'exams', 'learning', 'history', 'study']) {
      await page.locator(`.nav-item[data-view="${view}"]`).click();
      await page.locator(`#view-${view}`).waitFor();
    }
    await page.keyboard.press('Control+k');
    await page.locator('#command-search').fill('错题');
    await page.keyboard.press('Enter');
    await page.locator('#view-learning').waitFor();
    await page.locator('.nav-item[data-view="study"]').click();
    results.navigation_and_shortcuts = true;

    results.responsive = [];
    for (const width of [320, 390, 768, 1024, 1440]) {
      await page.setViewportSize({width, height: 900});
      await page.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
      const dimensions = await page.evaluate(() => ({viewport: innerWidth, content: document.documentElement.scrollWidth}));
      assert.ok(dimensions.content <= dimensions.viewport, `Overflow at ${width}: ${dimensions.content}`);
      await page.locator('#palette-menu > summary').click();
      const bounds = await page.locator('.palette-popover').boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width, `Palette outside viewport at ${width}`);
      await page.keyboard.press('Escape');
      if (width <= 700) {
        await page.locator('#sidebar-toggle').click();
        await page.locator('.nav-item[data-view="learning"]').click();
        assert.equal(await page.locator('#sidebar-toggle').getAttribute('aria-expanded'), 'false');
        await page.locator('#view-learning').waitFor();
        await page.locator('#sidebar-toggle').click();
        await page.locator('.nav-item[data-view="study"]').click();
        if (width === 390) await screenshot('mobile');
      }
      results.responsive.push(dimensions);
    }
    await page.setViewportSize({width: 1440, height: 700});
    await page.evaluate(() => window.scrollTo({top: 600, behavior: 'instant'}));
    await page.locator('#back-to-top').waitFor();
    const transform = await page.locator('.scroll-meter').evaluate(el => getComputedStyle(el).transform);
    assert.notEqual(transform, 'matrix(0, 0, 0, 1, 0, 0)');
    await page.locator('#back-to-top').click();
    await page.waitForFunction(() => scrollY === 0);
    results.scroll_controls = true;

    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.locator('.hero').hover();
    assert.equal(await hero.evaluate(el => el.style.getPropertyValue('--parallax-x')), '');
    assert.equal(await page.locator('.orbit-one').evaluate(el => getComputedStyle(el).animationName), 'none');
    results.reduced_motion = true;
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, []);
    results.javascript_errors = errors;
    results.api_writes = writes.length;
    fs.writeFileSync('docs/evaluation-vibrant-ui.json', JSON.stringify({date: '2026-10-10', ...results}, null, 2) + '\n');
    console.log(JSON.stringify(results, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
