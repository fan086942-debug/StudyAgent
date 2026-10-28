(() => {
  "use strict";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)");
  const nav = document.querySelector(".side-nav");
  const indicator = document.createElement("div");
  indicator.className = "nav-active-indicator";
  indicator.setAttribute("aria-hidden", "true");
  nav.prepend(indicator);
  nav.classList.add("nav-ready");
  let navFrame = 0;
  function positionNav() {
    navFrame = 0;
    const button = nav.querySelector(".nav-item.active");
    if (!button) return;
    indicator.style.setProperty("--nav-y", `${button.offsetTop}px`);
    indicator.style.setProperty("--nav-height", `${button.offsetHeight}px`);
  }
  function queueNav() { if (!navFrame) navFrame = requestAnimationFrame(positionNav); }
  new MutationObserver(queueNav).observe(nav, {subtree: true, attributes: true, attributeFilter: ["class"]});
  new ResizeObserver(queueNav).observe(nav);
  positionNav();
  const railToggle = $("desktop-sidebar-toggle");
  let collapsed = matchMedia("(min-width: 701px) and (max-width: 979px)").matches;
  try {
    const saved = localStorage.getItem("study-rail-collapsed");
    if (saved !== null) collapsed = saved === "true";
  } catch {}
  function synchronizeRail() {
    document.body.classList.toggle("rail-collapsed", collapsed);
    railToggle.setAttribute("aria-expanded", String(!collapsed));
    railToggle.setAttribute("aria-label", collapsed ? "展开导航与资料库" : "收起导航");
    railToggle.title = railToggle.getAttribute("aria-label");
    queueNav();
  }
  nav.querySelectorAll(".nav-item").forEach(button => { button.setAttribute("aria-label", button.querySelector("span").textContent); button.title = button.getAttribute("aria-label"); });
  function setRailCollapsed(value) {
    collapsed = value;
    try { localStorage.setItem("study-rail-collapsed", String(collapsed)); } catch {}
    synchronizeRail();
  }
  railToggle.addEventListener("click", () => setRailCollapsed(!collapsed));
  window.studyRail = {expand: () => setRailCollapsed(false)};
  synchronizeRail();


  const scene = $("knowledge-scene"), toggle = $("scene-motion");
  let paused = false, inView = false, pointerFrame = 0;
  try { paused = localStorage.getItem("study-motion-paused") === "true"; } catch {}
  function synchronizeMotion() {
    const stopped = paused || reduced.matches || document.hidden || !inView;
    scene.classList.toggle("scene-paused", stopped);
    toggle.disabled = reduced.matches;
    toggle.setAttribute("aria-pressed", String(paused));
    toggle.setAttribute("aria-label", reduced.matches ? "系统已启用减少动画" : paused ? "播放知识连接动效" : "暂停知识连接动效");
    $("scene-motion-icon").setAttribute("d", paused ? "m7 4 8 6-8 6Z" : "M7 5v10M13 5v10");
  }
  toggle.addEventListener("click", () => {
    paused = !paused;
    try { localStorage.setItem("study-motion-paused", String(paused)); } catch {}
    synchronizeMotion();
  });
  new IntersectionObserver(entries => {
    inView = entries[0].isIntersecting;
    synchronizeMotion();
  }, {threshold: .1}).observe(scene);
  document.addEventListener("visibilitychange", synchronizeMotion);
  function resetPointer() {
    cancelAnimationFrame(pointerFrame); pointerFrame = 0;
    scene.style.removeProperty("--scene-x"); scene.style.removeProperty("--scene-y");
  }
  scene.addEventListener("pointermove", event => {
    if (paused || reduced.matches || !finePointer.matches || event.pointerType !== "mouse") return;
    const rect = scene.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width - .5;
    const y = (event.clientY - rect.top) / rect.height - .5;
    if (pointerFrame) return;
    pointerFrame = requestAnimationFrame(() => {
      pointerFrame = 0;
      scene.style.setProperty("--scene-x", `${(x * 16).toFixed(1)}px`);
      scene.style.setProperty("--scene-y", `${(y * 12).toFixed(1)}px`);
    });
  }, {passive: true});
  scene.addEventListener("pointerleave", resetPointer);
  reduced.addEventListener("change", () => { resetPointer(); synchronizeMotion(); });
  synchronizeMotion();

  const cardAnimations = new WeakMap();
  const seen = new WeakSet();
  function reveal(node, delay = 0) {
    if (reduced.matches || !node.getClientRects().length) return;
    cardAnimations.get(node)?.cancel();
    const animation = node.animate([
      {opacity: 0, transform: "translateY(14px)"},
      {opacity: 1, transform: "translateY(0)"},
    ], {duration: 400, delay, easing: "cubic-bezier(.2,.75,.2,1)", fill: "backwards"});
    cardAnimations.set(node, animation);
  }
  const observer = new IntersectionObserver(entries => {
    let index = 0;
    for (const entry of entries) {
      if (!entry.isIntersecting || seen.has(entry.target)) continue;
      seen.add(entry.target); observer.unobserve(entry.target);
      reveal(entry.target, Math.min(index++ * 45, 180));
    }
  }, {threshold: .06});
  const selector = ".stat-card,.history-record,.history-empty,.surface-card,.question-item,.source";
  function observeCards(root) {
    if (root.matches?.(selector) && !seen.has(root)) observer.observe(root);
    root.querySelectorAll?.(selector).forEach(node => { if (!seen.has(node)) observer.observe(node); });
  }
  observeCards($("workspace"));
  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) {
      if (node.nodeType === Node.ELEMENT_NODE) observeCards(node);
    }
  }).observe($("workspace"), {subtree: true, childList: true});
  reduced.addEventListener("change", () => {
    if (reduced.matches) $("workspace").getAnimations({subtree: true}).forEach(animation => animation.cancel());
  });
})();
