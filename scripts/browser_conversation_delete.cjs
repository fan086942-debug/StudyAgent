// All mutations occur in the isolated demo server, never in the user library.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
 const root='http://127.0.0.1:8767';
 page.on('pageerror',e=>errors.push(e.message));
 try{
  const course=await(await context.request.post(root+'/api/courses',{data:{name:'对话删除 · 隔离验收'}})).json();
  await page.goto(root);await page.locator('#course').selectOption(course.id);
  async function ask(question){
   await page.locator('#question').fill(question);
   const response=page.waitForResponse(r=>r.url().endsWith('/api/agent')&&r.request().method()==='POST');
   await page.locator('#ask-button').click();const result=await(await response).json();
   await page.locator('#session-count').filter({hasText:`已串联 ${result.context_turns} 轮`}).waitFor();return result;
  }
  const first=await ask('A*是什么？');const second=await ask('它是如何计算的？');
  await page.locator('[data-view="history"]').first().click();
  const rows=page.locator('#conversation-history .paper-row');await rows.first().waitFor();assert.equal(await rows.count(),2);
  page.once('dialog',d=>d.dismiss());await rows.first().getByRole('button',{name:'删除对话'}).click();assert.equal(await rows.count(),2);
  page.once('dialog',d=>d.accept());await rows.first().getByRole('button',{name:'删除对话'}).click();
  await page.locator('#status').filter({hasText:'对话已删除'}).waitFor();assert.equal(await rows.count(),1);
  assert.equal((await context.request.get(`${root}/api/courses/${course.id}/conversations/${second.conversation_id}`)).status(),404);
  assert.equal((await context.request.get(`${root}/api/courses/${course.id}/conversations/${first.conversation_id}`)).status(),200);
  await page.locator('[data-view="study"]').first().click();await page.locator('#session-count').filter({hasText:'新对话'}).waitFor();
  const third=await ask('BFS是什么？');await page.locator('#session-history summary').click();
  page.once('dialog',d=>d.accept());await page.locator('#session-turns').getByRole('button',{name:'删除对话'}).click();
  await page.locator('#status').filter({hasText:'对话已删除'}).waitFor();assert.equal((await context.request.get(`${root}/api/courses/${course.id}/conversations/${third.conversation_id}`)).status(),404);
  await page.locator('[data-view="history"]').first().click();await rows.first().waitFor();
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  page.once('dialog',d=>d.accept());await rows.first().getByRole('button',{name:'删除对话'}).click();
  await page.locator('#conversation-history .empty').waitFor();
  await page.reload();await page.locator('#sidebar-toggle').click();await page.locator('[data-view="history"]').first().click();await page.locator('#conversation-history .empty').waitFor();
  assert.deepEqual(errors,[]);
  const report={history_delete:true,cancel_keeps_record:true,session_delete:true,dependent_context_reset:true,persists_after_reload:true,mobile_no_overflow:true,javascript_errors:errors};
  fs.writeFileSync('docs/evaluation-conversation-delete-ui.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
