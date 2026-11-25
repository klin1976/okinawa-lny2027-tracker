const API_KEY_STORAGE = "travel_radar_api_key";
const GH_TOKEN_STORAGE = "travel_radar_gh_token";
const GH_REPO_STORAGE = "travel_radar_gh_repo";
const PARTY_STORAGE = "travel_radar_party";
const PAGE_LIMIT_INITIAL = 100;

const state = {
  mode: "LOADING", // "LIVE" | "STATIC"
  data: null,
  selectedTripId: "ALL",
  selectedCountry: "",
  selectedRegion: "",
  customRegionKeyword: "",
  activeTab: "rankings",
  showAllRows: false,
  useCustomParty: false,
  party: {
    adults: 2,
    childrenWithBed: 0,
    childrenNoBed: 0,
    infants: 0,
  },
  filters: {
    agency: "",
    airport: "",
    sort: "score_desc",
    keyword: "",
    onlySufficient: false,
    onlyNoShopping: false,
    onlyWithinBudget: false,
  },
  chartInstance: null,
};

const ROLE_LABELS = {
  adult: "一般成人",
  senior: "高齡長輩",
  child_with_bed: "兒童（佔床）",
  child_no_bed: "兒童（不佔床）",
  infant: "嬰兒（不佔機位）",
  service_tips: "領隊導遊小費",
  single_supplement: "單人房差",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeUrl(raw) {
  if (!raw || typeof raw !== "string") return "";
  try {
    const parsed = new URL(raw, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.href;
    }
  } catch {
    return "";
  }
  return "";
}

function formatTwd(num) {
  if (num === null || num === undefined || Number.isNaN(Number(num))) return "--";
  return `NT$${Number(num).toLocaleString("zh-TW")}`;
}

function formatDateTime(isoStr) {
  if (!isoStr) return "--";
  const d = new Date(isoStr);
  if (Number.isNaN(d.getTime())) return String(isoStr);
  return d.toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function getAgencyClass(agency) {
  if (agency === "雄獅旅遊") return "agency-lion";
  if (agency === "可樂旅遊") return "agency-cola";
  if (agency === "東南旅遊") return "agency-settour";
  if (agency === "山富旅遊") return "agency-richmont";
  if (agency === "世邦旅遊") return "agency-fourp";
  return "agency-other";
}

function getStoredApiKey() {
  return localStorage.getItem(API_KEY_STORAGE) || "";
}

function updateKeyIndicator() {
  const dot = document.getElementById("key-status-dot");
  if (!dot) return;
  dot.classList.toggle("configured", Boolean(getStoredApiKey()));
}

function detectDefaultGhRepo() {
  const saved = localStorage.getItem(GH_REPO_STORAGE);
  if (saved) return saved;
  const host = window.location.hostname || "";
  if (host.endsWith(".github.io")) {
    const owner = host.split(".")[0];
    const seg = (window.location.pathname || "/").split("/").filter(Boolean)[0];
    if (owner && seg) return `${owner}/${seg}`;
  }
  return "klin1976/okinawa-lny2027-tracker";
}

function getStoredGhToken() {
  return localStorage.getItem(GH_TOKEN_STORAGE) || "";
}

function updateGhTokenIndicator() {
  const dot = document.getElementById("gh-token-dot");
  if (!dot) return;
  dot.classList.toggle("configured", Boolean(getStoredGhToken()));
}

function showBanner(message, isError = false) {
  const banner = document.getElementById("global-banner");
  if (!banner) return;
  banner.textContent = message;
  banner.classList.remove("hidden", "banner-error");
  if (isError) banner.classList.add("banner-error");
}

function hideBanner() {
  const banner = document.getElementById("global-banner");
  if (banner) banner.classList.add("hidden");
}

function getDefaultParty() {
  const dp = state.data?.default_party || {};
  return {
    adults: Number(dp.adults ?? 2),
    childrenWithBed: Number(dp.children_with_bed ?? 0),
    childrenNoBed: Number(dp.children_no_bed ?? 0),
    infants: Number(dp.infants ?? 0),
  };
}

function isSameParty(a, b) {
  return (
    Number(a.adults) === Number(b.adults) &&
    Number(a.childrenWithBed) === Number(b.childrenWithBed) &&
    Number(a.childrenNoBed) === Number(b.childrenNoBed) &&
    Number(a.infants) === Number(b.infants)
  );
}

function initPartyFromStorageOrDefault() {
  const defaults = getDefaultParty();
  try {
    const raw = localStorage.getItem(PARTY_STORAGE);
    if (raw) {
      const parsed = JSON.parse(raw);
      state.party = {
        adults: Math.max(1, Number(parsed.adults ?? defaults.adults)),
        childrenWithBed: Math.max(0, Number(parsed.childrenWithBed ?? defaults.childrenWithBed)),
        childrenNoBed: Math.max(0, Number(parsed.childrenNoBed ?? defaults.childrenNoBed)),
        infants: Math.max(0, Number(parsed.infants ?? defaults.infants)),
      };
      state.useCustomParty = !isSameParty(state.party, defaults);
      syncPartyInputsUi();
      return;
    }
  } catch {
    // ignore corrupted storage
  }
  state.party = { ...defaults };
  state.useCustomParty = false;
  syncPartyInputsUi();
}

function syncPartyInputsUi() {
  document.getElementById("party-adults").value = String(state.party.adults);
  document.getElementById("party-child-bed").value = String(state.party.childrenWithBed);
  document.getElementById("party-child-nobed").value = String(state.party.childrenNoBed);
  document.getElementById("party-infants").value = String(state.party.infants);

  const totalPax =
    state.party.adults +
    state.party.childrenWithBed +
    state.party.childrenNoBed +
    state.party.infants;
  const seatsNeeded =
    state.party.adults + state.party.childrenWithBed + state.party.childrenNoBed;
  const bedsNeeded = state.party.adults + state.party.childrenWithBed;

  const pill = document.getElementById("party-summary-pill");
  pill.textContent = `共 ${totalPax} 人 · ${seatsNeeded} 機位 / ${bedsNeeded} 床位${
    state.useCustomParty ? " (自訂試算)" : " (家族預設)"
  }`;
  pill.classList.toggle("is-custom", state.useCustomParty);

  const thBudget = document.getElementById("th-total-budget");
  const kpiBudgetLabel = document.getElementById("kpi-min-budget-label");
  if (thBudget) {
    thBudget.textContent = state.useCustomParty
      ? `自訂 ${totalPax} 人總預算`
      : "家族真實總預算";
  }
  if (kpiBudgetLabel) {
    kpiBudgetLabel.textContent = state.useCustomParty
      ? `最低總預算 (${totalPax}人)`
      : "最低家族真實總預算";
  }

  const ageHint = document.getElementById("hint-child-bed-age");
  if (ageHint) {
    const isLongHaul =
      state.selectedCountry === "歐洲" || state.selectedCountry === "紐澳美加";
    ageHint.textContent = isLongHaul ? "≥12歲" : "≥6歲";
  }
}

function computeEffectiveBudget(tour) {
  if (!state.useCustomParty || !tour.pricing_params) {
    return tour.budget;
  }

  const p = tour.pricing_params;
  const adults = Math.max(0, Number(state.party.adults || 0));
  const childBed = Math.max(0, Number(state.party.childrenWithBed || 0));
  const childNoBed = Math.max(0, Number(state.party.childrenNoBed || 0));
  const infants = Math.max(0, Number(state.party.infants || 0));

  const totalPax = adults + childBed + childNoBed + infants;
  const seatsNeeded = adults + childBed + childNoBed;
  const bedsNeeded = adults + childBed;

  let seatStatus = "UNKNOWN";
  if (tour.seats_available !== null && tour.seats_available !== undefined) {
    seatStatus = Number(tour.seats_available) >= seatsNeeded ? "SUFFICIENT" : "INSUFFICIENT";
  }

  const adultPrice = p.adult_twin_price;
  if (adultPrice === null || adultPrice === undefined) {
    return {
      ...tour.budget,
      grand_total_twd: 0,
      avg_cost_per_person_twd: 0,
      total_family_members: totalPax,
      total_flight_seats_needed: seatsNeeded,
      total_beds_needed: bedsNeeded,
      seat_status: seatStatus,
      is_estimated: true,
      assumptions: ["尚未取得成人基礎團費報價，無法估算總價"],
      breakdown: { items: [] },
    };
  }

  const items = [];
  const assumptions = [];
  let isEstimated = false;

  if (adults > 0) {
    items.push({
      role: "adult",
      count: adults,
      unit_price: adultPrice,
      subtotal: adultPrice * adults,
      note: "一般成人團費",
      is_estimated: false,
    });
  }

  if (childBed > 0) {
    let unit = adultPrice;
    let note = "兒童佔床未特別報價，採成人同價估算";
    let itemEst = false;
    if (p.child_with_bed_price !== null && p.child_with_bed_price !== undefined) {
      unit = p.child_with_bed_price;
      note = "兒童佔床專屬報價";
    } else if (p.child_with_bed_diff !== null && p.child_with_bed_diff !== undefined) {
      unit = Math.max(0, adultPrice + p.child_with_bed_diff);
      note = `兒童佔床價差計算（${p.child_with_bed_diff}）`;
    } else {
      itemEst = true;
      isEstimated = true;
      assumptions.push("兒童佔床未標價，採成人同價估算");
    }
    items.push({
      role: "child_with_bed",
      count: childBed,
      unit_price: unit,
      subtotal: unit * childBed,
      note,
      is_estimated: itemEst,
    });
  }

  if (childNoBed > 0) {
    let unit = 0;
    let note = "";
    let itemEst = false;
    if (p.child_no_bed_price !== null && p.child_no_bed_price !== undefined) {
      unit = p.child_no_bed_price;
      note = "兒童不佔床專屬報價";
    } else if (p.child_no_bed_diff !== null && p.child_no_bed_diff !== undefined) {
      unit = Math.max(0, adultPrice + p.child_no_bed_diff);
      note = `兒童不佔床價差計算（${p.child_no_bed_diff}）`;
    } else {
      const fallbackDiff = Number(p.fallback_child_no_bed_diff ?? -3000);
      unit = Math.max(0, adultPrice + fallbackDiff);
      note = `兒童不佔床未標價，以預設價差 ${fallbackDiff} 估算`;
      itemEst = true;
      isEstimated = true;
      assumptions.push(`兒童不佔床未標價，採預設價差 ${fallbackDiff} 估算`);
    }
    items.push({
      role: "child_no_bed",
      count: childNoBed,
      unit_price: unit,
      subtotal: unit * childNoBed,
      note,
      is_estimated: itemEst,
    });
  }

  if (infants > 0) {
    let unit = 0;
    let note = "";
    let itemEst = false;
    if (p.infant_price !== null && p.infant_price !== undefined) {
      unit = p.infant_price;
      note = "未滿2歲嬰兒報價";
    } else {
      const fallbackInfant = Number(p.fallback_infant_price ?? 6000);
      unit = fallbackInfant;
      note = `嬰兒未標價，以預設 ${fallbackInfant} 估算`;
      itemEst = true;
      isEstimated = true;
      assumptions.push(`嬰兒未標價，採預設 ${fallbackInfant} 估算`);
    }
    items.push({
      role: "infant",
      count: infants,
      unit_price: unit,
      subtotal: unit * infants,
      note,
      is_estimated: itemEst,
    });
  }

  const days = Number(tour.days || 1);
  const tipPerDay = Number(p.tip_per_day_twd ?? p.default_tip_per_day ?? 300);
  const tipPax = adults + childBed + childNoBed;
  const tipsTotal = tipPerDay * days * tipPax;
  const tipEstimated = p.tip_per_day_twd === null || p.tip_per_day_twd === undefined;
  if (tipEstimated) {
    isEstimated = true;
    assumptions.push(`行程未載明每日小費，採專案預設每日 ${tipPerDay} 元估算`);
  }
  items.push({
    role: "service_tips",
    count: tipPax,
    unit_price: tipPerDay * days,
    subtotal: tipsTotal,
    note: `領隊導遊小費（每日 ${tipPerDay} 元 × ${days} 天 × ${tipPax} 人）`,
    is_estimated: tipEstimated,
  });

  if (bedsNeeded % 2 === 1) {
    const supplement = Number(
      p.single_room_supplement ?? p.fallback_single_room_supplement ?? 12000
    );
    const supplementEstimated =
      p.single_room_supplement === null || p.single_room_supplement === undefined;
    if (bedsNeeded === 1 || p.allows_triple_room === false) {
      if (supplementEstimated) isEstimated = true;
      items.push({
        role: "single_supplement",
        count: 1,
        unit_price: supplement,
        subtotal: supplement,
        note: bedsNeeded === 1 ? "單人參團須補單人房差" : "奇數床位且行程不支援三人房，加計單人房差",
        is_estimated: supplementEstimated,
      });
    } else {
      assumptions.push("佔床總人數為奇數，以雙人房搭配 1 間三人房/加床估算（免收單人房差）");
    }
  }

  const grandTotal = items.reduce((acc, it) => acc + Number(it.subtotal || 0), 0);
  const avgPerPerson = totalPax > 0 ? Math.round(grandTotal / totalPax) : 0;

  return {
    ...tour.budget,
    grand_total_twd: grandTotal,
    avg_cost_per_person_twd: avgPerPerson,
    total_family_members: totalPax,
    total_flight_seats_needed: seatsNeeded,
    total_beds_needed: bedsNeeded,
    seat_status: seatStatus,
    is_estimated: isEstimated,
    assumptions,
    breakdown: {
      ...(tour.budget?.breakdown || {}),
      items,
    },
  };
}

async function fetchJsonWithTimeout(url, timeoutMs = 2500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}

async function loadDashboardData() {
  hideBanner();
  const modeBadge = document.getElementById("mode-badge");
  modeBadge.className = "mode-badge mode-loading";
  modeBadge.textContent = "連線偵測中...";

  try {
    const livePayload = await fetchJsonWithTimeout("/api/v1/dashboard", 2500);
    if (livePayload && Array.isArray(livePayload.tours)) {
      state.mode = "LIVE";
      state.data = livePayload;
      applyLoadedData();
      return;
    }
  } catch {
    // Fallback to static snapshot JSON
  }

  try {
    const staticPayload = await fetchJsonWithTimeout(`./data/dashboard.json?t=${Date.now()}`, 5000);
    if (staticPayload && Array.isArray(staticPayload.tours)) {
      state.mode = "STATIC";
      state.data = staticPayload;
      applyLoadedData();
      return;
    }
  } catch (err) {
    state.mode = "STATIC";
    state.data = {
      generated_at: null,
      last_run_at: null,
      summary: { total_active_tours: 0, agencies: [], trips_count: 0, diffs_count: 0 },
      destinations_catalog: [],
      default_party: { adults: 2, children_with_bed: 0, children_no_bed: 0, infants: 0 },
      trips: [],
      tours: [],
      recent_diffs: [],
      scan_history: [],
    };
    applyLoadedData();
    showBanner(
      `尚未載入儀表板資料（${err.message}）。請執行 python -m src.cli build-web 匯出靜態資料，或執行 python -m src.cli serve 啟動即時服務。`,
      true
    );
  }
}

function applyLoadedData() {
  const modeBadge = document.getElementById("mode-badge");
  const liveControls = document.getElementById("live-controls");
  const staticCloudControls = document.getElementById("static-cloud-controls");
  const lastRunText = document.getElementById("last-run-text");

  if (state.mode === "LIVE") {
    modeBadge.className = "mode-badge mode-live";
    modeBadge.textContent = "LIVE API";
    liveControls.classList.remove("hidden");
    staticCloudControls?.classList.add("hidden");
  } else {
    modeBadge.className = "mode-badge mode-static";
    modeBadge.textContent = "STATIC SNAPSHOT";
    liveControls.classList.add("hidden");
    staticCloudControls?.classList.remove("hidden");
  }

  const ts = state.data.last_run_at || state.data.generated_at;
  lastRunText.textContent = `資料時間：${formatDateTime(ts)}`;
  updateKeyIndicator();
  updateGhTokenIndicator();
  initPartyFromStorageOrDefault();
  populateCountrySelector();
  populateRegionSelector();
  populateTripSelectors();
  populateAgencyFilter();
  updateScanDestinationButton();
  renderAll();
}

function getCatalog() {
  return state.data?.destinations_catalog || [];
}

function populateCountrySelector() {
  const sel = document.getElementById("select-country");
  const catalog = getCatalog();
  const prev = state.selectedCountry;

  let html = `<option value="">全部國家 (${catalog.length})</option>`;
  for (const group of catalog) {
    html += `<option value="${escapeHtml(group.country)}">${escapeHtml(group.country)}</option>`;
  }
  html += `<option value="__CUSTOM__">✏️ 自訂國家 / 關鍵字</option>`;
  sel.innerHTML = html;
  sel.value = prev;
}

function populateRegionSelector() {
  const sel = document.getElementById("select-region");
  const customWrap = document.getElementById("custom-region-wrap");
  const catalog = getCatalog();

  if (state.selectedCountry === "__CUSTOM__") {
    sel.innerHTML = `<option value="__CUSTOM__">自訂地區關鍵字</option>`;
    sel.value = "__CUSTOM__";
    state.selectedRegion = "__CUSTOM__";
    customWrap.classList.remove("hidden");
    return;
  }

  const group = catalog.find((g) => g.country === state.selectedCountry);
  let html = `<option value="">全部地區</option>`;
  if (group) {
    for (const r of group.regions) {
      const cntHint = r.trip_ids && r.trip_ids.length > 0 ? " ★" : "";
      html += `<option value="${escapeHtml(r.region_name)}">${escapeHtml(r.region_name)}${cntHint}</option>`;
    }
  } else if (!state.selectedCountry) {
    for (const g of catalog) {
      for (const r of g.regions) {
        html += `<option value="${escapeHtml(r.region_name)}">${escapeHtml(g.country)} · ${escapeHtml(
          r.region_name
        )}</option>`;
      }
    }
  }
  html += `<option value="__CUSTOM__">✏️ 自訂地區關鍵字...</option>`;
  sel.innerHTML = html;

  const hasCurrent = Array.from(sel.options).some((o) => o.value === state.selectedRegion);
  if (!hasCurrent) state.selectedRegion = "";
  sel.value = state.selectedRegion;

  customWrap.classList.toggle("hidden", state.selectedRegion !== "__CUSTOM__");
}

function updateScanDestinationButton() {
  const btn = document.getElementById("btn-scan-destination");
  if (!btn) return;
  const hasRegion =
    (state.selectedCountry && state.selectedCountry !== "__CUSTOM__" && state.selectedRegion && state.selectedRegion !== "__CUSTOM__") ||
    (state.selectedRegion === "__CUSTOM__" && state.customRegionKeyword.trim().length > 0);
  btn.textContent = state.mode === "LIVE" ? "⚡ 掃描此地區" : "☁️ 雲端掃描此地區";
  btn.classList.toggle("hidden", !hasRegion);
}

function getTripConfigMap() {
  const map = new Map();
  for (const trip of state.data?.trips || []) {
    map.set(trip.trip_id, trip);
  }
  return map;
}

function findRegionMeta(country, regionName) {
  for (const g of getCatalog()) {
    if (country && g.country !== country) continue;
    const hit = g.regions.find((r) => r.region_name === regionName);
    if (hit) return { country: g.country, ...hit };
  }
  return null;
}

function getToursForCurrentScope() {
  let tours = state.data?.tours || [];

  if (state.selectedTripId && state.selectedTripId !== "ALL") {
    tours = tours.filter((t) => t.trip_id === state.selectedTripId);
  }

  if (state.selectedCountry && state.selectedCountry !== "__CUSTOM__") {
    tours = tours.filter(
      (t) =>
        t.destination_country === state.selectedCountry ||
        String(t.tour_name || "").includes(state.selectedCountry)
    );
  }

  if (state.selectedRegion === "__CUSTOM__") {
    const kw = state.customRegionKeyword.trim().toLowerCase();
    if (kw) {
      tours = tours.filter((t) =>
        `${t.tour_name || ""} ${t.destination_region || ""} ${(t.tags || []).join(" ")}`
          .toLowerCase()
          .includes(kw)
      );
    }
  } else if (state.selectedRegion) {
    const meta = findRegionMeta(state.selectedCountry, state.selectedRegion);
    const kws = (meta?.keywords || [state.selectedRegion]).map((k) => k.toLowerCase());
    tours = tours.filter((t) => {
      if (t.destination_region === state.selectedRegion) return true;
      const text = `${t.tour_name || ""} ${(t.tags || []).join(" ")}`.toLowerCase();
      return kws.some((k) => text.includes(k));
    });
  }

  return tours.map((t) => ({
    ...t,
    effectiveBudget: computeEffectiveBudget(t),
  }));
}

function getDiffsForSelectedTrip() {
  const allDiffs = state.data?.recent_diffs || [];
  if (state.selectedTripId === "ALL") return allDiffs;
  return allDiffs.filter((d) => d.trip_id === state.selectedTripId);
}

function getScansForSelectedTrip() {
  const allScans = state.data?.scan_history || [];
  if (state.selectedTripId === "ALL") return allScans;
  return allScans.filter((s) => s.trip_id === state.selectedTripId);
}

function populateTripSelectors() {
  const trips = state.data?.trips || [];
  const scanSel = document.getElementById("scan-trip-select");
  const extractSel = document.getElementById("extract-trip-select");
  if (scanSel) {
    scanSel.innerHTML =
      `<option value="">預設啟用專案</option>` +
      trips
        .map(
          (t) =>
            `<option value="${escapeHtml(t.trip_id)}">${escapeHtml(t.trip_name)} (${escapeHtml(
              t.trip_id
            )})</option>`
        )
        .join("");
  }
  if (extractSel) {
    extractSel.innerHTML =
      `<option value="">使用預設家族設定</option>` +
      trips
        .map(
          (t) =>
            `<option value="${escapeHtml(t.trip_id)}">${escapeHtml(t.trip_name)} (${escapeHtml(
              t.country
            )})</option>`
        )
        .join("");
  }
}

function populateAgencyFilter() {
  const select = document.getElementById("filter-agency");
  if (!select) return;
  const currentVal = state.filters.agency;
  const agencies = state.data?.summary?.agencies || [];
  select.innerHTML =
    `<option value="">全部旅行社 (${agencies.length})</option>` +
    agencies.map((a) => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join("");
  if (agencies.includes(currentVal)) {
    select.value = currentVal;
  } else {
    state.filters.agency = "";
  }
}

function renderTripTabs() {
  const container = document.getElementById("trip-tabs");
  const trips = state.data?.trips || [];
  const allTours = state.data?.tours || [];

  const counts = new Map();
  for (const tour of allTours) {
    counts.set(tour.trip_id, (counts.get(tour.trip_id) || 0) + 1);
  }

  let html = `
    <button class="trip-pill ${state.selectedTripId === "ALL" && !state.selectedCountry && !state.selectedRegion ? "active" : ""}" data-trip="ALL" type="button">
      <div class="trip-pill-title">
        <span>🌍 全部專案</span>
        <span class="trip-pill-count">${allTours.length}</span>
      </div>
      <div class="trip-pill-meta">跨目的地總覽 (${trips.length} 個專案)</div>
    </button>
  `;

  for (const trip of trips) {
    const cnt = counts.get(trip.trip_id) || 0;
    const isActive = state.selectedTripId === trip.trip_id;
    const budgetText = trip.target_total_budget_twd
      ? `預算 ${formatTwd(trip.target_total_budget_twd)}`
      : "未設預算上限";
    html += `
      <button class="trip-pill ${isActive ? "active" : ""}" data-trip="${escapeHtml(
      trip.trip_id
    )}" type="button">
        <div class="trip-pill-title">
          <span>${escapeHtml(trip.country)} / ${escapeHtml(trip.region_name)}</span>
          <span class="trip-pill-count">${cnt}</span>
          ${trip.enabled ? "" : '<span class="trip-paused">停用</span>'}
        </div>
        <div class="trip-pill-meta">${escapeHtml(trip.departure_date_start)} ~ ${escapeHtml(
      trip.departure_date_end
    )} · ${escapeHtml(budgetText)}</div>
      </button>
    `;
  }

  container.innerHTML = html;
  container.querySelectorAll(".trip-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tripId = btn.dataset.trip || "ALL";
      state.selectedTripId = tripId;
      state.showAllRows = false;
      if (tripId === "ALL") {
        state.selectedCountry = "";
        state.selectedRegion = "";
        state.customRegionKeyword = "";
      } else {
        const cfg = getTripConfigMap().get(tripId);
        if (cfg) {
          state.selectedCountry = cfg.country;
          state.selectedRegion = cfg.region_name;
          state.customRegionKeyword = "";
        }
      }
      populateCountrySelector();
      populateRegionSelector();
      syncPartyInputsUi();
      updateScanDestinationButton();
      renderAll();
    });
  });
}

function renderKpis() {
  const tours = getToursForCurrentScope();
  const diffs = getDiffsForSelectedTrip();
  const tripMap = getTripConfigMap();

  document.getElementById("kpi-total-tours").textContent = String(tours.length);
  const agenciesSet = new Set(tours.map((t) => t.agency));
  document.getElementById("kpi-total-sub").textContent =
    agenciesSet.size > 0 ? `涵蓋 ${agenciesSet.size} 家旅行社` : "此篩選範圍尚無活躍團次";

  const pricedTours = tours.filter(
    (t) => t.effectiveBudget && Number(t.effectiveBudget.grand_total_twd) > 0
  );
  if (pricedTours.length > 0) {
    const cheapest = pricedTours.reduce((a, b) =>
      a.effectiveBudget.grand_total_twd <= b.effectiveBudget.grand_total_twd ? a : b
    );
    document.getElementById("kpi-min-budget").textContent = formatTwd(
      cheapest.effectiveBudget.grand_total_twd
    );
    document.getElementById("kpi-min-budget-sub").textContent = `${cheapest.agency} · ${
      cheapest.departure_date
    } · ${cheapest.days}日`;
  } else {
    document.getElementById("kpi-min-budget").textContent = "--";
    document.getElementById("kpi-min-budget-sub").textContent = "尚無有效報價";
  }

  let qualifiedCount = 0;
  for (const t of pricedTours) {
    if (t.effectiveBudget.seat_status !== "SUFFICIENT") continue;
    const cfg = tripMap.get(t.trip_id);
    const limit = cfg?.target_total_budget_twd;
    if (state.useCustomParty || !limit || t.effectiveBudget.grand_total_twd <= limit) {
      qualifiedCount += 1;
    }
  }
  document.getElementById("kpi-qualified").textContent = String(qualifiedCount);
  const activeTripCfg =
    state.selectedTripId !== "ALL" ? tripMap.get(state.selectedTripId) : null;
  if (state.useCustomParty) {
    const seatsNeed =
      state.party.adults + state.party.childrenWithBed + state.party.childrenNoBed;
    document.getElementById("kpi-qualified-sub").textContent = `剩餘機位 >= ${seatsNeed} 席`;
  } else {
    document.getElementById("kpi-qualified-sub").textContent = activeTripCfg?.target_total_budget_twd
      ? `目標上限 ${formatTwd(activeTripCfg.target_total_budget_twd)} 且機位足夠`
      : "機位足夠全家族成員";
  }

  document.getElementById("kpi-diffs").textContent = String(diffs.length);
  document.getElementById("tab-count-rankings").textContent = String(tours.length);
  document.getElementById("tab-count-diffs").textContent = String(diffs.length);
  document.getElementById("tab-count-scans").textContent = String(getScansForSelectedTrip().length);
}

function getFilteredAndSortedTours() {
  const tripMap = getTripConfigMap();
  const baseTours = getToursForCurrentScope();
  const f = state.filters;
  const kw = f.keyword.trim().toLowerCase();

  const filtered = baseTours.filter((t) => {
    if (f.agency && t.agency !== f.agency) return false;
    if (f.airport && t.departure_airport !== f.airport) return false;
    if (f.onlySufficient && t.effectiveBudget?.seat_status !== "SUFFICIENT") return false;
    if (f.onlyNoShopping && t.has_shopping_station) return false;
    if (f.onlyWithinBudget) {
      const target = tripMap.get(t.trip_id)?.target_total_budget_twd;
      if (target && Number(t.effectiveBudget?.grand_total_twd || 0) > target) return false;
    }
    if (kw) {
      const hay = [
        t.tour_name,
        t.tour_code,
        t.agency,
        t.departure_date,
        ...(t.tags || []),
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(kw)) return false;
    }
    return true;
  });

  filtered.sort((a, b) => {
    if (f.sort === "budget_asc") {
      return (
        (a.effectiveBudget?.grand_total_twd || 0) -
        (b.effectiveBudget?.grand_total_twd || 0)
      );
    }
    if (f.sort === "adult_asc") {
      return (a.adult_price || 9999999) - (b.adult_price || 9999999);
    }
    if (f.sort === "date_asc") {
      return String(a.departure_date).localeCompare(String(b.departure_date));
    }
    const scoreDiff = (b.composite_score || 0) - (a.composite_score || 0);
    if (scoreDiff !== 0) return scoreDiff;
    return (
      (a.effectiveBudget?.grand_total_twd || 0) -
      (b.effectiveBudget?.grand_total_twd || 0)
    );
  });

  return filtered;
}

function renderRankingsTable() {
  const tbody = document.getElementById("rankings-tbody");
  const emptyEl = document.getElementById("rankings-empty");
  const loadMoreWrap = document.getElementById("load-more-wrap");
  const countText = document.getElementById("filtered-count-text");
  const tripMap = getTripConfigMap();

  const filtered = getFilteredAndSortedTours();
  countText.textContent = `顯示 ${filtered.length} 筆符合行程`;

  if (filtered.length === 0) {
    tbody.innerHTML = "";
    emptyEl.classList.remove("hidden");
    loadMoreWrap.classList.add("hidden");
    return;
  }

  emptyEl.classList.add("hidden");
  const displayRows = state.showAllRows
    ? filtered
    : filtered.slice(0, PAGE_LIMIT_INITIAL);

  if (!state.showAllRows && filtered.length > PAGE_LIMIT_INITIAL) {
    loadMoreWrap.classList.remove("hidden");
    document.getElementById(
      "btn-show-all"
    ).textContent = `顯示全部 ${filtered.length} 筆（目前前 ${PAGE_LIMIT_INITIAL} 筆）`;
  } else {
    loadMoreWrap.classList.add("hidden");
  }

  tbody.innerHTML = displayRows
    .map((t) => {
      const budget = t.effectiveBudget || t.budget;
      const score = Number(t.composite_score || 0);
      const scoreCls = score >= 80 ? "score-high" : score >= 60 ? "score-mid" : "score-low";
      const targetBudget = !state.useCustomParty
        ? tripMap.get(t.trip_id)?.target_total_budget_twd
        : null;
      const grandTotal = Number(budget?.grand_total_twd || 0);

      let deltaHtml = "";
      if (targetBudget && grandTotal > 0) {
        const diff = grandTotal - targetBudget;
        if (diff <= 0) {
          deltaHtml = `<div class="budget-delta delta-under">低於預算 ${formatTwd(Math.abs(diff))}</div>`;
        } else {
          deltaHtml = `<div class="budget-delta delta-over">超支 ${formatTwd(diff)}</div>`;
        }
      } else if (state.useCustomParty && grandTotal > 0) {
        deltaHtml = `<div class="meta-text">均 ${formatTwd(budget.avg_cost_per_person_twd)} / 人</div>`;
      }

      const seatStatus = budget?.seat_status || "UNKNOWN";
      const seatCls =
        seatStatus === "SUFFICIENT"
          ? "seat-ok"
          : seatStatus === "INSUFFICIENT"
          ? "seat-bad"
          : "seat-unknown";
      const seatText =
        t.seats_available !== null && t.seats_available !== undefined
          ? `餘 ${t.seats_available} 席`
          : seatStatus === "SUFFICIENT"
          ? "充足"
          : "未標機位";

      const tagsHtml = (t.tags || [])
        .slice(0, 5)
        .map((tag) => `<span class="tag-pill">${escapeHtml(tag)}</span>`)
        .join("");

      const url = safeUrl(t.detail_url);
      const linkBtn = url
        ? `<a class="btn btn-secondary btn-sm" href="${escapeHtml(
            url
          )}" target="_blank" rel="noopener noreferrer" data-stop-row="true">原頁</a>`
        : "";

      return `
        <tr class="clickable-row" data-uid="${escapeHtml(t.tour_uid)}">
          <td><span class="score-pill ${scoreCls}">${score.toFixed(0)}</span></td>
          <td><span class="agency-badge ${getAgencyClass(t.agency)}">${escapeHtml(t.agency)}</span></td>
          <td class="tour-title-cell">
            <span class="tour-name-text">${escapeHtml(t.tour_name)}</span>
            <div class="tour-code-sub">${escapeHtml(t.tour_code || t.tour_uid)}</div>
            ${tagsHtml ? `<div class="tag-list">${tagsHtml}</div>` : ""}
          </td>
          <td>
            <div>${escapeHtml(t.departure_date)}</div>
            <div class="meta-text">${escapeHtml(t.days)} 日 · ${escapeHtml(t.departure_airport)}</div>
          </td>
          <td class="num">${formatTwd(t.adult_price)}</td>
          <td class="num">
            <div class="budget-main">
              ${formatTwd(grandTotal)}
              ${budget?.is_estimated ? '<span class="est-badge" title="含估算補位費用">估</span>' : ""}
            </div>
            ${deltaHtml}
          </td>
          <td>
            <span class="seat-badge ${seatCls}">${escapeHtml(seatText)}</span>
            <div class="meta-text" style="margin-top:4px">${escapeHtml(t.status)}</div>
          </td>
          <td>
            <div class="action-cell">
              <button class="btn btn-primary btn-sm" type="button" data-open-detail="${escapeHtml(
                t.tour_uid
              )}">明細</button>
              ${linkBtn}
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll("tr.clickable-row").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest("[data-stop-row]")) return;
      openDetailDrawer(tr.dataset.uid);
    });
  });
}

function classifyDiff(diff) {
  if (diff.old_status === null || diff.old_status === undefined) {
    return { label: "🆕 新團上架", cls: "diff-new" };
  }
  if (
    diff.old_price !== null &&
    diff.new_price !== null &&
    Number(diff.new_price) < Number(diff.old_price)
  ) {
    return { label: "📉 團費降價", cls: "diff-drop" };
  }
  if (
    diff.old_price !== null &&
    diff.new_price !== null &&
    Number(diff.new_price) > Number(diff.old_price)
  ) {
    return { label: "📈 團費調漲", cls: "diff-up" };
  }
  if (
    diff.old_seats !== null &&
    diff.new_seats !== null &&
    Number(diff.new_seats) > Number(diff.old_seats)
  ) {
    return { label: "🎟️ 釋出機位", cls: "diff-seats" };
  }
  return { label: "🔄 狀態異動", cls: "diff-seats" };
}

function renderDiffs() {
  const listEl = document.getElementById("diffs-list");
  const emptyEl = document.getElementById("diffs-empty");
  const diffs = getDiffsForSelectedTrip();

  if (diffs.length === 0) {
    listEl.innerHTML = "";
    emptyEl.classList.remove("hidden");
    return;
  }

  emptyEl.classList.add("hidden");
  const toursByUid = new Map((state.data?.tours || []).map((t) => [t.tour_uid, t]));

  listEl.innerHTML = diffs
    .map((d) => {
      const badge = classifyDiff(d);
      const hasTour = toursByUid.has(d.tour_uid);
      const priceLine =
        d.old_price !== d.new_price
          ? `<span>成人價：${formatTwd(d.old_price)} → <strong>${formatTwd(d.new_price)}</strong></span>`
          : `<span>成人價：${formatTwd(d.new_price)}</span>`;
      const seatsLine =
        d.old_seats !== d.new_seats
          ? `<span>機位：${escapeHtml(d.old_seats ?? "--")} → <strong>${escapeHtml(
              d.new_seats ?? "--"
            )}</strong></span>`
          : `<span>機位：${escapeHtml(d.new_seats ?? "--")}</span>`;
      const statusLine =
        d.old_status !== d.new_status
          ? `<span>狀態：${escapeHtml(d.old_status ?? "首次記錄")} → <strong>${escapeHtml(
              d.new_status ?? "--"
            )}</strong></span>`
          : `<span>狀態：${escapeHtml(d.new_status ?? "--")}</span>`;

      return `
        <article class="diff-card ${hasTour ? "clickable" : ""}" data-uid="${escapeHtml(
        d.tour_uid
      )}">
          <div>
            <div class="diff-title-row">
              <span class="diff-badge ${badge.cls}">${badge.label}</span>
              <span class="agency-badge ${getAgencyClass(d.agency)}">${escapeHtml(d.agency)}</span>
              <strong>${escapeHtml(d.tour_name)}</strong>
            </div>
            <div class="diff-changes">
              <span>出發：${escapeHtml(d.departure_date)}</span>
              ${priceLine}
              ${seatsLine}
              ${statusLine}
            </div>
          </div>
          <div class="meta-text">${escapeHtml(formatDateTime(d.captured_at))}</div>
        </article>
      `;
    })
    .join("");

  listEl.querySelectorAll(".diff-card.clickable").forEach((card) => {
    card.addEventListener("click", () => openDetailDrawer(card.dataset.uid));
  });
}

function renderScanHistory() {
  const tbody = document.getElementById("scans-tbody");
  const emptyEl = document.getElementById("scans-empty");
  const scans = getScansForSelectedTrip();

  if (scans.length === 0) {
    tbody.innerHTML = "";
    emptyEl.classList.remove("hidden");
    return;
  }

  emptyEl.classList.add("hidden");
  tbody.innerHTML = scans
    .map((s) => {
      let agenciesLabel = s.agencies_run || "--";
      try {
        const parsed = JSON.parse(s.agencies_run);
        if (Array.isArray(parsed)) agenciesLabel = parsed.join("、");
      } catch {
        // keep string
      }

      return `
        <tr>
          <td style="white-space:nowrap">${escapeHtml(formatDateTime(s.scanned_at))}</td>
          <td><code>${escapeHtml(s.trip_id)}</code></td>
          <td>${escapeHtml(agenciesLabel)}</td>
          <td class="num">${Number(s.total_found || 0)}</td>
          <td class="num">${Number(s.new_count || 0)}</td>
          <td class="num">${Number(s.price_drop_count || 0)}</td>
          <td class="num">${Number(s.seats_released_count || 0)}</td>
          <td class="num">${Number(s.status_change_count || 0)}</td>
          <td>${s.error_summary ? escapeHtml(s.error_summary) : '<span class="meta-text">正常</span>'}</td>
        </tr>
      `;
    })
    .join("");
}

function renderBreakdownRows(budget) {
  const items = budget?.breakdown?.items || [];
  if (items.length === 0) {
    return '<tr><td colspan="5" class="meta-text">尚無明細資料</td></tr>';
  }
  return items
    .map((item) => {
      const roleLabel = ROLE_LABELS[item.role] || item.role;
      return `
        <tr>
          <td>
            ${escapeHtml(roleLabel)}
            ${item.is_estimated ? '<span class="est-badge">估</span>' : ""}
          </td>
          <td class="num">${Number(item.count || 0)}</td>
          <td class="num">${formatTwd(item.unit_price)}</td>
          <td class="num"><strong>${formatTwd(item.subtotal)}</strong></td>
          <td>${escapeHtml(item.note)}</td>
        </tr>
      `;
    })
    .join("");
}

function openDetailDrawer(tourUid) {
  const rawTour = (state.data?.tours || []).find((t) => t.tour_uid === tourUid);
  if (!rawTour) return;
  const budget = computeEffectiveBudget(rawTour);

  const agencyBadge = document.getElementById("drawer-agency-badge");
  agencyBadge.className = `agency-badge ${getAgencyClass(rawTour.agency)}`;
  agencyBadge.textContent = rawTour.agency;

  document.getElementById("drawer-title").textContent = rawTour.tour_name;
  document.getElementById("drawer-subtitle").textContent =
    `${rawTour.tour_code || rawTour.tour_uid} · 出發 ${rawTour.departure_date} · ${
      rawTour.days
    } 日 · ${rawTour.departure_airport}`;

  document.getElementById("drawer-grand-total").textContent = formatTwd(budget?.grand_total_twd);
  document.getElementById("drawer-avg-person").textContent = formatTwd(
    budget?.avg_cost_per_person_twd
  );
  document.getElementById("drawer-score").textContent = `${Number(
    rawTour.composite_score || 0
  ).toFixed(1)} 分`;
  const seatsLabel =
    rawTour.seats_available !== null && rawTour.seats_available !== undefined
      ? `餘 ${rawTour.seats_available} 席`
      : "未標";
  document.getElementById("drawer-seats").textContent = `${seatsLabel} (${rawTour.status})`;

  const linkEl = document.getElementById("drawer-external-link");
  const validUrl = safeUrl(rawTour.detail_url);
  if (validUrl) {
    linkEl.href = validUrl;
    linkEl.classList.remove("hidden");
  } else {
    linkEl.classList.add("hidden");
  }

  document.getElementById("drawer-parsed-at").textContent = rawTour.detail_parsed_at
    ? `LLM 詳情解析：${formatDateTime(rawTour.detail_parsed_at)}`
    : "僅列表頁基礎資料（未執行 LLM 詳情解析）";

  document.getElementById("drawer-breakdown-tbody").innerHTML = renderBreakdownRows(budget);

  const assumptionsBox = document.getElementById("drawer-assumptions");
  const assumptions = budget?.assumptions || [];
  if (assumptions.length > 0) {
    assumptionsBox.innerHTML =
      `<strong>📌 估算假設說明：</strong><ul>` +
      assumptions.map((a) => `<li>${escapeHtml(a)}</li>`).join("") +
      `</ul>`;
    assumptionsBox.classList.remove("hidden");
  } else {
    assumptionsBox.classList.add("hidden");
  }

  const warningsBox = document.getElementById("drawer-warnings");
  const warnings = budget?.risk_warnings || [];
  if (warnings.length > 0 && !state.useCustomParty) {
    warningsBox.innerHTML =
      `<strong>⚠️ 風險與注意事項：</strong><ul>` +
      warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("") +
      `</ul>`;
    warningsBox.classList.remove("hidden");
  } else {
    warningsBox.classList.add("hidden");
  }

  const rulesContent = document.getElementById("drawer-rules-content");
  const passed = (rawTour.passed_rules || [])
    .map((r) => `<span class="tag-pill" style="color:#4ade80">✅ ${escapeHtml(r)}</span>`)
    .join("");
  const failed = (rawTour.failed_rules || [])
    .map((r) => `<span class="tag-pill" style="color:#fca5a5">❌ ${escapeHtml(r)}</span>`)
    .join("");
  rulesContent.innerHTML = `
    <div class="tag-list">${passed || '<span class="meta-text">無加分規則命中</span>'}</div>
    <div class="tag-list">${failed}</div>
  `;

  renderSnapshotChart(rawTour.snapshots || []);

  document.getElementById("drawer-backdrop").classList.remove("hidden");
  document.getElementById("detail-drawer").classList.remove("hidden");
}

function closeDetailDrawer() {
  document.getElementById("drawer-backdrop").classList.add("hidden");
  document.getElementById("detail-drawer").classList.add("hidden");
  if (state.chartInstance) {
    state.chartInstance.destroy();
    state.chartInstance = null;
  }
}

function renderSnapshotChart(snapshots) {
  const wrap = document.getElementById("drawer-chart-wrap");
  const noteEl = document.getElementById("drawer-chart-note");

  if (state.chartInstance) {
    state.chartInstance.destroy();
    state.chartInstance = null;
  }

  if (!snapshots || snapshots.length === 0) {
    wrap.classList.add("hidden");
    noteEl.textContent = "尚無歷史價格快照資料。";
    return;
  }

  wrap.classList.remove("hidden");
  noteEl.textContent =
    snapshots.length === 1
      ? "目前僅有 1 筆快照，待後續定時巡檢產生變動後將顯示趨勢曲線。"
      : `共記錄 ${snapshots.length} 筆快照異動軌跡。`;

  if (typeof window.Chart === "undefined") {
    wrap.classList.add("hidden");
    noteEl.innerHTML =
      "Chart.js 離線未載入，改以文字清單顯示最近快照：" +
      snapshots
        .slice(-5)
        .map(
          (s) =>
            `[${escapeHtml(formatDateTime(s.captured_at))} ${escapeHtml(
              formatTwd(s.adult_price)
            )} / 餘${escapeHtml(s.seats_available ?? "--")}席]`
        )
        .join(" ");
    return;
  }

  const labels = snapshots.map((s) => formatDateTime(s.captured_at));
  const adultPrices = snapshots.map((s) => s.adult_price);
  const seats = snapshots.map((s) => s.seats_available);

  const ctx = document.getElementById("drawer-chart").getContext("2d");
  state.chartInstance = new window.Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "成人團費 (TWD)",
          data: adultPrices,
          borderColor: "#38bdf8",
          backgroundColor: "rgba(56, 189, 248, 0.2)",
          yAxisID: "yPrice",
          tension: 0.25,
          pointRadius: 4,
        },
        {
          label: "剩餘機位",
          data: seats,
          borderColor: "#f59e0b",
          backgroundColor: "rgba(245, 158, 11, 0.2)",
          yAxisID: "ySeats",
          tension: 0.25,
          pointRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: "#cbd5e1", font: { size: 12 } },
        },
      },
      scales: {
        x: {
          ticks: { color: "#94a3b8", maxRotation: 20, font: { size: 10 } },
          grid: { color: "rgba(148,163,184,0.1)" },
        },
        yPrice: {
          type: "linear",
          position: "left",
          ticks: { color: "#7dd3fc" },
          grid: { color: "rgba(148,163,184,0.1)" },
        },
        ySeats: {
          type: "linear",
          position: "right",
          beginAtZero: true,
          ticks: { color: "#fcd34d", precision: 0 },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
}

function renderAll() {
  renderTripTabs();
  renderKpis();
  renderRankingsTable();
  renderDiffs();
  renderScanHistory();
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.remove("hidden");
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.add("hidden");
}

function setFeedback(elId, msg, kind = "info") {
  const el = document.getElementById(elId);
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden", "is-error", "is-success");
  if (kind === "error") el.classList.add("is-error");
  if (kind === "success") el.classList.add("is-success");
}

function setScanModalMode(mode) {
  const radios = document.querySelectorAll('input[name="scan-mode"]');
  radios.forEach((r) => {
    r.checked = r.value === mode;
  });
  const isDynamic = mode === "dynamic";
  document.getElementById("scan-trip-fields").classList.toggle("hidden", isDynamic);
  document.getElementById("scan-dynamic-fields").classList.toggle("hidden", !isDynamic);
  document.getElementById("scan-save-trip-wrap").classList.toggle("hidden", !isDynamic);
}

function updateScanPartyPreview() {
  const el = document.getElementById("scan-party-preview");
  if (!el) return;
  el.innerHTML = `👥 套用人數：成人 <strong>${state.party.adults}</strong> 位、兒童佔床 <strong>${state.party.childrenWithBed}</strong> 位、兒童不佔床 <strong>${state.party.childrenNoBed}</strong> 位、嬰兒 <strong>${state.party.infants}</strong> 位`;
}

function openScanModalWithScope(preferDynamic = false) {
  document.getElementById("scan-feedback").classList.add("hidden");
  updateScanPartyPreview();

  const today = new Date();
  const start = new Date(today.getTime() + 30 * 86400000).toISOString().slice(0, 10);
  const end = new Date(today.getTime() + 90 * 86400000).toISOString().slice(0, 10);
  if (!document.getElementById("scan-date-start").value) {
    document.getElementById("scan-date-start").value = start;
  }
  if (!document.getElementById("scan-date-end").value) {
    document.getElementById("scan-date-end").value = end;
  }

  if (state.selectedTripId !== "ALL") {
    document.getElementById("scan-trip-select").value = state.selectedTripId;
  }

  const countryVal =
    state.selectedCountry === "__CUSTOM__" ? "自訂" : state.selectedCountry || "日本";
  const regionVal =
    state.selectedRegion === "__CUSTOM__"
      ? state.customRegionKeyword.trim()
      : state.selectedRegion || "";
  document.getElementById("scan-country-input").value = countryVal;
  document.getElementById("scan-region-input").value = regionVal;

  const meta = findRegionMeta(countryVal, regionVal);
  if (meta) {
    document.getElementById("scan-min-days").value = String(meta.default_min_days || 4);
    document.getElementById("scan-max-days").value = String(meta.default_max_days || 6);
  }

  setScanModalMode(preferDynamic ? "dynamic" : "trip");
  openModal("modal-scan");
}

async function callProtectedApi(path, body) {
  const apiKey = getStoredApiKey();
  const resp = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
    },
    body: JSON.stringify(body),
  });
  const payload = await resp.json().catch(() => ({}));
  if (resp.status === 401) {
    openModal("modal-api-key");
    setFeedback(
      "api-key-feedback",
      "API Key 無效或未設定，請輸入 .env 中的 API_KEY 後重試。",
      "error"
    );
    throw new Error("Unauthorized (401)");
  }
  if (!resp.ok) {
    throw new Error(payload.detail || `HTTP ${resp.status}`);
  }
  return payload;
}

function handlePartyInputChange() {
  const adults = Math.max(1, Number(document.getElementById("party-adults").value || 1));
  const childrenWithBed = Math.max(
    0,
    Number(document.getElementById("party-child-bed").value || 0)
  );
  const childrenNoBed = Math.max(
    0,
    Number(document.getElementById("party-child-nobed").value || 0)
  );
  const infants = Math.max(0, Number(document.getElementById("party-infants").value || 0));

  state.party = { adults, childrenWithBed, childrenNoBed, infants };
  state.useCustomParty = !isSameParty(state.party, getDefaultParty());
  localStorage.setItem(PARTY_STORAGE, JSON.stringify(state.party));

  syncPartyInputsUi();
  renderKpis();
  renderRankingsTable();
}

function bindEvents() {
  document.getElementById("btn-refresh").addEventListener("click", loadDashboardData);

  // Country & Region selector
  document.getElementById("select-country").addEventListener("change", (e) => {
    state.selectedCountry = e.target.value;
    state.selectedRegion = "";
    state.selectedTripId = "ALL";
    state.showAllRows = false;
    populateRegionSelector();
    syncPartyInputsUi();
    updateScanDestinationButton();
    renderAll();
  });

  document.getElementById("select-region").addEventListener("change", (e) => {
    state.selectedRegion = e.target.value;
    state.selectedTripId = "ALL";
    state.showAllRows = false;

    const meta = findRegionMeta(state.selectedCountry, state.selectedRegion);
    if (meta && !state.selectedCountry) {
      state.selectedCountry = meta.country;
      document.getElementById("select-country").value = meta.country;
    }
    if (meta && meta.trip_ids && meta.trip_ids.length === 1) {
      state.selectedTripId = meta.trip_ids[0];
    }

    document
      .getElementById("custom-region-wrap")
      .classList.toggle("hidden", state.selectedRegion !== "__CUSTOM__");
    syncPartyInputsUi();
    updateScanDestinationButton();
    renderAll();
  });

  document.getElementById("input-custom-region").addEventListener("input", (e) => {
    state.customRegionKeyword = e.target.value;
    state.showAllRows = false;
    updateScanDestinationButton();
    renderKpis();
    renderRankingsTable();
  });

  document.getElementById("btn-scan-destination").addEventListener("click", () => {
    if (state.mode === "LIVE") {
      openScanModalWithScope(true);
    } else {
      openCloudScanModal();
    }
  });

  // Party inputs
  ["party-adults", "party-child-bed", "party-child-nobed", "party-infants"].forEach((id) => {
    document.getElementById(id).addEventListener("input", handlePartyInputChange);
  });

  document.getElementById("btn-reset-party").addEventListener("click", () => {
    localStorage.removeItem(PARTY_STORAGE);
    state.party = getDefaultParty();
    state.useCustomParty = false;
    syncPartyInputsUi();
    renderKpis();
    renderRankingsTable();
  });

  // Main tabs
  document.querySelectorAll(".main-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      state.activeTab = target;
      document
        .querySelectorAll(".main-tab")
        .forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `panel-${target}`);
      });
    });
  });

  // Filters
  document.getElementById("filter-agency").addEventListener("change", (e) => {
    state.filters.agency = e.target.value;
    state.showAllRows = false;
    renderRankingsTable();
  });
  document.getElementById("filter-airport").addEventListener("change", (e) => {
    state.filters.airport = e.target.value;
    state.showAllRows = false;
    renderRankingsTable();
  });
  document.getElementById("filter-sort").addEventListener("change", (e) => {
    state.filters.sort = e.target.value;
    renderRankingsTable();
  });
  document.getElementById("filter-keyword").addEventListener("input", (e) => {
    state.filters.keyword = e.target.value;
    state.showAllRows = false;
    renderRankingsTable();
  });
  document.getElementById("toggle-sufficient").addEventListener("change", (e) => {
    state.filters.onlySufficient = e.target.checked;
    state.showAllRows = false;
    renderRankingsTable();
  });
  document.getElementById("toggle-no-shopping").addEventListener("change", (e) => {
    state.filters.onlyNoShopping = e.target.checked;
    state.showAllRows = false;
    renderRankingsTable();
  });
  document.getElementById("toggle-within-budget").addEventListener("change", (e) => {
    state.filters.onlyWithinBudget = e.target.checked;
    state.showAllRows = false;
    renderRankingsTable();
  });

  document.getElementById("btn-reset-filters").addEventListener("click", () => {
    state.filters = {
      agency: "",
      airport: "",
      sort: "score_desc",
      keyword: "",
      onlySufficient: false,
      onlyNoShopping: false,
      onlyWithinBudget: false,
    };
    state.showAllRows = false;
    document.getElementById("filter-agency").value = "";
    document.getElementById("filter-airport").value = "";
    document.getElementById("filter-sort").value = "score_desc";
    document.getElementById("filter-keyword").value = "";
    document.getElementById("toggle-sufficient").checked = false;
    document.getElementById("toggle-no-shopping").checked = false;
    document.getElementById("toggle-within-budget").checked = false;
    renderRankingsTable();
  });

  document.getElementById("btn-show-all").addEventListener("click", () => {
    state.showAllRows = true;
    renderRankingsTable();
  });

  // Drawer close
  document.getElementById("btn-close-drawer").addEventListener("click", closeDetailDrawer);
  document.getElementById("drawer-backdrop").addEventListener("click", closeDetailDrawer);

  // Modals close
  document.querySelectorAll(".modal-close").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.dataset.close));
  });

  // API Key modal
  document.getElementById("btn-api-key").addEventListener("click", () => {
    document.getElementById("input-api-key").value = getStoredApiKey();
    document.getElementById("api-key-feedback").classList.add("hidden");
    openModal("modal-api-key");
  });
  document.getElementById("btn-save-api-key").addEventListener("click", async () => {
    const val = document.getElementById("input-api-key").value.trim();
    if (!val) {
      setFeedback("api-key-feedback", "請輸入有效的 API Key。", "error");
      return;
    }
    const saveBtn = document.getElementById("btn-save-api-key");
    saveBtn.disabled = true;
    setFeedback("api-key-feedback", "正在向後端驗證金鑰...", "info");
    try {
      const resp = await fetch("/api/v1/trips", {
        headers: { "X-API-Key": val },
        cache: "no-store",
      });
      if (resp.status === 401) {
        setFeedback(
          "api-key-feedback",
          "驗證失敗 (401)：金鑰與目前執行中的後端不符（若剛修改過 .env 請重啟伺服器）。",
          "error"
        );
        return;
      }
      if (!resp.ok) {
        setFeedback("api-key-feedback", `驗證失敗：HTTP ${resp.status}`, "error");
        return;
      }
      localStorage.setItem(API_KEY_STORAGE, val);
      updateKeyIndicator();
      setFeedback("api-key-feedback", "API Key 驗證通過，已儲存至瀏覽器 localStorage。", "success");
    } catch (err) {
      setFeedback("api-key-feedback", `無法連線驗證：${err.message}`, "error");
    } finally {
      saveBtn.disabled = false;
    }
  });
  document.getElementById("btn-clear-api-key").addEventListener("click", () => {
    localStorage.removeItem(API_KEY_STORAGE);
    document.getElementById("input-api-key").value = "";
    updateKeyIndicator();
    setFeedback("api-key-feedback", "已清除儲存的 API Key。", "info");
  });

  // Live Scan modal
  document.getElementById("btn-run-scan").addEventListener("click", () => {
    openScanModalWithScope(false);
  });
  document.querySelectorAll('input[name="scan-mode"]').forEach((radio) => {
    radio.addEventListener("change", (e) => setScanModalMode(e.target.value));
  });
  document.getElementById("btn-submit-scan").addEventListener("click", async () => {
    const btn = document.getElementById("btn-submit-scan");
    const mode = document.querySelector('input[name="scan-mode"]:checked')?.value || "trip";
    const skipFlight = document.getElementById("scan-skip-flights").checked;
    const forceReparse = document.getElementById("scan-force-reparse").checked;
    const maxDetailsRaw = document.getElementById("scan-max-details").value;

    const payload = {
      skip_flight_benchmark: skipFlight,
      force_reparse: forceReparse,
      max_new_details_per_run: Number(maxDetailsRaw || 0),
    };

    if (mode === "dynamic") {
      const country = document.getElementById("scan-country-input").value.trim();
      const regionName = document.getElementById("scan-region-input").value.trim();
      if (!regionName) {
        setFeedback("scan-feedback", "請輸入要掃描的地區或關鍵字。", "error");
        return;
      }
      payload.country = country || "其他";
      payload.region_name = regionName;
      payload.departure_date_start = document.getElementById("scan-date-start").value || null;
      payload.departure_date_end = document.getElementById("scan-date-end").value || null;
      payload.min_days = Number(document.getElementById("scan-min-days").value || 4);
      payload.max_days = Number(document.getElementById("scan-max-days").value || 6);
      payload.save_as_trip = document.getElementById("scan-save-trip").checked;
      payload.adults = state.party.adults;
      payload.children_with_bed = state.party.childrenWithBed;
      payload.children_no_bed = state.party.childrenNoBed;
      payload.infants = state.party.infants;
    } else {
      payload.trip_id = document.getElementById("scan-trip-select").value || null;
      if (state.useCustomParty) {
        payload.adults = state.party.adults;
        payload.children_with_bed = state.party.childrenWithBed;
        payload.children_no_bed = state.party.childrenNoBed;
        payload.infants = state.party.infants;
      }
    }

    btn.disabled = true;
    setFeedback("scan-feedback", "正在執行爬蟲巡檢與預算計算，請稍候...", "info");
    try {
      const res = await callProtectedApi("/api/v1/pipeline/daily-run", payload);
      const stats = res.stats || {};
      setFeedback(
        "scan-feedback",
        `掃描完成 (${res.status})：探索 ${stats.total_discovered || 0} 筆、寫入快照 ${
          stats.snapshots_inserted || 0
        } 筆、告警 ${stats.alerts_count || 0} 則。`,
        "success"
      );
      await loadDashboardData();
    } catch (err) {
      setFeedback("scan-feedback", `執行失敗：${err.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  });

  // Extract single modal
  document.getElementById("btn-extract-single").addEventListener("click", () => {
    document.getElementById("extract-feedback").classList.add("hidden");
    document.getElementById("extract-result").classList.add("hidden");
    if (state.selectedTripId !== "ALL") {
      document.getElementById("extract-trip-select").value = state.selectedTripId;
    }
    openModal("modal-extract");
  });
  document.getElementById("btn-submit-extract").addEventListener("click", async () => {
    const url = document.getElementById("extract-url-input").value.trim();
    if (!url) {
      setFeedback("extract-feedback", "請輸入行程詳情頁網址。", "error");
      return;
    }
    const btn = document.getElementById("btn-submit-extract");
    btn.disabled = true;
    const resultEl = document.getElementById("extract-result");
    resultEl.classList.add("hidden");
    setFeedback("extract-feedback", "正在以 Crawl4AI + LLM 解析詳情頁...", "info");
    try {
      const payload = {
        url,
        agency_hint: document.getElementById("extract-agency-select").value || null,
        trip_id: document.getElementById("extract-trip-select").value || null,
      };
      if (state.useCustomParty) {
        payload.adults = state.party.adults;
        payload.children_with_bed = state.party.childrenWithBed;
        payload.children_no_bed = state.party.childrenNoBed;
        payload.infants = state.party.infants;
      }
      const res = await callProtectedApi("/api/v1/extract/single", payload);
      setFeedback("extract-feedback", "解析與試算完成！", "success");
      const tour = res.tour || {};
      const budget = res.budget || {};
      const evalRes = res.evaluation || {};
      resultEl.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;">
          <strong>${escapeHtml(tour.tour_name || "未命名行程")}</strong>
          <span class="score-pill score-high">${Number(evalRes.score || 0).toFixed(1)} 分</span>
        </div>
        <div class="meta-text" style="margin-bottom:10px;">
          ${escapeHtml(tour.agency)} · 出發 ${escapeHtml(tour.departure_date)} · ${escapeHtml(
        tour.days
      )} 日 · 預估總預算 <strong>${formatTwd(budget.grand_total_twd)}</strong>
        </div>
        <div class="table-wrapper">
          <table class="mini-table">
            <thead>
              <tr><th>項目</th><th class="num">人數</th><th class="num">單價</th><th class="num">小計</th><th>說明</th></tr>
            </thead>
            <tbody>${renderBreakdownRows(budget)}</tbody>
          </table>
        </div>
      `;
      resultEl.classList.remove("hidden");
    } catch (err) {
      setFeedback("extract-feedback", `解析失敗：${err.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  });

  // GitHub Cloud Token modal
  document.getElementById("btn-gh-token")?.addEventListener("click", () => {
    document.getElementById("input-gh-repo").value = detectDefaultGhRepo();
    document.getElementById("input-gh-token").value = getStoredGhToken();
    document.getElementById("gh-token-feedback").classList.add("hidden");
    openModal("modal-gh-token");
  });

  document.getElementById("btn-clear-gh-token")?.addEventListener("click", () => {
    localStorage.removeItem(GH_TOKEN_STORAGE);
    document.getElementById("input-gh-token").value = "";
    updateGhTokenIndicator();
    setFeedback("gh-token-feedback", "已清除儲存的 GitHub Token。", "info");
  });

  document.getElementById("btn-save-gh-token")?.addEventListener("click", async () => {
    const repo = document.getElementById("input-gh-repo").value.trim();
    const token = document.getElementById("input-gh-token").value.trim();
    if (!repo || !repo.includes("/")) {
      setFeedback("gh-token-feedback", "請輸入正確的 Repository 格式（owner/repo）。", "error");
      return;
    }
    if (!token) {
      setFeedback("gh-token-feedback", "請輸入有效的 GitHub PAT。", "error");
      return;
    }

    const saveBtn = document.getElementById("btn-save-gh-token");
    saveBtn.disabled = true;
    setFeedback("gh-token-feedback", "正在向 GitHub API 驗證權限...", "info");
    try {
      const resp = await fetch(
        `https://api.github.com/repos/${repo}/actions/workflows/cloud_scan.yml`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
          },
        }
      );
      if (resp.status === 401 || resp.status === 403) {
        setFeedback(
          "gh-token-feedback",
          `權限驗證失敗 (HTTP ${resp.status})，請確認 Token 有效且已勾選 Actions: Read and write。`,
          "error"
        );
        return;
      }
      if (resp.status === 404) {
        setFeedback(
          "gh-token-feedback",
          `找不到 ${repo} 或 cloud_scan.yml（請確認 Repo 名稱或 Token 是否有權限存取）。`,
          "error"
        );
        return;
      }
      if (!resp.ok) {
        setFeedback("gh-token-feedback", `驗證失敗：HTTP ${resp.status}`, "error");
        return;
      }
      localStorage.setItem(GH_REPO_STORAGE, repo);
      localStorage.setItem(GH_TOKEN_STORAGE, token);
      updateGhTokenIndicator();
      setFeedback("gh-token-feedback", "驗證通過！Token 已儲存於本機 localStorage。", "success");
    } catch (err) {
      setFeedback("gh-token-feedback", `無法連線至 GitHub API：${err.message}`, "error");
    } finally {
      saveBtn.disabled = false;
    }
  });

  // Cloud Scan modal
  document.getElementById("btn-cloud-scan")?.addEventListener("click", openCloudScanModal);
  document.getElementById("btn-submit-cloud-scan")?.addEventListener("click", triggerCloudScan);
}

let cloudPollTimer = null;

function openCloudScanModal() {
  document.getElementById("cloud-scan-feedback").classList.add("hidden");
  const today = new Date();
  const start = new Date(today.getTime() + 30 * 86400000).toISOString().slice(0, 10);
  const end = new Date(today.getTime() + 90 * 86400000).toISOString().slice(0, 10);
  if (!document.getElementById("cloud-date-start").value) {
    document.getElementById("cloud-date-start").value = start;
  }
  if (!document.getElementById("cloud-date-end").value) {
    document.getElementById("cloud-date-end").value = end;
  }

  const countryVal =
    state.selectedCountry === "__CUSTOM__" ? "自訂" : state.selectedCountry || "自訂";
  const regionVal =
    state.selectedRegion === "__CUSTOM__"
      ? state.customRegionKeyword.trim()
      : state.selectedRegion || "";
  document.getElementById("cloud-country-input").value = countryVal;
  document.getElementById("cloud-region-input").value = regionVal;

  const meta = findRegionMeta(countryVal, regionVal);
  if (meta) {
    document.getElementById("cloud-min-days").value = String(meta.default_min_days || 4);
    document.getElementById("cloud-max-days").value = String(meta.default_max_days || 6);
  }
  openModal("modal-cloud-scan");
}

function setFeedbackHtml(elId, html, kind = "info") {
  const el = document.getElementById(elId);
  if (!el) return;
  el.innerHTML = html;
  el.classList.remove("hidden", "is-error", "is-success");
  if (kind === "error") el.classList.add("is-error");
  if (kind === "success") el.classList.add("is-success");
}

async function triggerCloudScan() {
  const token = getStoredGhToken();
  const repo = detectDefaultGhRepo();
  if (!token) {
    openModal("modal-gh-token");
    setFeedback(
      "gh-token-feedback",
      "請先設定具備 Actions: Read and write 權限的 GitHub Token。",
      "error"
    );
    return;
  }

  const country = document.getElementById("cloud-country-input").value.trim() || "自訂";
  const region = document.getElementById("cloud-region-input").value.trim();
  if (!region) {
    setFeedback("cloud-scan-feedback", "請輸入地區或搜尋關鍵字（例如：泰國曼谷）。", "error");
    return;
  }

  const btn = document.getElementById("btn-submit-cloud-scan");
  btn.disabled = true;
  if (cloudPollTimer) {
    clearInterval(cloudPollTimer);
    cloudPollTimer = null;
  }

  const dispatchedAtMs = Date.now();
  setFeedback("cloud-scan-feedback", "正在送出雲端爬蟲任務至 GitHub Actions...", "info");

  try {
    const resp = await fetch(
      `https://api.github.com/repos/${repo}/actions/workflows/cloud_scan.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "X-GitHub-Api-Version": "2022-11-28",
        },
        body: JSON.stringify({
          ref: "main",
          inputs: {
            country,
            region,
            date_start: document.getElementById("cloud-date-start").value || "",
            date_end: document.getElementById("cloud-date-end").value || "",
            min_days: String(document.getElementById("cloud-min-days").value || "4"),
            max_days: String(document.getElementById("cloud-max-days").value || "6"),
            no_playwright: document.getElementById("cloud-no-playwright").checked,
            save_trip: document.getElementById("cloud-save-trip").checked,
          },
        }),
      }
    );

    if (resp.status === 401 || resp.status === 403) {
      openModal("modal-gh-token");
      setFeedback(
        "gh-token-feedback",
        `Token 權限不足 (HTTP ${resp.status})，請確認 Fine-grained PAT 具有 Actions: Read and write 權限。`,
        "error"
      );
      setFeedback("cloud-scan-feedback", `觸發失敗：HTTP ${resp.status}`, "error");
      btn.disabled = false;
      return;
    }

    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      throw new Error(errBody.message || `HTTP ${resp.status}`);
    }

    setFeedback(
      "cloud-scan-feedback",
      `⏳ 已送出「${country} · ${region}」雲端抓團任務！正在等待 GitHub Runner 接單（約 1～2 分鐘）...`,
      "info"
    );
    pollCloudScanStatus(repo, token, dispatchedAtMs, country, region, btn);
  } catch (err) {
    setFeedback("cloud-scan-feedback", `觸發失敗：${err.message}`, "error");
    btn.disabled = false;
  }
}

function pollCloudScanStatus(repo, token, dispatchedAtMs, country, region, btn) {
  let attempts = 0;
  const maxAttempts = 40;

  const checkOnce = async () => {
    attempts += 1;
    try {
      const resp = await fetch(
        `https://api.github.com/repos/${repo}/actions/workflows/cloud_scan.yml/runs?event=workflow_dispatch&per_page=5&_=${Date.now()}`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
          },
          cache: "no-store",
        }
      );
      if (!resp.ok) return;
      const data = await resp.json();
      const runs = data.workflow_runs || [];
      const targetRun = runs.find(
        (r) => new Date(r.created_at).getTime() >= dispatchedAtMs - 15000
      );
      if (!targetRun) {
        if (attempts >= maxAttempts) {
          clearInterval(cloudPollTimer);
          cloudPollTimer = null;
          btn.disabled = false;
          setFeedback("cloud-scan-feedback", "輪詢逾時，請稍後手動按「🔄 重新整理」查看資料。", "info");
        }
        return;
      }

      const runLink = safeUrl(targetRun.html_url);
      const linkHtml = runLink
        ? ` <a href="${escapeHtml(runLink)}" target="_blank" rel="noopener noreferrer" style="color:#7dd3fc;">查看執行紀錄 ↗</a>`
        : "";

      if (targetRun.status !== "completed") {
        const label =
          targetRun.status === "queued"
            ? "排隊等待 Runner 中"
            : "雲端爬蟲與網頁部署執行中";
        setFeedbackHtml(
          "cloud-scan-feedback",
          `⏳ 「${escapeHtml(country)} · ${escapeHtml(region)}」${label}... (${attempts * 8}s)${linkHtml}`,
          "info"
        );
        if (attempts >= maxAttempts) {
          clearInterval(cloudPollTimer);
          cloudPollTimer = null;
          btn.disabled = false;
        }
        return;
      }

      clearInterval(cloudPollTimer);
      cloudPollTimer = null;
      btn.disabled = false;

      if (targetRun.conclusion === "success") {
        setFeedbackHtml(
          "cloud-scan-feedback",
          `✅ 雲端抓團與部署成功！正在自動刷新頁面資料...${linkHtml}`,
          "success"
        );
        await new Promise((r) => setTimeout(r, 3000));
        await loadDashboardData();
        setFeedbackHtml(
          "cloud-scan-feedback",
          `🎉 「${escapeHtml(country)} · ${escapeHtml(region)}」資料已同步至最新排行榜！${linkHtml}`,
          "success"
        );
      } else {
        setFeedbackHtml(
          "cloud-scan-feedback",
          `❌ 雲端執行結束（狀態：${escapeHtml(targetRun.conclusion || "failed")}）。${linkHtml}`,
          "error"
        );
      }
    } catch {
      // keep polling silently on transient network glitches
    }
  };

  cloudPollTimer = setInterval(checkOnce, 8000);
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  loadDashboardData();
});
