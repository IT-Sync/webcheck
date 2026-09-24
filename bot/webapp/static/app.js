(() => {
  "use strict";

  const telegram = window.Telegram?.WebApp;
  const accessGate = document.querySelector("#access-gate");
  const appShell = document.querySelector("#app-shell");

  if (!telegram?.initData) {
    accessGate.hidden = false;
    document.body.classList.add("direct-access");
    return;
  }

  appShell.hidden = false;
  document.body.classList.add("telegram-access");
  const state = {
    sites: [], user: null, limit: 0, loaded: false, filter: "all",
    sort: "priority", query: "", group: "all", tag: "all", project: "all", projects: [], historySite: null,
    maintenanceSite: null,
    historyDays: 7, historyRequest: 0,
  };
  const elements = {
    list: document.querySelector("#site-list"),
    empty: document.querySelector("#empty-state"),
    notice: document.querySelector("#notice"),
    welcome: document.querySelector("#welcome"),
    dialog: document.querySelector("#add-dialog"),
    form: document.querySelector("#add-form"),
    input: document.querySelector("#site-url"),
    groupInput: document.querySelector("#site-group"),
    tagsInput: document.querySelector("#site-tags"),
    formError: document.querySelector("#form-error"),
    submit: document.querySelector("#add-submit"),
    template: document.querySelector("#site-template"),
    closeAdd: document.querySelector("#close-add"),
    filterEmpty: document.querySelector("#filter-empty"),
    filterLabel: document.querySelector("#filter-label"),
    visibleCount: document.querySelector("#visible-count"),
    sort: document.querySelector("#sort-select"),
    search: document.querySelector("#site-search"),
    group: document.querySelector("#group-select"),
    tag: document.querySelector("#tag-select"),
    project: document.querySelector("#project-select"),
    siteProject: document.querySelector("#site-project"),
    teamDialog: document.querySelector("#team-dialog"),
    teamIdentity: document.querySelector("#team-identity"),
    teamCreateForm: document.querySelector("#team-create-form"),
    teamProjectName: document.querySelector("#team-project-name"),
    teamProjectSelect: document.querySelector("#team-project-select"),
    teamMemberList: document.querySelector("#team-member-list"),
    teamMemberForm: document.querySelector("#team-member-form"),
    teamMemberId: document.querySelector("#team-member-id"),
    teamMemberRole: document.querySelector("#team-member-role"),
    teamError: document.querySelector("#team-error"),
    monitorSection: document.querySelector("#monitor-section"),
    maintenanceDialog: document.querySelector("#maintenance-dialog"),
    maintenanceForm: document.querySelector("#maintenance-form"),
    maintenanceTitle: document.querySelector("#maintenance-title"),
    maintenanceStart: document.querySelector("#maintenance-start"),
    maintenanceEnd: document.querySelector("#maintenance-end"),
    maintenanceReason: document.querySelector("#maintenance-reason"),
    maintenanceError: document.querySelector("#maintenance-error"),
    maintenanceSubmit: document.querySelector("#maintenance-submit"),
    maintenanceList: document.querySelector("#maintenance-list"),
    closeMaintenance: document.querySelector("#close-maintenance"),
    historyDialog: document.querySelector("#history-dialog"),
    historyEyebrow: document.querySelector("#history-eyebrow"),
    historyTitle: document.querySelector("#history-title"),
    historyPeriods: [...document.querySelectorAll("#history-periods [data-days]")],
    historySummary: document.querySelector("#history-summary"),
    historyGranularity: document.querySelector("#history-granularity"),
    historyChart: document.querySelector("#history-chart"),
    historyLatencyChart: document.querySelector("#history-latency-chart"),
    historyPolicy: document.querySelector("#history-policy"),
    historyRegions: document.querySelector("#history-regions"),
    historyIncidents: document.querySelector("#history-incidents"),
    historyMaintenance: document.querySelector("#history-maintenance"),
    historyEvents: document.querySelector("#history-events"),
    closeHistory: document.querySelector("#close-history"),
    feedback: document.querySelector("#open-feedback"),
    metrics: [...document.querySelectorAll(".metric[data-filter]")],
  };

  const cacheKey = `webcheck.bootstrap.v2.${telegram?.initDataUnsafe?.user?.id || "anonymous"}`;

  function haptic(kind = "light") {
    telegram?.HapticFeedback?.impactOccurred(kind);
  }

  function authHeaders() {
    return {
      "Content-Type": "application/json",
      Authorization: `tma ${telegram?.initData || ""}`,
    };
  }

  async function api(path, options = {}) {
    const { timeoutMs = 15000, ...fetchOptions } = options;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, {
        ...fetchOptions,
        signal: controller.signal,
        headers: { ...authHeaders(), ...(fetchOptions.headers || {}) },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error?.message || "Сервис временно недоступен");
      }
      return payload;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Сервер отвечает слишком долго. Попробуйте ещё раз.");
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function hostFromUrl(value) {
    try { return new URL(value).hostname; } catch { return value; }
  }

  function relativeTime(value) {
    if (!value) return "ещё не проверялся";
    const delta = Math.max(0, Date.now() - new Date(value).getTime());
    const minutes = Math.floor(delta / 60000);
    if (minutes < 1) return "только что";
    if (minutes < 60) return `${minutes} мин. назад`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} ч. назад`;
    return new Date(value).toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
  }

  function latencyFromStatus(status) {
    const match = status?.match(/(?:\||^)\s*(\d+)\s*m?s(?:\s*\||$)/i);
    return match ? `${match[1]} мс` : "ожидает замера";
  }

  function statusLabel(site) {
    return ({ up: "В сети", down: "Недоступен", warning: "Внимание", paused: "На паузе", maintenance: "Обслуживание", pending: "Ожидает" })[site.status_kind];
  }

  function updateMetrics() {
    const counts = {
      total: state.sites.length,
      up: state.sites.filter((site) => site.status_kind === "up").length,
      attention: state.sites.filter((site) => ["down", "warning"].includes(site.status_kind)).length,
      paused: state.sites.filter((site) => site.is_paused).length,
    };
    Object.entries(counts).forEach(([key, value]) => {
      document.querySelector(`#metric-${key}`).textContent = value;
    });
    elements.metrics.forEach((metric) => {
      const active = metric.dataset.filter === state.filter;
      metric.classList.toggle("is-active", active);
      metric.setAttribute("aria-pressed", String(active));
    });
  }

  function visibleSites() {
    const filtered = state.sites.filter((site) => {
      const statusMatches = state.filter === "all"
        || (state.filter === "attention" && ["down", "warning"].includes(site.status_kind))
        || (state.filter === "paused" && site.is_paused)
        || site.status_kind === state.filter;
      const groupMatches = state.group === "all" || (site.site_group || "") === state.group;
      const tagMatches = state.tag === "all" || (site.tags || []).includes(state.tag);
      const projectMatches = state.project === "all" || String(site.project_id) === state.project;
      const haystack = [site.url, site.site_group || "", ...(site.tags || [])].join(" ").toLocaleLowerCase("ru");
      return statusMatches && groupMatches && tagMatches && projectMatches && haystack.includes(state.query);
    });
    const priority = { down: 0, warning: 1, pending: 2, up: 3, maintenance: 4, paused: 5 };
    return filtered.sort((left, right) => {
      if (state.sort === "name") return hostFromUrl(left.url).localeCompare(hostFromUrl(right.url), "ru");
      if (state.sort === "recent") return (Date.parse(right.last_checked) || 0) - (Date.parse(left.last_checked) || 0);
      return (priority[left.status_kind] ?? 5) - (priority[right.status_kind] ?? 5)
        || hostFromUrl(left.url).localeCompare(hostFromUrl(right.url), "ru");
    });
  }

  function showNotice(message) {
    elements.notice.textContent = message;
    elements.notice.classList.remove("hidden");
  }

  function hideNotice() {
    elements.notice.classList.add("hidden");
  }

  function makeSiteCard(site) {
    const card = elements.template.content.firstElementChild.cloneNode(true);
    card.dataset.siteId = site.id;
    card.dataset.status = site.status_kind;
    card.querySelector(".site-host").textContent = hostFromUrl(site.url);
    card.querySelector(".site-url").textContent = site.url;
    card.querySelector(".checked-at").textContent = relativeTime(site.last_checked);
    card.querySelector(".latency").textContent = latencyFromStatus(site.last_status);
    card.querySelector(".site-details").textContent = site.last_status || "Первый замер будет выполнен по расписанию или вручную.";
    card.querySelector(".status-badge b").textContent = statusLabel(site);
    card.querySelector(".site-project").textContent = `${site.project_name || "Personal"} · ${site.role || "owner"}`;
    const groupBadge = card.querySelector(".site-group");
    if (site.site_group) {
      groupBadge.textContent = site.site_group;
      groupBadge.classList.remove("hidden");
    }
    const maintenanceBadge = card.querySelector(".maintenance-badge");
    if (site.is_maintenance) maintenanceBadge.classList.remove("hidden");
    const tagRail = card.querySelector(".site-tags");
    tagRail.replaceChildren(...(site.tags || []).map((tag) => {
      const token = document.createElement("span");
      token.textContent = "#" + tag;
      return token;
    }));

    const actions = card.querySelector(".site-actions");
    const more = card.querySelector(".more-button");
    const toggle = card.querySelector('[data-action="toggle"]');
    toggle.textContent = site.is_maintenance ? "Идёт обслуживание" : (site.is_paused ? "Возобновить" : "Поставить на паузу");
    toggle.disabled = site.is_maintenance;
    if (site.role === "viewer") {
      actions.querySelectorAll('button[data-action]:not([data-action="history"])').forEach((button) => button.remove());
    }

    more.addEventListener("click", () => {
      const expanded = card.classList.toggle("expanded");
      actions.classList.toggle("hidden", !expanded);
      more.setAttribute("aria-expanded", String(expanded));
      haptic();
    });

    actions.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const action = button.dataset.action;
      if (action === "history") {
        await openHistory(site);
        return;
      }
      if (action === "group") {
        await changeGroup(site);
        return;
      }
      if (action === "tags") {
        await changeTags(site);
        return;
      }
      if (action === "maintenance") {
        await openMaintenance(site);
        return;
      }
      if (action === "delete") {
        const confirmed = await confirmDelete(hostFromUrl(site.url));
        if (!confirmed) return;
      }
      await runAction(site, action, actions);
    });
    return card;
  }

  function render() {
    const sites = visibleSites();
    const hasSites = state.sites.length > 0;
    elements.list.replaceChildren(...sites.map(makeSiteCard));
    elements.list.classList.toggle("hidden", sites.length === 0);
    elements.empty.classList.toggle("hidden", state.sites.length !== 0);
    elements.filterEmpty.classList.toggle("hidden", !hasSites || sites.length !== 0);
    elements.visibleCount.textContent = `${sites.length} из ${state.sites.length}`;
    elements.filterLabel.textContent = ({ all: "Все ресурсы", up: "Ресурсы в сети", attention: "Требуют внимания", paused: "Мониторинг на паузе" })[state.filter];
    renderGroups();
    renderTags();
    renderProjects();
    updateMetrics();
  }

  function renderGroups() {
    const selected = state.group;
    const groups = [...new Set(state.sites.map((site) => site.site_group).filter(Boolean))]
      .sort((left, right) => left.localeCompare(right, "ru"));
    elements.group.replaceChildren(
      new Option("Все группы", "all"),
      ...groups.map((group) => new Option(group, group)),
    );
    state.group = groups.includes(selected) ? selected : "all";
    elements.group.value = state.group;
  }

  function renderTags() {
    const selected = state.tag;
    const tags = [...new Set(state.sites.flatMap((site) => site.tags || []))]
      .sort((left, right) => left.localeCompare(right, "ru"));
    elements.tag.replaceChildren(
      new Option("Все теги", "all"),
      ...tags.map((tag) => new Option("#" + tag, tag)),
    );
    state.tag = tags.includes(selected) ? selected : "all";
    elements.tag.value = state.tag;
  }

  function renderProjects() {
    const selected = state.project;
    elements.project.replaceChildren(new Option("Все проекты", "all"),
      ...state.projects.map((project) => new Option(project.name, String(project.id))));
    state.project = state.projects.some((project) => String(project.id) === selected) ? selected : "all";
    elements.project.value = state.project;
    const editable = state.projects.filter((project) => project.role !== "viewer");
    const selectedForAdd = elements.siteProject.value;
    elements.siteProject.replaceChildren(...editable.map((project) => new Option(project.name, String(project.id))));
    const preferred = editable.find((project) => String(project.id) === selectedForAdd)
      || editable.find((project) => String(project.id) === state.project)
      || editable.find((project) => project.is_personal);
    if (preferred) elements.siteProject.value = String(preferred.id);
  }

  function setFilter(filter, { scroll = true } = {}) {
    state.filter = filter;
    render();
    if (scroll) elements.monitorSection.scrollIntoView({ behavior: "smooth", block: "start" });
    haptic();
  }

  function applyBootstrap(payload, { cache = true } = {}) {
    state.sites = payload.sites || [];
    state.projects = payload.projects || [];
    state.user = payload.user || null;
    state.limit = payload.limits?.sites || 0;
    state.loaded = true;
    const name = state.user?.first_name || state.user?.username || "пользователь";
    elements.welcome.textContent = `${name}, мониторинг активен. Данные синхронизированы с вашим Telegram-ботом.`;
    render();
    if (cache) {
      try {
        sessionStorage.setItem(cacheKey, JSON.stringify({ ...payload, cached_at: Date.now() }));
      } catch (_) {
        // Storage may be disabled by the client.
      }
    }
  }

  function renderCachedBootstrap() {
    try {
      const cached = JSON.parse(sessionStorage.getItem(cacheKey));
      if (!cached?.sites || !cached?.user) return false;
      applyBootstrap(cached, { cache: false });
      elements.welcome.textContent = "Показываем последние данные, обновляем статусы…";
      return true;
    } catch (_) {
      return false;
    }
  }

  function confirmDelete(host) {
    return new Promise((resolve) => {
      if (telegram?.showConfirm) {
        telegram.showConfirm(`Удалить ${host} из мониторинга?`, resolve);
      } else {
        resolve(window.confirm(`Удалить ${host} из мониторинга?`));
      }
    });
  }

  async function openFeedback() {
    hideNotice();
    elements.feedback.disabled = true;
    const originalText = elements.feedback.innerHTML;
    elements.feedback.textContent = "Открываем чат…";
    try {
      await api("/api/webapp/feedback/start", { method: "POST", body: "{}" });
      telegram?.HapticFeedback?.notificationOccurred("success");
      window.setTimeout(() => telegram?.close(), 180);
    } catch (error) {
      showNotice(error.message);
      elements.feedback.disabled = false;
      elements.feedback.innerHTML = originalText;
      telegram?.HapticFeedback?.notificationOccurred("error");
    }
  }

  async function runAction(site, action, container) {
    hideNotice();
    const buttons = [...container.querySelectorAll("button")];
    buttons.forEach((button) => { button.disabled = true; });
    const endpointAction = action === "toggle" ? (site.is_paused ? "resume" : "pause") : action;
    try {
      if (endpointAction === "delete") {
        await api(`/api/webapp/sites/${site.id}`, { method: "DELETE" });
      } else {
        const payload = await api(`/api/webapp/sites/${site.id}/${endpointAction}`, {
          method: "POST",
          body: "{}",
          timeoutMs: endpointAction === "check" ? 45000 : 15000,
        });
        if (payload.site) {
          state.sites = state.sites.map((item) => item.id === site.id ? payload.site : item);
        }
      }
      if (endpointAction === "delete") state.sites = state.sites.filter((item) => item.id !== site.id);
      if (["pause", "resume"].includes(endpointAction)) await load(); else render();
      haptic("medium");
    } catch (error) {
      showNotice(error.message);
      telegram?.HapticFeedback?.notificationOccurred("error");
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  async function changeGroup(site) {
    const value = window.prompt("Название группы (пустое значение уберёт группу):", site.site_group || "");
    if (value === null) return;
    try {
      const payload = await api(`/api/webapp/sites/${site.id}/group`, {
        method: "POST",
        body: JSON.stringify({ site_group: value }),
      });
      state.sites = state.sites.map((item) => item.id === site.id ? payload.site : item);
      render();
      haptic("medium");
    } catch (error) {
      showNotice(error.message);
    }
  }

  async function changeTags(site) {
    const current = (site.tags || []).join(", ");
    const value = window.prompt("Теги через запятую (пустое значение уберёт теги):", current);
    if (value === null) return;
    try {
      const payload = await api("/api/webapp/sites/" + site.id + "/tags", {
        method: "POST",
        body: JSON.stringify({ tags: value }),
      });
      state.sites = state.sites.map((item) => item.id === site.id ? payload.site : item);
      render();
      haptic("medium");
    } catch (error) {
      showNotice(error.message);
    }
  }

  function localDateTimeValue(date) {
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }

  function closeMaintenance() {
    if (elements.maintenanceDialog.open) elements.maintenanceDialog.close();
  }

  async function openMaintenance(site) {
    state.maintenanceSite = site;
    const start = new Date();
    start.setSeconds(0, 0);
    const end = new Date(start.getTime() + 60 * 60 * 1000);
    elements.maintenanceTitle.textContent = "Обслуживание · " + hostFromUrl(site.url);
    elements.maintenanceStart.value = localDateTimeValue(start);
    elements.maintenanceEnd.value = localDateTimeValue(end);
    elements.maintenanceReason.value = "";
    elements.maintenanceError.classList.add("hidden");
    elements.maintenanceDialog.showModal();
    document.body.classList.add("dialog-open");
    telegram?.BackButton?.show();
    await loadMaintenanceWindows();
  }

  async function loadMaintenanceWindows() {
    if (!state.maintenanceSite) return;
    elements.maintenanceList.innerHTML = "<p class=\"history-empty\">Загружаем окна…</p>";
    try {
      const payload = await api("/api/webapp/sites/" + state.maintenanceSite.id + "/maintenance");
      const windows = payload.maintenance_windows || [];
      elements.maintenanceList.replaceChildren(...windows.map((windowItem) => {
        const row = document.createElement("article");
        const copy = document.createElement("div");
        const title = document.createElement("b");
        const detail = document.createElement("span");
        const cancel = document.createElement("button");
        const starts = new Date(windowItem.starts_at);
        const ends = new Date(windowItem.ends_at);
        const active = starts <= new Date() && ends > new Date();
        row.className = "maintenance-row" + (active ? " active" : "");
        title.textContent = (active ? "ACTIVE · " : "SCHEDULED · ") + starts.toLocaleString("ru-RU") + " → " + ends.toLocaleString("ru-RU");
        detail.textContent = windowItem.reason || "Без описания";
        cancel.type = "button";
        cancel.textContent = "Отменить";
        cancel.addEventListener("click", async () => {
          cancel.disabled = true;
          try {
            await api("/api/webapp/sites/" + state.maintenanceSite.id + "/maintenance/" + windowItem.id, { method: "DELETE" });
            await Promise.all([loadMaintenanceWindows(), load()]);
          } catch (error) {
            elements.maintenanceError.textContent = error.message;
            elements.maintenanceError.classList.remove("hidden");
            cancel.disabled = false;
          }
        });
        copy.append(title, detail);
        row.append(copy, cancel);
        return row;
      }));
      if (!windows.length) elements.maintenanceList.innerHTML = "<p class=\"history-empty\">Активных и будущих окон нет</p>";
    } catch (error) {
      elements.maintenanceList.textContent = error.message;
    }
  }

  async function submitMaintenance(event) {
    event.preventDefault();
    if (!state.maintenanceSite) return;
    elements.maintenanceError.classList.add("hidden");
    elements.maintenanceSubmit.disabled = true;
    try {
      await api("/api/webapp/sites/" + state.maintenanceSite.id + "/maintenance", {
        method: "POST",
        body: JSON.stringify({
          starts_at: new Date(elements.maintenanceStart.value).toISOString(),
          ends_at: new Date(elements.maintenanceEnd.value).toISOString(),
          reason: elements.maintenanceReason.value,
        }),
      });
      elements.maintenanceReason.value = "";
      await Promise.all([loadMaintenanceWindows(), load()]);
      telegram?.HapticFeedback?.notificationOccurred("success");
    } catch (error) {
      elements.maintenanceError.textContent = error.message;
      elements.maintenanceError.classList.remove("hidden");
    } finally {
      elements.maintenanceSubmit.disabled = false;
    }
  }

  function closeHistory() {
    if (elements.historyDialog.open) elements.historyDialog.close();
  }

  async function openHistory(site) {
    state.historySite = site;
    elements.historyTitle.textContent = hostFromUrl(site.url);
    elements.historyDialog.showModal();
    document.body.classList.add("dialog-open");
    telegram?.BackButton?.show();
    await loadHistory(state.historyDays);
  }

  async function loadHistory(days) {
    if (!state.historySite) return;
    state.historyDays = days;
    const request = ++state.historyRequest;
    elements.historyPeriods.forEach((button) => {
      button.classList.toggle("active", Number(button.dataset.days) === days);
    });
    elements.historyEyebrow.textContent = `RESOURCE SIGNAL / ${days} DAY${days === 1 ? "" : "S"}`;
    elements.historySummary.innerHTML = '<div class="history-empty">Загружаем историю…</div>';
    elements.historyChart.replaceChildren();
    elements.historyLatencyChart.replaceChildren();
    elements.historyRegions.replaceChildren();
    elements.historyIncidents.replaceChildren();
    elements.historyMaintenance.replaceChildren();
    elements.historyEvents.replaceChildren();
    elements.historyPolicy.textContent = "";
    try {
      const payload = await api(
        `/api/webapp/sites/${state.historySite.id}/history?days=${days}`,
        { timeoutMs: 15000 },
      );
      if (request !== state.historyRequest) return;
      renderHistory(payload.history);
    } catch (error) {
      if (request !== state.historyRequest) return;
      elements.historySummary.innerHTML = "";
      const empty = document.createElement("div");
      empty.className = "history-empty";
      empty.textContent = error.message;
      elements.historySummary.append(empty);
    }
  }

  function formatDuration(seconds) {
    if (seconds < 60) return `${seconds} сек`;
    if (seconds < 3600) return `${Math.round(seconds / 60)} мин`;
    if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} ч`;
    return `${(seconds / 86400).toFixed(1)} дн`;
  }

  function renderHistory(history) {
    elements.historyGranularity.textContent = history.granularity === "day" ? "по дням" : "по часам";
    const summaryItems = [
      [history.summary.availability == null ? "—" : `${history.summary.availability}%`, "Доступность"],
      [history.summary.avg_latency_ms == null ? "—" : `${history.summary.avg_latency_ms} мс`, "Средняя"],
      [history.summary.max_latency_ms == null ? "—" : `${history.summary.max_latency_ms} мс`, "Пиковая"],
      [String(history.summary.checks), "Проверки"],
    ];
    elements.historySummary.replaceChildren(...summaryItems.map(([value, label]) => {
      const item = document.createElement("div");
      item.className = "history-metric";
      const strong = document.createElement("b");
      const caption = document.createElement("span");
      strong.textContent = value;
      caption.textContent = label;
      item.append(strong, caption);
      return item;
    }));

    const buckets = new Map();
    const regions = new Map();
    history.points.forEach((point) => {
      const bucket = buckets.get(point.bucket_start) || {
        checks: 0, successful: 0, latencySum: 0, latencySamples: 0, maxLatency: null,
      };
      bucket.checks += point.checks;
      bucket.successful += point.successful_checks;
      bucket.latencySum += point.latency_sum_ms || 0;
      bucket.latencySamples += point.latency_samples || 0;
      if (point.max_latency_ms != null) {
        bucket.maxLatency = Math.max(bucket.maxLatency || 0, point.max_latency_ms);
      }
      buckets.set(point.bucket_start, bucket);
      const region = regions.get(point.agent_id) || {
        checks: 0,
        successful: 0,
        label: [point.country, point.region].filter(Boolean).join(" · ") || point.agent_id,
      };
      region.checks += point.checks;
      region.successful += point.successful_checks;
      regions.set(point.agent_id, region);
    });

    const orderedBuckets = [...buckets.entries()];
    const availabilityBars = orderedBuckets.map(([bucket, point]) => {
      const availability = point.checks ? point.successful * 100 / point.checks : 0;
      const bar = document.createElement("span");
      bar.className = `history-bar ${availability < 90 ? "down" : availability < 100 ? "warning" : ""}`;
      bar.style.height = `${Math.max(4, availability)}%`;
      bar.title = `${new Date(bucket).toLocaleString("ru-RU")}: ${availability.toFixed(1)}% · ${point.checks} проверок`;
      return bar;
    });
    elements.historyChart.replaceChildren(...availabilityBars);
    if (!availabilityBars.length) {
      elements.historyChart.innerHTML = '<div class="history-empty">Замеров за период пока нет</div>';
    }

    const latencyCeiling = Math.max(
      1,
      ...orderedBuckets.map(([, point]) => point.maxLatency || 0),
    );
    const latencyColumns = orderedBuckets.map(([bucket, point]) => {
      const average = point.latencySamples ? point.latencySum / point.latencySamples : 0;
      const peak = point.maxLatency || average;
      const column = document.createElement("span");
      const averageBar = document.createElement("i");
      const peakMarker = document.createElement("b");
      column.className = "latency-column";
      averageBar.className = "latency-average";
      peakMarker.className = "latency-peak";
      averageBar.style.height = `${Math.max(2, average * 100 / latencyCeiling)}%`;
      peakMarker.style.bottom = `${Math.min(99, peak * 100 / latencyCeiling)}%`;
      column.title = `${new Date(bucket).toLocaleString("ru-RU")}: avg ${Math.round(average)} мс · peak ${peak} мс`;
      column.append(averageBar, peakMarker);
      return column;
    });
    elements.historyLatencyChart.replaceChildren(...latencyColumns);
    if (!latencyColumns.length) {
      elements.historyLatencyChart.innerHTML = '<div class="history-empty">Latency пока не измерена</div>';
    }

    elements.historyPolicy.textContent = (
      "Availability: только фактические agent checks; отсутствующие замеры не считаются. В окно ТО расписание отключено, ручные замеры учитываются."
    );
    elements.historyRegions.replaceChildren(...[...regions.values()].map((region) => {
      const chip = document.createElement("span");
      chip.className = "region-chip";
      const availability = region.checks ? region.successful * 100 / region.checks : 0;
      chip.textContent = `${region.label} · ${availability.toFixed(1)}%`;
      return chip;
    }));

    const incidents = history.incidents.map((incident) => {
      const row = document.createElement("article");
      const time = document.createElement("time");
      const text = document.createElement("p");
      row.className = "history-incident";
      time.textContent = new Date(incident.started_at).toLocaleString("ru-RU", {
        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
      });
      const stateLabel = incident.ended_at ? "восстановлен" : "продолжается";
      const reason = incident.start_error || (
        incident.start_http_status ? `HTTP ${incident.start_http_status}` : "нет ответа"
      );
      text.textContent = `${stateLabel} · ${formatDuration(incident.duration_seconds)} · ${incident.failure_count} ошибок · ${reason}`;
      row.append(time, text);
      return row;
    });
    elements.historyIncidents.replaceChildren(...incidents);
    if (!incidents.length) {
      elements.historyIncidents.innerHTML = '<div class="history-empty">Центральных инцидентов не было</div>';
    }

    const maintenance = (history.maintenance_windows || []).map((windowItem) => {
      const row = document.createElement("article");
      const time = document.createElement("time");
      const text = document.createElement("p");
      row.className = "history-maintenance-row";
      time.textContent = new Date(windowItem.starts_at).toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
      text.textContent = (windowItem.is_active ? "идёт сейчас" : "завершено") + " · " + formatDuration(windowItem.duration_seconds) + " · " + (windowItem.reason || "без описания");
      row.append(time, text);
      return row;
    });
    elements.historyMaintenance.replaceChildren(...maintenance);
    if (!maintenance.length) {
      elements.historyMaintenance.innerHTML = "<div class=\"history-empty\">Планового обслуживания не было</div>";
    }

    const events = history.events.map((event) => {
      const row = document.createElement("article");
      row.className = "history-event";
      const time = document.createElement("time");
      const text = document.createElement("p");
      time.textContent = new Date(event.created_at).toLocaleString("ru-RU", {
        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
      });
      text.textContent = event.message;
      row.append(time, text);
      return row;
    });
    elements.historyEvents.replaceChildren(...events);
    if (!events.length) {
      elements.historyEvents.innerHTML = '<div class="history-empty">За период событий не было</div>';
    }
  }

  function teamFailure(error) {
    elements.teamError.textContent = error.message;
    elements.teamError.classList.remove("hidden");
  }

  async function loadTeamMembers() {
    const id = Number(elements.teamProjectSelect.value);
    const project = state.projects.find((item) => item.id === id);
    elements.teamMemberForm.hidden = !project || project.role !== "owner";
    elements.teamMemberList.textContent = "Загружаем участников…";
    if (!project) return;
    try {
      const payload = await api(`/api/webapp/projects/${id}/members`);
      if (Number(elements.teamProjectSelect.value) !== id) return;
      elements.teamMemberList.replaceChildren(...payload.members.map((member) => {
        const row = document.createElement("div");
        const label = document.createElement("span");
        row.className = "team-member";
        label.textContent = `${member.user_id} · ${member.role}`;
        row.append(label);
        if (project.role === "owner" && member.role !== "owner") {
          const remove = document.createElement("button");
          remove.type = "button";
          remove.textContent = "Убрать";
          remove.addEventListener("click", async () => {
            remove.disabled = true;
            try {
              await api(`/api/webapp/projects/${id}/members/${member.user_id}`, { method: "DELETE" });
              await Promise.all([loadTeamMembers(), load()]);
            } catch (error) { teamFailure(error); remove.disabled = false; }
          });
          row.append(remove);
        }
        return row;
      }));
    } catch (error) { teamFailure(error); }
  }

  function renderTeamProjects(preferredId) {
    const selected = String(preferredId || elements.teamProjectSelect.value || "");
    elements.teamProjectSelect.replaceChildren(...state.projects.map((project) =>
      new Option(`${project.name} · ${project.role}`, String(project.id))));
    if (state.projects.some((project) => String(project.id) === selected)) {
      elements.teamProjectSelect.value = selected;
    }
    loadTeamMembers();
  }

  function openTeam() {
    elements.teamError.classList.add("hidden");
    elements.teamIdentity.textContent = `Ваш Telegram ID: ${state.user?.id || "—"}`;
    elements.teamDialog.showModal();
    document.body.classList.add("dialog-open");
    telegram?.BackButton?.show();
    renderTeamProjects();
    haptic();
  }

  function closeTeam() {
    if (elements.teamDialog.open) elements.teamDialog.close();
  }

  async function createTeamProject(event) {
    event.preventDefault();
    elements.teamError.classList.add("hidden");
    try {
      const payload = await api("/api/webapp/projects", {
        method: "POST", body: JSON.stringify({ name: elements.teamProjectName.value }),
      });
      elements.teamProjectName.value = "";
      await load();
      renderTeamProjects(payload.project_id);
    } catch (error) { teamFailure(error); }
  }

  async function saveTeamMember(event) {
    event.preventDefault();
    elements.teamError.classList.add("hidden");
    const projectId = Number(elements.teamProjectSelect.value);
    const memberId = Number(elements.teamMemberId.value);
    try {
      await api(`/api/webapp/projects/${projectId}/members/${memberId}`, {
        method: "PUT", body: JSON.stringify({ role: elements.teamMemberRole.value }),
      });
      elements.teamMemberId.value = "";
      await loadTeamMembers();
    } catch (error) { teamFailure(error); }
  }

  function openAdd() {
    elements.formError.classList.add("hidden");
    elements.input.value = "";
    elements.groupInput.value = "";
    elements.tagsInput.value = "";
    const selectedProject = state.projects.find((project) => String(project.id) === state.project && project.role !== "viewer");
    if (selectedProject) elements.siteProject.value = String(selectedProject.id);
    elements.dialog.showModal();
    document.body.classList.add("dialog-open");
    telegram?.BackButton?.show();
    setTimeout(() => elements.input.focus(), 120);
    haptic();
  }

  function closeAdd() {
    if (!elements.dialog.open) return;
    elements.dialog.close();
  }

  function cleanupAddDialog() {
    document.body.classList.remove("dialog-open");
    telegram?.BackButton?.hide();
  }

  async function addSite(event) {
    if (event.submitter?.value === "cancel") {
      cleanupAddDialog();
      return;
    }
    event.preventDefault();
    elements.formError.classList.add("hidden");
    elements.submit.disabled = true;
    elements.submit.textContent = "Проверяем DNS…";
    const slowMessage = window.setTimeout(() => {
      elements.submit.textContent = "DNS отвечает медленно…";
    }, 2500);
    try {
      const payload = await api("/api/webapp/sites", {
        method: "POST",
        body: JSON.stringify({ url: elements.input.value, project_id: Number(elements.siteProject.value), site_group: elements.groupInput.value, tags: elements.tagsInput.value }),
        timeoutMs: 8000,
      });
      state.sites.push(payload.site);
      closeAdd();
      render();
      telegram?.HapticFeedback?.notificationOccurred("success");
    } catch (error) {
      elements.formError.textContent = error.message;
      elements.formError.classList.remove("hidden");
      telegram?.HapticFeedback?.notificationOccurred("error");
    } finally {
      window.clearTimeout(slowMessage);
      elements.submit.disabled = false;
      elements.submit.textContent = "Добавить в мониторинг";
    }
  }

  async function load() {
    hideNotice();
    try {
      const payload = await api("/api/webapp/bootstrap", { timeoutMs: 10000 });
      applyBootstrap(payload);
    } catch (error) {
      if (!state.loaded) {
        state.sites = [];
        render();
      }
      showNotice(error.message);
    }
  }

  document.querySelector("#current-date").textContent = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short" }).format(new Date()).toUpperCase();
  document.querySelector("#open-add").addEventListener("click", openAdd);
  elements.feedback.addEventListener("click", openFeedback);
  document.querySelector("#empty-add").addEventListener("click", openAdd);
  document.querySelector("#reset-filter").addEventListener("click", () => setFilter("all"));
  elements.metrics.forEach((metric) => {
    metric.addEventListener("click", () => setFilter(metric.dataset.filter));
  });
  elements.sort.addEventListener("change", () => {
    state.sort = elements.sort.value;
    render();
    haptic();
  });
  elements.search.addEventListener("input", () => {
    state.query = elements.search.value.trim().toLocaleLowerCase("ru");
    render();
  });
  elements.group.addEventListener("change", () => {
    state.group = elements.group.value;
    render();
  });
  elements.project.addEventListener("change", () => {
    state.project = elements.project.value;
    render();
  });
  document.querySelector("#open-team").addEventListener("click", openTeam);
  document.querySelector("#close-team").addEventListener("click", closeTeam);
  elements.teamCreateForm.addEventListener("submit", createTeamProject);
  elements.teamMemberForm.addEventListener("submit", saveTeamMember);
  elements.teamProjectSelect.addEventListener("change", loadTeamMembers);
  elements.teamDialog.addEventListener("close", cleanupAddDialog);
  elements.teamDialog.addEventListener("cancel", (event) => { event.preventDefault(); closeTeam(); });
  elements.teamDialog.addEventListener("click", (event) => {
    if (event.target === elements.teamDialog) closeTeam();
  });
  elements.tag.addEventListener("change", () => {
    state.tag = elements.tag.value;
    render();
  });
  elements.closeAdd.addEventListener("click", (event) => {
    event.preventDefault();
    closeAdd();
  });
  elements.form.addEventListener("submit", addSite);
  elements.dialog.addEventListener("close", cleanupAddDialog);
  elements.dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeAdd();
  });
  elements.dialog.addEventListener("click", (event) => {
    if (event.target === elements.dialog) closeAdd();
  });
  elements.closeMaintenance.addEventListener("click", closeMaintenance);
  elements.maintenanceForm.addEventListener("submit", submitMaintenance);
  elements.maintenanceDialog.addEventListener("close", cleanupAddDialog);
  elements.maintenanceDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeMaintenance();
  });
  elements.maintenanceDialog.addEventListener("click", (event) => {
    if (event.target === elements.maintenanceDialog) closeMaintenance();
  });
  elements.closeHistory.addEventListener("click", closeHistory);
  elements.historyPeriods.forEach((button) => {
    button.addEventListener("click", () => {
      loadHistory(Number(button.dataset.days));
      haptic();
    });
  });
  elements.historyDialog.addEventListener("close", cleanupAddDialog);
  elements.historyDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeHistory();
  });
  elements.historyDialog.addEventListener("click", (event) => {
    if (event.target === elements.historyDialog) closeHistory();
  });
  telegram?.BackButton?.onClick(closeAdd);
  telegram?.BackButton?.onClick(closeHistory);
  telegram?.BackButton?.onClick(closeMaintenance);
  telegram?.BackButton?.onClick(closeTeam);

  telegram?.ready();
  telegram?.expand();
  telegram?.setHeaderColor?.("#07110f");
  telegram?.setBackgroundColor?.("#07110f");
  renderCachedBootstrap();
  load();
})();
