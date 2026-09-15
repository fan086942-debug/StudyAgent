const $ = (id) => document.getElementById(id);
const selected = new Set();
let currentCourse = "";

function status(message, error = false) {
  $("status").textContent = message;
  $("status").className = error ? "error" : "";
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "请求失败，请检查输入并重试。");
  return data;
}
function post(path, data) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
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
  for (const course of courses) {
    const option = element("option", course.name);
    option.value = course.id;
    $("course").append(option);
  }
  if (!courses.length) $("course").append(element("option", "请先创建课程"));
  if (preferred) $("course").value = preferred;
  currentCourse = courses.length ? $("course").value : "";
  selected.clear();
  $("result").hidden = true;
  await loadDocuments();
}
async function loadDocuments() {
  const courseId = currentCourse;
  if (!courseId) return;
  const documents = await api(`/api/courses/${courseId}/documents`);
  if (courseId !== currentCourse) return;
  $("documents").replaceChildren();
  const names = { ready: "可检索", processing: "正在处理", failed: "处理失败", stale: "需要重建" };
  for (const doc of documents) {
    const row = element("div", undefined, "document");
    const box = element("input"); box.type = "checkbox"; box.id = `doc-${doc.id}`;
    box.disabled = doc.status !== "ready";
    if (box.disabled) selected.delete(doc.id);
    box.checked = selected.has(doc.id);
    box.addEventListener("change", () => box.checked ? selected.add(doc.id) : selected.delete(doc.id));
    const label = element("label", doc.name); label.htmlFor = box.id;
    label.append(element("small", `${names[doc.status] || doc.status} · ${doc.chunk_count} 个片段`));
    if (doc.error || doc.warning) label.append(element("small", doc.error || doc.warning, "doc-error"));
    if (["failed", "stale"].includes(doc.status)) {
      const retry = element("button", "重试 / 重建", "link-button"); retry.type = "button";
      retry.addEventListener("click", async (event) => {
        event.preventDefault(); retry.disabled = true; status(`正在处理 ${doc.name}…`);
        try { await api(`/api/documents/${doc.id}/retry`, { method: "POST" }); status("资料已可检索。"); }
        catch (error) { status(error.message, true); }
        finally { await loadDocuments(); }
      }); label.append(retry);
    }
    row.append(box, label); $("documents").append(row);
  }
  if (!documents.length) $("documents").append(element("p", "还没有资料。上传第一份教材或课件吧。", "empty"));
}
$("course-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const course = await post("/api/courses", { name: $("course-name").value.trim() });
    $("course-name").value = ""; await loadCourses(course.id); status("课程已创建，可以上传资料了。");
  } catch (error) { status(error.message, true); }
});
$("course").addEventListener("change", async () => {
  currentCourse = $("course").value; selected.clear(); $("result").hidden = true;
  try { await loadDocuments(); status(""); } catch (error) { status(error.message, true); }
});
$("refresh").addEventListener("click", () => loadDocuments().catch(error => status(error.message, true)));
$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentCourse) return status("请先创建课程。", true);
  const courseId = currentCourse;
  $("upload-button").disabled = true;
  const failures = [];
  const files = Array.from($("files").files);
  for (const file of files) {
    const data = new FormData(); data.append("file", file); data.append("document_type", $("document-type").value);
    status(`正在解析与索引：${file.name}。大文件或远程模型可能需要较长时间…`);
    try { await api(`/api/courses/${courseId}/documents`, { method: "POST", body: data }); }
    catch (error) { failures.push(`${file.name}：${error.message}`); status(failures.at(-1), true); }
    await loadDocuments().catch(() => {});
  }
  $("upload-button").disabled = false; $("files").value = "";
  status(failures.length ? `上传处理结束：${files.length - failures.length} 份成功。${failures.join("；")}` : "资料已建立索引，可以开始提问。", failures.length > 0);
});
$("question-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentCourse) return status("请先选择课程并上传资料。", true);
  const courseId = currentCourse;
  const body = { course_id: courseId, question: $("question").value.trim() };
  if (selected.size) body.document_ids = [...selected];
  $("ask-button").disabled = true; status("正在检索资料并整理回答…");
  try {
    const result = await post("/api/chat", body);
    if (courseId !== currentCourse) return;
    $("answer").textContent = result.answer; $("warning").textContent = result.warning || "";
    $("timing").textContent = `检索 ${Math.round(result.retrieval_ms)} ms · 总计 ${Math.round(result.total_ms)} ms`;
    $("sources").replaceChildren();
    for (const source of result.sources) {
      const card = element("article", undefined, "source");
      const link = element("a", `[${source.citation_id}] ${source.document_name}`);
      link.href = source.file_url; link.target = "_blank"; link.rel = "noopener";
      const location = source.location_type === "pdf_page" ? `PDF 物理第 ${source.page} 页` :
        source.location_type === "slide" ? `第 ${source.page} 张幻灯片` : `文档第 ${source.block_index} 个段落 / 表格块`;
      card.append(link, element("small", location + (source.section ? ` · ${source.section}` : "")), element("p", source.text));
      $("sources").append(card);
    }
    if (!result.sources.length) $("sources").append(element("p", "没有可展示的可靠引用。可补充资料或换一种问法。", "empty"));
    $("result").hidden = false; $("welcome").hidden = true; status("处理完成。");
  } catch (error) { status(error.message, true); }
  finally { $("ask-button").disabled = false; }
});
async function start() {
  try {
    const health = await api("/health");
    const demo = health.mode === "demo";
    $("mode").textContent = demo ? "演示模式 · 未连接 LLM" : "API 模式";
    $("mode").classList.toggle("live", !demo);
    $("mode-note").textContent = demo ? "当前为零密钥演示：可体验解析、检索与来源定位；回答是原文摘录，不代表真实 LLM 效果。配置本地 .env 并重启后可使用真实模型。" : "已启用模型 API。回答优先基于上传资料；请对照引用原文核查。";
    await loadCourses();
  } catch (error) { status(error.message, true); }
}
start();
