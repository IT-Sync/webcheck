(() => {
  "use strict";

  const telegram = window.Telegram?.WebApp;
  const state = { sites: [], user: null, limit: 0 };
  const elements = {
    list: document.querySelector("#site-list"),
    empty: document.querySelector("#empty-state"),
    notice: document.querySelector("#notice"),
    welcome: document.querySelector("#welcome"),
    dialog: document.querySelector("#add-dialog"),
    form: document.querySelector("#add-form"),
    input: document.querySelector("#site-url"),
    formError: document.querySelector("#form-error"),
    submit: document.querySelector("#add-submit"),
    template: document.querySelector("#site-template"),
  };

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
    const response = await fetch(path, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error?.message || "Сервис временно недоступен");
    }
    return payload;
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
    return ({ up: "В сети", down: "Недоступен", warning: "Внимание", paused: "На паузе", pending: "Ожидает" })[site.status_kind];
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

    const actions = card.querySelector(".site-actions");
    const more = card.querySelector(".more-button");
    const toggle = card.querySelector('[data-action="toggle"]');
    toggle.textContent = site.is_paused ? "Возобновить" : "Поставить на паузу";

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
      if (action === "delete") {
        const confirmed = await confirmDelete(hostFromUrl(site.url));
        if (!confirmed) return;
      }
      await runAction(site, action, actions);
    });
    return card;
  }

  function render() {
    elements.list.replaceChildren(...state.sites.map(makeSiteCard));
    elements.list.classList.toggle("hidden", state.sites.length === 0);
    elements.empty.classList.toggle("hidden", state.sites.length !== 0);
    updateMetrics();
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

  async function runAction(site, action, container) {
    hideNotice();
    const buttons = [...container.querySelectorAll("button")];
    buttons.forEach((button) => { button.disabled = true; });
    const endpointAction = action === "toggle" ? (site.is_paused ? "resume" : "pause") : action;
    try {
      if (endpointAction === "delete") {
        await api(`/api/webapp/sites/${site.id}`, { method: "DELETE" });
      } else {
        const payload = await api(`/api/webapp/sites/${site.id}/${endpointAction}`, { method: "POST", body: "{}" });
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

  function openAdd() {
    elements.formError.classList.add("hidden");
    elements.input.value = "";
    elements.dialog.showModal();
    setTimeout(() => elements.input.focus(), 120);
    haptic();
  }

  async function addSite(event) {
    event.preventDefault();
    const submitter = event.submitter;
    if (submitter?.value === "cancel") return elements.dialog.close();
    elements.formError.classList.add("hidden");
    elements.submit.disabled = true;
    elements.submit.textContent = "Проверяем адрес…";
    try {
      const payload = await api("/api/webapp/sites", {
        method: "POST",
        body: JSON.stringify({ url: elements.input.value }),
      });
      state.sites.push(payload.site);
      elements.dialog.close();
      render();
      telegram?.HapticFeedback?.notificationOccurred("success");
    } catch (error) {
      elements.formError.textContent = error.message;
      elements.formError.classList.remove("hidden");
      telegram?.HapticFeedback?.notificationOccurred("error");
    } finally {
      elements.submit.disabled = false;
      elements.submit.textContent = "Добавить в мониторинг";
    }
  }

  async function load() {
    hideNotice();
    try {
      if (!telegram?.initData) throw new Error("Откройте приложение из Telegram-бота, чтобы войти безопасно.");
      const payload = await api("/api/webapp/bootstrap");
      state.sites = payload.sites;
      state.user = payload.user;
      state.limit = payload.limits.sites;
      const name = payload.user.first_name || payload.user.username || "пользователь";
      elements.welcome.textContent = `${name}, мониторинг активен. Данные синхронизированы с вашим Telegram-ботом.`;
      render();
    } catch (error) {
      state.sites = [];
      render();
      showNotice(error.message);
    }
  }

  document.querySelector("#current-date").textContent = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short" }).format(new Date()).toUpperCase();
  document.querySelector("#open-add").addEventListener("click", openAdd);
  document.querySelector("#empty-add").addEventListener("click", openAdd);
  elements.form.addEventListener("submit", addSite);

  telegram?.ready();
  telegram?.expand();
  telegram?.setHeaderColor?.("#07110f");
  telegram?.setBackgroundColor?.("#07110f");
  load();
})();
