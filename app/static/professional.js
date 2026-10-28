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
  let sourceRecords = [], citationOpener = null;
  function openCitation(identifier, record) {
    const source = record || sourceRecords.find(item => item.citation_id === identifier);
    if (!source) return;
    notify('');
    citationOpener = document.activeElement;
    $('source-preview').replaceChildren(sourceCard(source, true));
    $('source-drawer-title').textContent = `来源 ${identifier.replace(/^S/, '')} · 原文依据`;
    const drawer = $('source-drawer');
    if (!drawer.open) { if (innerWidth < 1280) drawer.showModal(); else drawer.show(); }
    drawer.querySelector('button').focus({preventScroll: true});
  }
  $('source-drawer').addEventListener('close', () => {
    $('source-preview').replaceChildren();
    if (citationOpener?.isConnected && citationOpener.getClientRects().length) citationOpener.focus({preventScroll: true});
    citationOpener = null;
  });
  $('source-drawer').addEventListener('keydown', event => {
    if (event.key === 'Escape' && innerWidth >= 1280) { event.preventDefault(); $('source-drawer').close(); }
  });
  function inline(target, text, citations) {
    const pieces = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[S\d+\])/g);
    for (const piece of pieces) {
      let node;
      if (piece.startsWith('**') && piece.endsWith('**')) node = element('strong',piece.slice(2,-2));
      else if (piece.startsWith('`') && piece.endsWith('`')) node = element('code',piece.slice(1,-1));
      else if (/^\[S\d+\]$/.test(piece) && citations.has(piece.slice(1,-1))) {
        node = element('button',piece.replace(/\[S(\d+)\]/, '$1'),'inline-citation'); node.type='button';
        node.setAttribute('aria-label',`查看资料依据 ${piece.slice(1,-1)}`);
        node.title = (sourceRecords.find(item => item.citation_id === piece.slice(1,-1))?.text || '').slice(0, 180);
        node.addEventListener('click',()=>openCitation(piece.slice(1,-1)));
      } else node = document.createTextNode(piece);
      target.append(node);
    }
  }
  function renderAnswer(result) {
    sourceRecords = result.sources || [];
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
    openCitation,
    update(result) {
      sourceRecords = result.sources || [];
      $('source-drawer').close(); $('source-preview').replaceChildren();
      $('source-count').textContent=String(sourceRecords.length);selectTab('answer');
    },
    reading(active) {
      document.body.classList.toggle('reading-mode', active);
      $('question').style.removeProperty('height');
      $('question').placeholder = active ? '继续追问，或提出新的问题…' : '今天，你想弄懂什么？例如：梳理这一章的重点，或找到相关考题。';
      if (active) $('result').after($('question-form'));
      else $('session-history').after($('question-form'));
    },
  };
  function context() {
    const guest = document.body.dataset.auth === 'guest';
    $('workspace-course').textContent=guest?'连接你的学习资料':currentCourse?$('course').selectedOptions[0]?.textContent:'选择一门课程';
    const ready=libraryDocuments.filter(doc=>doc.status==='ready').length;
    $('workspace-scope').textContent=guest?'登录后，课程、对话与练习保存在同一空间':!currentCourse?'在资料库创建课程或选择已有课程':selected.size?`限定 ${selected.size} 份资料 · 引用附原文位置`:ready?`${ready} 份可用资料 · 使用当前课程全部范围`:'可直接解题 · 上传教材或课件可补充来源页码';
    $('workspace-memory').textContent=guest?'专属学习空间':'上下文自动保存';
    $('workspace-library').setAttribute('aria-label',guest?'登录并连接学习资料':'管理当前课程与资料范围');
    if (!guest) {
      const hour = Number(new Intl.DateTimeFormat('en-US', {hour:'numeric', hourCycle:'h23', timeZone:'Asia/Shanghai'}).format(new Date()));
      document.querySelector('.hero h1').textContent = hour < 6 ? '夜深了，慢慢读。' : hour < 12 ? '早上好，从一个问题开始。' : hour < 18 ? '下午好，接着学一点。' : '晚上好，今天想弄懂什么？';
      document.querySelector('.hero .intro').textContent = '从你的资料出发，让每一次理解都有依据。';
    } else {
      document.querySelector('.hero h1').textContent = '从资料，到真正理解。';
      document.querySelector('.hero .intro').textContent = '提出问题，追溯依据，把每次理解积累下来。';
    }
  }
  // Place weak actions next to the context they affect, keeping three suggestions.
  document.querySelector('.workspace-context').append(document.querySelector('.session-bar'));
  const tools = element('div', undefined, 'composer-tools');
  const settings = $('open-generation-settings');
  settings.textContent = '⚙'; settings.className = 'icon-button';
  settings.setAttribute('aria-label', '题型与数量设置'); settings.title = '题型与数量设置';
  tools.append(settings, document.querySelector('.question-actions > .hint'));
  document.querySelector('#question-form .question-actions').prepend(tools);
  $('pulse-week').addEventListener('click', () => { showView('learning'); $('activity-chart').scrollIntoView({block:'center', behavior:motion()}); });
  $('pulse-accuracy').addEventListener('click', () => showView('learning'));
  $('pulse-wrong').addEventListener('click', () => { showView('learning'); $('wrongbook').scrollIntoView({block:'start', behavior:motion()}); });
  $('desk-plans').addEventListener('click', () => { showView('learning'); $('plans').scrollIntoView({block:'start', behavior:motion()}); });
  $('desk-history').addEventListener('click', () => showView('history'));
  $('question').addEventListener('input', () => {
    $('question').style.height = 'auto';
    $('question').style.height = `${Math.min(240, Math.max(document.body.classList.contains('reading-mode') ? 64 : 96, $('question').scrollHeight))}px`;
  });
  const settingsIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  settingsIcon.setAttribute('viewBox', '0 0 24 24'); settingsIcon.setAttribute('class', 'icon'); settingsIcon.setAttribute('aria-hidden', 'true');
  const settingsPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  settingsPath.setAttribute('d', 'M4 7h16M4 17h16M9 4v6m6 4v6'); settingsIcon.append(settingsPath); settings.replaceChildren(settingsIcon);
  for (const id of ['view-learning', 'view-exams']) {
    const back = element('button', '← 回到学习工作台', 'link-button'); back.type = 'button';
    back.addEventListener('click', () => showView('study')); $(id).prepend(back);
  }
  function localDate(value) { return new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai'}).format(new Date(value)); }
  let recentEpoch = 0;
  window.studyDesk = {
    reset() {
      recentEpoch += 1;
      for (const id of ['pulse-week', 'pulse-accuracy', 'pulse-wrong']) $(id).querySelector('strong').textContent = '—';
      $('pulse-chart').replaceChildren();
      $('pulse-chart').setAttribute('aria-label', '选择课程后显示近七天练习趋势');
      $('desk-plan-summary').textContent = '选择课程后，查看复习进度。';
      $('desk-weak-topics').replaceChildren();
      $('desk-recent').replaceChildren(element('p', '选择课程后，接着上次的问题。', 'hint'));
    },
    progress(data) {
      const week = data.week || [];
      $('pulse-week').querySelector('strong').textContent = String(week.reduce((total, day) => total + day.count, 0));
      $('pulse-accuracy').querySelector('strong').textContent = data.accuracy === null ? '—' : `${data.accuracy}%`;
      $('pulse-wrong').querySelector('strong').textContent = String(data.active_wrong);
      const maximum = Math.max(1, ...week.map(day => day.count));
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      line.setAttribute('points', week.map((day, index) => `${4 + index * 17},${26 - day.count / maximum * 22}`).join(' '));
      line.setAttribute('fill', 'none'); line.setAttribute('stroke', 'currentColor'); line.setAttribute('stroke-width', '2');
      $('pulse-chart').replaceChildren(line);
      $('pulse-chart').setAttribute('aria-label', `近七天练习：${week.map(day => `${day.date} ${day.count} 次`).join('；')}`);
      $('desk-plan-summary').textContent = data.plan_tasks ? `全部计划 · 已完成 ${data.completed_tasks} / ${data.plan_tasks} 项任务` : '还没有复习计划。可以从一个薄弱知识点开始。';
      $('desk-weak-topics').replaceChildren();
      for (const point of data.weak_topics.slice(0, 3)) {
        const button = element('button', `${point.topic} · ${point.count} 道待复习`, 'recent-conversation'); button.type = 'button';
        button.addEventListener('click', () => promptQuestion(`请帮我复习「${point.topic}」，结合资料解释容易混淆的概念。`)); $('desk-weak-topics').append(button);
      }
    },
    async recent(course, epoch) {
      const request = ++recentEpoch;
      try {
        const records = await api(`/api/courses/${course}/conversations?limit=3`);
        if (course !== currentCourse || epoch !== scopeEpoch || request !== recentEpoch) return;
        $('desk-recent').replaceChildren();
        for (const record of records) {
          const button = element('button', undefined, 'recent-conversation'); button.type = 'button';
          button.append(element('strong', record.question), element('small', `${localDate(record.created_at)} · ${record.source_count || 0} 条引用`));
          button.addEventListener('click', () => openConversation(record.id, course, epoch).catch(error => status(error.message, true)));
          $('desk-recent').append(button);
        }
        if (!records.length) $('desk-recent').append(element('p', '还没有对话。问出第一个问题，它会保存在这里。', 'hint'));
      } catch (error) {
        if (course === currentCourse && epoch === scopeEpoch && request === recentEpoch) $('desk-recent').replaceChildren(element('p', '最近对话暂未加载，可从全部记录重试。', 'hint'));
      }
    },
  };
  const refresh=new MutationObserver(context);
  refresh.observe($('course'),{childList:true});
  refresh.observe($('document-count'),{childList:true});
  refresh.observe(document.body,{attributes:true,attributeFilter:['data-auth']});
  document.addEventListener('study-scope-change',context);
  $('workspace-library').addEventListener('click',()=>{
    if (!window.studyAuth?.require('登录后，连接你的学习资料。')) return;
    if (innerWidth<=700) { if(!document.body.classList.contains('sidebar-open')) $('sidebar-toggle').click(); }
    else window.studyRail?.expand();
    $('course').focus({preventScroll:true});$('course').scrollIntoView({block:'nearest',behavior:motion()});
  });
  context();
})();
