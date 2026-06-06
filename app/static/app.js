const state = {
  activities: [],
  thresholds: [],
  imports: [],
  goals: [],
  selectedMonth: "all",
};

const page = document.body.dataset.page;
const el = (id) => document.getElementById(id);

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#039;",
}[char]));

const formatDuration = (seconds) => {
  if (seconds === null || seconds === undefined) return "--";
  const total = Math.max(0, Number(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return [hours, minutes, secs].map((part) => String(part).padStart(2, "0")).join(":");
};

const formatSplitDelta = (seconds) => {
  if (seconds === null || seconds === undefined || Number(seconds) === 0) return "";
  const sign = Number(seconds) > 0 ? "-" : "+";
  const className = Number(seconds) > 0 ? "delta-positive" : "delta-negative";
  return `<strong class="${className}">${sign}${formatDuration(Math.abs(Number(seconds)))}</strong>`;
};

const formatPace = (seconds) => {
  if (seconds === null || seconds === undefined) return "--";
  const minutes = Math.floor(Number(seconds) / 60);
  const secs = Number(seconds) % 60;
  return `${minutes}'${String(secs).padStart(2, "0")}"/км`;
};

const formatDistance = (km) => km === null || km === undefined ? "--" : `${Number(km).toFixed(2)} км`;
const formatHr = (bpm) => bpm === null || bpm === undefined ? "--" : `${bpm} уд/мин`;
const formatCadence = (spm) => spm === null || spm === undefined ? "--" : `${spm} шаг/мин`;
const formatMeters = (meters) => meters === null || meters === undefined ? "--" : `${Number(meters).toFixed(1)} м`;
const formatDate = (value) => value ? new Date(value.replace(" ", "T")).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" }) : "Дата не указана";
const formatShortDate = (value) => value ? new Date(value.replace(" ", "T")).toLocaleDateString("ru-RU", { day: "2-digit", month: "short" }) : "Дата не указана";

const pluralRu = (count, one, few, many) => {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

function setStatus(text, mode) {
  const status = el("data-status");
  if (!status) return;
  status.textContent = text;
  status.className = `status-card ${mode || ""}`.trim();
}

function toggle(id, hidden) {
  const node = el(id);
  if (node) node.classList.toggle("hidden", hidden);
}

function renderMetrics() {
  const totalDistance = state.activities.reduce((sum, activity) => sum + Number(activity.distance_km || 0), 0);
  const bestThresholdPace = state.thresholds.reduce((best, item) => {
    const pace = item.threshold_pace_seconds_per_km;
    return pace && (!best || pace < best) ? pace : best;
  }, null);
  const thresholdHr = state.thresholds[0]?.threshold_heart_rate_bpm;

  if (el("metric-workouts")) el("metric-workouts").textContent = state.activities.length;
  if (el("metric-distance")) el("metric-distance").textContent = formatDistance(totalDistance);
  if (el("metric-threshold-pace")) el("metric-threshold-pace").textContent = formatPace(bestThresholdPace);
  if (el("metric-threshold-hr")) el("metric-threshold-hr").textContent = formatHr(thresholdHr);
}

function monthKey(value) {
  if (!value) return "unknown";
  return value.slice(0, 7);
}

function monthLabel(key) {
  if (key === "all") return "Все месяцы";
  if (key === "unknown") return "Без даты";
  const [year, month] = key.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
}

function monthOptions() {
  return [...new Set(state.activities.map((activity) => monthKey(activity.started_at)))];
}

function filteredActivities() {
  if (state.selectedMonth === "all") return state.activities;
  return state.activities.filter((activity) => monthKey(activity.started_at) === state.selectedMonth);
}

function renderMonthFilters() {
  const chips = el("month-chips");
  if (!chips) return;
  const options = ["all", ...monthOptions()];
  chips.innerHTML = options.map((key) => {
    const count = key === "all" ? state.activities.length : state.activities.filter((activity) => monthKey(activity.started_at) === key).length;
    const active = state.selectedMonth === key;
    return `
      <button class="month-chip ${active ? "active" : ""}" type="button" data-month="${key}" aria-pressed="${active}">
        <span>${monthLabel(key)}</span>
        <strong>${count}</strong>
      </button>
    `;
  }).join("");
}

function activityCard(activity) {
  const stress = activity.aerobic_training_stress ? Number(activity.aerobic_training_stress).toFixed(1) : "--";
  return `
    <article class="training-card">
      <a class="training-card-link" href="/activity?id=${activity.id}">
        <div class="training-card-main">
          <span>${formatDate(activity.started_at)}</span>
          <strong>${formatDistance(activity.distance_km)}</strong>
          <small>${escapeHtml(activity.title || "Тренировка")}</small>
        </div>
        <div class="training-card-metrics">
          <div><span>Время</span><strong>${formatDuration(activity.duration_seconds)}</strong></div>
          <div><span>Темп</span><strong>${formatPace(activity.average_pace_seconds_per_km)}</strong></div>
          <div><span>Пульс</span><strong>${formatHr(activity.average_heart_rate_bpm)}</strong></div>
          <div><span>Стресс</span><strong>${stress}</strong></div>
        </div>
        <div class="training-card-footer">
          <span>${activity.segments?.length || 0} ${pluralRu(activity.segments?.length || 0, "сегмент", "сегмента", "сегментов")}</span>
          <span>Открыть разбор →</span>
        </div>
      </a>
      <button class="danger-action delete-activity" type="button" data-activity-id="${activity.id}">Удалить тренировку</button>
    </article>
  `;
}

function renderActivitiesPage() {
  renderMetrics();
  const hasData = state.activities.length > 0;
  const activities = filteredActivities();
  const countLabel = `${activities.length} ${pluralRu(activities.length, "тренировка", "тренировки", "тренировок")}`;

  setStatus(`Загружено: ${state.activities.length} ${pluralRu(state.activities.length, "тренировка", "тренировки", "тренировок")}`, "ready");
  toggle("empty-panel", hasData);
  toggle("filtered-empty-panel", !hasData || activities.length > 0);

  if (el("filtered-count-pill")) el("filtered-count-pill").textContent = countLabel;
  renderMonthFilters();

  const list = el("activity-list");
  if (list) list.innerHTML = activities.map(activityCard).join("");
}

function summaryItem(label, value) {
  return `<div class="summary-item"><span>${label}</span><strong>${value}</strong></div>`;
}

function getActivityFromUrl() {
  const id = Number(new URLSearchParams(window.location.search).get("id"));
  if (!id && state.activities.length) return state.activities[0];
  return state.activities.find((activity) => activity.id === id) || null;
}

function renderActivity(activity) {
  el("activity-title").textContent = activity.title || "Тренировка";
  el("activity-date").textContent = formatDate(activity.started_at);
  el("activity-summary").innerHTML = [
    summaryItem("Дистанция", formatDistance(activity.distance_km)),
    summaryItem("Длительность", formatDuration(activity.duration_seconds)),
    summaryItem("Средний темп", formatPace(activity.average_pace_seconds_per_km)),
    summaryItem("Средний пульс", formatHr(activity.average_heart_rate_bpm)),
    summaryItem("Калории", activity.calories_kcal ? `${activity.calories_kcal} ккал` : "--"),
    summaryItem("Скорость", activity.average_speed_kmh ? `${Number(activity.average_speed_kmh).toFixed(2)} км/ч` : "--"),
    summaryItem("Каденс", formatCadence(activity.average_cadence_spm)),
    summaryItem("Шаги", activity.steps_count ? activity.steps_count.toLocaleString("ru-RU") : "--"),
    summaryItem("Набор", formatMeters(activity.elevation_gain_m)),
    summaryItem("Спуск", formatMeters(activity.elevation_loss_m)),
    summaryItem("Аэробный стресс", activity.aerobic_training_stress ? Number(activity.aerobic_training_stress).toFixed(1) : "--"),
    summaryItem("Эффект", activity.aerobic_training_effect || "--"),
  ].join("");

  el("segments-table").innerHTML = activity.segments.map((segment) => `
    <tr>
      <td>${segment.segment_index}</td>
      <td>${formatDistance(segment.distance_km)}</td>
      <td>${formatDuration(segment.duration_seconds)}</td>
      <td>${formatPace(segment.pace_seconds_per_km)}</td>
      <td>${formatHr(segment.average_heart_rate_bpm)}</td>
      <td>${formatCadence(segment.average_cadence_spm)}</td>
    </tr>
  `).join("");

  renderPaceBars(activity.segments);
  renderSplits(activity.split_blocks);
}

function renderPaceBars(segments) {
  if (!segments.length) {
    el("pace-bars").innerHTML = `<div class="notice">Нет данных по отрезкам.</div>`;
    return;
  }
  const paces = segments.map((segment) => segment.pace_seconds_per_km).filter(Boolean);
  const slowest = Math.max(...paces);
  const fastest = Math.min(...paces);
  const range = Math.max(1, slowest - fastest);

  el("pace-bars").innerHTML = segments.map((segment) => {
    const speedScore = (slowest - segment.pace_seconds_per_km) / range;
    const width = 34 + speedScore * 66;
    return `
      <div class="pace-row">
        <strong>${segment.segment_index} км</strong>
        <div class="bar-track"><div class="bar-fill" style="width:${width.toFixed(1)}%"></div></div>
        <span>${formatPace(segment.pace_seconds_per_km)}</span>
      </div>
    `;
  }).join("");
}

function renderSplits(blocks) {
  if (!blocks.length) {
    el("split-blocks").innerHTML = `<div class="notice">Нет сплит-блоков.</div>`;
    return;
  }
  const first = blocks[0]?.duration_seconds;
  el("split-blocks").innerHTML = blocks.map((block) => {
    const pace = Math.round(block.duration_seconds / block.distance_km);
    const delta = first && block.block_index > 1 ? first - block.duration_seconds : null;
    return `
      <article class="split-card">
        <div>
          <span>${block.start_km}-${block.end_km} км</span>
          <strong>${formatDuration(block.duration_seconds)}</strong>
        </div>
        <div>
          <span>${formatPace(pace)}</span>
          ${formatSplitDelta(delta)}
        </div>
      </article>
    `;
  }).join("");
}

function renderThreshold(measurement) {
  if (!measurement) {
    el("threshold-content").innerHTML = `<div class="notice">Нет измерений лактатного порога.</div>`;
    return;
  }
  el("threshold-content").innerHTML = `
    <div class="threshold-hero">
      <div class="threshold-cell"><span>Пороговый пульс</span><strong>${formatHr(measurement.threshold_heart_rate_bpm)}</strong></div>
      <div class="threshold-cell"><span>Пороговый темп</span><strong>${formatPace(measurement.threshold_pace_seconds_per_km)}</strong></div>
    </div>
    <div class="threshold-grid">
      <div class="threshold-cell"><span>Длительность</span><strong>${formatDuration(measurement.duration_seconds)}</strong></div>
      <div class="threshold-cell"><span>Средний пульс</span><strong>${formatHr(measurement.average_heart_rate_bpm)}</strong></div>
      <div class="threshold-cell"><span>Средний темп</span><strong>${formatPace(measurement.average_pace_seconds_per_km)}</strong></div>
      <div class="threshold-cell"><span>Каденс</span><strong>${formatCadence(measurement.average_cadence_spm)}</strong></div>
    </div>
  `;
}

function sourceLink(source) {
  const href = `/${source.file_path}`;
  return `
    <a class="source-link" href="${href}" target="_blank" rel="noreferrer">
      <div>
        <strong>${escapeHtml(source.screen_type)}</strong>
        <span>${escapeHtml(source.notes || source.file_path)}</span>
      </div>
      <span>открыть</span>
    </a>
  `;
}

function renderSources(activity, measurement) {
  const sources = [...(activity?.screenshot_sources || [])];
  if (measurement?.screenshot_source) sources.push(measurement.screenshot_source);
  const unique = [...new Map(sources.map((source) => [source.id, source])).values()];
  el("sources-list").innerHTML = unique.length ? unique.map(sourceLink).join("") : `<div class="notice">Нет ссылок на скриншоты.</div>`;
}

function renderActivityDetailPage() {
  const activity = getActivityFromUrl();
  const threshold = state.thresholds[0];

  if (!activity) {
    setStatus("Тренировка не найдена", "failed");
    toggle("empty-panel", false);
    toggle("dashboard", true);
    return;
  }

  setStatus(`${formatDate(activity.started_at)} · ${formatDistance(activity.distance_km)}`, "ready");
  toggle("empty-panel", true);
  toggle("dashboard", false);
  renderActivity(activity);
  renderThreshold(threshold);
  renderSources(activity, threshold);
}

function renderImportBatches() {
  const container = el("import-batches");
  if (!container) return;
  if (!state.imports.length) {
    container.innerHTML = `<div class="notice">Импортов пока нет.</div>`;
    return;
  }
  container.innerHTML = state.imports.map((batch) => `
    <article class="import-card">
      <div>
        <span>${formatDate(batch.created_at)}</span>
        <strong>${escapeHtml(batch.status)}</strong>
        <p>${escapeHtml(batch.recognition_message || "")}</p>
      </div>
      <div class="import-sources">
        ${(batch.sources || []).map((source) => `<a href="/${source.file_path}" target="_blank" rel="noreferrer">${escapeHtml(source.file_path)}</a>`).join("")}
      </div>
      ${batch.created_activity_id ? `<a class="text-action" href="/activity?id=${batch.created_activity_id}">Открыть созданную тренировку</a>` : ""}
    </article>
  `).join("");
}

function renderImportPage() {
  setStatus("Можно загрузить скрины тренировки", "ready");
  renderImportBatches();
}

function monthlyStats() {
  const byMonth = new Map();
  for (const activity of state.activities) {
    const key = monthKey(activity.started_at);
    const current = byMonth.get(key) || { key, distance: 0, duration: 0, count: 0 };
    current.distance += Number(activity.distance_km || 0);
    current.duration += Number(activity.duration_seconds || 0);
    current.count += 1;
    byMonth.set(key, current);
  }
  return [...byMonth.values()].sort((a, b) => b.key.localeCompare(a.key));
}

function averageHr() {
  const values = state.activities.map((activity) => Number(activity.average_heart_rate_bpm || 0)).filter(Boolean);
  if (!values.length) return null;
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

function renderAnalyticsPage() {
  const totalDistance = state.activities.reduce((sum, activity) => sum + Number(activity.distance_km || 0), 0);
  const totalDuration = state.activities.reduce((sum, activity) => sum + Number(activity.duration_seconds || 0), 0);
  const longest = state.activities.reduce((best, activity) => Number(activity.distance_km || 0) > Number(best?.distance_km || 0) ? activity : best, null);
  const fastest = state.activities.reduce((best, activity) => {
    const pace = Number(activity.average_pace_seconds_per_km || 0);
    return pace && (!best || pace < Number(best.average_pace_seconds_per_km || Infinity)) ? activity : best;
  }, null);
  const months = monthlyStats();
  const maxMonthlyDistance = Math.max(1, ...months.map((month) => month.distance));

  setStatus(`В аналитике ${state.activities.length} ${pluralRu(state.activities.length, "тренировка", "тренировки", "тренировок")}`, "ready");
  el("analytics-distance").textContent = formatDistance(totalDistance);
  el("analytics-pace").textContent = totalDistance ? formatPace(Math.round(totalDuration / totalDistance)) : "--";
  el("analytics-longest").textContent = longest ? formatDistance(longest.distance_km) : "--";
  el("analytics-hr").textContent = formatHr(averageHr());

  el("monthly-bars").innerHTML = months.length ? months.map((month) => `
    <div class="monthly-row">
      <strong>${monthLabel(month.key)}</strong>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(8, month.distance / maxMonthlyDistance * 100).toFixed(1)}%"></div></div>
      <span>${formatDistance(month.distance)} · ${month.count}</span>
    </div>
  `).join("") : `<div class="notice">Пока нет тренировок для аналитики.</div>`;

  el("analytics-summary").innerHTML = [
    summaryItem("Всего времени", formatDuration(totalDuration)),
    summaryItem("Самый быстрый средний темп", fastest ? formatPace(fastest.average_pace_seconds_per_km) : "--"),
    summaryItem("Средняя дистанция", state.activities.length ? formatDistance(totalDistance / state.activities.length) : "--"),
    summaryItem("Месяцев с данными", months.length),
  ].join("");
}

function activitiesInGoalPeriod(goal) {
  return state.activities.filter((activity) => {
    const date = activity.started_at?.slice(0, 10);
    if (!date) return false;
    if (goal.period_start && date < goal.period_start) return false;
    if (goal.period_end && date > goal.period_end) return false;
    return true;
  });
}

function goalProgress(goal) {
  const activities = activitiesInGoalPeriod(goal);
  if (goal.goal_type === "workout_count") return activities.length;
  if (goal.goal_type === "longest_run") return Math.max(0, ...activities.map((activity) => Number(activity.distance_km || 0)));
  if (goal.goal_type === "monthly_distance" || goal.goal_type === "race") {
    return activities.reduce((sum, activity) => sum + Number(activity.distance_km || 0), 0);
  }
  return null;
}

function goalCard(goal) {
  const progress = goalProgress(goal);
  const target = Number(goal.target_value || 0);
  const percent = progress !== null && target > 0 ? Math.min(100, progress / target * 100) : null;
  const progressText = progress === null ? "Личная цель" : `${Number(progress).toFixed(goal.goal_type === "workout_count" ? 0 : 1)} ${escapeHtml(goal.unit || "")}`.trim();
  const targetText = target ? `${target} ${escapeHtml(goal.unit || "")}`.trim() : "без числовой цели";
  return `
    <article class="goal-card">
      <div class="goal-card-head">
        <div>
          <span>${escapeHtml(goal.goal_type)}</span>
          <strong>${escapeHtml(goal.title)}</strong>
        </div>
        <button class="danger-action delete-goal" type="button" data-goal-id="${goal.id}">Удалить</button>
      </div>
      <p>${escapeHtml(goal.reason || "Причина не указана")}</p>
      <div class="goal-progress">
        <div class="bar-track"><div class="bar-fill" style="width:${percent === null ? 12 : Math.max(6, percent).toFixed(1)}%"></div></div>
        <span>${progressText} / ${targetText}</span>
      </div>
    </article>
  `;
}

function renderGoalsPage() {
  setStatus(`${state.goals.length} ${pluralRu(state.goals.length, "цель", "цели", "целей")}`, "ready");
  const list = el("goals-list");
  list.innerHTML = state.goals.length ? state.goals.map(goalCard).join("") : `<div class="notice">Целей пока нет.</div>`;
}

function renderPage() {
  if (page === "activities") renderActivitiesPage();
  if (page === "activity-detail") renderActivityDetailPage();
  if (page === "import") renderImportPage();
  if (page === "analytics") renderAnalyticsPage();
  if (page === "goals") renderGoalsPage();
}

document.addEventListener("click", (event) => {
  const monthChip = event.target.closest(".month-chip");
  if (monthChip) {
    state.selectedMonth = monthChip.dataset.month;
    renderActivitiesPage();
    return;
  }

  const deleteActivity = event.target.closest(".delete-activity");
  if (deleteActivity) {
    const activityId = Number(deleteActivity.dataset.activityId);
    if (!window.confirm("Удалить тренировку и ее сегменты из базы?")) return;
    fetchJson(`/api/activities/${activityId}`, { method: "DELETE" })
      .then(() => fetchJson("/api/activities"))
      .then((activities) => {
        state.activities = activities;
        renderActivitiesPage();
      })
      .catch((error) => {
        setStatus("Ошибка удаления", "failed");
        if (el("error-panel")) {
          el("error-panel").textContent = error.message;
          el("error-panel").classList.remove("hidden");
        }
      });
    return;
  }

  const deleteGoal = event.target.closest(".delete-goal");
  if (deleteGoal) {
    const goalId = Number(deleteGoal.dataset.goalId);
    if (!window.confirm("Удалить цель?")) return;
    fetchJson(`/api/goals/${goalId}`, { method: "DELETE" })
      .then(() => fetchJson("/api/goals"))
      .then((goals) => {
        state.goals = goals;
        renderGoalsPage();
      })
      .catch((error) => setStatus(`Ошибка удаления цели: ${error.message}`, "failed"));
  }
});

document.addEventListener("change", (event) => {
  if (event.target.id !== "screenshots-input") return;
  const files = [...event.target.files];
  const label = el("selected-files-label");
  if (label) label.textContent = files.length ? files.map((file) => file.name).join(", ") : "Файлы не выбраны";
});

document.addEventListener("submit", (event) => {
  if (event.target.id === "upload-form") {
    event.preventDefault();
    const form = event.target;
    const data = new FormData(form);
    setStatus("Загрузка скринов...", "");
    fetchJson("/api/import-screenshots", { method: "POST", body: data })
      .then((result) => Promise.all([result, fetchJson("/api/import-batches"), fetchJson("/api/activities")]))
      .then(([result, imports, activities]) => {
        state.imports = imports;
        state.activities = activities;
        setStatus(result.message, result.created_activity_id ? "ready" : "failed");
        const uploadResult = el("upload-result");
        uploadResult.classList.remove("hidden");
        uploadResult.innerHTML = result.created_activity_id
          ? `Тренировка создана. <a class="text-action" href="/activity?id=${result.created_activity_id}">Открыть разбор</a>`
          : `${escapeHtml(result.message)}<br />Файлы сохранены, можно обработать вручную позже.`;
        form.reset();
        if (el("selected-files-label")) el("selected-files-label").textContent = "Файлы не выбраны";
        renderImportBatches();
      })
      .catch((error) => {
        setStatus("Ошибка импорта", "failed");
        const uploadResult = el("upload-result");
        uploadResult.classList.remove("hidden");
        uploadResult.textContent = error.message;
      });
    return;
  }

  if (event.target.id === "goal-form") {
    event.preventDefault();
    const form = event.target;
    const payload = Object.fromEntries(new FormData(form).entries());
    fetchJson("/api/goals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(() => fetchJson("/api/goals"))
      .then((goals) => {
        state.goals = goals;
        form.reset();
        renderGoalsPage();
      })
      .catch((error) => setStatus(`Ошибка сохранения цели: ${error.message}`, "failed"));
  }
});

async function init() {
  try {
    const [activities, thresholds, imports, goals] = await Promise.all([
      fetchJson("/api/activities"),
      fetchJson("/api/lactate-thresholds"),
      fetchJson("/api/import-batches"),
      fetchJson("/api/goals"),
    ]);
    state.activities = activities;
    state.thresholds = thresholds;
    state.imports = imports;
    state.goals = goals;
    renderPage();
  } catch (error) {
    console.error(error);
    setStatus("Ошибка загрузки", "failed");
    if (el("error-panel")) {
      el("error-panel").textContent = `Не удалось загрузить данные API: ${error.message}`;
      el("error-panel").classList.remove("hidden");
    }
  }
}

init();
