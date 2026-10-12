// Isolated acceptance server: python -m scripts.documents_preview (port 8767).
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const root = 'http://127.0.0.1:8767';
  try {
    const course = await (await context.request.post(root + '/api/courses', {data: {name: '课程删除 · 隔离验收'}})).json();
    const other = await (await context.request.post(root + '/api/courses', {data: {name: '保留这门课'}})).json();
    const bytes = fs.readFileSync('data/exam-samples/2025期末练习卷.docx');
    const upload = await context.request.post(`${root}/api/courses/${course.id}/documents`, {multipart: {
      file: {name: '课程删除验收.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: bytes}, document_type: 'exam'
    }});
    assert.equal(upload.status(), 201);
    const doc = await upload.json();
    await page.goto(root);
    await page.locator('#documents .empty').filter({hasText: '资料库是空的'}).waitFor();
    assert.equal(await page.locator('#course-delete-open').isVisible(), false);
    assert.equal((await (await context.request.get(root + '/health')).json()).max_upload_mb, 200);
    assert.ok((await page.locator('.upload-hint').innerText()).includes('200 MB'));
    await page.locator('#course').selectOption(course.id);
    await page.locator('.document-delete').filter({hasText: /^删除$/}).waitFor();
    await page.locator('#course-delete-open').click();
    assert.equal(await page.locator('#delete-course-name').innerText(), course.name);
    assert.ok((await page.locator('#delete-course-description').innerText()).includes('对话记录'));
    fs.mkdirSync('docs/screenshots', {recursive: true});
    await page.screenshot({path: 'docs/screenshots/courses-delete.png', animations: 'disabled'});
    await page.locator('#delete-course-cancel').click();
    assert.equal((await context.request.get(`${root}/api/documents/${doc.id}/file`)).status(), 200);
    // Busy response leaves the dialog and course intact, then allows retry.
    await page.route(`**/api/courses/${course.id}`, route => route.fulfill({status: 409, contentType: 'application/json', body: JSON.stringify({message: '当前有任务正在处理，请结束后再删除课程'})}));
    await page.locator('#course-delete-open').click();
    await page.locator('#delete-course-confirm').click();
    await page.locator('#delete-course-status').filter({hasText: '当前有任务'}).waitFor();
    await page.waitForFunction(() => !document.getElementById('delete-course-confirm').disabled);
    assert.equal(await page.locator('#delete-course-confirm').isEnabled(), true);
    await page.unroute(`**/api/courses/${course.id}`);
    await page.locator('#delete-course-cancel').click();
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('#sidebar-toggle').click();
    await page.locator('#course-delete-open').click();
    const rect = await page.locator('#delete-course-dialog').boundingBox();
    assert.ok(rect.x >= 0 && rect.x + rect.width <= 390);
    await page.locator('#theme-toggle').evaluate(button => button.click());
    await page.screenshot({path: 'docs/screenshots/courses-delete-mobile-dark.png', animations: 'disabled'});
    await page.locator('#delete-course-confirm').click();
    await page.locator('#delete-course-dialog').waitFor({state: 'hidden'});
    await page.locator('#documents .empty').filter({hasText: '资料库是空的'}).waitFor();
    await page.waitForFunction(id => !Array.from(document.getElementById('course').options).some(o => o.value === id), course.id);
    assert.equal(await page.locator('#course').inputValue(), '');
    assert.equal(await page.locator('#course-delete-open').isVisible(), false);
    assert.equal(await page.locator('#stat-documents').innerText(), '0');
    assert.equal(await page.locator('#document-count').innerText(), '0');
    assert.equal((await context.request.get(`${root}/api/documents/${doc.id}/file`)).status(), 404);
    assert.equal((await context.request.get(`${root}/api/courses/${other.id}/documents`)).status(), 200);
    assert.equal(await page.evaluate(() => localStorage.getItem('study-course')), null);
    await page.reload();
    await page.locator('#documents .empty').filter({hasText: '资料库是空的'}).waitFor({state: 'attached'});
    assert.equal(await page.locator('#course').inputValue(), '');
    await page.locator('#sidebar-toggle').click();
    await page.locator('#course').selectOption(other.id);
    await page.locator('#course-delete-open').waitFor();
    await page.locator('#course-delete-open').click();
    await page.keyboard.press('Escape');
    assert.equal((await context.request.get(`${root}/api/courses/${other.id}/documents`)).status(), 200);
    assert.deepEqual(errors, []);
    const result = {upload_limit_mb: 200, cancel_preserves_data: true, busy_allows_retry: true, mobile_dark_dialog: true, confirmed_delete_removes_file_and_course: true, other_course_preserved: true, empty_selection_stats_and_reload: true, escape_cancels: true, javascript_errors: errors};
    fs.writeFileSync('docs/evaluation-courses-ui.json', JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode = 1;});
