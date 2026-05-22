from flask import Blueprint

tableau_custom_views_bp = Blueprint(
    "tableau_custom_views", __name__, url_prefix="/tableau")

from . import routes  # noqa: F401
