// Run only with scripts/documents_preview.py on port 8767; never uses user data.
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
    // Existing saved material must not be selected on a first visit.
    const course = await (await context.request.post(root + '/api/courses', {data: {name: '资料删除 · 隔离验收'}})).json();
    const bytes = fs.readFileSync('data/exam-samples/2025期末练习卷.docx');
    const upload = await context.request.post(`${root}/api/courses/${course.id}/documents`, {multipart: {
      file: {name: '删除验收试卷.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: bytes}, document_type: 'exam'
    }});
    assert.equal(upload.status(), 201);
    const doc = await upload.json();
    await page.goto(root);
    await page.locator('#documents .empty').filter({hasText: '资料库是空的'}).waitFor();
    assert.equal(await page.locator('#course').inputValue(), '');
    assert.equal(await page.locator('#document-count').innerText(), '0');
    assert.equal(await page.locator('#stat-documents').innerText(), '0');
    fs.mkdirSync('docs/screenshots', {recursive: true});
    await page.screenshot({path: 'docs/screenshots/documents-empty.png', fullPage: true, animations: 'disabled'});
    await page.locator('#course').selectOption(course.id);
    await page.locator('.document-delete').waitFor();
    await page.locator(`input[id="doc-${doc.id}"]`).check();
    await page.locator('.document-delete').click();
    assert.equal(await page.locator('#delete-document-name').innerText(), '删除验收试卷.docx');
    await page.screenshot({path: 'docs/screenshots/documents-delete.png', animations: 'disabled'});
    await page.locator('#delete-document-cancel').click();
    assert.equal(await page.locator('.document').count(), 1);
    assert.equal((await context.request.get(`${root}/api/documents/${doc.id}/file`)).status(), 200);
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('#sidebar-toggle').click();
    await page.locator('.document-delete').click();
    const rect = await page.locator('#delete-document-dialog').boundingBox();
    assert.ok(rect.x >= 0 && rect.x + rect.width <= 390);
    await page.locator('#delete-document-confirm').click();
    await page.locator('#documents .empty').filter({hasText: '还没有资料'}).waitFor();
    await page.locator('#document-count').filter({hasText: /^0$/}).waitFor();
    await page.locator('#stat-documents').filter({hasText: /^0$/}).waitFor({state: 'attached'});
    assert.equal((await context.request.get(`${root}/api/documents/${doc.id}/file`)).status(), 404);
    assert.equal(await page.locator('.document-delete').count(), 0);
    assert.ok((await page.locator('#scope-note').innerText()).includes('未勾选'));
    assert.equal((await (await context.request.get(`${root}/api/courses/${course.id}/papers`)).json()).length, 0);
    await page.reload();
    await page.locator('#documents .empty').filter({hasText: '还没有资料'}).waitFor({state: 'attached'});
    assert.equal(await page.locator('#course').inputValue(), course.id);
    await page.locator('#sidebar-toggle').click();
    await page.locator('#course').selectOption('');
    await page.locator('#documents .empty').filter({hasText: '资料库是空的'}).waitFor();
    await page.locator('#sidebar-toggle').click();
    await page.screenshot({path: 'docs/screenshots/documents-empty-mobile.png', fullPage: true, animations: 'disabled'});
    assert.deepEqual(errors, []);
    const result = {empty_first_visit_with_existing_data: true, delete_cancel_preserves_file: true, confirmed_delete_removes_file_and_paper: true, selection_and_stats_refreshed: true, persists_after_reload: true, mobile_dialog: true, javascript_errors: errors};
    fs.writeFileSync('docs/evaluation-documents-ui.json', JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode = 1;});
