# app/blueprints/automation/routes.py
from __future__ import annotations

from flask_login import login_required

from ...features.automation.rule_copier import routes as rule_copier_feature
from ...features.automation.sprint_viewer import routes as sprint_viewer_feature
from . import automation_bp


@automation_bp.route("/rule-copier", methods=["GET"])
@login_required
def rule_copier_page():
    return rule_copier_feature.rule_copier_page()


@automation_bp.route("/rule-copier/fetch-rule", methods=["POST"])
@login_required
def fetch_rule():
    return rule_copier_feature.fetch_rule()


@automation_bp.route("/rule-copier/copy-rule", methods=["POST"])
@login_required
def copy_rule():
    return rule_copier_feature.copy_rule()


@automation_bp.route("/sprint-viewer", methods=["GET"])
@login_required
def sprint_viewer_page():
    return sprint_viewer_feature.sprint_viewer_page()


@automation_bp.route("/sprint-viewer/sprints", methods=["POST"])
@login_required
def sprint_viewer_get_sprints():
    return sprint_viewer_feature.sprint_viewer_get_sprints()


@automation_bp.route("/sprint-viewer/issues", methods=["POST"])
@login_required
def sprint_viewer_fetch_issues():
    return sprint_viewer_feature.sprint_viewer_fetch_issues()


@automation_bp.route("/sprint-viewer/metrics", methods=["POST"])
@login_required
def sprint_viewer_fetch_metrics():
    return sprint_viewer_feature.sprint_viewer_fetch_metrics()


@automation_bp.route("/sprint-viewer/snapshots/<snapshot_id>/status", methods=["GET"])
@login_required
def sprint_snapshot_status(snapshot_id):
    return sprint_viewer_feature.sprint_snapshot_status(snapshot_id)


@automation_bp.route("/sprint-viewer/snapshots/<snapshot_id>/issues", methods=["GET"])
@login_required
def sprint_snapshot_issues(snapshot_id):
    return sprint_viewer_feature.sprint_snapshot_issues(snapshot_id)


@automation_bp.route("/sprint-viewer/snapshots/<snapshot_id>/components/<component_key>", methods=["GET"])
@login_required
def sprint_snapshot_component(snapshot_id, component_key):
    return sprint_viewer_feature.sprint_snapshot_component(snapshot_id, component_key)


@automation_bp.route("/sprint-viewer/snapshots/<snapshot_id>/retry", methods=["POST"])
@login_required
def sprint_snapshot_retry(snapshot_id):
    return sprint_viewer_feature.sprint_snapshot_retry(snapshot_id)


@automation_bp.route("/sprint-viewer/snapshots/<snapshot_id>/authorize", methods=["POST"])
@login_required
def sprint_snapshot_authorize(snapshot_id):
    return sprint_viewer_feature.sprint_snapshot_authorize(snapshot_id)


@automation_bp.route("/sprint-viewer/snapshots/<snapshot_id>/export-manifest", methods=["GET"])
@login_required
def sprint_snapshot_export_manifest(snapshot_id):
    return sprint_viewer_feature.sprint_snapshot_export_manifest(snapshot_id)
