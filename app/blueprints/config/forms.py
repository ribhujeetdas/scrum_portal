# app/blueprints/config/forms.py
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length

from ...features.settings.projects_boards.forms import (
    AddProjectForm,
    DeleteBoardForm,
    DeleteProjectForm,
)
from ...features.settings.tableau_custom_views.forms import (
    TableauCustomViewDeleteForm,
    TableauCustomViewForm,
)


class JiraConfigForm(FlaskForm):
    jira_pat = PasswordField(
        "Enterprise Agile Jira PAT",
        validators=[DataRequired(message="Token is required."), Length(max=56)],
    )
    validate_and_save = SubmitField("Validate & Save Token")


class TableauConfigForm(FlaskForm):
    tableau_pat_name = StringField(
        "Tableau PAT Name",
        validators=[DataRequired(message="PAT name is required."), Length(max=128)],
    )
    tableau_pat_secret = PasswordField(
        "Tableau PAT Secret",
        validators=[DataRequired(message="PAT secret is required."), Length(max=256)],
    )
    tableau_validate_and_save = SubmitField("Validate & Save Tableau PAT")


__all__ = [
    "AddProjectForm",
    "DeleteBoardForm",
    "DeleteProjectForm",
    "JiraConfigForm",
    "TableauConfigForm",
    "TableauCustomViewDeleteForm",
    "TableauCustomViewForm",
]
