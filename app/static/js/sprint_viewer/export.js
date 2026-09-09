function xmlText(value) {
  return String(value ?? "")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

function columnName(index) {
  let name = ""; let n = index + 1;
  while (n > 0) { const rem = (n - 1) % 26; name = String.fromCharCode(65 + rem) + name; n = Math.floor((n - 1) / 26); }
  return name;
}

function cell(value, row, column) {
  const ref = `${columnName(column)}${row}`;
  if (typeof value === "number" && Number.isFinite(value)) return `<c r="${ref}"><v>${value}</v></c>`;
  return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlText(value)}</t></is></c>`;
}

function worksheet(rows) {
  const body = rows.map((values, index) => `<row r="${index + 1}">${values.map((value, column) => cell(value, index + 1, column)).join("")}</row>`).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${body}</sheetData></worksheet>`;
}

function crc32(bytes) {
  if (!crc32.table) crc32.table = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k += 1) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1); return c >>> 0; });
  let crc = 0xffffffff; bytes.forEach((byte) => { crc = crc32.table[(crc ^ byte) & 0xff] ^ (crc >>> 8); }); return (crc ^ 0xffffffff) >>> 0;
}
function u16(target, offset, value) { target[offset] = value & 255; target[offset + 1] = (value >>> 8) & 255; }
function u32(target, offset, value) { target[offset] = value & 255; target[offset + 1] = (value >>> 8) & 255; target[offset + 2] = (value >>> 16) & 255; target[offset + 3] = (value >>> 24) & 255; }
function concat(parts) { const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0)); let offset = 0; parts.forEach((part) => { out.set(part, offset); offset += part.length; }); return out; }

function zip(files) {
  const encoder = new TextEncoder(); const locals = []; const centrals = []; let offset = 0;
  files.forEach((file) => {
    const name = encoder.encode(file.name); const data = encoder.encode(file.content); const crc = crc32(data);
    const local = new Uint8Array(30 + name.length); u32(local, 0, 0x04034b50); u16(local, 4, 20); u32(local, 14, crc); u32(local, 18, data.length); u32(local, 22, data.length); u16(local, 26, name.length); local.set(name, 30); locals.push(local, data);
    const central = new Uint8Array(46 + name.length); u32(central, 0, 0x02014b50); u16(central, 4, 20); u16(central, 6, 20); u32(central, 16, crc); u32(central, 20, data.length); u32(central, 24, data.length); u16(central, 28, name.length); u32(central, 42, offset); central.set(name, 46); centrals.push(central); offset += local.length + data.length;
  });
  const end = new Uint8Array(22); u32(end, 0, 0x06054b50); u16(end, 8, files.length); u16(end, 10, files.length); u32(end, 12, centrals.reduce((sum, part) => sum + part.length, 0)); u32(end, 16, offset);
  return concat([...locals, ...centrals, end]);
}

function summaryRows(report) {
  const sprint = report.core.sprint || {}; const metrics = report.metrics || {}; const stats = report.core.stats || {};
  return [
    ["Sprint Metadata", "Metric", "Value"],
    ["Sprint Metadata", "Project Key", report.selection.projectKey],
    ["Sprint Metadata", "Board", report.selection.boardName],
    ["Sprint Metadata", "Board ID", report.selection.boardId],
    ["Sprint Metadata", "Sprint", sprint.name || report.selection.sprintName],
    ["Sprint Metadata", "Sprint ID", report.selection.sprintId],
    ["Sprint Metadata", "Snapshot ID", report.manifest.snapshot_id],
    ["Sprint Metadata", "Generation", report.manifest.generation],
    ["Sprint Metadata", "Access checked at", report.manifest.access_checked_at],
    ["Sprint Metadata", "Ticket values", report.manifest.time_basis?.tickets || ""],
    ["Sprint Metadata", "Metric values", report.manifest.time_basis?.metrics || ""],
    [], ["Totals", "Total issues", report.core.total], ["Totals", "Standard issues", report.core.standard_total], ["Totals", "Total points", report.core.total_sp],
    [], ["Quality Metrics", "Unestimated count", stats.unestimated_count], ["Quality Metrics", "Bug count", stats.bug_count], ["Quality Metrics", "Relevant comments", stats.relevant_comment_count ?? "Unavailable"],
    [], ["Scrum Metrics", "Metric", "Count", "Points", "Percent"],
    ["Scrum Metrics", "Original Commitment", metrics.committed_count, metrics.committed_sp, ""],
    ["Scrum Metrics", "Completed from Commitment", metrics.completed_original_count, metrics.completed_original_sp, metrics.predictability_pct],
    ["Scrum Metrics", "Total Completed", metrics.delivered_count, metrics.delivered_sp, metrics.total_delivery_vs_commitment_pct],
    ["Scrum Metrics", "Carryover", metrics.spillover_count, metrics.spillover_sp, metrics.spill_pct],
    ["Scrum Metrics", "Added Scope", metrics.scope_added_count, metrics.scope_added_sp, metrics.scope_pct],
    ["Scrum Metrics", "Removed Scope", metrics.descope_count, metrics.descope_sp, metrics.removed_scope_pct],
  ];
}

function ticketRows(report) {
  const scopeKeys = new Set(report.metrics?.scope_added_keys || []);
  const rows = [["Developer", "Developer EID", "Issue Key", "Summary", "Type", "Status", "Story Points", "Feature Key", "Relevant Comments", "Data", "Added After Sprint Start"]];
  report.issues.forEach((issue) => rows.push([
    issue.assignee_name || "Unassigned", issue.assignee_eid || "", issue.issue_key || "", issue.summary || "", issue.issue_type || "", issue.status || "", Number.isFinite(Number(issue.story_points)) && issue.story_points !== null ? Number(issue.story_points) : "", issue.feature_key || "", issue.relevant_comment_count ?? "Unavailable", issue.historical_fallback ? "Current fallback" : "Sprint-end", scopeKeys.has(issue.issue_key) ? "Yes" : "No",
  ]));
  return rows;
}

export function buildWorkbookBytes(report) {
  const sheets = [{ name: "Sprint Summary", rows: summaryRows(report) }, { name: "Ticket Details", rows: ticketRows(report) }];
  const workbook = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>${sheets.map((sheet, i) => `<sheet name="${xmlText(sheet.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("")}</sheets></workbook>`;
  const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join("")}</Relationships>`;
  const types = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>${sheets.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("")}</Types>`;
  return zip([
    { name: "[Content_Types].xml", content: types },
    { name: "_rels/.rels", content: "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>" },
    { name: "xl/workbook.xml", content: workbook }, { name: "xl/_rels/workbook.xml.rels", content: rels },
    ...sheets.map((sheet, i) => ({ name: `xl/worksheets/sheet${i + 1}.xml`, content: worksheet(sheet.rows) })),
  ]);
}

export function downloadWorkbook(bytes, sprintName) {
  const blob = new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  const url = URL.createObjectURL(blob); const link = document.createElement("a");
  const name = String(sprintName || "sprint-report").replace(/[^a-z0-9_-]+/gi, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "sprint-report";
  link.href = url; link.download = `${name}-sprint-report.xlsx`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
}
