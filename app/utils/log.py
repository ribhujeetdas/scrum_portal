import logging
from flask import current_app, has_app_context


def _get_logger():
    """
    Returns Flask app logger if available, else a module-level logger.
    Safe everywhere.
    """
    if has_app_context():
        return current_app.logger
    return logging.getLogger("app")


class LogProxy:
    def debug(self, msg, *args, **kwargs):
        _get_logger().debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        _get_logger().info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        _get_logger().warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        _get_logger().error(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        # logs stack trace automatically
        _get_logger().exception(msg, *args, **kwargs)


log = LogProxy()
