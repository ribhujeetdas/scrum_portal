from . import routes
from flask import Blueprint

automation_bp = Blueprint("automation", __name__, url_prefix="/automation")
