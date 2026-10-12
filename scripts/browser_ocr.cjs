// Uses only synthetic scans and the isolated documents_preview server on 8767.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const context = await browser.newContext({viewport:{width:1440,height:1000}});
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const root = 'http://127.0.0.1:8767';
  try {
    const course = await (await context.request.post(root+'/api/courses',{data:{name:'OCR · 合成扫描页验收'}})).json();
    await page.goto(root);
    await page.locator('#documents .empty').filter({hasText:'资料库是空的'}).waitFor();
    assert.ok((await page.locator('.upload-hint').innerText()).includes('自动 OCR'));
    await page.locator('#course').selectOption(course.id);
    await page.locator('#files').setInputFiles('data/ocr-test-fixtures/scanned-learning.pdf');
    const upload = page.waitForResponse(r => r.url().endsWith(`/api/courses/${course.id}/documents`) && r.request().method()==='POST');
    await page.locator('#upload-button').click();
    const response = await upload;
    assert.equal(response.status(),202);
    const doc = await response.json();
    assert.equal(doc.status,'processing');
    await page.locator('.doc-progress').filter({hasText:'OCR'}).waitFor();
    await page.locator('.doc-progress').scrollIntoViewIfNeeded();
    assert.equal((await context.request.get(root+'/health')).status(),200);
    fs.mkdirSync('docs/screenshots',{recursive:true});
    await page.screenshot({path:'docs/screenshots/ocr-progress.png',fullPage:true,animations:'disabled'});
    // Reload must resume polling the server's existing job, without starting another.
    await page.reload();
    await page.waitForFunction(() => Array.from(document.querySelectorAll('.document label small')).some(n=>n.textContent.includes('可检索')), null, {timeout:60000});
    await page.locator('#upload-button:not([disabled])').waitFor();
    assert.ok((await page.locator('.document').innerText()).includes('本地 OCR'));
    await page.locator('#stat-documents').filter({hasText:/^1$/}).waitFor({state:'attached'});
    await page.locator('#status').filter({hasText:'资料处理完成'}).waitFor({state:'attached'});
    const search = await (await context.request.post(root+'/api/search',{data:{course_id:course.id,document_ids:[doc.id],question:'机器学习 监督学习 训练数据 Machine Learning'}})).json();
    assert.ok(search.sources.length>0);
    assert.ok(search.sources.every(s=>s.location_type==='pdf_page' && s.page>=1 && s.page<=8));
    assert.ok(search.sources.some(s=>s.text.includes('机器学习')));
    await page.setViewportSize({width:390,height:844});
    await page.locator('#sidebar-toggle').click();
    await page.locator('.document').scrollIntoViewIfNeeded();
    await page.screenshot({path:'docs/screenshots/ocr-ready-mobile.png',animations:'disabled'});
    await page.locator('.document-delete').click();
    await page.locator('#delete-document-confirm').click();
    await page.locator('#documents .empty').filter({hasText:'还没有资料'}).waitFor();
    assert.equal((await context.request.get(`${root}/api/documents/${doc.id}/file`)).status(),404);
    assert.equal(fs.existsSync(`data/documents-browser-check/ocr/${doc.id}`),false);
    assert.deepEqual(errors,[]);
    const result = {synthetic_scanned_pdf_only:true, upload_returns_202:true, local_chinese_english_ocr:true, progress_visible:true, reload_resumes_polling:true, searchable_with_real_page_numbers:true, mobile_layout:true, delete_cleans_ocr_cache:true, user_textbook_imported:false, javascript_errors:errors};
    fs.writeFileSync('docs/evaluation-ocr-ui.json',JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify(result,null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
