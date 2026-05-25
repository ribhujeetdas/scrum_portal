from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


INLINE_SCRIPT_TEMPLATES = [
    "app/templates/automation/rule_copier.html",
    "app/templates/automation/sprint_viewer.html",
    "app/templates/tableau/custom_views.html",
    "app/templates/config/projects_boards.html",
    "app/templates/config/custom_views.html",
]

FEATURE_JS_FILES = [
    "app/static/js/rule_copier.js",
    "app/static/js/sprint_viewer.js",
    "app/static/js/tci_custom_views.js",
    "app/static/js/projects_boards.js",
    "app/static/js/tableau_custom_view_settings.js",
]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_phase4_target_templates_do_not_contain_inline_page_scripts():
    for path in INLINE_SCRIPT_TEMPLATES:
        source = read(path)
        assert "<script>" not in source
        assert "</script>" not in source


def test_phase4_feature_javascript_files_exist_and_are_loaded_by_templates():
    for path in FEATURE_JS_FILES:
        assert (ROOT / path).exists(), path

    assert "js/rule_copier.js" in read("app/templates/automation/rule_copier.html")
    assert "js/sprint_viewer.js" in read("app/templates/automation/sprint_viewer.html")
    assert "js/tci_custom_views.js" in read("app/templates/tableau/custom_views.html")
    assert "js/projects_boards.js" in read("app/templates/config/projects_boards.html")
    assert "js/tableau_custom_view_settings.js" in read("app/templates/config/custom_views.html")


def test_phase4_feature_fetches_use_canonical_api_routes():
    combined = "\n".join(read(path) for path in FEATURE_JS_FILES)

    assert "/api/automation/rule-copier/fetch" in combined
    assert "/api/automation/rule-copier/copy" in combined
    assert "/api/automation/sprint-viewer/sprints" in combined
    assert "/api/automation/sprint-viewer/issues" in combined
    assert "/api/automation/sprint-viewer/metrics" in combined
    assert "/api/reports/tci/link-details" in combined

    legacy_api_paths = [
        "/automation/rule-copier/fetch-rule",
        "/automation/rule-copier/copy-rule",
        "/automation/sprint-viewer/sprints",
        "/automation/sprint-viewer/issues",
        "/automation/sprint-viewer/metrics",
        "/tableau/custom-views/link-details",
    ]
    for legacy_path in legacy_api_paths:
        assert f'"{legacy_path}' not in combined
        assert f"'{legacy_path}" not in combined
        assert f"`{legacy_path}" not in combined


def test_sprint_viewer_report_download_waits_for_metrics():
    template = read("app/templates/automation/sprint_viewer.html")
    script = read("app/static/js/sprint_viewer.js")

    assert "sv-reset-fetch-mode" in template
    assert "sprintViewerFavicon" in template
    assert "Actual Start" in template
    assert "Completed:" not in template
    assert 'id="downloadSprintReportBtn"' in template
    assert "Download Report" in template
    assert "downloadSprintReportBtn" in script
    assert "confirmStartOver" in script
    assert "buildSprintReportWorkbook" in script
    assert "buildXlsxBlob" in script
    assert ".xlsx" in script
    assert "startMetricsRequest" in script
    assert "setReportDownloadReady(false)" in script
    assert "setReportDownloadReady(true)" in script
