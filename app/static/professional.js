(() => {
  "use strict";
  const tabs = [$('answer-tab'), $('sources-tab')];
  function selectTab(name, focus = false) {
    tabs.forEach(tab => {
      const active = tab.dataset.resultTab === name;
      tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
      $(tab.getAttribute('aria-controls')).hidden = !active;
      if (active && focus) tab.focus({preventScroll: true});
    });
  }
  tabs.forEach(tab => tab.addEventListener('click', () => selectTab(tab.dataset.resultTab)));
  $('result-tabs').addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const selected = tabs.findIndex(tab => tab.getAttribute('aria-selected') === 'true');
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - selected;
    selectTab(tabs[next].dataset.resultTab, true);
  });
  function openCitation(identifier) {
    selectTab('sources');
    const source = [...$('sources').children].find(node => node.dataset.citation === identifier);
    if (source) { source.tabIndex = -1; source.focus({preventScroll:true}); source.scrollIntoView({block:'center',behavior:motion()}); }
  }
  function inline(target, text, citations) {
    const pieces = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[S\d+\])/g);
    for (const piece of pieces) {
      let node;
      if (piece.startsWith('**') && piece.endsWith('**')) node = element('strong',piece.slice(2,-2));
      else if (piece.startsWith('`') && piece.endsWith('`')) node = element('code',piece.slice(1,-1));
      else if (/^\[S\d+\]$/.test(piece) && citations.has(piece.slice(1,-1))) {
        node = element('button',piece,'inline-citation'); node.type='button';
        node.setAttribute('aria-label',`查看资料依据 ${piece.slice(1,-1)}`);
        node.addEventListener('click',()=>openCitation(piece.slice(1,-1)));
      } else node = document.createTextNode(piece);
      target.append(node);
    }
  }
  function renderAnswer(result) {
    const fragment = document.createDocumentFragment();
    const citations = new Set((result.sources || []).map(source=>source.citation_id));
    let list = null, paragraph = null, code = null;
    for (const line of result.answer.split(/\r?\n/)) {
      if (line.trimStart().startsWith('```')) {
        if (code) code = null;
        else { const pre = element('pre'); code=element('code');pre.append(code);fragment.append(pre); }
        list=paragraph=null;continue;
      }
      if (code) { code.append(document.createTextNode(line+'\n'));continue; }
      if (!line.trim()) { list=paragraph=null;continue; }
      const heading = /^(#{1,6})\s+(.+)$/.exec(line);
      const item = /^\s*(?:[-*+]\s+|\d+[.)、]\s+)(.+)$/.exec(line);
      if (heading) {
        const node=element(`h${Math.min(heading[1].length+1,6)}`);inline(node,heading[2],citations);fragment.append(node);list=paragraph=null;
      } else if (item) {
        const kind=/^\s*\d/.test(line)?'ol':'ul';
        if (!list || list.tagName.toLowerCase() !== kind) {list=element(kind);fragment.append(list);}
        const node=element('li');inline(node,item[1],citations);list.append(node);paragraph=null;
      } else if (line.startsWith('> ')) {
        const node=element('blockquote');inline(node,line.slice(2),citations);fragment.append(node);list=paragraph=null;
      } else {
        if (!paragraph) { paragraph=element('p');fragment.append(paragraph); }
        else paragraph.append(element('br'));
        inline(paragraph,line,citations);list=null;
      }
    }
    return fragment;
  }
  window.studyReader = {
    renderAnswer,
    update(result) { $('source-count').textContent=String(result.sources?.length || 0);selectTab('answer'); },
  };
  function context() {
    const guest = document.body.dataset.auth === 'guest';
    $('workspace-course').textContent=guest?'连接你的学习资料':currentCourse?$('course').selectedOptions[0]?.textContent:'选择一门课程';
    const ready=libraryDocuments.filter(doc=>doc.status==='ready').length;
    $('workspace-scope').textContent=guest?'登录后，课程、对话与练习保存在同一空间':!currentCourse?'在资料库创建课程或选择已有课程':selected.size?`限定 ${selected.size} 份资料 · 引用附原文位置`:ready?`${ready} 份可用资料 · 使用当前课程全部范围`:'可直接解题 · 上传教材或课件可补充来源页码';
    $('workspace-memory').textContent=guest?'专属学习空间':'上下文自动保存';
    $('workspace-library').setAttribute('aria-label',guest?'登录并连接学习资料':'管理当前课程与资料范围');
  }
  const refresh=new MutationObserver(context);
  refresh.observe($('course'),{childList:true});
  refresh.observe($('document-count'),{childList:true});
  refresh.observe(document.body,{attributes:true,attributeFilter:['data-auth']});
  document.addEventListener('study-scope-change',context);
  $('workspace-library').addEventListener('click',()=>{
    if (!window.studyAuth?.require('登录后，连接你的学习资料。')) return;
    if (innerWidth<=700) { if(!document.body.classList.contains('sidebar-open')) $('sidebar-toggle').click(); }
    else if (document.body.classList.contains('rail-collapsed')) $('desktop-sidebar-toggle').click();
    $('course').focus({preventScroll:true});$('course').scrollIntoView({block:'nearest',behavior:motion()});
  });
  context();
})();
