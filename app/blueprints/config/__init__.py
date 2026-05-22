from . import routes
from flask import Blueprint

config_bp = Blueprint("config", __name__, url_prefix="/config")
