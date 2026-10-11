(() => {
  "use strict";
  const root = document.documentElement;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)");
  const palettes = new Set(["aurora", "ocean", "sunset"]);
  const paletteMenu = document.getElementById("palette-menu");
  const paletteButtons = [...paletteMenu.querySelectorAll("[data-palette]")];

  function syncThemeColor() {
    const color = getComputedStyle(root).getPropertyValue("--bg").trim();
    document.querySelector('meta[name="theme-color"]').content = color;
  }
  function selectPalette(palette, save = true) {
    root.dataset.palette = palettes.has(palette) ? palette : "aurora";
    paletteButtons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.palette === root.dataset.palette)));
    if (save) { try { localStorage.setItem("study-palette", root.dataset.palette); } catch {} }
    syncThemeColor();
  }
  selectPalette(root.dataset.palette, false);
  paletteButtons.forEach(button => button.addEventListener("click", () => {
    selectPalette(button.dataset.palette);
    paletteMenu.open = false;
    paletteMenu.querySelector("summary").focus({preventScroll: true});
  }));
  document.addEventListener("pointerdown", event => {
    if (paletteMenu.open && !paletteMenu.contains(event.target)) paletteMenu.open = false;
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && paletteMenu.open) {
      paletteMenu.open = false; paletteMenu.querySelector("summary").focus({preventScroll: true});
    }
  });
  const themeObserver = new MutationObserver(syncThemeColor);
  themeObserver.observe(root, {attributes: true, attributeFilter: ["data-theme"]});

  const hour = Number(new Intl.DateTimeFormat("en-US", {timeZone: "Asia/Shanghai", hour: "numeric", hourCycle: "h23"}).format(new Date()));
  const greeting = hour < 6 ? "夜深了，学习也可以慢一点。" : hour < 12 ? "上午好，给今天一点新灵感。" : hour < 18 ? "午后好，让好奇心继续发光。" : "晚上好，把今天的收获连起来。";
  document.getElementById("hero-greeting").textContent = greeting;

  const pointerCards = [...document.querySelectorAll(".hero, .capability-card")];
  pointerCards.forEach(card => {
    let frame = 0, x = .5, y = .5;
    card.addEventListener("pointermove", event => {
      if (reduced.matches || !finePointer.matches || event.pointerType !== "mouse") return;
      const rect = card.getBoundingClientRect();
      x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        card.style.setProperty("--pointer-x", `${(x * 100).toFixed(1)}%`);
        card.style.setProperty("--pointer-y", `${(y * 100).toFixed(1)}%`);
        if (card.classList.contains("hero")) {
          card.style.setProperty("--parallax-x", `${((x - .5) * 10).toFixed(1)}px`);
          card.style.setProperty("--parallax-y", `${((y - .5) * 8).toFixed(1)}px`);
        } else {
          card.style.setProperty("--tilt-x", `${((.5 - y) * 3).toFixed(2)}deg`);
          card.style.setProperty("--tilt-y", `${((x - .5) * 3).toFixed(2)}deg`);
        }
      });
    }, {passive: true});
    const reset = () => {
      cancelAnimationFrame(frame); frame = 0;
      ["--pointer-x", "--pointer-y", "--parallax-x", "--parallax-y", "--tilt-x", "--tilt-y"].forEach(name => card.style.removeProperty(name));
    };
    card.addEventListener("pointerleave", reset);
    reduced.addEventListener("change", reset);
  });

  document.addEventListener("pointerdown", event => {
    if (reduced.matches || event.button !== 0) return;
    const button = event.target.closest(".question-actions button, .nav-item, .hero-link, .full, .capability-card");
    if (!button || button.disabled || button.querySelectorAll(".button-pulse").length >= 2) return;
    const rect = button.getBoundingClientRect(), size = Math.max(rect.width, rect.height);
    const pulse = document.createElement("span"); pulse.className = "button-pulse"; pulse.setAttribute("aria-hidden", "true");
    pulse.style.width = pulse.style.height = `${size}px`;
    pulse.style.left = `${event.clientX - rect.left - size / 2}px`;
    pulse.style.top = `${event.clientY - rect.top - size / 2}px`;
    button.classList.add("pulse-host"); button.append(pulse);
    const animation = pulse.animate([{transform: "scale(0)", opacity: .16}, {transform: "scale(2.5)", opacity: 0}], {duration: 500, easing: "ease-out"});
    animation.finished.then(() => pulse.remove(), () => pulse.remove());
  }, {passive: true});

  if ("IntersectionObserver" in window) {
    const reveal = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        if (!reduced.matches) entry.target.classList.add("reveal-visible");
        reveal.unobserve(entry.target);
      });
    }, {threshold: .1});
    document.querySelectorAll(".stat-card, .capability-card, .surface-card, .section-heading").forEach(node => reveal.observe(node));
  }

  const statAnimations = new WeakMap();
  const statsObserver = new MutationObserver(records => {
    if (reduced.matches) return;
    const targets = new Set(records.map(record => (record.target.nodeType === Node.TEXT_NODE ? record.target.parentElement : record.target)?.closest(".stat-card strong")).filter(Boolean));
    targets.forEach(target => {
      statAnimations.get(target)?.cancel();
      const animation = target.animate([{opacity: .5, transform: "translateY(4px)"}, {opacity: 1, transform: "translateY(0)"}], {duration: 280, easing: "ease-out"});
      statAnimations.set(target, animation);
    });
  });
  statsObserver.observe(document.querySelector(".stats-grid"), {childList: true, characterData: true, subtree: true});

  const meter = document.createElement("div"); meter.className = "scroll-meter"; meter.setAttribute("aria-hidden", "true");
  document.querySelector(".app-header").append(meter);
  const backToTop = document.getElementById("back-to-top");
  let scrollFrame = 0;
  function updateScroll() {
    scrollFrame = 0;
    const range = document.documentElement.scrollHeight - innerHeight;
    meter.style.transform = `scaleX(${range > 0 ? Math.min(1, Math.max(0, scrollY / range)) : 0})`;
    // Keep the focused control available after it scrolls back to the top.
    backToTop.hidden = scrollY < 420 && document.activeElement !== backToTop;
  }
  const queueScroll = () => { if (!scrollFrame) scrollFrame = requestAnimationFrame(updateScroll); };
  window.addEventListener("scroll", queueScroll, {passive: true});
  window.addEventListener("resize", queueScroll, {passive: true});
  document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => setTimeout(queueScroll, 0)));
  backToTop.addEventListener("click", () => {
    document.getElementById("workspace").focus({preventScroll: true});
    window.scrollTo({top: 0, behavior: reduced.matches ? "instant" : "smooth"});
  });
  backToTop.addEventListener("blur", queueScroll);
  updateScroll();
  document.addEventListener("visibilitychange", () => root.classList.toggle("motion-paused", document.hidden));
})();
