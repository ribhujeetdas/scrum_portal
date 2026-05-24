from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import HiddenField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class TableauCustomViewForm(FlaskForm):
    epic_key = SelectField(
        "Map to Epic Key",
        validators=[DataRequired(message="Epic key is required.")],
        choices=[],
    )

    tableau_custom_view_id = StringField(
        "Tableau Custom View ID",
        validators=[
            DataRequired(message="Custom View ID is required."),
            Length(max=64),
        ],
    )

    save_tableau_custom_view = SubmitField("Save Custom View")


class TableauCustomViewDeleteForm(FlaskForm):
    delete_custom_view_id = HiddenField(validators=[DataRequired()])
    delete_tableau_custom_view = SubmitField("Delete")
