(function () {

  "use strict";

  const root = document.getElementById("sprintViewerV2");

  if (!root) return;

  const $ = id => document.getElementById(`sv${id}`);

  const api = window.portalApiFetch || window.fetch.bind(window);

  const boards = JSON.parse(root.dataset.boards || "{}");

  const params = new URLSearchParams(location.search);

  const roles = ["team", "developer", "po", "scrum", "manager"];

  const tabs = ["overview", "suggestions", "flow", "trends", "retro"];

  let state = { view: roles.includes(params.get("view")) ? params.get("view") : "team", tab: tabs.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview", focus: params.get("focus") || "all", developer: params.get("developer") || "", search: params.get("search") || "", evidence: params.get("evidence") || "", page: 1, revision: "", viewId: "", snapshotId: "", analysis: null, suggestions: [], records: [] };

  let sequence = 0, issueSequence = 0, drawerSequence = 0, controller = new AbortController(), pollTimer, searchTimer, accessTimer, edit = null;

  function node(tag, text, className) { const el = document.createElement(tag); if (text != null) el.textContent = text; if (className) el.className = className; if (className === "sv2-table-region") { el.tabIndex = 0; el.setAttribute("role", "region"); el.setAttribute("aria-label", "Scrollable evidence table"); } return el; }

  function button(text, fn) { const b = node("button", text); b.type = "button"; b.addEventListener("click", fn); return b; }

  function message(text) { $("Message").textContent = text; }

  function unavailable(text) { return node("p", `Unavailable — ${text}`, "sv2-empty"); }

  function pretty(value) { const text = String(value || "").replaceAll("_", " "); return text ? text[0].toUpperCase() + text.slice(1) : ""; }

  function urlState(replace = false) {

    const url = new URL(location.href);

    const values = { snapshot: state.snapshotId, revision: state.revision, feature: $("Feature").value, application: $("Application").value, issue_type: $("IssueType").value, status: $("Status").value, sort: $("Sort").value, group: $("Group").value, project: $("Project").value, board: $("Board").value, sprint: $("Sprint").value, view: state.view, focus: state.focus, developer: state.developer, search: state.search, evidence: state.evidence };

    Object.entries(values).forEach(([key, value]) => value ? url.searchParams.set(key, value) : url.searchParams.delete(key));

    url.hash = state.tab;

    history[replace ? "replaceState" : "pushState"](null, "", url);

  }

  async function request(url, body, signal = controller.signal) {

    const options = { signal, headers: { "Content-Type": "application/json" } };

    if (body !== undefined) Object.assign(options, { method: "POST", body: JSON.stringify(body) });

    const response = await api(url, options);

    const result = await response.json();

    if (!response.ok) { const error = new Error(result.error?.message || `Request failed (${response.status})`); error.status = response.status; throw error; }

    return result;

  }

  function fail(error) {

    if (error.name === "AbortError") return;

    message(error.message);

    if ([401, 403, 404].includes(error.status)) { $("Report").hidden = true; state.analysis = null; $("Issues").replaceChildren(); clearTimeout(pollTimer); }

  }

  function base(operation) { return `/automation/sprint-viewer/views/${encodeURIComponent(state.viewId)}/${operation}`; }

  function query() {

    return new URLSearchParams({ feature: $("Feature").value, application: $("Application").value, issue_type: $("IssueType").value, status: $("Status").value, sort: $("Sort").value, revision: state.revision, focus: state.focus, developer: state.developer, search: state.search, evidence: state.evidence, page: state.page, view: state.view });

  }

  function options(select, items, selected, empty) {

    select.replaceChildren();

    if (empty) select.append(new Option(empty, ""));

    items.forEach(([value, label]) => select.append(new Option(label, value)));

    if ([...select.options].some(o => o.value === String(selected))) select.value = String(selected);

  }

  function resetReport() {

    sequence++; issueSequence++; clearTimeout(accessTimer); controller.abort(); controller = new AbortController(); clearTimeout(pollTimer);

    state.analysis = null; state.revision = ""; state.viewId = ""; state.snapshotId = ""; state.page = 1;

    $("Report").hidden = true; $("Issues").replaceChildren();

  }

  async function loadBoards(initial = false) {

    resetReport();

    const list = boards[$("Project").value] || [];

    options($("Board"), list.map(b => [b.board_id, b.board_name]), initial ? params.get("board") : "", "Select board");

    if (!$("Board").value && list.length) $("Board").value = list[0].board_id;

    await loadSprints(false, initial);

  }

  async function loadSprints(refresh = false, initial = false) {

    resetReport(); const token = sequence;

    if (!$("Board").value) return;

    message("Loading closed sprint catalogue…");

    try {

      const result = await request("/automation/sprint-viewer/sprints", { project_key: $("Project").value, board_id: $("Board").value, refresh });

      if (token !== sequence) return;

      const list = (result.sprints || []).filter(s => !s.state || s.state === "closed");

      const selected = initial ? params.get("sprint") : $("Sprint").value;

      options($("Sprint"), list.map(s => [s.id || s.sprint_id, s.name || s.sprint_name]), selected, list.length ? null : "No closed sprints available");

      if (list.length) await loadSprint(); else message("No closed sprints available.");

    } catch (error) { fail(error); }

  }

  async function loadSprint(rebuild = false) {

    resetReport(); const token = sequence;

    if (!$("Sprint").value) return;

    urlState(true); message(rebuild ? "Building a new historical revision…" : "Authorizing the selected report…");

    try {

      const result = await request("/automation/sprint-viewer/issues", { board_id: $("Board").value, sprint_id: $("Sprint").value, client_action_id: crypto.randomUUID(), rebuild, snapshot_id: !rebuild && params.get("sprint") === $("Sprint").value ? params.get("snapshot") : null });

      if (token !== sequence) return;

      state.viewId = result.view_id; state.snapshotId = result.snapshot_id;

      if (!state.viewId) throw new Error("This view requires snapshot mode and its worker.");

      await poll(token);

    } catch (error) { fail(error); }

  }

  async function rebuildAnalysis() {

    if (!state.analysis) return loadSprint(true);

    const token = sequence;

    message("Building a candidate revision. The published report remains available below.");

    try {

      const candidate = await request("/automation/sprint-viewer/issues", { board_id: $("Board").value, sprint_id: $("Sprint").value, client_action_id: crypto.randomUUID(), rebuild: true });

      const check = async () => {

        if (token !== sequence) return;

        try {

          const status = await request(`/automation/sprint-viewer/snapshots/${candidate.snapshot_id}/status?view_id=${candidate.view_id}`);

          if (token !== sequence) return;

          if (status.state === "ready" && status.access?.core === "granted") {

            state.viewId = candidate.view_id; state.snapshotId = candidate.snapshot_id; state.evidence = ""; state.page = 1;

            await poll(token);

          } else if (status.state === "failed" || Object.values(status.components || {}).some(c => c.state === "failed")) message("Candidate rebuild failed. The previous published report remains available.");

          else pollTimer = setTimeout(check, 2500);

        } catch (error) { if (error.name !== "AbortError") message(`Candidate rebuild: ${error.message}. Previous report retained.`); }

      };

      await check();

    } catch (error) { if (error.name !== "AbortError") message(error.message); }

  }

  async function poll(token) {

    if (token !== sequence) return;

    try {

      const status = await request(`/automation/sprint-viewer/snapshots/${state.snapshotId}/status?view_id=${state.viewId}`);

      if (token !== sequence) return;

      if (status.access?.core === "denied") { const e = new Error("Report access was denied."); e.status = 403; throw e; }

      if (status.access?.core === "granted") {

        const result = await request(base("analysis"));

        if (token !== sequence) return;

        const changed = state.revision !== result.revision;

        state.analysis = result; state.revision = result.revision; params.set("sprint", $("Sprint").value); params.set("snapshot", state.snapshotId); urlState(true); state.records = result.review_records || [];

        clearTimeout(accessTimer);

        if (result.access_expires_at) accessTimer = setTimeout(() => { const error = new Error("Jira access expired. Select the sprint again to reauthorize."); error.status = 403; fail(error); }, Math.max(0, Date.parse(result.access_expires_at) - Date.now()));

        $("Report").hidden = false;

        render();

        if (changed) { await loadIssues(); await loadSuggestions(); }

        message(result.population_complete ? `Historical revision ${result.revision} · Generation ${result.generation}` : "Core issues are available. Historical analysis is pending or unavailable; missing evidence is not zero.");

      } else message("Import queued. Core issues will appear before enrichment finishes.");

      const terminal = Object.values(status.components || {}).every(c => ["ready", "failed", "unavailable", "cancelled"].includes(c.state));

      if (!terminal || status.access?.core !== "granted" || (status.components?.history?.state === "ready" && status.access?.history === "pending")) pollTimer = setTimeout(() => poll(token), 2000);

    } catch (error) { if (token === sequence) fail(error); }

  }

  function metricCard(id, label) {

    let metric = state.analysis?.metrics[id];

    if (id.startsWith("assigned_")) {

      const person = state.analysis?.sections?.contribution?.find(p => p.identity === state.developer);

      const key = { assigned_completed: "done", assigned_unfinished: "unfinished", assigned_cycle: "cycle_median", assigned_reopened: "reopened" }[id];

      metric = { value: person?.[key] ?? null, availability: person ? "ready" : "unavailable", measured_count: key === "cycle_median" ? person?.cycle_sample || 0 : person?.[key] || 0, eligible_count: person ? person.done + person.unfinished : 0, unit: key === "cycle_median" ? "elapsed_days" : "issues", evidence_ref: person?.evidence?.[key], cohort_label: person ? `Closing / removal assignments: ${person.label}` : "Select a historical developer", time_basis: "close or removal assignment; cycle spans full issue lifecycle", calculation_version: "2.0.0" };

    }

    const card = node("div", null, "sv2-card"); card.append(node("span", label || pretty(id)));

    const value = metric?.value;

    card.append(node("strong", value == null ? "—" : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })}${metric.unit === "percent" ? "%" : ""}`));

    card.append(node("small", metric ? `${metric.availability} · ${metric.measured_count}/${metric.eligible_count} measured · ${pretty(metric.unit)}` : "Unavailable — required evidence is not recorded"));

    if (metric?.reason_codes?.length) card.append(node("small", metric.reason_codes.map(pretty).join("; ")));

    if (metric?.evidence_ref && value != null) card.append(button("View issues", () => evidence(metric.evidence_ref)));

    const details = node("details"); details.append(node("summary", "Definition and time basis"), node("p", metric ? `${metric.cohort_label}; ${metric.time_basis}. Calculation ${metric.calculation_version}. Numerator ${metric.numerator ?? 'N/A'}; denominator ${metric.denominator ?? 'N/A'}.` : "This measure requires additional historical evidence.")); card.append(details);

    return card;

  }

  function render() {

    const data = state.analysis; if (!data) return;

    $("Role").value = state.view; $("Focus").value = state.focus; $("Search").value = state.search;

    $("SprintName").textContent = data.sprint?.name || "Closed sprint";

    const formatDate = value => {
      if (!value) return "Unavailable";
      try { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: data.timezone || "Asia/Kolkata" }).format(new Date(value)); }
      catch { return value; }
    };
    $("Dates").textContent = `${formatDate(data.sprint?.activated_date || data.sprint?.start_date)} → ${formatDate(data.sprint?.complete_date)} · ${data.timezone || "Asia/Kolkata"} · Mapping ${data.mapping_version}${data.sprint?.activated_date ? "" : " · Scheduled start fallback"}${data.sprint?.end_date && data.sprint.end_date !== data.sprint.complete_date ? ` · Scheduled end ${formatDate(data.sprint.end_date)}` : ""}`;

    $("Goal").textContent = data.sprint?.goal ? `Recorded goal: ${data.sprint.goal}` : "Sprint goal is not recorded.";

    $("Assessment").textContent = state.records.find(r => r.kind === "assessment")?.payload.state || "Not assessed";

    const role = data.role_sections[state.view];

    $("RoleHeading").textContent = role.title; $("RoleDescription").textContent = `${role.title} Shared totals always cover the whole authorized sprint.`;

    $("DeveloperLabel").hidden = state.view !== "developer";

    options($("Developer"), (data.developers || []).map(d => [d.id, d.label]), state.developer, "Select developer");

    $("Summary").replaceChildren(...($("Lens").value === "points" ? [metricCard("planned_points", "Planned"), metricCard("plan_completed", "Plan completed · count ratio"), metricCard("delivered_points", "Total completed"), metricCard("unfinished_points", "Unfinished at close"), metricCard("added_points", "Added baseline points")] : [metricCard("planned", "Planned"), metricCard("plan_completed", "Plan completed"), metricCard("completed", "Total completed"), metricCard("unfinished", "Unfinished at close"), metricCard("added", "Scope additions")]));

    $("Summary").lastChild.append(node("small", `Removals: ${data.metrics[$("Lens").value === "points" ? "removed_points" : "removed"]?.value ?? "Unavailable"}`), button("View removals", () => evidence(data.metrics.removed.evidence_ref)));

    $("RoleMetrics").replaceChildren(...role.metrics.map(id => metricCard(id)));

    $("RoleEvidence").replaceChildren();

    role.sections.forEach(title => { $("RoleEvidence").append(node("h3", title)); renderSection(title, $("RoleEvidence")); });

    $("Outcome").replaceChildren(node("p", `Original eligible plan: ${data.metrics.planned.value ?? "Unavailable"}. Already-Done exclusions: ${data.metrics.planned.exclusion_counts?.already_done ?? "Unavailable"}.`));
    const outcomes = node("div", null, "sv2-outcomes");
    [["plan_completed","Completed","#177a68"],["original_unfinished","Unfinished","#986313"],["original_removed","Removed","#59677e"]].forEach(([id,label,color]) => { const m = data.metrics[id]; const count = id === "plan_completed" ? m.numerator : m.value; const segment = button(`${label}: ${count ?? "Unavailable"}`, () => evidence(m.evidence_ref)); segment.style.borderBottom = `5px solid ${color}`; segment.style.flex = String(Math.max(1, count || 0)); outcomes.append(segment); }); $("Outcome").append(outcomes);

    $("Flow").replaceChildren(...["cycle_median", "cycle_p85", "closing_age", "reopened", "blocked_duration"].map(id => metricCard(id)));

    $("Stages").textContent = "Stage durations are available in issue timelines when complete status history is present. Unknown intervals are unavailable.";
    $("Daily").replaceChildren();
    if (data.daily?.availability === "ready") {
      $("Daily").append(node("h3", "Daily scope, Done and WIP"), node("p", data.daily.time_basis));
      const table = node("table"), head = node("tr"); ["Date", "Scope", "Done in scope", "WIP"].forEach(t => head.append(node("th", t))); table.append(head);
      data.daily.samples.forEach(sample => { const tr = node("tr"); [sample.date,sample.scope,sample.done,sample.wip].forEach(value => tr.append(node("td", value ?? "Unavailable"))); table.append(tr); }); const region = node("div", null, "sv2-table-region"); region.append(table); $("Daily").append(region);
    } else $("Daily").append(unavailable("Daily scope/Done/WIP requires validated complete events. No daily values have been fabricated."));

    renderActions(); showTab(false);

  }

  function renderSection(title, target) {

    const sections = state.analysis.sections || {};

    let items = [];

    if (title.includes("contribution")) items = sections.contribution || [];

    else if (title.includes("feature")) items = sections.features || [];

    else if (title.includes("Scope")) { const band = node("div", null, "sv2-leading"); band.append(metricCard("added"), metricCard("removed")); target.append(band); state.records.filter(r => r.kind === "issue_review" && r.payload.scope_reason).forEach(r => target.append(node("p", `Issue ${r.payload.issue_id} · Human scope reason recorded ${r.recorded_at}: ${r.payload.scope_reason}`))); return; }

    else if (title.includes("Work mix")) items = sections.work_mix || [];

    else if (title.includes("acceptance")) {

      const records = state.records.filter(r => r.kind === "issue_review");

      target.append(node("p", `${records.filter(r => r.payload.goal_linked).length} explicitly goal-linked issues; ${records.filter(r => r.payload.acceptance === "Accepted").length} accepted among ${records.length} manually reviewed issues. Current human records, entered after sprint close; not a goal achievement score.`));

      records.forEach(r => target.append(node("p", `Issue ${r.payload.issue_id}: ${r.payload.acceptance} · ${r.recorded_at}`))); return;

    } else if (title.includes("Capacity")) {

      const record = state.records.find(r => r.kind === "context"); target.append(record ? node("p", `${record.payload.note || ""} · Recorded ${record.recorded_at}`) : unavailable("No team capacity or dependency context recorded. Add a note in Retrospective.")); return;

    }

    else if (title.includes("Selected developer")) {

      const person = (sections.contribution || []).find(p => p.identity === state.developer);

      if (person) items = [person];

    } else if (title.includes("action")) { target.append(node("p", `${state.records.filter(r => r.kind === "action" && r.payload.state !== "Done").length} current actions not Done. Review due dates in Retrospective.`)); return; }

    else if (title.includes("Flow")) { target.append(metricCard("cycle_median"), metricCard("closing_age")); return; }

    if (!items.length) { target.append(unavailable("Required evidence has not been recorded or authorized for this revision.")); return; }
    if (!state.analysis.population_complete) target.append(node("p", "Covered historical issues only. The complete sprint population has not been verified; these are partial counts."));

    const table = node("table"); const head = node("tr"); const contribution = title.includes("contribution") || title.includes("Selected developer"); ["Population", "Completed", "Unfinished", "Removed", ...(contribution ? ["Closing scope", "Completed baseline points", "Share of team completions", "Story / Bug / Task"] : [])].forEach(t => head.append(node("th", t))); const thead = node("thead"); thead.append(head); table.append(thead); const body = node("tbody");

    items.forEach(item => { const tr = node("tr"); tr.append(node("td", contribution ? `${item.label} [${item.identity}]` : item.label)); ["done", "unfinished", "removed"].forEach(k => { const td = node("td"); td.append(button(String(item[k] ?? "—"), () => evidence(item.evidence[k]))); tr.append(td); }); if (contribution) [item.closing_scope, `${item.completed_baseline_points ?? "Unavailable"} (${item.estimated_completed_count}/${item.done} estimated)`, item.team_completed_share == null ? "N/A" : `${item.team_completed_share.toFixed(1)}%`, `${item.type_split?.Story || 0} / ${item.type_split?.Bug || 0} / ${item.type_split?.Task || 0}`].forEach(value => tr.append(node("td", value))); body.append(tr); }); table.append(body); const region = node("div", null, "sv2-table-region"); region.append(table); target.append(region);

    if (title.includes("contribution")) target.append(node("p", "Closing/removal assignment is context, not a measure of effort or individual performance. Unassigned identities remain included."));

  }

  async function loadIssues() {

    if (!state.analysis) return;

    const token = ++issueSequence, selected = sequence;

    try {

      const result = await request(`${base("issues")}?${query()}`);

      if (token !== issueSequence || selected !== sequence || result.revision !== state.revision) return;

      $("Issues").replaceChildren();

      const group = $("Group").value;

      let rows = result.issues;

      const groupLabel = r => group === "assignee" ? `${r.assignee?.label || "Unknown"} [${r.assignee?.id || "unknown"}]` : typeof r[group] === "object" ? JSON.stringify(r[group]) : r[group] || "Unknown";

      if (group) rows = [...rows].sort((a, b) => groupLabel(a).localeCompare(groupLabel(b)));

      let lastGroup = null;

      rows.forEach(row => {

        if (group && groupLabel(row) !== lastGroup) { lastGroup = groupLabel(row); const tr = node("tr", null, "sv2-group"), td = node("td", `${lastGroup} · groups on this page`); td.colSpan = 8; tr.append(td); $("Issues").append(tr); }

        const tr = node("tr"), key = node("td"); key.append(button(row.issue_key || row.issue_id, () => drawer(row.issue_id)), node("div", row.summary)); tr.append(key);

        [row.issue_type, row.assignee?.label || "Unknown historical assignment", `${row.origin || "Unavailable"} / ${row.outcome || "Unavailable"}`, row.status || "Unavailable", row.baseline_points ?? "Unavailable", typeof row.feature === "string" ? row.feature : "Unavailable", row.relevant_comment_count ?? "Unavailable"].forEach(value => tr.append(node("td", value)));

        $("Issues").append(tr);

      });

      $("FilterStatus").textContent = `${result.total} matching issues · Focus: ${pretty(state.focus)}${state.evidence ? " · Exact evidence cohort" : ""}${state.search ? ` · Search: ${state.search}` : ""}`;

      $("PageInfo").textContent = `Page ${result.page} of ${Math.max(1, Math.ceil(result.total / 25))}`;

      $("PagePrev").disabled = state.page <= 1; $("PageNext").disabled = state.page * 25 >= result.total;

      if (!rows.length) { const tr = node("tr"), td = node("td", "No issues match these filters."); td.colSpan = 8; tr.append(td); $("Issues").append(tr); }

    } catch (error) { if (selected === sequence) fail(error); }

  }

  function evidence(ref) { ["Feature","Application","IssueType","Status"].forEach(id => $(id).value = ""); state.evidence = ref; state.focus = "all"; state.search = ""; state.page = 1; $("Focus").value = "all"; $("Search").value = ""; urlState(); loadIssues(); $("FilterStatus").scrollIntoView({ block: "center" }); }

  async function drawer(id) {

    try { const token = sequence, result = await request(`${base(`issues/${encodeURIComponent(id)}/timeline`)}?revision=${state.revision}`); if (token !== sequence) return;

      const row = result.issue; $("DrawerContent").replaceChildren(node("h2", `${row.issue_key} · ${row.summary}`), node("p", `Coverage: ${row.coverage}. Basis: ${row.time_basis || "unavailable"}. Start / entry estimate: ${row.baseline_points ?? "Unavailable"}; close / removal: ${row.closing_points ?? "Unavailable"}.`));

      $("DrawerContent").append(node("p", "Summary is observed at collection; boundary status, assignment and estimates require historical coverage."));
      $("DrawerContent").append(node("p", `Sprint-window team comments: ${row.relevant_comment_count ?? "Unavailable"} (${row.comment_coverage || "unavailable"}). Comment volume is context, not performance.`));
      $("DrawerContent").append(node("p", `Cycle: ${row.cycle_days ?? "Unavailable"} elapsed days. Closing age: ${row.closing_age_days ?? "Unavailable"} elapsed days.`), node("h3", "Recorded field events"));

      (row.events || []).forEach(e => $("DrawerContent").append(node("p", `${e.at} · ${e.field}: ${JSON.stringify(e.old)} → ${JSON.stringify(e.new)}`)));

      if (!(row.events || []).length) $("DrawerContent").append(node("p", "No event evidence available in this revision."));

      $("DrawerContent").append(button("Record goal link, acceptance or scope reason", () => { $("Drawer").close(); openEdit("issue_review", `issue:${id}`, { issue_id: String(id), acceptance: "Not recorded", goal_linked: false }); }));

      $("Drawer").showModal();

    } catch (error) { fail(error); }

  }

  async function loadSuggestions() { if (!state.analysis) return; const token = sequence; try { const data = await request(`${base("suggestions")}?revision=${state.revision}`); if (token !== sequence) return; state.suggestions = data.suggestions; renderSuggestions(); } catch (error) { fail(error); } }

  function renderSuggestions() {

    const list = $("Suggestions"); list.replaceChildren();

    const unavailableCount = state.suggestions.filter(s => s.status === "unavailable").length;

    list.append(node("p", `${unavailableCount} rules could not be evaluated. ${!state.suggestions.length ? "Historical rule evidence is unavailable." : ""}`));

    let count = 0;

    state.suggestions.forEach(s => {

      const disposition = state.records.find(r => r.record_key === `observation:${s.id}`)?.payload.state || (state.records.some(r => r.kind === "action" && r.payload.source_evidence === s.id) ? "Action created" : "Open");

      if (s.status !== "matched" || disposition !== $("Disposition").value || ($("Category").value && s.category !== $("Category").value)) return;

      count++; const panel = node("article", null, "sv2-observation");
      if (state.records.some(r => r.payload.source_rule_id === s.rule_id && r.payload.source_evidence !== s.id)) panel.append(node("small", "Updated evidence · previous disposition retained in review history."));
      panel.append(node("h3", `${s.count} ${s.evidence_record_keys ? "actions" : "issues"} · ${s.title}`), node("p", s.prompt));

      panel.append(button(`View ${s.count} ${s.evidence_record_keys ? "actions" : "issues"}`, () => { if (s.evidence_record_keys) { state.tab = "retro"; showTab(); } else evidence(s.id); }), button("Create action", () => openEdit("action", crypto.randomUUID(), { title: s.title, note: s.prompt, source_evidence: s.id, state: "Open" })), button(disposition === "Dismissed" ? "Undo dismissal" : "Dismiss", () => openEdit("disposition", `observation:${s.id}`, { source_evidence: s.id, state: disposition === "Dismissed" ? "Open" : "Dismissed" })));

      const details = node("details"); details.append(node("summary", "Why this appears"), node("p", `${s.rule_id} v${s.rule_version} · ${s.time_basis} · threshold ${s.threshold} · checked ${s.coverage.checked}/${s.coverage.eligible}. ${s.prompt}`)); panel.append(details); list.append(panel);

    });

    if (!count) list.append(node("p", "No observations matched the current filters. This does not assert a healthy sprint."));

    const details = node("details"); details.append(node("summary", "Rule availability")); state.suggestions.filter(s => s.status === "unavailable").forEach(s => details.append(node("p", `${s.rule_id}: ${s.reason_codes.map(pretty).join(", ")}`))); list.append(details);

  }

  function renderActions() {

    $("Actions").replaceChildren();

    state.records.filter(r => ["action", "context", "assessment", "issue_review"].includes(r.kind)).forEach(r => { const box = node("article", null, "sv2-observation"); box.append(node("h3", r.payload.title || pretty(r.kind)), node("p", `${r.payload.state || r.payload.acceptance || ""} · ${r.payload.owner || ""} ${r.payload.due_date || ""}`), node("p", r.payload.note || r.payload.scope_reason || ""), node("small", `Recorded ${r.recorded_at} · author ${r.author_id} · revision ${r.revision}`), button("Edit", () => openEdit(r.kind, r.record_key, r.payload)), button("Audit history", async () => { try { const result = await request(`${base("record-history")}?record_key=${encodeURIComponent(r.record_key)}`); $("DrawerContent").replaceChildren(node("h2", "Human record history")); result.records.forEach(record => $("DrawerContent").append(node("p", `Revision ${record.revision} · ${record.recorded_at} · ${JSON.stringify(record.payload)}`))); $("Drawer").showModal(); } catch (error) { fail(error); } })); $("Actions").append(box); });

    if (!$("Actions").children.length) $("Actions").append(node("p", "No private review records yet."));
    $("Actions").append(node("h3", "Previous sprint actions"));
    const previous = state.analysis.previous_actions || [];
    if (!previous.length) $("Actions").append(node("p", "No previous actions available from authorized reports."));
    previous.forEach(record => { const box = node("article", null, "sv2-observation"); box.append(node("h3", record.payload.title), node("p", `${record.sprint_name} · ${record.payload.state} · Due ${record.payload.due_date}`), button("Follow up", () => openEdit("action", record.record_key, record.payload, record))); $("Actions").append(box); });

  }

  function openEdit(kind, key, initial = {}) {

    const prior = state.records.find(r => r.record_key === key);

    edit = { kind, key, revision: prior?.revision || 0, initial: { ...initial, ...(prior?.payload || {}) }, idem: crypto.randomUUID(), viewId: state.viewId };

    $("EditTitle").textContent = `Record ${pretty(kind)}`; $("EditFields").replaceChildren(); $("EditError").textContent = "";

    const fields = kind === "assessment" ? ["state", "note", "evidence_url"] : kind === "action" ? ["title", "owner", "due_date", "state", "note", "evidence_url"] : kind === "issue_review" ? ["goal_linked", "acceptance", "scope_reason", "evidence_url"] : kind === "disposition" ? ["state", "note"] : ["title", "note", "evidence_url"];

    fields.forEach(name => {

      const label = node("label", pretty(name)); let input;

      const enums = name === "state" ? kind === "assessment" ? ["Not assessed", "Achieved", "Partially achieved", "Not achieved"] : kind === "action" ? ["Open", "In progress", "Done", "Archived"] : ["Open", "Dismissed", "Action created"] : name === "acceptance" ? ["Not recorded", "Accepted", "Pending review", "Rejected", "Not ready"] : null;

      if (enums) { input = node("select"); enums.forEach(v => input.append(new Option(v, v))); }

      else input = node(["note", "scope_reason"].includes(name) ? "textarea" : "input");

      input.name = name; input.value = edit.initial[name] || "";

      if (name === "goal_linked") { input.type = "checkbox"; input.checked = Boolean(edit.initial[name]); }

      else if (name === "due_date") { input.type = "date"; input.required = true; }

      else if (name === "evidence_url") input.type = "url";

      if (kind === "action" && ["title", "owner"].includes(name)) input.required = true;

      if (enums && !input.value) input.value = enums[0]; input.maxLength = ["note", "scope_reason"].includes(name) ? 4000 : 500;

      label.append(input); $("EditFields").append(label);

    }); $("Edit").showModal();

  }

  $("EditForm").addEventListener("submit", async event => {

    event.preventDefault(); const saved = edit; const payload = { ...saved.initial };

    $("EditFields").querySelectorAll("[name]").forEach(input => payload[input.name] = input.type === "checkbox" ? input.checked : input.value);

    try {

      const result = await request(`/automation/sprint-viewer/views/${saved.viewId}/records`, { kind: saved.kind, record_key: saved.key, expected_revision: saved.revision, idempotency_key: saved.idem, payload });

      state.records = state.records.filter(r => r.record_key !== saved.key).concat(result.record); $("Edit").close(); edit = null;
      if (state.analysis) { state.analysis = await request(base("analysis")); state.records = state.analysis.review_records; render(); await loadSuggestions(); }

    } catch (error) { $("EditError").textContent = `${error.message} Your draft is retained.`; }

  });

  $("Drawer").addEventListener("close", () => { drawerSequence++; });
  $("EditCancel").onclick = () => { $("Edit").close(); edit = null; };

  function showTab(write = true) {

    tabs.forEach(tab => { $( `Panel-${tab}`).hidden = tab !== state.tab; const b = $(`Tab-${tab}`); b.setAttribute("aria-selected", String(tab === state.tab)); b.tabIndex = tab === state.tab ? 0 : -1; });

    if (write) urlState();

    if (state.tab === "trends" && state.analysis) { const token = sequence; request(base("trends")).then(data => { if (token === sequence) {

        const box = $("Trends"); box.replaceChildren(node("p", data.note));

        if (data.availability !== "ready") box.append(unavailable("No authorized comparable baseline. Open preceding closed sprint reports to grant access; no automatic imports are started."));

        else {

          box.append(node("p", `Previous ${data.sample_size} comparable sprints · Throughput median ${data.throughput_median}; range ${data.throughput_range.join("–")}; plan completion median ${data.plan_completion_median ?? "Unavailable"}%.`));

          const table = node("table"), head = node("tr"); ["Sprint", "Completed", "Plan completed %", "Added", "Removed", "Cycle days"].forEach(t => head.append(node("th", t))); table.append(head);

          [data.selected, ...data.previous].forEach(s => { const row = node("tr"); [s.name,s.completed,s.plan_completed,s.added,s.removed,s.cycle_median].forEach(v => row.append(node("td", v ?? "Unavailable"))); table.append(row); }); const region = node("div", null, "sv2-table-region"); region.append(table); box.append(region);

        }

      } }).catch(fail); }

  }

  $("Tabs").addEventListener("click", e => { if (e.target.dataset.tab) { state.tab = e.target.dataset.tab; showTab(); } });

  $("Tabs").addEventListener("keydown", e => { const index = tabs.indexOf(state.tab); let next; if (e.key === "ArrowRight") next = (index + 1) % tabs.length; if (e.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length; if (e.key === "Home") next = 0; if (e.key === "End") next = tabs.length - 1; if (next != null) { e.preventDefault(); state.tab = tabs[next]; showTab(); $(`Tab-${state.tab}`).focus(); } });

  $("Role").onchange = () => { state.view = $("Role").value; state.focus = state.analysis.role_sections[state.view].focus; state.evidence = ""; state.search = ""; state.page = 1; urlState(); render(); loadIssues(); };

  $("Developer").onchange = () => { state.developer = $("Developer").value; state.page = 1; state.focus = "developer"; urlState(); render(); loadIssues(); };

  $("Focus").onchange = () => { state.focus = $("Focus").value; state.page = 1; urlState(); loadIssues(); };

  $("Search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.search = $("Search").value; state.page = 1; urlState(); loadIssues(); }, 180); };

  $("Clear").onclick = () => { ["Feature","Application","IssueType","Status"].forEach(id => $(id).value = ""); state.focus = "all"; state.search = ""; state.evidence = ""; state.page = 1; $("Search").value = ""; $("Focus").value = "all"; urlState(); loadIssues(); };

  $("Group").onchange = () => { urlState(); loadIssues(); };
  ["Feature","Application","IssueType","Status","Sort"].forEach(id => $(id).onchange = () => { state.page = 1; urlState(); loadIssues(); }); $("Lens").onchange = render;

  $("PagePrev").onclick = () => { state.page--; loadIssues(); }; $("PageNext").onclick = () => { state.page++; loadIssues(); };

  function clearSelectionFilters() { state.evidence = ""; state.search = ""; state.focus = "all"; state.developer = ""; state.page = 1; ["Feature","Application","IssueType","Status"].forEach(id => $(id).value = ""); }
  $("Project").onchange = () => { clearSelectionFilters(); loadBoards(); }; $("Board").onchange = () => { clearSelectionFilters(); loadSprints(); }; $("Sprint").onchange = () => { clearSelectionFilters(); urlState(); loadSprint(); };

  $("Refresh").onclick = () => loadSprints(true); $("Rebuild").onclick = rebuildAnalysis;

  $("Prev").onclick = () => { if ($("Sprint").selectedIndex < $("Sprint").options.length - 1) { $("Sprint").selectedIndex++; $("Sprint").onchange(); } }; $("Next").onclick = () => { if ($("Sprint").selectedIndex > 0) { $("Sprint").selectedIndex--; $("Sprint").onchange(); } };

  $("Export").onclick = async () => { if (!state.analysis) return; try { const response = await api(`${base("export")}?${query()}`, { signal: controller.signal }); if (!response.ok) { const error = new Error("Export access expired or the revision changed."); error.status = response.status; throw error; } const href = URL.createObjectURL(await response.blob()); const a = node("a"); a.href = href; a.download = "sprint-analysis.csv"; a.click(); setTimeout(() => URL.revokeObjectURL(href), 1000); } catch (error) { fail(error); } };

  $("Assess").onclick = () => openEdit("assessment", "assessment", { state: "Not assessed" }); $("NewAction").onclick = () => openEdit("action", crypto.randomUUID(), { state: "Open" }); $("Context").onclick = () => openEdit("context", "context");

  $("Disposition").onchange = renderSuggestions; $("Category").onchange = renderSuggestions;

  window.addEventListener("popstate", async () => {
    const p = new URLSearchParams(location.search);
    [...params.keys()].forEach(key => params.delete(key)); p.forEach((value,key) => params.set(key,value));
    const changedProject = p.get("project") !== $("Project").value;
    const changedBoard = p.get("board") !== $("Board").value;
    const changedSprint = p.get("sprint") !== $("Sprint").value;
    state.view = roles.includes(p.get("view")) ? p.get("view") : "team";
    state.tab = tabs.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
    state.focus = p.get("focus") || "all"; state.search = p.get("search") || "";
    state.developer = p.get("developer") || ""; state.evidence = p.get("evidence") || ""; state.page = 1;
    Object.entries({ feature: "Feature", application: "Application", issue_type: "IssueType", status: "Status", sort: "Sort", group: "Group" }).forEach(([key,id]) => $(id).value = p.get(key) || (key === "sort" ? "issue_key" : ""));
    if (changedProject || changedBoard) { $("Project").value = p.get("project") || ""; await loadBoards(true); }
    else if (changedSprint) { $("Sprint").value = p.get("sprint") || ""; await loadSprint(); }
    else { render(); loadIssues(); }
  });
  if (params.get("project") && [...$("Project").options].some(o => o.value === params.get("project"))) $("Project").value = params.get("project");

  else if ($("Project").options.length > 1) $("Project").selectedIndex = 1;

  Object.entries({ feature: "Feature", application: "Application", issue_type: "IssueType", status: "Status", sort: "Sort", group: "Group" }).forEach(([key,id]) => { if (params.has(key)) $(id).value = params.get(key); });
  loadBoards(true);

})();
