// Execute production functions with DOM/API doubles; no frontend dependencies.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const functions = source.split(/(?=\n  (?:async )?function )/);
const names = ["hostFromUrl", "tagsForSite", "visibleSites", "render", "renderGroups",
  "renderTags", "loadCheckSettings", "saveCheckSettings", "applyBootstrap", "renderCachedBootstrap", "addSite", "bulkAddSites", "runAction"];
const production = names.map((name) => functions.find((part) =>
  new RegExp(`^\\n  (?:async )?function ${name}\\(`).test(part))).join("\n");
const scenario = `
const node = () => ({value: "", textContent: "", disabled: false,
  classList: {toggle() {}, add() {}, remove() {}},
  replaceChildren(...children) {this.children = children;}});
const elements = new Proxy({}, {get(target, key) {return target[key] ||= node();}});
const state = {sites: [], projects: [], filter: "all", sort: "priority", query: "",
  group: "all", tag: "all", project: "all"};
const telegram = null;
const cacheKey = "test";
const cache = new Map();
const sessionStorage = {setItem(k, v) {cache.set(k, v);}, getItem(k) {return cache.get(k);}};
const document = {querySelector: () => node()};
const window = {setTimeout: () => 1, clearTimeout() {}};
const Option = function(text, value) {this.text = text; this.value = value;};
const makeSiteCard = (site) => ({id: site.id, host: hostFromUrl(site.url)});
const renderProjects = () => {};
const updateMetrics = () => {};
const hideNotice = () => {};
const haptic = () => {};
const closeAdd = () => {};
const showNotice = (message) => {
  if (message !== "Настройки проверки сохранены") throw new Error(message);
};
const operationsFailure = (error) => {throw error;};
const renderBulkResults = () => {};
let response;
const requests = [];
const api = async (path, options) => {requests.push({path, options}); return response;};
const load = async () => applyBootstrap(response.bootstrap);
${production}
(async () => {
  const pending = {id: 1, url: "https://new.example", status_kind: "pending", tags: [null, "api", "", 12]};
  const down = {id: 2, url: "https://down.example", status_kind: "down", tags: null};
  const legacy = {id: 3, url: null, status_kind: "pending", tags: ["production", null]};
  const bootstrap = {sites: [pending, down, legacy], user: {first_name: "User"}};
  applyBootstrap(bootstrap);
  assert.deepEqual(elements.list.children.map(card => card.id), [2, 3, 1]);
  assert.equal(elements.visibleCount.textContent, "3 из 3");
  assert.deepEqual(elements.tag.children.map(option => option.value), ["all", "api", "production"]);
  assert.equal(renderCachedBootstrap(), true);
  state.sort = "name"; render();
  assert.equal(elements.list.children.length, 3);
  state.tag = "api"; render();
  assert.deepEqual(elements.list.children.map(card => card.id), [1]);
  state.tag = "all";
  response = {site: {id: 4, url: "https://offline.example", status_kind: "pending", tags: [null]}};
  await addSite({preventDefault() {}});
  assert.equal(elements.list.children.length, 4);
  assert.equal(elements.submit.disabled, false);
  response = {results: [{ok: true}], bootstrap};
  await bulkAddSites();
  assert.equal(elements.list.children.length, 3);
  assert.equal(elements.bulkAdd.disabled, false);
  const button = {disabled: false};
  await runAction(legacy, "delete", {querySelectorAll: () => [button]});
  assert.deepEqual(state.sites.map(site => site.id), [1, 2]);
  assert.equal(requests.at(-1).path, "/api/webapp/sites/3");
  assert.equal(requests.at(-1).options.method, "DELETE");
  assert.equal(button.disabled, false);
  assert.equal(elements.list.children.length, 2);
  elements.checkSite.value = "7";
  response = {settings: {dns_monitoring_enabled: false}};
  await loadCheckSettings();
  assert.equal(elements.dnsMonitoring.checked, false);
  await saveCheckSettings({preventDefault() {}});
  assert.equal(JSON.parse(requests.at(-1).options.body).dns_monitoring_enabled, false);
})().catch(error => {console.error(error); process.exitCode = 1;});
`;
vm.runInNewContext(scenario, {assert, URL, console, process});
