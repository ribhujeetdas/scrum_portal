from __future__ import annotations

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, UserBoard, UserProject


class ProjectBoardTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    LOG_TO_CONSOLE = False
    LOG_FILE = "test-app.log"


def create_project_board_app(tmp_path):
    class TestConfig(ProjectBoardTestConfig):
        LOG_DIR = str(tmp_path)

    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        user = User(
            eid="E123",
            jira_key="JIRAUSER1",
            email="user@wellsfargo.com",
            display_name="Test User",
            active=True,
            deleted=False,
            password_hash="not-used",
        )
        db.session.add(user)
        db.session.commit()
    return app


def login_test_user(client, user_id=1):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def add_project_with_boards(user_id: int = 1, board_ids: tuple[int, ...] = (101,)):
    project = UserProject(user_id=user_id, project_key="ABC", admin_projects=True)
    db.session.add(project)
    db.session.flush()
    for board_id in board_ids:
        db.session.add(
            UserBoard(
                project_id=project.id,
                board_id=board_id,
                board_name=f"Board {board_id}",
                board_type="scrum",
                board_url=f"https://jira.example/boards/{board_id}",
            )
        )
    db.session.commit()
    return project


def test_projects_page_uses_app_modal_instead_of_browser_confirm(tmp_path):
    app = create_project_board_app(tmp_path)
    with app.app_context():
        add_project_with_boards()

    client = app.test_client()
    login_test_user(client)

    response = client.get("/config/projects")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "confirm(" not in html
    assert "deleteConfirmModal" in html
    assert "Delete" in html
    assert "Cancel" in html


def test_empty_project_key_post_redirects_with_toast_message(tmp_path):
    app = create_project_board_app(tmp_path)
    client = app.test_client()
    login_test_user(client)

    response = client.post(
        "/config/projects",
        data={"project_key": "", "validate_and_add": "Validate & Add Project"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/settings/projects-boards" in response.headers["Location"]

    follow = client.get("/config/projects")
    html = follow.get_data(as_text=True)

    assert "Project key is required." in html
    assert "portal-toast" in html
    assert "text-danger small" not in html


def test_deleting_last_board_deletes_parent_project(tmp_path):
    app = create_project_board_app(tmp_path)
    with app.app_context():
        add_project_with_boards(board_ids=(101,))

    client = app.test_client()
    login_test_user(client)

    response = client.post(
        "/config/projects",
        data={
            "delete_project_key": "ABC",
            "delete_board_id": "101",
            "delete_board": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        assert UserProject.query.filter_by(user_id=1, project_key="ABC").first() is None
        assert UserBoard.query.count() == 0


def test_deleting_one_of_multiple_boards_keeps_parent_project(tmp_path):
    app = create_project_board_app(tmp_path)
    with app.app_context():
        add_project_with_boards(board_ids=(101, 202))

    client = app.test_client()
    login_test_user(client)

    response = client.post(
        "/config/projects",
        data={
            "delete_project_key": "ABC",
            "delete_board_id": "101",
            "delete_board": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        project = UserProject.query.filter_by(user_id=1, project_key="ABC").first()
        assert project is not None
        remaining_board_ids = [board.board_id for board in project.boards]
        assert remaining_board_ids == [202]
