(() => {
  const selectedTrendingId = () =>
    document.querySelector('#trending-audio-panel input[name="trending_audio_id"]:checked')?.value ?? "";
  document.querySelectorAll("form[data-trending-aware]").forEach((form) => {
    form.addEventListener("submit", () => {
      let hidden = form.querySelector('input[type="hidden"][name="trending_audio_id"]');
      if (!hidden) {
        hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "trending_audio_id";
        form.appendChild(hidden);
      }
      hidden.value = selectedTrendingId();
    });
  });

  const campaignForm = document.getElementById("campaign-form");
  if (campaignForm) setupCampaignBuilder(campaignForm);

  document.querySelectorAll(".secret-form").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("[data-busy-label]");
      const message = form.querySelector(".busy-message");
      if (button) {
        button.disabled = true;
        button.textContent = button.dataset.busyLabel;
      }
      if (message) message.textContent = " This can take several minutes.";
    });
  });

  const aggregate = document.getElementById("aggregate-logs");
  if (aggregate) setupAggregateLogs(aggregate);

  const logs = document.getElementById("job-logs");
  if (!logs) return;
  const jobId = logs.dataset.jobId;
  const statusEl = document.getElementById("job-status");
  const autoScroll = document.getElementById("log-autoscroll");
  const pauseButton = document.getElementById("log-pause");
  let paused = false;

  pauseButton?.addEventListener("click", () => {
    paused = !paused;
    pauseButton.textContent = paused ? "Resume" : "Pause";
  });
  document.getElementById("log-copy")?.addEventListener("click", async (event) => {
    await navigator.clipboard.writeText(logs.textContent || "");
    event.currentTarget.textContent = "Copied";
    setTimeout(() => { event.currentTarget.textContent = "Copy"; }, 1200);
  });

  const poll = async () => {
    if (paused) return;
    try {
      const res = await fetch(`/api/jobs/${jobId}`, { headers: { Accept: "application/json" } });
      if (!res.ok) return;
      const data = await res.json();
      if (data.logs !== undefined) {
        logs.textContent = data.logs || "No log lines yet.";
        if (autoScroll?.checked) logs.scrollTop = logs.scrollHeight;
      }
      if (statusEl && data.status) statusEl.textContent = data.status;
      const badge = document.querySelector(".badge[data-status]");
      if (badge && data.status && badge.dataset.status !== data.status) {
        window.location.reload();
      }
    } catch {
      /* keep last view */
    }
  };

  const status = statusEl?.textContent?.trim();
  if (["queued", "submitting", "running", "cancel_requested"].includes(status)) {
    setInterval(poll, 2500);
  }
  if (autoScroll?.checked) logs.scrollTop = logs.scrollHeight;
})();

function setupAggregateLogs(container) {
  const filters = document.getElementById("logs-filters");
  const pauseButton = document.getElementById("aggregate-pause");
  const autoScroll = document.getElementById("aggregate-autoscroll");
  const state = document.getElementById("logs-live-state");
  let paused = false;

  const load = async () => {
    if (paused) return;
    const params = new URLSearchParams(new FormData(filters));
    try {
      const response = await fetch(`/api/logs?${params}`, {headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error("Log endpoint unavailable");
      const data = await response.json();
      container.replaceChildren(...data.entries.map((entry) => {
        const row = document.createElement("div");
        row.className = "log-line";
        const meta = document.createElement("span");
        meta.className = "log-meta";
        const jobLink = document.createElement("a");
        jobLink.href = entry.job_url;
        jobLink.textContent = `${entry.job_id.slice(0, 8)} · ${entry.status}`;
        meta.append(jobLink);
        if (entry.kernel_url) {
          const kernel = document.createElement("a");
          kernel.href = entry.kernel_url;
          kernel.target = "_blank";
          kernel.rel = "noopener";
          kernel.textContent = "Kaggle";
          meta.append(" · ", kernel);
        }
        const text = document.createElement("span");
        text.className = "log-text";
        text.textContent = entry.line;
        row.append(meta, text);
        return row;
      }));
      document.getElementById("logs-job-count").textContent = `${data.jobs.length} jobs`;
      state.textContent = `Updated ${new Date(data.generated_at).toLocaleTimeString()}`;
      if (autoScroll.checked) container.scrollTop = container.scrollHeight;
    } catch {
      state.textContent = "Polling interrupted";
    }
  };
  filters.addEventListener("submit", (event) => {
    event.preventDefault();
    load();
  });
  pauseButton.addEventListener("click", () => {
    paused = !paused;
    pauseButton.textContent = paused ? "Resume" : "Pause";
    state.textContent = paused ? "Polling paused" : "Live polling";
    if (!paused) load();
  });
  document.getElementById("aggregate-copy").addEventListener("click", async (event) => {
    await navigator.clipboard.writeText(
      [...container.querySelectorAll(".log-text")].map((node) => node.textContent).join("\n")
    );
    event.currentTarget.textContent = "Copied";
    setTimeout(() => { event.currentTarget.textContent = "Copy"; }, 1200);
  });
  const initial = new URLSearchParams(window.location.search);
  for (const name of ["status", "job", "text"]) {
    if (initial.has(name)) filters.elements[name].value = initial.get(name);
  }
  load();
  setInterval(load, 2500);
}

function setupCampaignBuilder(form) {
  const preview = document.getElementById("reel-preview");
  const campaignJson = document.getElementById("campaign-json");
  const error = document.getElementById("plan-error");
  const submit = form.querySelector(".queue-campaign");
  const customSingle = document.getElementById("custom-single");
  const customMode = () => Boolean(customSingle?.checked);
  let plan = null;
  let timer = null;

  const selected = (name) => form.querySelector(`[name="${name}"]:checked`)?.value;
  const variables = () => Object.fromEntries(
    [...form.querySelectorAll("[data-variable]")].map((input) => [input.dataset.variable, input.value])
  );
  const setDefaults = (radio) => {
    const defaults = JSON.parse(radio.dataset.defaults || "{}");
    form.querySelectorAll("[data-variable]").forEach((input) => {
      if (defaults[input.dataset.variable] !== undefined) input.value = defaults[input.dataset.variable];
    });
  };
  const syncJson = () => {
    if (plan && !customMode()) campaignJson.value = JSON.stringify(plan);
  };
  const render = () => {
    preview.innerHTML = "";
    plan.reels.forEach((reel, index) => {
      const card = document.createElement("article");
      card.className = "reel-card";
      card.innerHTML = `
        <header><span class="reel-number">${index + 1}</span><div><strong>Reel ${index + 1}</strong><small>${reel.language} · ${reel.animate ? "unique animation" : `reuses motion ${reel.motion_source_index + 1}`}</small></div></header>
        <label class="field"><span>Hook</span><textarea rows="2" maxlength="500" data-reel="${index}" data-key="hook"></textarea></label>
        <label class="field"><span>Narration</span><textarea rows="3" maxlength="4000" data-reel="${index}" data-key="narration"></textarea></label>
        <label class="field"><span>Captions <small>one per line, up to 8</small></span><textarea rows="3" data-reel="${index}" data-key="captions"></textarea></label>
        <label class="field"><span>CTA</span><input maxlength="500" data-reel="${index}" data-key="cta"></label>
        <details><summary>Visual prompts</summary>
          <label class="field"><span>Image prompt</span><textarea rows="4" data-reel="${index}" data-key="flux_prompt"></textarea></label>
          <label class="field"><span>Motion prompt</span><textarea rows="3" data-reel="${index}" data-key="ltx_motion_prompt"></textarea></label>
          <label class="field"><span>Negative prompt</span><textarea rows="2" data-reel="${index}" data-key="negative_prompt"></textarea></label>
        </details>`;
      preview.appendChild(card);
      card.querySelectorAll("[data-key]").forEach((input) => {
        const value = reel[input.dataset.key];
        input.value = Array.isArray(value) ? value.join("\n") : value;
      });
    });
    syncJson();
  };
  const refresh = async () => {
    if (customMode()) return;
    error.classList.add("hidden");
    submit.disabled = true;
    try {
      const response = await fetch("/api/campaigns/preview", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({
          template_id: selected("template_id"),
          language: form.elements.language.value,
          campaign_size: Number(form.elements.campaign_size.value),
          strategy: selected("strategy"),
          variables: variables()
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not build campaign preview.");
      plan = data;
      render();
      submit.disabled = false;
    } catch (reason) {
      plan = null;
      campaignJson.value = "";
      error.textContent = reason.message;
      error.classList.remove("hidden");
      preview.innerHTML = '<p class="empty">Fix the campaign details to preview reels.</p>';
    }
  };
  const schedule = () => {
    clearTimeout(timer);
    if (!customMode()) submit.disabled = true;
    timer = setTimeout(refresh, 250);
  };

  form.querySelectorAll("[data-template-tab]").forEach((button) => button.addEventListener("click", () => {
    form.querySelectorAll("[data-template-tab]").forEach((item) => item.classList.toggle("active", item === button));
    form.querySelectorAll("[data-template-panel]").forEach((panel) => panel.classList.toggle("hidden", panel.dataset.templatePanel !== button.dataset.templateTab));
  }));
  form.querySelectorAll("[name=template_id]").forEach((radio) => radio.addEventListener("change", () => {
    setDefaults(radio);
    schedule();
  }));
  form.querySelectorAll("[data-variable], #campaign-language, #campaign-size, [name=strategy]").forEach((input) => input.addEventListener("input", schedule));
  document.getElementById("refresh-plan").addEventListener("click", refresh);
  preview.addEventListener("input", (event) => {
    const input = event.target.closest("[data-reel]");
    if (!input || !plan) return;
    plan.reels[Number(input.dataset.reel)][input.dataset.key] =
      input.dataset.key === "captions" ? input.value.split("\n") : input.value;
    syncJson();
  });
  customSingle?.addEventListener("change", () => {
    const custom = customMode();
    ["language", "voice", "strategy", "campaign_size"].forEach((name) => {
      form.querySelectorAll(`[name="${name}"]`).forEach((input) => input.disabled = custom);
    });
    form.querySelectorAll("[data-variable]").forEach((input) => input.required = !custom && ["vendor_name", "dish_name", "offer_text", "area", "cta_url"].includes(input.dataset.variable));
    campaignJson.value = custom ? "" : JSON.stringify(plan || {});
    preview.closest(".reel-preview").classList.toggle("muted-section", custom);
    submit.textContent = custom ? "Queue custom job" : "Queue campaign";
    submit.disabled = custom ? !form.elements.prompt.value.trim() : !plan;
  });
  form.elements.prompt?.addEventListener("input", () => {
    if (customMode()) submit.disabled = !form.elements.prompt.value.trim();
  });
  form.addEventListener("submit", (event) => {
    if (!customMode() && !plan) {
      event.preventDefault();
      refresh();
      return;
    }
    const oversized = [...form.querySelectorAll('input[type="file"][data-max-bytes]')]
      .find((input) => input.files[0] && input.files[0].size > Number(input.dataset.maxBytes));
    if (oversized) {
      event.preventDefault();
      error.textContent = `${oversized.name} exceeds the configured upload size limit.`;
      error.classList.remove("hidden");
      oversized.focus();
      return;
    }
    if (!customMode()) {
      const invalidCaptions = plan.reels.some((reel) =>
        !Array.isArray(reel.captions) || reel.captions.length < 1 ||
        reel.captions.length > 8 || reel.captions.some((line) => !line.trim() || [...line].length > 500)
      );
      if (invalidCaptions) {
        event.preventDefault();
        error.textContent = "Each reel needs 1–8 non-empty captions of at most 500 characters.";
        error.classList.remove("hidden");
        return;
      }
      syncJson();
    }
  });

  const initial = form.querySelector("[name=template_id]:checked");
  if (initial) setDefaults(initial);
  refresh();
}
