from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import HiddenField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Regexp


class AddProjectForm(FlaskForm):
    project_key = StringField(
        "Jira Project Key",
        validators=[
            DataRequired(message="Project key is required."),
            Length(min=2, max=32),
            Regexp(
                r"^[A-Za-z_]+$",
                message="Project key can contain only letters and underscore only.",
            ),
        ],
    )
    validate_and_add = SubmitField("Validate & Add Project")


class DeleteProjectForm(FlaskForm):
    delete_project_key = HiddenField(
        validators=[DataRequired(), Length(max=32)])
    delete_project = SubmitField("Delete Project")


class DeleteBoardForm(FlaskForm):
    delete_project_key = HiddenField(
        validators=[DataRequired(), Length(max=32)])
    delete_board_id = HiddenField(validators=[DataRequired(), Length(max=32)])
    delete_board = SubmitField("Delete Board")
