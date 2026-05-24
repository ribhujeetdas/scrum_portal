from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField
from wtforms.validators import DataRequired


class TableauCustomViewSelectForm(FlaskForm):
    custom_view_id = SelectField(
        "Select Custom View",
        validators=[DataRequired()],
        choices=[],
    )
    view_details = SubmitField("View Details")
    preview_data = SubmitField("Preview Data")
    download_csv = SubmitField("Download CSV")
