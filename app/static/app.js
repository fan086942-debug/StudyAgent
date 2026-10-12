const $ = (id) => document.getElementById(id);
const selected = new Set();
let currentCourse = "";
let maxUploadMb = 200;
let documentRefreshTimer = null;
let libraryDocuments = [];

function status(message, error = false) {
  $("status").textContent = message;
  $("status").className = error ? "error" : "";
  if (message) notify(message, error);
}
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, options); }
  catch (error) { if (error.name === "AbortError") throw error; throw new Error("无法连接学习服务，请确认服务正在运行。"); }
  let data;
  try { data = await response.json(); } catch { throw new Error("服务返回了无法读取的响应，请重试。"); }
  if (!response.ok) throw new Error((data.message || "请求失败，请检查输入并重试。") + (data.request_id ? `（请求 ${data.request_id.slice(0, 8)}）` : ""));
  return data;
}
function post(path, data, options = {}) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data), ...options });
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function loadCourses(preferred) {
  const courses = await api("/api/courses");
  $("course").replaceChildren();
  const placeholder = element("option", courses.length ? "选择课程 · 从你的资料开始" : "请先创建课程");
  placeholder.value = ""; $("course").append(placeholder);
  for (const course of courses) {
    const option = element("option", course.name);
    option.value = course.id;
    $("course").append(option);
  }
  let stored;
  try { stored = localStorage.getItem("study-course"); } catch {}
  const desired = preferred || stored;
  $("course").value = desired && courses.some(c => c.id === desired) ? desired : "";
  currentCourse = $("course").value;
  $("course-delete-open").hidden = !currentCourse;
  selected.clear();
  resetLearning();
  $("result").hidden = true;
  resetArtifacts();
  await Promise.all([loadDocuments(), loadArtifacts(), refreshProgress()]);
}
async function loadDocuments() {
  clearTimeout(documentRefreshTimer);
  const courseId = currentCourse;
  if (!courseId) {
    libraryDocuments = [];
    $("upload-button").disabled = false;
    selected.clear(); $("document-count").textContent = "0"; updateScope();
    $("documents").replaceChildren(element("p", "资料库是空的。创建或选择一门课程，上传你的第一份资料。", "empty"));
    $("papers").replaceChildren(element("p", "选择课程后，查看你上传的试卷。", "empty"));
    $("paper-filter").replaceChildren(element("option", "全部已解析试卷"));
    $("paper-filter").firstElementChild.value = "";
    $("question-list").replaceChildren(element("p", "选择课程并上传试卷后，开始练习。", "empty"));
    return;
  }
  const epoch = scopeEpoch;
  const documents = await api(`/api/courses/${courseId}/documents`);
  if (courseId === currentCourse && epoch === scopeEpoch) libraryDocuments = documents;
  if (courseId !== currentCourse || epoch !== scopeEpoch) return;
  const processing = documents.some(doc => ["processing", "cancelling"].includes(doc.status));
  const pendingIds = documents.filter(doc => ["processing", "cancelling"].includes(doc.status)).map(doc => doc.id);
  $("upload-button").disabled = processing;
  if (processing) documentRefreshTimer = setTimeout(async function poll() {
    if (currentCourse !== courseId || scopeEpoch !== epoch) return;
    try {
      const latest = await loadDocuments(); await refreshProgress();
      if (currentCourse !== courseId || scopeEpoch !== epoch) return;
      if (latest && !latest.some(doc => ["processing", "cancelling"].includes(doc.status))) {
        const failed = latest.find(doc => pendingIds.includes(doc.id) && doc.status === "failed");
        const cancelled = latest.find(doc => pendingIds.includes(doc.id) && doc.status === "cancelled");
        status(failed ? `${failed.name}：${failed.error || "处理失败，请重试"}` : cancelled ? "处理已取消。原文件和已识别缓存保留，点击重试可继续。" : "资料处理完成，已建立索引，可以开始提问。", !!failed);
      }
    }
    catch (error) { status(error.message, true); documentRefreshTimer = setTimeout(poll, 4000); }
  }, 2000);
  selected.forEach(id => { if (!documents.some(d => d.id === id && d.status === "ready")) selected.delete(id); });
  $("document-count").textContent = documents.length;
  updateScope();
  $("documents").replaceChildren();
  const names = { ready: "可检索", processing: "正在处理", cancelling: "正在停止", cancelled: "已取消 · 可重试", failed: "处理失败", stale: "需要重建", deleting: "删除未完成 · 可重试" };
  for (const doc of documents) {
    const row = element("div", undefined, "document");
    const box = element("input"); box.type = "checkbox"; box.id = `doc-${doc.id}`;
    box.disabled = doc.status !== "ready";
    if (box.disabled) selected.delete(doc.id);
    box.checked = selected.has(doc.id);
    box.addEventListener("change", () => { box.checked ? selected.add(doc.id) : selected.delete(doc.id); updateScope(); });
    const label = element("label", doc.name); label.htmlFor = box.id;
    label.append(element("small", `${names[doc.status] || doc.status} · ${doc.chunk_count} 个片段`));
    if (doc.error || doc.warning) label.append(element("small", doc.error || doc.warning, ["processing", "cancelling", "cancelled"].includes(doc.status) ? "doc-progress" : "doc-error"));
    const actions = element("div", undefined, "document-actions");
    if (doc.status === "ready" && doc.document_type !== "exam") {
      const learn = element("button", "总结知识点", "link-button"); learn.type = "button";
      learn.addEventListener("click", () => summarizeMaterial(doc, learn));
      const match = element("button", "找关联试题", "link-button"); match.type = "button";
      match.addEventListener("click", () => openRelations({material_id: doc.id}, match));
      actions.append(learn, match);
    }
    if (["processing", "cancelling"].includes(doc.status)) {
      const cancel = element("button", doc.status === "cancelling" ? "正在停止…" : "取消处理", "link-button document-cancel"); cancel.type = "button";
      cancel.disabled = doc.status === "cancelling"; cancel.setAttribute("aria-label", `取消处理：${doc.name}`);
      cancel.addEventListener("click", async () => {
        cancel.disabled = true;
        try { await api(`/api/documents/${doc.id}/cancel`, {method: "POST"}); status("取消请求已提交，当前页或接口结束后会停止，已识别缓存会保留。"); }
        catch (error) { status(error.message, true); }
        finally { await loadDocuments().catch(error => status(error.message, true)); }
      }); actions.append(cancel);
    }
    if (["failed", "stale", "cancelled"].includes(doc.status)) {
      const retry = element("button", "重试 / 重建", "link-button"); retry.type = "button";
      retry.addEventListener("click", async (event) => {
        event.preventDefault(); retry.disabled = true; status(`正在处理 ${doc.name}…`);
        try { const result = await api(`/api/documents/${doc.id}/retry?background=true`, { method: "POST" }); status(result.status === "processing" ? "已开始后台处理，进度会自动更新。" : "资料已可检索。"); }
        catch (error) { status(error.message, true); }
        finally { await loadDocuments(); }
      }); actions.append(retry);
    }
    const remove = element("button", "删除", "link-button document-delete"); remove.type = "button";
    remove.setAttribute("aria-label", `删除资料：${doc.name}`); remove.disabled = ["processing", "cancelling"].includes(doc.status);
    remove.addEventListener("click", () => openDocumentDelete(doc, courseId));
    actions.append(remove);
    row.append(box, label, actions); $("documents").append(row);
  }
  if (!documents.length) $("documents").append(element("p", "还没有资料。上传第一份教材或课件吧。", "empty"));
  await loadPapers(documents);
  return documents;
}
$("course-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    $("course-form").querySelector("button").disabled = true;
    const course = await post("/api/courses", { name: $("course-name").value.trim() });
    $("course-name").value = ""; await loadCourses(course.id);
    try { localStorage.setItem("study-course", course.id); } catch {}
    status("课程已创建，可以上传资料了。");
  } catch (error) { status(error.message, true); }
  finally { $("course-form").querySelector("button").disabled = false; }
});
$("course").addEventListener("change", async () => {
  currentCourse = $("course").value; selected.clear(); resetLearning(); $("result").hidden = true;
  $("course-delete-open").hidden = !currentCourse;
  try { localStorage.setItem("study-course", currentCourse); } catch {}
  $("question-list").replaceChildren();
  resetArtifacts();
  try { await Promise.all([loadDocuments(), loadArtifacts(), refreshProgress()]); if (activeView === "learning") await loadLearning(); if (activeView === "history") await loadHistory(); status(""); } catch (error) { status(error.message, true); }
});
$("refresh").addEventListener("click", () => loadDocuments().catch(error => status(error.message, true)));
$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentCourse) return status("请先创建课程。", true);
  const courseId = currentCourse, epoch = scopeEpoch, documentType = $("document-type").value;
  $("upload-button").disabled = true;
  const failures = [];
  let backgroundPending = false;
  const files = Array.from($("files").files);
  if (!files.length || files.some(file => !/\.(pdf|pptx|docx)$/i.test(file.name) || file.size > maxUploadMb * 1024 * 1024)) {
    $("upload-button").disabled = false;
    return status(`请选择 PDF、PPTX 或 DOCX，单文件不超过 ${maxUploadMb} MB。`, true);
  }
  for (const file of files) {
    const data = new FormData(); data.append("file", file); data.append("document_type", documentType);
    if (files.length === 1 && /\.pdf$/i.test(file.name)) data.append("background", "true");
    status(`正在解析与索引：${file.name}。大文件或远程模型可能需要较长时间…`);
    try { const result = await api(`/api/courses/${courseId}/documents`, { method: "POST", body: data }); backgroundPending = result.status === "processing"; }
    catch (error) { failures.push(`${file.name}：${error.message}`); status(failures.at(-1), true); }
    if (courseId === currentCourse && epoch === scopeEpoch) await loadDocuments().catch(() => {});
  }
  $("upload-button").disabled = backgroundPending; $("files").value = ""; updateFiles();
  if (courseId !== currentCourse || epoch !== scopeEpoch) return;
  await refreshProgress().catch(() => {});
  status(failures.length ? `上传处理结束：${files.length - failures.length} 份成功。${failures.join("；")}` : backgroundPending ? "文件已接收，正在后台解析与 OCR，资料列表会自动更新进度。" : "资料已建立索引，可以开始提问。", failures.length > 0);
});
$("question-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentCourse) return status("请先选择课程并上传资料。", true);
  const courseId = currentCourse, epoch = scopeEpoch, askId = ++askEpoch;
  questionController?.abort(); questionController = new AbortController();
  const body = { course_id: courseId, question: $("question").value.trim() };
  if (selected.size) body.document_ids = [...selected];
  $("ask-button").disabled = true; $("result").hidden = true; setAnalyzing(true); status("正在检索资料并整理回答…");
  try {
    const result = await post(`/api/${$("task-mode").value}`, body, {signal: questionController.signal});
    if (courseId !== currentCourse || epoch !== scopeEpoch || askId !== askEpoch) return;
    renderResult(result);
    status("处理完成。");
  } catch (error) { if (error.name !== "AbortError" && askId === askEpoch) status(error.message, true); }
  finally { if (askId === askEpoch) { $("ask-button").disabled = false; setAnalyzing(false); } }
});
function renderResult(result) {
    showView("study", false);
    $("agent-learning").replaceChildren();
    for (const plan of result.plans || []) {
      const button = element("button", `查看 ${plan.title} ↗`, "secondary"); button.type = "button";
      button.addEventListener("click", () => showView("learning")); $("agent-learning").append(button);
    }
    if (result.learning?.wrongbook) {
      const button = element("button", "前往错题本练习 ↗", "secondary"); button.type = "button";
      button.addEventListener("click", () => showView("learning")); $("agent-learning").append(button);
    }
    refreshProgress().catch(() => {});
    $("answer").textContent = result.answer; $("warning").textContent = result.warning || "";
    $("timing").textContent = `${result.trace ? `工具 ${result.trace.length} 次 · ` : ""}总计 ${Math.round(result.total_ms || 0)} ms`;
    $("trace").replaceChildren();
    $("trace-panel").hidden = !result.trace?.length;
    for (const step of result.trace || []) {
      const row = element("article", undefined, "tool-step");
      row.append(element("strong", `${step.step}. ${step.tool} · ${step.status} · ${Math.round(step.elapsed_ms)} ms`), element("p", step.purpose));
      row.append(element("pre", JSON.stringify({参数: step.arguments, 结果: step.observation}, null, 2)));
      $("trace").append(row);
    }
    $("generated-artifacts").replaceChildren();
    for (const artifact of result.artifacts || []) {
      const button = element("button", "预览生成结果：" + artifact.title, "secondary");
      button.type = "button";
      button.addEventListener("click", () => openArtifact(artifact.id).catch(error => status(error.message, true)));
      $("generated-artifacts").append(button);
    }
    if (result.artifacts?.length) loadArtifacts().catch(error => status(error.message, true));
    renderQuestions(result.questions || [], $("matched-questions"));
    $("sources").replaceChildren();
    for (const source of result.sources) {
      $("sources").append(sourceCard(source));
    }
    if (!result.sources.length) $("sources").append(element("p", "没有可展示的可靠引用。可补充资料或换一种问法。", "empty"));
    $("result").hidden = false; $("welcome").hidden = true; status("处理完成。");
}

async function loadPapers(documents) {
  const courseId = currentCourse;
  if (!courseId) return;
  const papers = await api(`/api/courses/${courseId}/papers`);
  if (courseId !== currentCourse) return;
  const previous = $("paper-filter").value;
  $("papers").replaceChildren(); $("paper-filter").replaceChildren();
  const all = element("option", "全部已解析试卷"); all.value = ""; $("paper-filter").append(all);
  for (const doc of documents.filter(d => d.document_type === "exam")) {
    const paper = papers.find(p => p.document_id === doc.id);
    const row = element("div", undefined, "paper-row");
    const state = !paper ? "尚未提取题目" : paper.status === "ready" ? `${paper.question_count} 道题` : paper.status === "processing" ? "正在解析" : "解析失败";
    const info = element("div", `${doc.name} · ${state}`);
    if (paper?.error || paper?.warning) info.append(element("p", paper.error || paper.warning, "hint"));
    const button = element("button", paper?.status === "ready" ? "重新解析" : "解析题目", "secondary");
    button.type = "button"; button.disabled = doc.status !== "ready" || paper?.status === "processing";
    button.addEventListener("click", async () => {
      button.disabled = true; status("正在提取题目与知识点…");
      try { await api(`/api/documents/${doc.id}/extract-questions`, {method: "POST"}); status("题目解析完成。"); }
      catch (error) { status(error.message, true); }
      finally { await loadDocuments().catch(error => status(error.message, true)); }
    });
    row.append(info, button); $("papers").append(row);
    if (paper?.status === "ready") {
      const option = element("option", paper.name); option.value = paper.id; $("paper-filter").append(option);
    }
  }
  if ([...$("paper-filter").options].some(o => o.value === previous)) $("paper-filter").value = previous;
  if (!$("papers").children.length) $("papers").append(element("p", "还没有试卷，上传时请选择试卷类别。", "empty"));
}

function renderQuestions(questions, target) {
  target.replaceChildren();
  const types = {choice: "选择题", true_false: "判断题", fill_blank: "填空题", short_answer: "简答题", calculation: "计算题", essay: "综合题", unknown: "未分类"};
  const difficulties = {easy: "易", medium: "中", hard: "难", unknown: "未评估"};
  for (const question of questions) {
    const card = element("article", undefined, "question-item");
    const link = element("a", `${question.paper_name} · 第 ${question.number} 题`);
    link.href = question.file_url; link.target = "_blank"; link.rel = "noopener";
    card.append(link, element("p", question.content, "question-text"));
    card.append(element("p", `${types[question.type]} · 分值 ${question.score ?? "未标注"} · 难度 ${difficulties[question.difficulty]} · 知识点：${question.knowledge_points.join("、") || "未标注"}`, "hint"));
    const locate = element("button", "定位教材 / 课件依据", "secondary"); locate.type = "button";
    locate.addEventListener("click", () => openRelations({direction: "exam_to_material", question_id: question.id, exam_document_ids: [question.document_id]}, locate));
    const button = element("button", "查看资料并分析此题", "secondary"); button.type = "button";
    button.addEventListener("click", async () => {
      const courseId = currentCourse;
      button.disabled = true; status("正在检索课程资料并分析题目…");
      const body = {course_id: courseId, question: `分析第 ${question.number} 题`};
      if (selected.size) body.document_ids = [...selected];
      try {
        const begun = performance.now();
        const result = await post(`/api/questions/${question.id}/analyze`, body);
        if (currentCourse !== courseId) return;
        renderResult({...result, total_ms: performance.now() - begun});
        $("result").scrollIntoView({behavior: "smooth", block: "start"});
      } catch (error) { status(error.message, true); }
      finally { button.disabled = false; }
    });
    card.append(locate, button, practiceWidget({reference_type: "question", reference_id: question.id})); target.append(card);
  }
}

$("refresh-papers").addEventListener("click", () => loadDocuments().catch(error => status(error.message, true)));
$("question-search-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentCourse) return status("请先选择课程。", true);
  const courseId = currentCourse;
  try {
    const result = await post(`/api/courses/${courseId}/questions/search`, {query: $("question-keyword").value.trim(), paper_id: $("paper-filter").value || null, limit: 30});
    if (courseId !== currentCourse) return;
    renderQuestions(result, $("question-list"));
    if (!result.length) $("question-list").append(element("p", "没有匹配题目，请检查关键词或试卷解析状态。", "empty"));
    status(`显示 ${result.length} 道题，最多显示 30 道；可用关键词缩小范围。`);
  } catch (error) { status(error.message, true); }
});
async function start() {
  try {
    const health = await api("/health");
    maxUploadMb = health.max_upload_mb || 200;
    document.querySelector(".upload-hint").textContent = `${health.ocr_enabled ? "扫描 PDF 自动 OCR" : "文本型文件"} · 单文件上限 ${maxUploadMb} MB`;
    updateModelMode(health.mode);
    await loadCourses();
  } catch (error) { status(error.message, true); }
}

function updateModelMode(mode, model = "") {
  const demo = mode === "demo";
  $("mode").textContent = demo ? "演示模式 · 连接模型 ↗" : "API 模式 ↗";
  $("mode").classList.toggle("live", !demo);
  $("mode").title = demo ? "点击配置模型 API" : `${model || "模型 API"} · 点击管理连接`;
  $("mode-note").textContent = demo ? "当前为离线演示：回答是原文摘录。点击右上角模式或左侧「模型连接」，配置 API 即可使用真实模型。" : `已启用${model ? ` ${model} ` : ""}模型 API，Agent 将自主选择工具。回答基于上传资料，请对照引用原文核查。`;
}


let artifactOffset = 0;
let artifactEpoch = 0;
function resetArtifacts() {
  artifactEpoch += 1;
  artifactOffset = 0;
  $("artifact-preview").hidden = true;
  $("artifact-history").replaceChildren();
  $("more-artifacts").hidden = true;
  $("generation-status").textContent = "";
}
async function loadArtifacts(append = false) {
  const courseId = currentCourse;
  if (!courseId) return;
  const epoch = ++artifactEpoch;
  const offset = append ? artifactOffset : 0;
  const records = await api(`/api/courses/${courseId}/artifacts?limit=10&offset=${offset}`);
  if (courseId !== currentCourse || epoch !== artifactEpoch) return;
  if (!append) $("artifact-history").replaceChildren();
  for (const record of records) {
    const row = element("div", undefined, "paper-row");
    row.append(element("span", `${record.title} · ${new Date(record.created_at).toLocaleString()} · ${record.mode === "demo" ? "演示摘录" : "模型生成"}`));
    const button = element("button", "查看", "secondary"); button.type = "button";
    button.addEventListener("click", () => openArtifact(record.id).catch(error => status(error.message, true)));
    row.append(button); $("artifact-history").append(row);
  }
  artifactOffset = offset + records.length;
  $("more-artifacts").hidden = records.length < 10;
  if (!artifactOffset) $("artifact-history").append(element("p", "还没有生成记录。填写知识主题即可开始。", "empty"));
}
let previewEpoch = 0;
async function openArtifact(id) {
  const courseId = currentCourse;
  const epoch = ++previewEpoch;
  const artifact = await api(`/api/courses/${courseId}/artifacts/${id}`);
  if (courseId !== currentCourse || epoch !== previewEpoch) return;
  showView("generation", false);
  renderArtifact(artifact);
  $("artifact-preview").scrollIntoView({behavior: "smooth", block: "start"});
}
function renderArtifact(artifact) {
  $("artifact-title").textContent = artifact.title;
  $("artifact-warning").textContent = artifact.warning;
  $("artifact-downloads").replaceChildren();
  const download = (label, answers) => {
    const link = element("a", label, "secondary");
    link.href = `/api/courses/${artifact.course_id}/artifacts/${artifact.id}/download?include_answers=${answers}`;
    $("artifact-downloads").append(link);
  };
  download("下载完整 Markdown", true);
  if (artifact.content.questions.length) download("下载题目卷（不附答案）", false);
  const target = $("artifact-content"); target.replaceChildren();
  if (artifact.coverage?.units) {
    target.append(element("p", `本次覆盖 ${artifact.coverage.documents.length} 份资料 · ${artifact.coverage.units.length} 个章节/小节 · 分段读取 ${artifact.coverage.read_chunks} 个正文片段。`, "scope-summary"));
  }
  const refs = (ids) => element("p", "依据：" + ids.map(id => `[${id}]`).join(" "), "hint");
  for (const section of artifact.content.sections) {
    const card = element("article", undefined, "question-item");
    card.append(element("h3", section.topic), element("p", section.summary, "question-text"));
    const list = element("ul");
    for (const point of section.key_points) list.append(element("li", point, "question-text"));
    card.append(list);
    if (section.pitfalls.length) {
      card.append(element("strong", "易错点"));
      const pitfalls = element("ul");
      for (const point of section.pitfalls) pitfalls.append(element("li", point));
      card.append(pitfalls);
    }
    card.append(refs(section.citation_ids));
    const match = element("button", "这些知识点有哪些历史题？", "secondary"); match.type = "button";
    const chunks = artifact.sources.filter(s => section.citation_ids.includes(s.citation_id) && s.document_type !== "exam").map(s => s.chunk_id);
    match.disabled = !chunks.length;
    match.addEventListener("click", () => openRelations({chunk_ids: chunks, artifact_id: artifact.id}, match));
    card.append(match); target.append(card);
  }
  const types = {choice: "选择题", short_answer: "简答题", calculation: "计算题"};
  for (const [index, question] of artifact.content.questions.entries()) {
    const card = element("article", undefined, "question-item");
    card.append(element("h3", `${index + 1}. ${question.topic} · ${types[question.type]}`), element("p", question.stem, "question-text"));
    question.options.forEach((option, i) => card.append(element("p", `${"ABCD"[i]}. ${option}`)));
    const details = element("details");
    details.append(element("summary", "查看参考答案与解析"), element("p", question.answer, "question-text"), element("p", question.explanation, "question-text"), refs(question.citation_ids));
    const evidence = element("button", "查看这题的教材 / 课件依据", "secondary"); evidence.type = "button";
    evidence.addEventListener("click", () => {
      relationEpoch += 1;
      $("relation-title").textContent = `第 ${index + 1} 题 · 从练习回到资料`;
      $("relation-description").textContent = "本题生成时保存的依据原文，可对照知识点和参考解析阅读。";
      $("relation-content").replaceChildren(...artifact.sources.filter(s => question.citation_ids.includes(s.citation_id)).map(sourceCard));
      if (!$("relation-dialog").open) $("relation-dialog").showModal();
    });
    card.append(details, evidence, practiceWidget({reference_type: "artifact", reference_id: artifact.id, question_index: index}, artifact.course_id)); target.append(card);
  }
  $("artifact-sources").replaceChildren();
  for (const source of artifact.sources) {
    $("artifact-sources").append(sourceCard(source));
  }
  $("artifact-preview").hidden = false;
}
const studyPackOption = element("option", "整份资料学习包 · 分章重点与复习卷"); studyPackOption.value = "study_pack"; $("generation-kind").append(studyPackOption);
const summaryOption = element("option", "整份资料 · 提取与总结知识点"); summaryOption.value = "material_summary"; $("generation-kind").append(summaryOption);
$("generation-kind").addEventListener("change", () => {
  const summary = $("generation-kind").value === "material_summary";
  const pack = summary || $("generation-kind").value === "study_pack";
  $("exam-options").hidden = summary || $("generation-kind").value === "review";
  $("generation-topics").required = !pack;
  $("generation-topics").parentElement.hidden = pack;
  $("generation-count").max = pack ? "64" : "12";
  $("generation-count").required = !pack;
  $("generation-count").value = pack ? "" : "3";
  $("generation-count").placeholder = pack ? "自动分配，每节至少一道" : "";
  document.querySelector('label[for="generation-count"]').textContent = pack ? "题目数量 · 留空按章节分配" : "题目数量 · 1–12";
  document.querySelector('#generation-form > p.hint').textContent = pack ? "沿用左侧资料范围。支持 PDF、PPTX、DOCX，逐段读取正文，自动整理知识点、总结和易错点；学习包同时生成复习卷。" : "沿用左侧资料范围。用逗号分隔主题，每个主题都需要可检索的教材、课件或笔记。";
});
$("generation-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentCourse) return status("请先选择课程并上传资料。", true);
  const courseId = currentCourse, epoch = scopeEpoch;
  const topics = $("generation-topics").value.split(/[,，、;；\n]/).map(s => s.trim()).filter(Boolean);
  const body = {
    course_id: courseId, kind: $("generation-kind").value, topics,
    question_count: Number($("generation-count").value),
    question_type: $("generation-type").value, difficulty: $("generation-difficulty").value
  };
  const summary = body.kind === "material_summary";
  const pack = summary || body.kind === "study_pack";
  if (pack) { body.kind = "study_pack"; body.include_questions = !summary; delete body.topics; body.question_count = $("generation-count").value ? Number($("generation-count").value) : null; }
  if (selected.size) body.document_ids = [...selected];
  $("generate-button").disabled = true;
  $("generation-status").textContent = pack ? `正在分段读取资料、提取与总结知识点${summary ? "" : "并生成复习卷"}；整份资料可能需要几分钟，请稍候…` : "正在检索依据并生成内容，请稍候…";
  try {
    const artifact = await post(pack ? "/api/study" : "/api/generate", body);
    if (courseId !== currentCourse || epoch !== scopeEpoch) return;
    renderArtifact(artifact);
    $("generation-status").textContent = "已生成并保存，可以预览和下载。";
    await loadArtifacts();
  } catch (error) {
    if (courseId === currentCourse) $("generation-status").textContent = error.message;
  } finally { $("generate-button").disabled = false; }
});
$("refresh-artifacts").addEventListener("click", () => loadArtifacts().catch(error => status(error.message, true)));
$("more-artifacts").addEventListener("click", () => loadArtifacts(true).catch(error => status(error.message, true)));

async function summarizeMaterial(doc, button) {
  const courseId = currentCourse, epoch = scopeEpoch;
  button.disabled = true; showView("generation");
  $("generation-status").textContent = `正在逐段读取 ${doc.name}，提取知识点并整理总结，请稍候…`;
  try {
    const artifact = await post("/api/study", {course_id: courseId, document_ids: [doc.id], include_questions: false});
    if (courseId !== currentCourse || epoch !== scopeEpoch) return;
    renderArtifact(artifact); await loadArtifacts();
    $("generation-status").textContent = "知识点与总结已保存，可从各节查找相关试题。";
  } catch (error) { if (courseId === currentCourse && epoch === scopeEpoch) $("generation-status").textContent = error.message; }
  finally { button.disabled = false; }
}

function sourceCard(source) {
  const card = element("article", undefined, "source");
  const link = element("a", `[${source.citation_id}] ${source.document_name}`);
  link.href = source.file_url; link.target = "_blank"; link.rel = "noopener";
  const location = source.location_type === "pdf_page" ? `PDF 物理第 ${source.page} 页` :
    source.location_type === "slide" ? `第 ${source.page} 张幻灯片` : `第 ${source.block_index} 个段落 / 表格块`;
  card.append(link, element("small", location + (source.section ? ` · ${source.section}` : "")));
  const details = element("details"); details.append(element("summary", "展开原文"), element("p", source.text, "question-text"));
  card.append(element("p", source.text.slice(0, 260) + (source.text.length > 260 ? "…" : "")), details);
  return card;
}

let relationEpoch = 0;
async function openRelations(args = {}, button) {
  const courseId = currentCourse, epoch = scopeEpoch, requestId = ++relationEpoch;
  if (!courseId) return status("请先选择课程。", true);
  const chosen = libraryDocuments.filter(d => selected.has(d.id));
  const refs = chosen.filter(d => d.document_type !== "exam").map(d => d.id);
  const exams = chosen.filter(d => d.document_type === "exam").map(d => d.id);
  const body = {...args};
  if (body.material_id) body.document_ids = [body.material_id];
  else if (refs.length) body.document_ids = refs;
  if (!body.exam_document_ids && exams.length) body.exam_document_ids = exams;
  if (button) button.disabled = true;
  $("relation-title").textContent = body.direction === "exam_to_material" ? "这道题，在资料哪里讲？" : "从知识点，找到练习题。";
  $("relation-description").textContent = "参考资料按已选范围匹配；未选试卷时查找本课程全部已解析试卷。";
  $("relation-content").replaceChildren(element("p", "正在检查知识点与资料正文…", "hint"));
  if (!$("relation-dialog").open) $("relation-dialog").showModal();
  try {
    const result = await post(`/api/courses/${courseId}/material-question-links`, body);
    if (courseId !== currentCourse || epoch !== scopeEpoch || requestId !== relationEpoch) return;
    const target = $("relation-content"); target.replaceChildren(element("p", result.answer, "scope-summary"), element("p", result.warning, "hint"));
    for (const link of result.links) {
      const question = result.questions.find(q => q.id === link.question_id);
      const card = element("article", undefined, "question-item relation-pair");
      card.append(element("h3", `${question.paper_name} · 第 ${question.number} 题`));
      card.append(element("p", link.method === "knowledge_label" ? `匹配知识点：${link.concepts.join("、")}` : "文本相似候选 · 请核对是否考查同一概念", "hint"), element("p", question.content, "question-text"));
      const practice = element("button", "进入题库练习 ↗", "secondary"); practice.type = "button";
      practice.addEventListener("click", () => { $("relation-dialog").close(); showView("exams"); renderQuestions([question], $("question-list")); });
      card.append(practice);
      const sources = element("div", undefined, "relation-sources");
      result.sources.filter(s => link.chunk_ids.includes(s.chunk_id)).forEach(s => sources.append(sourceCard(s)));
      card.append(sources); target.append(card);
    }
  } catch (error) { if (requestId === relationEpoch) $("relation-content").replaceChildren(element("p", error.message, "error")); }
  finally { if (button) button.disabled = false; }
}

const knowledgeButton = element("button", "查看已保存的知识点总览 ↗", "secondary"); knowledgeButton.type = "button";
$("artifact-history").before(knowledgeButton);
knowledgeButton.addEventListener("click", async () => {
  const courseId = currentCourse, epoch = scopeEpoch, requestId = ++relationEpoch;
  if (!courseId) return status("请先选择课程。", true);
  knowledgeButton.disabled = true;
  $("relation-title").textContent = "你的知识点与总结";
  $("relation-description").textContent = "读取已保存的整理结果。删除或重建后已失效的来源不会作为当前知识展示。";
  $("relation-content").replaceChildren(element("p", "正在读取…", "hint"));
  if (!$("relation-dialog").open) $("relation-dialog").showModal();
  try {
    const records = await api(`/api/courses/${courseId}/material-knowledge`);
    if (courseId !== currentCourse || epoch !== scopeEpoch || requestId !== relationEpoch) return;
    const target = $("relation-content"); target.replaceChildren();
    if (!records.length) target.append(element("p", "尚未保存知识点总结。点击资料旁的「总结知识点」，或生成整份资料学习包。", "empty"));
    for (const record of records) {
      const card = element("article", undefined, "question-item");
      card.append(element("h3", record.topic), element("p", record.summary, "question-text"));
      if (record.mode === "demo") card.append(element("p", "离线演示：原文摘录，未进行模型总结。", "hint"));
      const points = element("ul"); record.key_points.forEach(p => points.append(element("li", p))); card.append(points);
      const match = element("button", "查找关联试题 ↗", "secondary"); match.type = "button";
      match.addEventListener("click", () => openRelations({chunk_ids: record.sources.map(s => s.chunk_id), artifact_id: record.artifact_id}, match));
      const preview = element("button", "查看完整总结 ↗", "secondary"); preview.type = "button";
      preview.addEventListener("click", () => { $("relation-dialog").close(); openArtifact(record.artifact_id).catch(e => status(e.message, true)); });
      card.append(match, preview); target.append(card);
    }
  } catch (error) { if (requestId === relationEpoch) $("relation-content").replaceChildren(element("p", error.message, "error")); }
  finally { knowledgeButton.disabled = false; }
});


// Views, learning records and interaction state. All user/model text uses textContent.
const viewNames = {study: "学习工作台", generation: "复习与生成", exams: "历史题库", learning: "错题与计划", history: "对话记录"};
let activeView = "study";
let scopeEpoch = 0;
let learningEpoch = 0;
let historyEpoch = 0;
let historyOffset = 0;
let wrongOffset = 0;
let planOffset = 0;
let toastTimer;
let requestTimer;
let questionController;
let askEpoch = 0;
const motion = () => matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";

function showView(view, scroll = true) {
  if (!viewNames[view]) return;
  activeView = view;
  document.querySelectorAll("[data-panel]").forEach(panel => { panel.hidden = panel.dataset.panel !== view; });
  document.querySelectorAll(".nav-item").forEach(button => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  $("view-label").textContent = viewNames[view];
  closeSidebar();
  if (scroll) window.scrollTo({top: 0, behavior: motion()});
  if (view === "learning") loadLearning().catch(error => status(error.message, true));
  if (view === "history") loadHistory().catch(error => status(error.message, true));
}
function notify(message, error = false) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").classList.toggle("error", error);
  $("toast").hidden = !message;
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 7000 : 3500);
}
function closeSidebar() {
  document.body.classList.remove("sidebar-open");
  $("sidebar-overlay").hidden = true;
  $("sidebar-toggle").setAttribute("aria-expanded", "false");
}
document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => showView(button.dataset.view)));
$("sidebar-toggle").addEventListener("click", () => {
  const open = !document.body.classList.contains("sidebar-open");
  document.body.classList.toggle("sidebar-open", open);
  $("sidebar-overlay").hidden = !open;
  $("sidebar-toggle").setAttribute("aria-expanded", String(open));
  if (open) $("sidebar").querySelector(".nav-item.active").focus();
});
$("sidebar-overlay").addEventListener("click", closeSidebar);
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) { closeSidebar(); $("sidebar-toggle").focus(); }
  if (event.key === "Tab" && document.body.classList.contains("sidebar-open")) {
    const focusable = [...$("sidebar").querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,a[href]')]
      .filter(node => node.getClientRects().length);
    const first = focusable[0], last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
});
matchMedia("(min-width: 701px)").addEventListener("change", event => { if (event.matches) closeSidebar(); });
function promptQuestion(question) {
  showView("study"); $("question").value = question; updateQuestionCount(); $("question").focus();
  $("question-form").scrollIntoView({behavior: motion(), block: "center"});
}
document.querySelectorAll("[data-prompt]").forEach(button => button.addEventListener("click", () => promptQuestion(button.dataset.prompt)));
$("hero-focus").addEventListener("click", () => {
  $("question-form").scrollIntoView({behavior: motion(), block: "center"}); $("question").focus({preventScroll: true});
});
function updateQuestionCount() { $("question-count").textContent = $("question").value.length; }
$("question").addEventListener("input", updateQuestionCount);
$("question").addEventListener("keydown", event => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault(); if (!$("ask-button").disabled) $("question-form").requestSubmit();
  }
});
$("today-label").textContent = new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", month: "long", day: "numeric", weekday: "short"}).format(new Date());
function syncThemeButton() {
  const dark = document.documentElement.dataset.theme === "dark";
  $("theme-toggle").setAttribute("aria-pressed", String(dark));
  $("theme-toggle").setAttribute("aria-label", dark ? "切换浅色主题" : "切换深色主题");
  document.querySelector('meta[name="theme-color"]').content = dark ? "#131c19" : "#f6f7f3";
}
syncThemeButton();
$("theme-toggle").addEventListener("click", () => {
  document.documentElement.dataset.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("study-theme", document.documentElement.dataset.theme); } catch {}
  syncThemeButton();
});

const commands = [
  ...Object.entries(viewNames).map(([view, label]) => ({label, action: () => showView(view)})),
  {label: "查看学习进度", action: () => promptQuestion("查看我的学习进度")},
  {label: "安排一周复习计划", action: () => promptQuestion("安排7天复习计划，每天30分钟")},
  {label: "根据薄弱知识点生成复习资料", action: () => promptQuestion("生成薄弱知识点复习资料")},
];
function renderCommands() {
  const query = $("command-search").value.trim().toLocaleLowerCase();
  $("command-results").replaceChildren();
  for (const command of commands.filter(c => c.label.toLocaleLowerCase().includes(query))) {
    const button = element("button", command.label + " ↗"); button.type = "button";
    button.addEventListener("click", () => { $("command-dialog").close(); command.action(); });
    $("command-results").append(button);
  }
  if (!$("command-results").children.length) $("command-results").append(element("p", "没有匹配的操作，试试“复习”或“题库”。", "empty"));
}
function openCommands() {
  $("command-search").value = ""; renderCommands();
  if (!$("command-dialog").open) $("command-dialog").showModal();
  $("command-search").focus();
}
$("command-open").addEventListener("click", openCommands);
$("command-search").addEventListener("input", renderCommands);
document.addEventListener("keydown", event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "k") { event.preventDefault(); openCommands(); }
});
$("command-dialog").addEventListener("keydown", event => {
  const buttons = [...$("command-results").querySelectorAll("button")];
  const i = buttons.indexOf(document.activeElement);
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const next = i < 0 ? (event.key === "ArrowDown" ? 0 : buttons.length - 1) : (i + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
  } else if (event.key === "Enter" && document.activeElement === $("command-search")) { event.preventDefault(); buttons[0]?.click(); }
});
$("command-dialog").addEventListener("click", event => {
  const r = $("command-dialog").getBoundingClientRect();
  if (event.target === $("command-dialog") && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) $("command-dialog").close();
});

function updateFiles() {
  const files = [...$("files").files];
  $("file-caption").textContent = files.length ? `已选择 ${files.length} 份 · ${(files.reduce((n, f) => n + f.size, 0) / 1024 / 1024).toFixed(1)} MB` : "或点击选择 · PDF / PPTX / DOCX";
}
$("files").addEventListener("change", updateFiles);
for (const eventName of ["dragenter", "dragover"]) $("drop-zone").addEventListener(eventName, event => {
  event.preventDefault(); $("drop-zone").classList.add("drag-over");
});
for (const eventName of ["dragleave", "drop"]) $("drop-zone").addEventListener(eventName, event => {
  event.preventDefault(); $("drop-zone").classList.remove("drag-over");
});
$("drop-zone").addEventListener("drop", event => {
  const files = [...event.dataTransfer.files];
  if (!files.length) return;
  if (files.some(file => !/\.(pdf|pptx|docx)$/i.test(file.name))) return status("支持 PDF、PPTX 和 DOCX，请先转换其他格式。", true);
  const transfer = new DataTransfer(); files.forEach(file => transfer.items.add(file));
  $("files").files = transfer.files; updateFiles();
});
function updateScope() { $("scope-note").textContent = !currentCourse ? "尚未选择课程 · 资料为空" : selected.size ? `已勾选 ${selected.size} 份 · 限定检索与生成范围` : "未勾选 · 使用当前课程全部资料"; }
function setAnalyzing(active) {
  clearInterval(requestTimer);
  $("analysis-progress").hidden = !active;
  $("question-form").setAttribute("aria-busy", String(active));
  $("ask-button").textContent = active ? "正在分析…" : "开始分析 ↗";
  if (active) {
    const begun = performance.now(); $("elapsed-label").textContent = "0 秒";
    requestTimer = setInterval(() => { $("elapsed-label").textContent = `${Math.floor((performance.now() - begun) / 1000)} 秒`; }, 1000);
  }
}
function resetLearning() {
  scopeEpoch += 1; learningEpoch += 1; historyEpoch += 1; previewEpoch += 1;
  status(""); notify("");
  questionController?.abort(); askEpoch += 1; $("ask-button").disabled = false; setAnalyzing(false);
  wrongOffset = planOffset = historyOffset = 0;
  for (const id of ["stat-documents", "stat-attempts", "stat-wrong"]) $(id).textContent = "0";
  $("stat-plan").textContent = "—";
  $("accuracy-note").textContent = "尚未记录练习。选择课程后，查看真实学习进度。";
  for (const id of ["wrongbook", "plans", "conversation-history", "activity-chart", "weak-topics", "agent-learning"]) $(id).replaceChildren();
  $("wrongbook").append(element("p", "选择课程后，查看你的错题与练习记录。", "empty"));
  $("plans").append(element("p", "选择课程并创建复习计划，按自己的节奏前进。", "empty"));
  $("conversation-history").append(element("p", "选择课程后，查看已保存的对话记录。", "empty"));
  $("weak-topics").append(element("p", "记录练习反馈后，薄弱点会出现在这里。", "empty"));
  $("weakness-review").disabled = true;
  for (const id of ["more-wrongs", "more-plans", "more-history"]) $(id).hidden = true;
  $("welcome").hidden = false; $("wrong-count").textContent = "0"; $("wrong-nav-count").textContent = "04";
  updateScope();
}
let pendingCourseDelete = null;
let courseDeleteBusy = false;
$("course-delete-open").addEventListener("click", () => {
  if (!currentCourse || courseDeleteBusy) return;
  pendingCourseDelete = {id: currentCourse, name: $("course").selectedOptions[0].textContent};
  $("delete-course-name").textContent = pendingCourseDelete.name;
  $("delete-course-status").textContent = "";
  $("delete-course-dialog").showModal();
});
$("delete-course-dialog").addEventListener("cancel", event => { if (courseDeleteBusy) event.preventDefault(); });
$("delete-course-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!pendingCourseDelete || courseDeleteBusy) return;
  const {id, name} = pendingCourseDelete;
  courseDeleteBusy = true;
  $("delete-course-confirm").disabled = true; $("delete-course-cancel").disabled = true;
  $("delete-course-status").textContent = "正在清理课程资料和学习记录…";
  let removed = false;
  try {
    await api(`/api/courses/${id}`, {method: "DELETE"});
    removed = true; $("delete-course-dialog").close();
    try { if (localStorage.getItem("study-course") === id) localStorage.removeItem("study-course"); } catch {}
    if (currentCourse === id) {
      currentCourse = ""; $("course").value = ""; $("course-delete-open").hidden = true;
      selected.clear(); resetLearning(); resetArtifacts(); $("result").hidden = true;
      $("files").value = ""; updateFiles();
      await loadDocuments();
    }
    await loadCourses();
    status(`已删除课程「${name}」及其学习记录。`);
  } catch (error) {
    if (removed) status(`课程已删除，但列表刷新失败：${error.message}`, true);
    else $("delete-course-status").textContent = error.message;
    if (!removed && currentCourse === id) await loadDocuments().catch(() => {});
  } finally {
    courseDeleteBusy = false;
    $("delete-course-confirm").disabled = false; $("delete-course-cancel").disabled = false;
  }
});
let pendingDocumentDelete = null;
let documentDeleteBusy = false;
function openDocumentDelete(doc, courseId) {
  if (documentDeleteBusy) return;
  pendingDocumentDelete = {doc, courseId};
  $("delete-document-name").textContent = doc.name;
  $("delete-document-status").textContent = "";
  $("delete-document-confirm").disabled = false;
  $("delete-document-cancel").disabled = false;
  $("delete-document-dialog").showModal();
}
$("delete-document-dialog").addEventListener("cancel", event => { if (documentDeleteBusy) event.preventDefault(); });
$("delete-document-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!pendingDocumentDelete || documentDeleteBusy) return;
  const {doc, courseId} = pendingDocumentDelete;
  $("delete-document-confirm").disabled = true;
  $("delete-document-cancel").disabled = true;
  documentDeleteBusy = true;
  let removed = false;
  $("delete-document-status").textContent = "正在删除原文件与索引…";
  try {
    await api(`/api/documents/${doc.id}`, {method: "DELETE"});
    removed = true; $("delete-document-dialog").close();
    if (currentCourse === courseId) {
      selected.delete(doc.id); resetLearning(); $("result").hidden = true; resetArtifacts();
      $("question-list").replaceChildren(element("p", "资料已更新，请重新查题。", "empty"));
      await Promise.all([loadDocuments(), loadArtifacts(), refreshProgress()]);
      if (activeView === "learning") await loadLearning();
      if (activeView === "history") await loadHistory();
    }
    status(`已删除 ${doc.name}。`);
  } catch (error) {
    if (removed) status(`资料已删除，但列表刷新失败：${error.message}`, true);
    else $("delete-document-status").textContent = error.message;
    if (currentCourse === courseId) await loadDocuments().catch(() => {});
  } finally {
    documentDeleteBusy = false;
    $("delete-document-confirm").disabled = false; $("delete-document-cancel").disabled = false;
  }
});
async function refreshProgress() {
  const course = currentCourse, epoch = scopeEpoch;
  if (!course) return;
  const progress = await api(`/api/courses/${course}/progress`);
  if (course !== currentCourse || epoch !== scopeEpoch) return;
  $("stat-documents").textContent = progress.ready_documents;
  $("stat-attempts").textContent = progress.attempts;
  $("stat-wrong").textContent = progress.active_wrong;
  $("stat-plan").textContent = progress.plan_tasks ? `${Math.round(progress.completed_tasks / progress.plan_tasks * 100)}%` : "—";
  $("wrong-count").textContent = progress.active_wrong;
  $("wrong-nav-count").textContent = progress.active_wrong || "04";
  $("accuracy-note").textContent = progress.accuracy === null ? "尚未记录练习。完成一次自评后，会显示正确率。" : `自评正确率 ${progress.accuracy}% · ${progress.practiced_questions} 道不同题目，采用最近一次自评；非自动评分。`;
  $("activity-chart").replaceChildren();
  const max = Math.max(...progress.week.map(day => day.count), 1);
  for (const day of progress.week) {
    const column = element("div", undefined, "chart-column");
    column.append(element("span", String(day.count)));
    const wrap = element("div", undefined, "chart-bar-wrap");
    const bar = element("div", undefined, "chart-bar"); bar.style.height = `${Math.max(day.count / max * 100, 3)}%`;
    wrap.append(bar); column.append(wrap, element("span", day.date.slice(5).replace("-", "/")));
    column.title = `${day.date}：${day.count} 次练习`; $("activity-chart").append(column);
  }
  $("activity-chart").setAttribute("aria-label", progress.week.map(d => `${d.date} ${d.count} 次练习`).join("；"));
  $("weak-topics").replaceChildren();
  for (const point of progress.weak_topics) {
    const row = element("div", undefined, "topic-row");
    row.append(element("span", point.topic), element("span", `${point.count} 道待复习`, "count-pill")); $("weak-topics").append(row);
  }
  if (!progress.weak_topics.length) $("weak-topics").append(element("p", "还没有待复习的知识点。把练习反馈留在错题本里。", "empty"));
  $("weakness-review").disabled = !progress.weak_topics.some(p => p.topic !== "未标注知识点");
}
function practiceWidget(reference, course = currentCourse, saved = {}) {
  const epoch = scopeEpoch;
  const details = element("details", undefined, "practice-box");
  details.append(element("summary", "练习与自评 · 记录这次反馈"));
  const label = element("label", "我的作答");
  const answer = element("textarea"); answer.rows = 2; answer.maxLength = 6000; answer.placeholder = "写下你的答案，或直接记录自评结果…"; answer.value = saved.answer || "";
  label.append(answer);
  const noteLabel = element("label", "错因 / 复习备注（可选）");
  const note = element("input"); note.maxLength = 1000; note.placeholder = "例如：混淆概念、条件遗漏…"; note.value = saved.note || ""; noteLabel.append(note);
  const actions = element("div", undefined, "practice-actions");
  const feedback = element("p", "自评用于记录学习情况，不代表系统或官方评分。", "hint");
  const buttons = [];
  for (const [outcome, text] of [["wrong", "需要再练 · 加入错题"], ["correct", "已掌握 · 记录练习"]]) {
    const button = element("button", text, "secondary"); button.type = "button"; buttons.push(button);
    button.addEventListener("click", async () => {
      if (course !== currentCourse || epoch !== scopeEpoch) return;
      buttons.forEach(b => { b.disabled = true; });
      try {
        await post(`/api/courses/${course}/practice`, {...reference, outcome, answer: answer.value, note: note.value});
        if (course !== currentCourse || epoch !== scopeEpoch) return;
        feedback.textContent = outcome === "wrong" ? "已记录本次练习并加入错题本。" : "已记录本次练习，相关错题标记为已掌握。";
        notify(feedback.textContent);
        await refreshProgress();
        if (activeView === "learning") await loadLearning();
      } catch (error) { if (course === currentCourse && epoch === scopeEpoch) { feedback.textContent = error.message; status(error.message, true); } }
      finally { buttons.forEach(b => { b.disabled = false; }); }
    }); actions.append(button);
  }
  details.append(label, noteLabel, actions, feedback); return details;
}
async function loadLearning() {
  if (!currentCourse) return;
  await Promise.all([refreshProgress(), loadWrongs(), loadPlans()]);
}
async function loadWrongs(append = false) {
  const course = currentCourse, epoch = scopeEpoch, requestEpoch = ++learningEpoch;
  if (!course) return;
  const offset = append ? wrongOffset : 0;
  const records = await api(`/api/courses/${course}/wrongbook?include_mastered=${$("include-mastered").checked}&limit=20&offset=${offset}`);
  if (course !== currentCourse || epoch !== scopeEpoch || requestEpoch !== learningEpoch) return;
  if (!append) $("wrongbook").replaceChildren();
  for (const wrong of records) {
    const card = element("article", undefined, "question-item wrong-item" + (wrong.mastered ? " mastered" : ""));
    const heading = element("div", undefined, "list-heading");
    heading.append(element("strong", wrong.snapshot.topics.join(" · ") || "待复习题目"), element("span", wrong.mastered ? "已掌握" : `错 ${wrong.wrong_count} 次`, "count-pill"));
    card.append(heading, element("p", wrong.snapshot.stem, "question-text"), element("p", wrong.snapshot.title, "hint"));
    if (wrong.snapshot.answer) {
      const detail = element("details"); detail.append(element("summary", "对照参考答案"), element("p", wrong.snapshot.answer, "question-text"), element("p", wrong.snapshot.explanation, "question-text")); card.append(detail);
    }
    card.append(practiceWidget({reference_type: "wrongbook", reference_id: wrong.id}, course, wrong));
    const toggle = element("button", wrong.mastered ? "继续复习此题" : "标记为已掌握", "link-button"); toggle.type = "button";
    toggle.addEventListener("click", async () => {
      toggle.disabled = true;
      try {
        await api(`/api/courses/${course}/wrongbook/${wrong.id}`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mastered: !wrong.mastered})});
        if (course !== currentCourse || epoch !== scopeEpoch) return;
        await loadLearning(); notify(wrong.mastered ? "已恢复为待复习错题。" : "已标记掌握。随时可以重新练习。");
      } catch (error) { status(error.message, true); }
      finally { toggle.disabled = false; }
    }); card.append(toggle); $("wrongbook").append(card);
  }
  wrongOffset = offset + records.length; $("more-wrongs").hidden = records.length < 20;
  if (!wrongOffset) $("wrongbook").append(element("p", "暂时没有错题。可在历史题库或模拟卷中练习，并记录自评。", "empty"));
}
let plansEpoch = 0;
async function loadPlans(append = false) {
  const course = currentCourse, epoch = scopeEpoch, requestEpoch = ++plansEpoch;
  if (!course) return;
  const offset = append ? planOffset : 0;
  const plans = await api(`/api/courses/${course}/plans?limit=10&offset=${offset}`);
  if (course !== currentCourse || epoch !== scopeEpoch || requestEpoch !== plansEpoch) return;
  if (!append) $("plans").replaceChildren();
  for (const plan of plans) {
    const card = element("article", undefined, "question-item plan-card");
    const heading = element("div", undefined, "plan-heading");
    const done = plan.tasks.filter(t => t.completed).length;
    const counter = element("span", `${done} / ${plan.tasks.length}`, "count-pill");
    heading.append(element("h3", `${plan.title} · 每天 ${plan.daily_minutes} 分钟`), counter);
    card.append(heading, element("p", plan.topics.join(" · "), "hint"));
    const progress = element("div", undefined, "plan-progress"); const bar = element("span"); bar.style.width = `${done / plan.tasks.length * 100}%`; progress.append(bar); card.append(progress);
    for (const task of plan.tasks) {
      const row = element("div", undefined, "plan-task" + (task.completed ? " completed" : ""));
      const check = element("input"); check.type = "checkbox"; check.checked = task.completed; check.id = `task-${task.id}`;
      const label = element("label", task.action + " · " + task.topics.join("、")); label.htmlFor = check.id;
      label.append(element("small", `${task.due_date} · ${task.minutes} 分钟`));
      row.append(check, label, element("span", `DAY ${String(task.day).padStart(2, "0")}`, "day-pill")); card.append(row);
      check.addEventListener("change", async () => {
        const completed = check.checked; check.disabled = true;
        try {
          const updated = await api(`/api/courses/${course}/plans/${plan.id}/tasks/${task.id}`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({completed})});
          if (course !== currentCourse || epoch !== scopeEpoch) return;
          row.classList.toggle("completed", completed);
          const count = updated.tasks.filter(t => t.completed).length;
          counter.textContent = `${count} / ${updated.tasks.length}`; bar.style.width = `${count / updated.tasks.length * 100}%`;
          await refreshProgress();
        } catch (error) { check.checked = !completed; status(error.message, true); }
        finally { check.disabled = false; }
      });
    }
    $("plans").append(card);
  }
  planOffset = offset + plans.length; $("more-plans").hidden = plans.length < 10;
  if (!planOffset) $("plans").append(element("p", "留一点时间给理解。创建第一份复习计划，从今天开始。", "empty"));
}
$("include-mastered").addEventListener("change", () => loadWrongs().catch(error => status(error.message, true)));
$("more-wrongs").addEventListener("click", () => loadWrongs(true).catch(error => status(error.message, true)));
$("more-plans").addEventListener("click", () => loadPlans(true).catch(error => status(error.message, true)));
$("plan-form").addEventListener("submit", async event => {
  event.preventDefault(); if (!currentCourse) return status("请先选择课程并上传资料。", true);
  const course = currentCourse, epoch = scopeEpoch; $("plan-button").disabled = true;
  const body = {topics: $("plan-topics").value.split(/[,，、;；\n]/).map(t => t.trim()).filter(Boolean), days: Number($("plan-days").value), daily_minutes: Number($("plan-minutes").value)};
  if (selected.size) body.document_ids = [...selected];
  try {
    await post(`/api/courses/${course}/plans`, body);
    if (course !== currentCourse || epoch !== scopeEpoch) return;
    await Promise.all([loadPlans(), refreshProgress()]); status("复习计划已保存。完成后勾选当天任务即可。");
  } catch (error) { if (epoch === scopeEpoch) status(error.message, true); }
  finally { $("plan-button").disabled = false; }
});
$("weakness-review").addEventListener("click", () => promptQuestion("生成薄弱知识点复习资料"));
async function loadHistory(append = false) {
  const course = currentCourse, epoch = scopeEpoch, requestEpoch = ++historyEpoch;
  if (!course) return;
  const offset = append ? historyOffset : 0;
  const records = await api(`/api/courses/${course}/conversations?limit=20&offset=${offset}`);
  if (course !== currentCourse || epoch !== scopeEpoch || requestEpoch !== historyEpoch) return;
  if (!append) $("conversation-history").replaceChildren();
  for (const record of records) {
    const row = element("article", undefined, "paper-row");
    const text = element("div", record.question);
    text.append(element("p", `${record.kind === "agent" ? "学习 Agent" : "资料问答"} · ${new Date(record.created_at).toLocaleString("zh-CN", {timeZone: "Asia/Shanghai"})}`, "hint"));
    const button = element("button", "重新查看 ↗", "secondary"); button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const detail = await api(`/api/courses/${course}/conversations/${record.id}`);
        if (course !== currentCourse || epoch !== scopeEpoch) return;
        $("question").value = detail.question; updateQuestionCount(); renderResult(detail.result);
        $("result").scrollIntoView({behavior: motion(), block: "start"}); status("已打开历史回答与来源快照。");
      } catch (error) { status(error.message, true); }
      finally { button.disabled = false; }
    }); row.append(text, button); $("conversation-history").append(row);
  }
  historyOffset = offset + records.length; $("more-history").hidden = records.length < 20;
  if (!historyOffset) $("conversation-history").append(element("p", "好问题值得留下。完成一次资料问答，记录将自动保存在这里。", "empty"));
}
$("refresh-history").addEventListener("click", () => loadHistory().catch(error => status(error.message, true)));
$("more-history").addEventListener("click", () => loadHistory(true).catch(error => status(error.message, true)));
$("copy-answer").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("answer").textContent); notify("回答已复制。"); }
  catch { status("浏览器未允许剪贴板访问，可选中回答手动复制。", true); }
});
start();
