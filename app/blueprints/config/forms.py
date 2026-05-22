# app/blueprints/config/forms.py
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import PasswordField, SubmitField, StringField, HiddenField, SelectField
from wtforms.validators import DataRequired, Length, Regexp


class JiraConfigForm(FlaskForm):
    jira_pat = PasswordField(
        "Enterprise Agile Jira PAT",
        validators=[DataRequired(
            message="Token is required."), Length(max=56)],
    )
    validate_and_save = SubmitField("Validate & Save Token")


class TableauConfigForm(FlaskForm):
    tableau_pat_name = StringField(
        "Tableau PAT Name",
        validators=[DataRequired(
            message="PAT name is required."), Length(max=128)],
    )
    tableau_pat_secret = PasswordField(
        "Tableau PAT Secret",
        validators=[DataRequired(
            message="PAT secret is required."), Length(max=256)],
    )
    tableau_validate_and_save = SubmitField("Validate & Save Tableau PAT")


class AddProjectForm(FlaskForm):
    project_key = StringField(
        "Jira Project Key",
        validators=[
            DataRequired(message="Project key is required."),
            Length(min=2, max=32),
            Regexp(
                r"^[A-Za-z_]+$", message="Project key can contain only letters and underscore only."),
        ],
    )
    validate_and_add = SubmitField("Validate & Add Project")


class TableauCustomViewForm(FlaskForm):
    # NEW: Mandatory Epic Key mapping (from DB)
    epic_key = SelectField(
        "Map to Epic Key",
        validators=[DataRequired(message="Epic key is required.")],
        choices=[],  # populated from DB in routes.py
    )

    tableau_custom_view_id = StringField(
        "Tableau Custom View ID",
        validators=[DataRequired(
            message="Custom View ID is required."), Length(max=64)],
    )

    save_tableau_custom_view = SubmitField("Save Custom View")


class TableauCustomViewDeleteForm(FlaskForm):
    delete_custom_view_id = HiddenField(validators=[DataRequired()])
    delete_tableau_custom_view = SubmitField("Delete")


class DeleteProjectForm(FlaskForm):
    delete_project_key = HiddenField(
        validators=[DataRequired(), Length(max=32)])
    delete_project = SubmitField("Delete Project")


class DeleteBoardForm(FlaskForm):
    delete_project_key = HiddenField(
        validators=[DataRequired(), Length(max=32)])
    delete_board_id = HiddenField(validators=[DataRequired(), Length(max=32)])
    delete_board = SubmitField("Delete Board")
