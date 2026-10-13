(() => {
  "use strict";
  const dialog = $("auth-screen"), form = $("auth-form");
  let registering = false, available = true, busy = false, setup = false;
  let opener = null, context = "登录后，继续你的学习。";
  let bootstrapEpoch = 0;
  const state = window.studyAuth = {enabled: true, ready: false, user: null, epoch: 0, require: requireAccount, open};

  function canUse() { return state.ready && (!state.enabled || !!state.user); }

  function synchronizeUI() {
    document.body.dataset.auth = canUse() ? "signed-in" : "guest";
    $("login-open").hidden = !state.enabled || !!state.user;
    $("account-menu").hidden = !state.user;
    $("account-name").textContent = state.user?.username || "";
    $("account-avatar").textContent = state.user?.username?.[0]?.toUpperCase() || "";
    $("ask-button").textContent = canUse() ? "发送问题" : "登录后提问";
    $("agent-availability").textContent = canUse() ? "准备就绪" : "登录后启用";
    document.querySelectorAll(".guest-only").forEach(node => { node.hidden = canUse(); });
    document.querySelectorAll(".account-only").forEach(node => { node.hidden = !canUse(); });
  }

  function clearWorkspace(keepDraft = true) {
    const draft = keepDraft ? $("question").value : "";
    clearTimeout(documentRefreshTimer);
    questionController?.abort();
    currentCourse = ""; selected.clear(); libraryDocuments = [];
    resetLearning(); resetArtifacts();
    $("result").hidden = true;
    for (const id of ["answer", "sources", "trace", "warning", "generated-artifacts", "matched-questions", "artifact-content", "artifact-sources", "artifact-downloads", "session-turns", "papers", "question-list"]) $(id).replaceChildren();
    $("session-history").hidden = true;
    $("question").value = draft; updateQuestionCount();
    $("course").replaceChildren(element("option", "登录后查看课程"));
    $("course").firstElementChild.value = "";
    $("course-name").value = ""; $("files").value = "";
    $("documents").replaceChildren(); $("document-count").textContent = "0";
    $("course-delete-open").hidden = true;
    $("connection-key").value = "";
    $("connection-model").value = ""; $("connection-url").value = "";
    document.querySelectorAll("dialog[open]").forEach(node => node.close());
    $("mode").textContent = "模型设置";
    $("mode").classList.remove("live");
    $("mode-note").textContent = "";
    for (const id of ["wrongbook", "plans", "conversation-history", "artifact-history", "question-list"]) {
      $(id).replaceChildren(element("p", "登录后，在这里继续你的学习。", "empty"));
    }
    for (const id of ["stat-documents", "stat-attempts", "stat-wrong", "stat-plan"]) $(id).textContent = "—";
    try { sessionStorage.removeItem("study-agent-session"); } catch {}
  }

  function mode(create) {
    registering = create;
    $("auth-title").textContent = create ? "创建学习账号" : "登录学习空间";
    $("auth-description").textContent = context;
    $("auth-submit").textContent = create ? "创建账号，开始学习" : "登录并继续";
    $("auth-password").autocomplete = create ? "new-password" : "current-password";
    for (const [id, selected] of [["auth-tab-login", !create], ["auth-tab-register", create]]) {
      $(id).setAttribute("aria-selected", String(selected));
      $(id).tabIndex = selected ? 0 : -1;
    }
    $("auth-tab-register").hidden = !available;
    form.setAttribute("aria-labelledby", create ? "auth-tab-register" : "auth-tab-login");
    $("auth-username-hint").hidden = !create;
    $("auth-password-hint").hidden = !create;
    $("auth-setup-note").hidden = !setup || !create;
    $("auth-error").textContent = "";
  }

  function open(reason = "登录后，继续你的学习。") {
    if (canUse()) return;
    context = reason;
    if (!dialog.open) {
      opener = document.activeElement;
      closeSidebar();
      $("command-dialog").close();
      mode(setup);
      dialog.showModal();
    } else $("auth-description").textContent = reason;
  }

  function requireAccount(reason = "登录后使用 Agent，保存你的学习进度。") {
    if (canUse()) return true;
    open(reason);
    return false;
  }

  window.showAuthGate = () => {
    if (!state.user) { open("登录后使用 Agent，继续这个问题。"); return; }
    state.user = null;
    state.epoch += 1;
    clearWorkspace(true);
    synchronizeUI();
    open("登录已过期，重新登录后继续。你的问题草稿已保留。");
  };

  async function enter(user) {
    state.user = user;
    state.epoch += 1;
    synchronizeUI();
    if (dialog.open) dialog.close();
    await start();
    showView(location.hash.slice(1) || "study", false);
  }

  async function bootstrap() {
    const epoch = ++bootstrapEpoch;
    $("auth-submit").disabled = true;
    $("auth-retry").hidden = true;
    try {
      const result = await api("/api/auth/me");
      if (epoch !== bootstrapEpoch) return;
      state.enabled = result.enabled;
      state.ready = true;
      available = result.registration_enabled !== false;
      setup = !!result.setup_required;
      if (!state.enabled || result.user) await enter(result.user);
      else {
        clearWorkspace(true); synchronizeUI(); mode(setup);
        showView(location.hash.slice(1) || "study", false);
      }
    } catch (error) {
      if (epoch !== bootstrapEpoch) return;
      state.ready = false;
      synchronizeUI();
      $("auth-error").textContent = error.message;
      $("auth-retry").hidden = false;
      status("服务暂时无法连接，可以稍后重试。", true);
    } finally { if (epoch === bootstrapEpoch) $("auth-submit").disabled = !state.ready; }
  }

  const protectedForms = new Set(["question-form", "course-form", "upload-form", "generation-form", "plan-form", "question-search-form", "connection-form"]);
  document.addEventListener("submit", event => {
    if (protectedForms.has(event.target.id) && !requireAccount()) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener("click", event => {
    const control = event.target.closest("#ask-button,#generate-button,#plan-button,#mode,#connection-open,#refresh,#refresh-papers,#refresh-artifacts,#refresh-history,#new-session");
    if (control && !requireAccount(control.id === "ask-button" ? "登录后使用 Agent，继续这个问题。" : "登录后，使用你的学习空间。")) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  document.querySelectorAll("[data-login]").forEach(button => button.addEventListener("click", () => open()));
  $("auth-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    const rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  });
  dialog.addEventListener("close", () => {
    $("auth-password").value = ""; $("auth-password").type = "password";
    $("auth-show-password").checked = false;
    queueMicrotask(() => {
      if (opener?.isConnected && opener.getClientRects().length) opener.focus({preventScroll: true});
      else if (!state.user) $("login-open").focus({preventScroll: true});
    });
  });
  $("auth-tab-login").addEventListener("click", () => mode(false));
  $("auth-tab-register").addEventListener("click", () => mode(true));
  $("auth-tabs").addEventListener("keydown", event => {
    if (!available || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    mode(event.key === "Home" ? false : event.key === "End" ? true : !registering);
    $(registering ? "auth-tab-register" : "auth-tab-login").focus();
  });
  $("auth-retry").addEventListener("click", bootstrap);
  $("auth-show-password").addEventListener("change", event => {
    $("auth-password").type = event.target.checked ? "text" : "password";
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || !state.ready || !form.reportValidity()) return;
    busy = true;
    bootstrapEpoch += 1;
    const payload = {username: $("auth-username").value.trim(), password: $("auth-password").value};
    const create = registering;
    $("auth-submit").disabled = true;
    $("auth-tab-login").disabled = $("auth-tab-register").disabled = true;
    $("auth-error").textContent = "";
    form.setAttribute("aria-busy", "true");
    $("auth-submit").textContent = "正在进入…";
    try {
      const result = await post(`/api/auth/${create ? "register" : "login"}`, payload);
      clearWorkspace(true);
      await enter(result.user);
      notify("已登录，继续你的学习。");
      if (activeView === "study") $("question").focus({preventScroll: true});
    } catch (error) {
      $("auth-error").textContent = error.message;
      if (dialog.open) $("auth-error").focus();
    } finally {
      busy = false;
      form.removeAttribute("aria-busy");
      $("auth-submit").disabled = false;
      $("auth-tab-login").disabled = $("auth-tab-register").disabled = false;
      $("auth-submit").textContent = registering ? "创建账号，开始学习" : "登录并继续";
    }
  });
  $("logout").addEventListener("click", async () => {
    $("logout").disabled = true;
    try {
      await post("/api/auth/logout", {});
      bootstrapEpoch += 1;
      state.user = null;
      state.epoch += 1;
      $("account-menu").open = false;
      clearWorkspace(false); synchronizeUI();
      try { localStorage.removeItem("study-course"); } catch {}
      showView("study", false);
      $("login-open").focus({preventScroll: true});
      notify("已退出账号。");
    } catch (error) { status(error.message, true); }
    finally { $("logout").disabled = false; }
  });
  bootstrap();
})();
