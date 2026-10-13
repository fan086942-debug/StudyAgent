(() => {
  "use strict";
  const dialog = $("connection-dialog"), form = $("connection-form");
  let profile = null, busy = false;
  function message(text, error = false) {
    $("connection-status").textContent = text;
    $("connection-status").classList.toggle("error", error);
  }
  function clearKey() {
    $("connection-key").value = "";
    $("connection-key").type = "password";
    $("connection-show-key").checked = false;
  }
  function requirements() {
    const apiMode = $("connection-mode").value === "api";
    $("connection-model").required = apiMode;
    $("connection-key").required = apiMode && !(profile?.has_api_key && profile.base_url === $("connection-url").value.trim().replace(/\/+$/, ""));
    $("connection-save").textContent = apiMode ? "保存并启用 ↗" : "切换为演示模式 ↗";
    let deepseek = false;
    try { deepseek = new URL($("connection-url").value.trim()).hostname === "api.deepseek.com"; } catch {}
    $("connection-model-hint").textContent = deepseek ? "DeepSeek Flash 的 API 模型 ID 为 deepseek-flash，请不要填写 DeepSeek-V4.1-Flash。" : "填写 API 模型 ID，不是官网的展示名称。";
    $("connection-model").placeholder = deepseek ? "deepseek-flash" : "填写服务商提供的模型 ID";
  }
  function fillProfile(data, prepareApi = false) {
    profile = data;
    $("connection-mode").value = prepareApi && data.mode === "demo" ? "api" : data.mode;
    $("connection-url").value = data.base_url;
    $("connection-model").value = data.model;
    clearKey();
    $("connection-key").placeholder = data.has_api_key ? "已保存密钥 · 留空保留，填写则替换" : "填写你的 API Key";
    $("connection-index").textContent = data.embedding_mode === "demo" ? "检索使用已有本地字词索引，无需额外填写 Embedding API。它不具备语义向量模型的检索能力。" : `资料检索沿用 ${data.embedding_model} 向量索引，模型切换无需重新上传。`;
    requirements();
  }
  async function openConnection() {
    if (busy) return;
    if (window.studyAuth && !window.studyAuth.require("登录后，配置你的学习模型。")) return;
    if (!dialog.open) dialog.showModal();
    message("正在读取连接设置…");
    setBusy(true);
    try { fillProfile(await api("/api/connection"), true); message(""); }
    catch (error) { message(error.message, true); }
    finally { setBusy(false); }
  }
  function setBusy(value) {
    busy = value;
    [...form.elements].forEach(control => { control.disabled = value; });
    dialog.setAttribute("aria-busy", String(value));
  }
  function body() {
    return {mode: $("connection-mode").value, base_url: $("connection-url").value.trim(), model: $("connection-model").value.trim(), api_key: $("connection-key").value.trim()};
  }
  $("mode").addEventListener("click", openConnection);
  $("connection-open").addEventListener("click", openConnection);
  commands.push({label: "模型连接与 API 设置", action: openConnection});
  $("connection-mode").addEventListener("change", requirements);
  $("connection-url").addEventListener("input", requirements);
  $("connection-show-key").addEventListener("change", () => { $("connection-key").type = $("connection-show-key").checked ? "text" : "password"; });
  dialog.addEventListener("close", clearKey);
  $("connection-test").addEventListener("click", async () => {
    if (busy || !form.reportValidity()) return;
    const payload = body();
    setBusy(true); message("正在验证接口与工具调用能力…");
    try { const result = await post("/api/connection/test", payload); if (dialog.open) message(result.message); }
    catch (error) { if (dialog.open) message(error.message, true); }
    finally { setBusy(false); }
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    const payload = body();
    setBusy(true); message("正在保存连接…");
    try {
      const data = await api("/api/connection", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
      fillProfile(data); updateModelMode(data.mode, data.model);
      const text = data.mode === "api" ? `已启用 ${data.model}。关闭面板后即可开始提问。` : "已切换为离线演示。";
      if (dialog.open) message(text);
      notify(text);
    } catch (error) { if (dialog.open) message(error.message, true); }
    finally { setBusy(false); }
  });
})();
