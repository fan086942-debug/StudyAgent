const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const errors=[], checks={};
 fs.mkdirSync('data/studio-browser-check/screenshots',{recursive:true});
 const shot=name=>`data/studio-browser-check/screenshots/${name}.png`;
 try{
  const p=await browser.newPage({viewport:{width:1440,height:960}});p.setDefaultTimeout(15000);
  p.on('pageerror',e=>errors.push(e.message));
  await p.goto(process.env.STUDY_URL || 'http://127.0.0.1:8767');
  await p.waitForFunction(()=>window.studyAuth?.ready);
  await p.waitForTimeout(500);
  const source=p.locator('.scene-source');
  assert.equal(await source.evaluate(e=>getComputedStyle(e).animationPlayState),'running');
  const first=await source.evaluate(e=>getComputedStyle(e).transform);
  await p.waitForTimeout(600);
  assert.notEqual(await source.evaluate(e=>getComputedStyle(e).transform),first);
  await p.locator('#scene-motion').click();
  assert.equal(await source.evaluate(e=>getComputedStyle(e).animationPlayState),'paused');
  await p.reload();await p.waitForFunction(()=>window.studyAuth?.ready);
  assert.equal(await p.locator('#scene-motion').getAttribute('aria-pressed'),'true');
  await p.locator('#scene-motion').click();
  await p.locator('.nav-item[data-view="history"]').click();await p.waitForTimeout(300);
  assert.equal(await source.evaluate(e=>getComputedStyle(e).animationPlayState),'paused');
  await p.screenshot({path:shot('history-guest'),animations:'disabled'});
  await p.locator('.history-empty button').click();await p.locator('#auth-screen').waitFor();
  await p.screenshot({path:shot('login'),animations:'disabled'});
  await p.locator('#auth-tab-register').click();
  await p.locator('#auth-username').fill(`studio_${Date.now()}`);
  await p.locator('#auth-password').fill('studio browser test 2026');await p.locator('#auth-submit').click();
  await p.locator('#auth-screen').waitFor({state:'hidden'});
  await p.locator('.nav-item[data-view="study"]').click();
  await p.locator('#course-name').fill('算法学习 · 工作空间');await p.locator('#course-form button').click();
  await p.locator('#status').filter({hasText:'课程已创建'}).waitFor();
  for(const question of ['A* 的评价函数如何理解？','梳理启发式搜索与最短路径的关系']){
   await p.locator('#question').fill(question);await p.locator('#ask-button').click();
   await p.locator('#result').waitFor();await p.waitForFunction(()=>!document.getElementById('ask-button').disabled);
   assert.ok(await p.locator('#progress-tools li').count());
  }
  checks.real_stream_tool_feedback=true;
  await p.locator('.nav-item[data-view="history"]').click();
  await p.locator('#conversation-history .history-record').nth(1).waitFor();
  await p.locator('#history-search').fill('A*');
  assert.equal(await p.locator('.history-record:visible').count(),1);
  await p.locator('#history-search').fill('不存在的历史问题');
  assert.ok(await p.locator('#history-filter-empty').isVisible());
  await p.locator('#history-search').fill('');checks.history_search=true;
  await p.evaluate(()=>{document.getElementById('status').textContent='';document.getElementById('toast').hidden=true;});await p.waitForTimeout(450);await p.screenshot({path:shot('history-desktop'),animations:'disabled'});
  await p.locator('#desktop-sidebar-toggle').click();
  assert.equal(await p.locator('#desktop-sidebar-toggle').getAttribute('aria-expanded'),'false');
  await p.screenshot({path:shot('history-focus'),animations:'disabled'});
  await p.reload();await p.waitForFunction(()=>window.studyAuth?.ready);
  assert.ok(await p.locator('body').evaluate(e=>e.classList.contains('rail-collapsed')));
  await p.locator('.nav-item[data-view="study"]').click();
  assert.ok(await p.locator('#view-study').isVisible());
  await p.locator('#desktop-sidebar-toggle').click();checks.collapsible_navigation=true;
  // A held network response exercises the stop control and stale-response guard.
  let release;const blocked=new Promise(resolve=>{release=resolve;});
  await p.route('**/api/agent/stream',async route=>{await blocked;await route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'result',data:{answer:'CANCELLED_RESULT',sources:[],questions:[],trace:[]}})+'\n\n'}).catch(()=>{});});
  await p.locator('#question').fill('测试停止操作');await p.locator('#ask-button').click();
  await p.locator('#analysis-progress').waitFor();await p.locator('#stop-analysis').click();
  assert.ok(await p.locator('#analysis-progress').isHidden());assert.equal(await p.locator('#ask-button').isDisabled(),false);
  release();await p.waitForTimeout(300);
  assert.ok(!(await p.locator('#answer').innerText()).includes('CANCELLED_RESULT'));
  assert.equal(await p.locator('#question').inputValue(),'测试停止操作');
  await p.unroute('**/api/agent/stream');checks.stop_and_draft=true;
  await p.locator('#question').fill('');
  await p.evaluate(()=>{document.getElementById('toast').hidden=true;document.getElementById('status').textContent='';});
  await p.locator('#new-session').click();
  await p.evaluate(()=>{window.scrollTo({top:0,behavior:'instant'});document.getElementById('toast').hidden=true;document.getElementById('status').textContent='';});
  await p.waitForTimeout(400);await p.screenshot({path:shot('workspace-desktop'),animations:'disabled'});
  await p.locator('#theme-toggle').click();await p.screenshot({path:shot('workspace-dark'),animations:'disabled'});await p.locator('#theme-toggle').click();
  for(const width of [320,375,390,768,1024,1440]){
   await p.setViewportSize({width,height:844});
   for(const view of ['study','history']){
    await p.evaluate(v=>showView(v),view);await p.waitForTimeout(100);
    assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`overflow ${view} ${width}`);
   }
  }
  checks.responsive_widths=[320,375,390,768,1024,1440];
  await p.setViewportSize({width:390,height:844});
  await p.screenshot({path:shot('history-mobile'),animations:'disabled'});
  await p.evaluate(()=>showView('study'));await p.screenshot({path:shot('workspace-mobile'),animations:'disabled'});
  await p.setViewportSize({width:1440,height:960});await p.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await source.evaluate(e=>getComputedStyle(e).animationName),'none');
  assert.ok(await p.locator('#scene-motion').isDisabled());checks.motion_pause_resume_offscreen_reduce=true;
  assert.deepEqual(errors,[]);checks.javascript_errors=0;
  fs.writeFileSync('docs/evaluation-studio-ui.json',JSON.stringify(checks,null,2)+'\n');console.log(JSON.stringify(checks));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
