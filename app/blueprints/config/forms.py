"""Compatibility exports for forms moved to feature packages."""

from ...features.settings.integrations.forms import JiraConfigForm, TableauConfigForm
from ...features.settings.projects_boards.forms import (
    AddProjectForm,
    DeleteBoardForm,
    DeleteProjectForm,
)
from ...features.settings.tableau_custom_views.forms import (
    TableauCustomViewDeleteForm,
    TableauCustomViewForm,
)

__all__ = [
    "AddProjectForm",
    "DeleteBoardForm",
    "DeleteProjectForm",
    "JiraConfigForm",
    "TableauConfigForm",
    "TableauCustomViewDeleteForm",
    "TableauCustomViewForm",
]
