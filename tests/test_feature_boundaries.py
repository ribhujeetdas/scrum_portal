from __future__ import annotations


def test_projects_boards_feature_exports_page_handler_and_forms():
    from app.blueprints.config.forms import AddProjectForm as CompatAddProjectForm
    from app.features.settings.projects_boards.forms import AddProjectForm
    from app.features.settings.projects_boards.routes import projects_page

    assert AddProjectForm is CompatAddProjectForm
    assert callable(projects_page)


def test_tableau_custom_view_settings_feature_exports_page_handler_and_forms():
    from app.blueprints.config.forms import (
        TableauCustomViewDeleteForm as CompatDeleteForm,
        TableauCustomViewForm as CompatCustomViewForm,
    )
    from app.features.settings.tableau_custom_views.forms import (
        TableauCustomViewDeleteForm,
        TableauCustomViewForm,
    )
    from app.features.settings.tableau_custom_views.routes import custom_views_page

    assert TableauCustomViewForm is CompatCustomViewForm
    assert TableauCustomViewDeleteForm is CompatDeleteForm
    assert callable(custom_views_page)


def test_rule_copier_feature_exports_route_handlers():
    from app.features.automation.rule_copier.routes import (
        copy_rule,
        fetch_rule,
        rule_copier_page,
    )

    assert callable(rule_copier_page)
    assert callable(fetch_rule)
    assert callable(copy_rule)


def test_sprint_viewer_feature_exports_route_handlers():
    from app.features.automation.sprint_viewer.routes import (
        sprint_viewer_fetch_issues,
        sprint_viewer_fetch_metrics,
        sprint_viewer_get_sprints,
        sprint_viewer_page,
    )

    assert callable(sprint_viewer_page)
    assert callable(sprint_viewer_get_sprints)
    assert callable(sprint_viewer_fetch_issues)
    assert callable(sprint_viewer_fetch_metrics)


def test_tci_feature_exports_route_handlers_and_csv_preview():
    from app.features.reports.tci.forms import TableauCustomViewSelectForm
    from app.features.reports.tci.routes import (
        custom_view_link_details,
        custom_views_page,
        parse_csv_preview,
    )

    assert TableauCustomViewSelectForm.__name__ == "TableauCustomViewSelectForm"
    assert callable(custom_views_page)
    assert callable(custom_view_link_details)
    assert callable(parse_csv_preview)
