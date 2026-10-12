// Isolated demo UI acceptance. Real model generation is verified by smoke_model_learning --topic-only.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs'), assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage(), errors = [], root = 'http://127.0.0.1:8767';
  page.on('pageerror', error => errors.push(error.message));
  try {
    const course = await (await context.request.post(root + '/api/courses', {data: {name: '按知识点出题 · 隔离验收'}})).json();
    const uploaded = await context.request.post(`${root}/api/courses/${course.id}/documents`, {multipart: {
      file: {name: '合成层次聚类资料.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        buffer: fs.readFileSync('data/topic-test-fixtures/合成层次聚类资料.docx')}, document_type: 'textbook'
    }});
    assert.equal(uploaded.status(), 201);
    await page.goto(root);
    await page.locator('#course').selectOption(course.id);
    await page.locator('.document').waitFor();
    await page.locator('#question').fill('根据层次聚类出两道题目');
    const response = page.waitForResponse(res => res.url().endsWith('/api/agent') && res.request().method() === 'POST');
    await page.locator('#ask-button').click();
    const result = await (await response).json();
    assert.equal(result.finish_reason, 'completed', JSON.stringify(result));
    assert.equal(result.artifacts.length, 1, result.answer);
    assert.deepEqual(result.trace.map(step => step.tool), ['generate_mock_exam']);
    assert.equal(result.trace[0].arguments.question_count, 2);
    assert.deepEqual(result.trace[0].arguments.topics, ['层次聚类']);
    await page.locator('#answer').filter({hasText: '已生成并保存'}).waitFor();
    await page.locator('#generated-artifacts button').click();
    await page.locator('#artifact-preview').waitFor();
    assert.equal(await page.locator('#artifact-content .question-item').count(), 2);
    const answer = page.locator('#artifact-content .question-item').first().locator('details').first();
    await answer.locator('summary').click();
    assert.ok(await answer.getAttribute('open') !== null);
    assert.ok((await answer.innerText()).includes('凝聚层次聚类'));
    await page.locator('#artifact-content button').filter({hasText: '查看这题的教材 / 课件依据'}).first().click();
    assert.ok(await page.locator('#relation-content .source').count() > 0);
    await page.locator('#relation-dialog button[aria-label="关闭学习关联"]').click();
    const download = page.locator('#artifact-downloads a').filter({hasText: '不附答案'});
    const exported = await context.request.get(root + await download.getAttribute('href'));
    assert.equal(exported.status(), 200);
    assert.ok(!(await exported.text()).includes('参考答案与解析'));
    await page.locator('[data-view="study"]').first().click();
    await page.locator('#question').fill('解释第二题，为什么这样做？');
    const explanationResponse = page.waitForResponse(res => res.url().endsWith('/api/agent') && res.request().method() === 'POST');
    await page.locator('#ask-button').click();
    const explanation = await (await explanationResponse).json();
    assert.equal(explanation.context_turns, 2);
    assert.equal(explanation.trace[0].arguments.query, '层次聚类');
    await page.locator('#session-count').filter({hasText: '已串联 2 轮'}).waitFor();
    await page.locator('#question').fill('再来两道题');
    const followResponse = page.waitForResponse(res => res.url().endsWith('/api/agent') && res.request().method() === 'POST');
    await page.locator('#ask-button').click();
    const follow = await (await followResponse).json();
    assert.equal(follow.context_turns, 3, JSON.stringify(follow));
    assert.equal(follow.artifacts.length, 1, follow.answer);
    assert.deepEqual(follow.trace[0].arguments.topics, ['层次聚类']);
    await page.locator('#session-count').filter({hasText: '已串联 3 轮'}).waitFor();
    await page.reload();
    await page.locator('#course').selectOption(course.id);
    await page.locator('#session-count').filter({hasText: '已串联 3 轮'}).waitFor();
    await page.locator('#session-history summary').click();
    assert.equal(await page.locator('#session-turns .session-turn').count(), 3);
    await page.locator('#new-session').click();
    await page.locator('#session-count').filter({hasText: '新对话'}).waitFor();
    assert.equal(await page.locator('#session-turns .session-turn').count(), 0);
    await page.locator('[data-view="generation"]').first().click();
    assert.ok((await page.locator('#artifact-history').innerText()).includes('模拟练习'));
    await page.setViewportSize({width: 390, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(errors, []);
    const report = {request: '根据层次聚类出两道题目', tool: 'generate_mock_exam', questions: 2,
      answer_and_explanation: true, source_modal: true, questions_only_download: true,
      persisted_after_reload: true, contextual_question_followup: true, contextual_generation: true,
      session_restored_after_reload: true, new_session_clears_context: true,
      mobile_no_overflow: true, javascript_errors: errors};
    fs.writeFileSync('docs/evaluation-topic-generation-ui.json', JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
