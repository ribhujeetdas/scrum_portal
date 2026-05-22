from wtforms.fields import SubmitField
from flask import Flask

from app.blueprints.tableau_custom_views.forms import TableauCustomViewSelectForm


def test_tableau_preview_and_download_actions_are_submit_fields():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"

    with app.test_request_context("/"):
        form = TableauCustomViewSelectForm(meta={"csrf": False})

    assert isinstance(form.preview_data, SubmitField)
    assert isinstance(form.download_csv, SubmitField)
