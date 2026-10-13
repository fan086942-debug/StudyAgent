const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const report={},errors=[];fs.mkdirSync('data/professional-browser-check/screenshots',{recursive:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:960}}),p=await context.newPage();
  p.setDefaultTimeout(20000);p.on('pageerror',e=>errors.push(e.message));
  const root=process.env.STUDY_URL || 'http://127.0.0.1:8767';
  await p.goto(root);await p.waitForFunction(()=>window.studyAuth?.ready);
  await p.screenshot({path:'data/professional-browser-check/screenshots/guest.png',fullPage:true,animations:'disabled'});
  await p.locator('#login-open').click();await p.locator('#auth-tab-register').click();
  assert.equal(await p.locator('#auth-password').getAttribute('minlength'),'6');
  assert.equal(await p.locator('#auth-password').getAttribute('maxlength'),null);
  await p.locator('#auth-username').fill(`review_${Date.now()}`);await p.locator('#auth-password').fill('123456');
  await p.locator('#auth-submit').click();await p.locator('#auth-screen').waitFor({state:'hidden'});report.six_digit_password=true;
  await p.locator('#course-name').fill('人工智能 · 资料与上下文验收');await p.locator('#course-form button').click();
  await p.locator('#status').filter({hasText:'课程已创建'}).waitFor();const course=await p.locator('#course').inputValue();
  const files=[['人工智能教材.pdf','data/learning-test-fixtures/人工智能教材.pdf','textbook'],['搜索算法课件.pptx','data/learning-test-fixtures/搜索算法课件.pptx','textbook'],['教师复习重点.docx','data/learning-test-fixtures/教师复习重点.docx','notes'],['关联练习卷.docx','data/learning-test-fixtures/关联练习卷.docx','exam'],['合成层次聚类资料.docx','data/topic-test-fixtures/合成层次聚类资料.docx','textbook']];
  const docs=[];
  for(const [name,path,kind] of files){
   const r=await context.request.post(`${root}/api/courses/${course}/documents`,{multipart:{file:{name,mimeType:'application/octet-stream',buffer:fs.readFileSync(path)},document_type:kind}});
   assert.equal(r.status(),201,await r.text());const doc=await r.json();assert.equal(doc.status,'ready');assert.ok(doc.chunk_count>0);docs.push(doc);
  }
  report.formats=['pdf','pptx','docx'];report.read_and_index=true;
  await p.locator('#refresh').click();await p.locator('#documents .document').nth(4).waitFor();
  const ask=async question=>{
   await p.evaluate(()=>showView('study'));await p.locator('#question').fill(question);
   await p.evaluate(()=>{
    window.reviewResult=null;
    if(!window.reviewWrapped){const original=renderResult;window.renderResult=function(result){window.reviewResult=result;return original(result);};window.reviewWrapped=true;}
   });
   await p.locator('#ask-button').click();
   await p.waitForFunction(()=>window.reviewResult!==null);
   const result=await p.evaluate(()=>window.reviewResult);
   await p.locator('#result').waitFor();await p.waitForFunction(()=>!document.getElementById('ask-button').disabled);
   return result;
  };
  await p.locator(`#doc-${docs[0].id}`).check();
  const locate=await ask('教材哪里讲了 A*？');
  assert.ok(locate.sources.length,JSON.stringify(locate));assert.ok(locate.sources.every(s=>s.document_id===docs[0].id));
  await p.locator('#sources-tab').click();await p.locator('#sources .source').first().waitFor();
  assert.ok((await p.locator('#sources').innerText()).includes('PDF 物理第 1 页'));report.source_scope_and_position=true;
  await p.locator('#answer-tab').click();
  if(await p.locator('#answer .inline-citation').count()){
    await p.locator('#answer .inline-citation').first().click();assert.equal(await p.locator('#sources-tab').getAttribute('aria-selected'),'true');
  }
  await p.locator(`#doc-${docs[0].id}`).uncheck();
  await p.locator(`#doc-${docs[4].id}`).check();
  const generation=await ask('根据层次聚类出两道题目');assert.equal(generation.artifacts.length,1);assert.equal(generation.context_turns,1);
  await p.locator('#generated-artifacts button').click();await p.locator('#artifact-preview').waitFor();
  assert.equal(await p.locator('#artifact-content .question-item').count(),2);report.generate_two_questions=true;
  const noAnswers=p.locator('#artifact-downloads a').filter({hasText:'不附答案'});
  const exported=await context.request.get(root+await noAnswers.getAttribute('href'));assert.equal(exported.status(),200);assert.ok(!(await exported.text()).includes('参考答案与解析'));report.questions_only_export=true;
  const follow=await ask('解释一下第二题，为什么这样做？');assert.equal(follow.context_turns,2);assert.ok(follow.sources.length);
  const more=await ask('再来两道题');assert.equal(more.context_turns,3);assert.equal(more.artifacts.length,1);assert.deepEqual(more.trace[0].arguments.topics,['层次聚类']);
  await p.reload();await p.locator('#session-count').filter({hasText:'已串联 3 轮'}).waitFor();
  assert.equal(await p.locator(`#doc-${docs[4].id}`).isChecked(),true);report.reload_restores_selected_scope_and_context=true;
  const continued=await ask('解释第二题，为什么这样做？');assert.equal(continued.context_turns,4,JSON.stringify(continued));assert.ok(continued.trace[0].arguments.query.includes('层次聚类'));report.contextual_followup=true;
  await p.locator('.nav-item[data-view="exams"]').click();await p.locator('#question-keyword').fill('A*');await p.locator('#question-search-form button').click();
  await p.locator('#question-list .question-item').first().waitFor();assert.ok((await p.locator('#question-list').innerText()).includes('A*'));report.exam_search=true;
  // Rendered model text stays inert, while supported headings and source links are usable.
  await p.evaluate(()=>renderResult({answer:'# 测试回答\n\n**重点**与依据 [S1]\n<script>window.BAD=true</script><img src=x onerror="window.BAD=true">',sources:[{citation_id:'S1',text:'合成测试来源',document_id:'test',document_name:'测试笔记',location_type:'paragraph',block_index:0,page:null,chapter:null,section:null,file_url:'#',chunk_id:'test'}],questions:[],artifacts:[],trace:[],total_ms:1}));
  assert.equal(await p.evaluate(()=>!!window.BAD),false);assert.equal(await p.locator('#answer script,#answer img').count(),0);assert.equal(await p.locator('#answer strong').innerText(),'重点');
  await p.locator('#answer .inline-citation').click();assert.ok(await p.locator('#source-panel').isVisible());
  await p.locator('#sources-tab').focus();await p.keyboard.press('ArrowLeft');assert.ok(await p.locator('#answer-panel').isVisible());report.safe_answer_and_keyboard_source_tabs=true;
  await p.locator('#new-session').click();await p.evaluate(()=>{window.scrollTo({top:0,behavior:'instant'});document.getElementById('status').textContent='';document.getElementById('toast').hidden=true;});
  await p.waitForTimeout(400);await p.screenshot({path:'data/professional-browser-check/screenshots/workspace.png',fullPage:true,animations:'disabled'});
  await p.locator('#theme-toggle').click();await p.screenshot({path:'data/professional-browser-check/screenshots/workspace-dark.png',fullPage:true,animations:'disabled'});await p.locator('#theme-toggle').click();
  for(const width of [320,375,390,768,1024,1440]){
   await p.setViewportSize({width,height:844});
   for(const view of ['study','generation','exams','learning','history']){
    await p.evaluate(view=>showView(view),view);await p.waitForTimeout(100);
    assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`overflow ${view} ${width}`);
   }
  }
  await p.setViewportSize({width:390,height:844});await p.evaluate(()=>showView('study'));await p.waitForTimeout(400);await p.screenshot({path:'data/professional-browser-check/screenshots/mobile.png',fullPage:true,animations:'disabled'});
  report.widths=[320,375,390,768,1024,1440];assert.deepEqual(errors,[]);report.javascript_errors=0;
  fs.writeFileSync('docs/evaluation-functional-review-ui.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
