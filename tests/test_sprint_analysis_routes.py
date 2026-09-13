from datetime import UTC, datetime, timedelta
import uuid

from cryptography.fernet import Fernet
import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, UserProject, UserBoard, UserBoardSprint
from app.features.automation.sprint_viewer.models import ReportView, SprintComponent, SprintComponentRevision
from app.features.automation.sprint_viewer.repository import get_or_create_snapshot
from app.features.automation.sprint_viewer.analysis.metrics import calculate


@pytest.fixture
def analysis_app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = 'test-secret'
        WTF_CSRF_ENABLED = False
        SESSION_COOKIE_SECURE = False
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{(tmp_path / "v2.db").as_posix()}'
        FERNET_KEY = Fernet.generate_key().decode()
        JIRA_BASE_URL = 'https://jira.example'
        JIRA_SOURCE_ID = 'v2-test'
        SPRINT_VIEWER_MODE = 'snapshot'
        SPRINT_VIEWER_V2_ENABLED = True
        LOG_TO_CONSOLE = False
        LOG_DIR = str(tmp_path / 'logs')
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        user = User(eid='TEST1', email='test@example.com', display_name='Test', password_hash='x', jira_pat_enc=b'placeholder')
        user.set_password('Password12345')
        db.session.add(user); db.session.flush()
        user_id = user.id
        project = UserProject(user_id=user.id, project_key='TEST', admin_projects=True)
        db.session.add(project); db.session.flush()
        db.session.add(UserBoard(project_id=project.id, board_id=10, board_name='Test board', board_type='scrum'))
        db.session.add(UserBoardSprint(user_id=user.id, board_id=10, sprint_id=42, sprint_name='Closed sprint', sprint_state='closed', start_date='2026-01-05T00:00:00Z', complete_date='2026-01-15T00:00:00Z'))
        db.session.flush()
        scope, snapshot, _ = get_or_create_snapshot(user, 10, 42)
        history = SprintComponent.query.filter_by(snapshot_id=snapshot.id, component_key='history').one()
        revision = SprintComponentRevision(component_id=history.id, revision=1, state='ready')
        db.session.add(revision); db.session.flush()
        row = dict(issue_id='1', issue_key='TEST-1', summary='=Dangerous spreadsheet formula', issue_type='Story',
                   origin='original', outcome='unfinished', coverage='ready', eligible=True, baseline_points=3,
                   assignee={'id': 'key:a', 'label': 'Developer A'}, status='review', events=[])
        data = calculate([row], population_complete=True, revision=str(revision.id))
        data.update(rows=[row], suggestions=[], mapping_version='test', calendar_version='test')
        revision.output = {'analysis_v2': data}; history.state = 'ready'; history.published_revision_id = revision.id
        view = ReportView(user_id=user.id, scope_id=scope.id, snapshot_id=snapshot.id, client_action_nonce=str(uuid.uuid4()),
                          expires_at=datetime.now(UTC)+timedelta(minutes=5), access_state={'core': 'granted', 'history': 'granted', 'metrics': 'granted'}, verified_revisions={'history': revision.id})
        db.session.add(view); db.session.commit()
        view_id = view.id
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id); session['_fresh'] = True
    yield app, client, view_id
    with app.app_context():
        db.session.remove(); db.engine.dispose()


def test_analysis_evidence_export_and_revisions(analysis_app):
    _, client, view = analysis_app
    base = f'/automation/sprint-viewer/views/{view}'
    response = client.get(base+'/analysis')
    assert response.status_code == 200
    data = response.json
    assert len(data['role_sections']) == 5
    ref = data['metrics']['unfinished']['evidence_ref']
    issues = client.get(base+'/issues', query_string={'evidence': ref, 'revision': data['revision']}).json
    assert issues['total'] == 1
    assert client.get(base+'/issues?evidence=forged').status_code == 400
    assert client.get(base+'/issues?revision=forged').status_code == 409
    csv = client.get(base+'/export', query_string={'evidence': ref}).text
    assert "'=Dangerous" in csv and 'TEST-1' in csv


def test_expired_grant_blocks_analysis_and_export(analysis_app):
    app, client, view = analysis_app
    with app.app_context():
        db.session.get(ReportView, view).expires_at = datetime.now(UTC)-timedelta(seconds=1)
        db.session.commit()
    for operation in ('analysis', 'issues', 'export', 'trends'):
        assert client.get(f'/automation/sprint-viewer/views/{view}/{operation}').status_code == 403


def test_reviews_idempotency_conflict_and_validation(analysis_app):
    _, client, view = analysis_app
    url = f'/automation/sprint-viewer/views/{view}/records'
    body = dict(kind='action', record_key='action-1', expected_revision=0, idempotency_key='request-1', payload={'title':'Follow up', 'owner':'Team', 'due_date':'2026-09-20', 'state':'Open'})
    assert client.post(url, json=body).json['record']['revision'] == 1
    assert client.post(url, json=body).json['record']['revision'] == 1
    assert client.post(url, json={**body, 'idempotency_key':'request-2'}).status_code == 409
    body['payload']['due_date'] = 'bad-date'
    assert client.post(url, json={**body, 'idempotency_key':'request-3'}).status_code == 400


def test_closed_only_and_rendered_shell(analysis_app):
    app, client, view = analysis_app
    text = client.get('/automation/sprint-viewer').text
    assert 'Past sprint analysis' in text and 'View as' in text
    assert 'Active sprint' not in text
    with app.app_context():
        UserBoardSprint.query.filter_by(sprint_id=42).one().sprint_state='active'
        db.session.commit()
    response = client.post('/automation/sprint-viewer/issues', json={'board_id':10, 'sprint_id':42})
    assert response.status_code == 400 and response.json['error']['code'] == 'sprint_not_closed'


def test_v2_rendered_roles_drilldown_review_and_mobile(page, analysis_app, tmp_path):
    import json
    import threading
    from werkzeug.serving import make_server
    app, _, view = analysis_app
    with app.app_context():
        snapshot = db.session.get(ReportView, view).snapshot_id
    server = make_server('127.0.0.1', 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/automation/sprint-viewer/sprints', lambda route: route.fulfill(json={'ok':True, 'sprints':[{'id':42,'name':'Closed sprint','state':'closed'}]}))
    page.route('**/automation/sprint-viewer/issues', lambda route: route.fulfill(json={'ok':True,'view_id':view,'snapshot_id':snapshot}))
    page.route('**/snapshots/*/status?*', lambda route: route.fulfill(json={'ok':True,'access':{'core':'granted','history':'granted'},'components':{'core':{'state':'ready'},'history':{'state':'ready'}}}))
    try:
        page.goto(origin+'/auth/login')
        page.locator('input[name="identifier"]').fill('test@example.com')
        page.locator('input[name="password"]').fill('Password12345')
        page.locator('button[type="submit"], input[type="submit"]').first.click()
        page.goto(origin+'/automation/sprint-viewer')
        page.locator('#svIssues button').first.wait_for()
        assert 'Past sprint analysis' in page.title()
        assert 'Asia/Kolkata' in page.locator('#svDates').inner_text()
        shared = page.locator('#svSummary').inner_text()
        for role in ('developer','po','scrum','manager','team'):
            page.select_option('#svRole', role)
            assert page.locator('#svSummary').inner_text() == shared
        page.locator('#svSummary button').nth(3).click()
        page.locator('#svIssues button').first.click()
        page.locator('#svDrawer').wait_for(state='visible')
        assert page.locator('#svDrawer').is_visible()
        page.keyboard.press('Escape')
        assert not page.locator('#svDrawer').is_visible()
        page.locator('#svAssess').click()
        assert page.locator('#svEdit select').input_value() == 'Not assessed'
        page.select_option('#svEdit select', 'Partially achieved')
        page.locator('#svEditForm button[type="submit"]').click()
        page.wait_for_function("document.getElementById('svAssessment').textContent === 'Partially achieved'")
        page.locator('#svTab-retro').click()
        page.locator('#svNewAction').click()
        page.locator('#svEdit [name="title"]').fill('Follow up review')
        page.locator('#svEdit [name="owner"]').fill('Team')
        page.locator('#svEdit [name="due_date"]').fill('2026-09-20')
        page.locator('#svEditForm button[type="submit"]').click()
        page.get_by_role('heading', name='Follow up review').wait_for()
        page.locator('#svTab-overview').click()
        page.set_viewport_size({'width':1440,'height':1000})
        page.screenshot(path=str(tmp_path/'v2-desktop.png'), full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(tmp_path/'v2-mobile.png'), full_page=True)
        assert page.locator('#sprintViewerV2').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        assert not errors
    finally:
        page.goto('about:blank'); server.shutdown(); thread.join(timeout=5)


def test_v2_worker_publishes_normalized_history_and_windowed_comments(analysis_app, monkeypatch):
    from app.core.dependencies import crypto_service
    from app.features.automation.sprint_viewer import jobs
    from app.features.automation.sprint_viewer.models import BackgroundJob
    from app.features.automation.sprint_viewer.repository import published_output
    from app.services.sprint_viewer_service import SprintViewerService
    from copy import deepcopy
    app, _, _ = analysis_app
    raw = {'id':'2','key':'TEST-2','fields':{'summary':'Worker fixture','created':'2026-01-01T00:00:00Z',
           'customfield_10106':5,'customfield_10104':[{'id':43}], 'customfield_11700':{'id':'app','value':'Application'},
           'customfield_10100':'F-1','status':{'id':'done','name':'Done'},'issuetype':{'name':'Story','subtask':False},
           'assignee':{'key':'A','name':'A','displayName':'Developer A'}},
           'changelog':{'total':2,'histories':[
               {'id':'h1','created':'2026-01-10T00:00:00Z','items':[{'fieldId':'status','from':'doing','to':'done','fromString':'Doing','toString':'Done'}]},
               {'id':'h2','created':'2026-01-20T00:00:00Z','items':[{'fieldId':'customfield_10106','from':'3','to':'5','fromString':'3','toString':'5'}]}]}}
    class Client:
        def get_json(self, path, **kwargs):
            if '/board/' in path:
                return {'values':[{'id':43,'state':'closed'}],'total':1,'startAt':0,'isLast':True}
            if path.endswith('/comment'):
                return {'comments':[],'total':0,'startAt':0}
            return deepcopy(raw)
    service = SprintViewerService('https://jira.example', http_client=Client())
    monkeypatch.setattr(jobs, 'sprint_viewer_service', lambda: service)
    monkeypatch.setattr(service, 'fetch_all_issues_for_sprint', lambda *args: {'issues':[deepcopy(raw)],'total':1})
    monkeypatch.setattr(service, '_aggregate_by_jql_with_client', lambda *args: {'count':1,'sp':5,'memberships':[{'issue_id':'2','issue_key':'TEST-2','story_points':5}]})
    monkeypatch.setattr(service, '_fetch_all_comments_for_issue', lambda *args: [
        {'id':str(i),'author':{'key':'A'},'created':date} for i,date in enumerate(['2026-01-01T00:00:00Z','2026-01-08T00:00:00Z','2026-01-20T00:00:00Z'])])
    with app.app_context():
        user = User.query.first(); user.jira_pat_enc = crypto_service().encrypt('synthetic-test-token')
        BackgroundJob.query.update({'state':'succeeded'})
        db.session.add(UserBoardSprint(user_id=user.id, board_id=10, sprint_id=43, sprint_name='Worker sprint', sprint_state='closed',start_date='2026-01-05T00:00:00Z',complete_date='2026-01-15T00:00:00Z'))
        db.session.flush()
        _, snapshot, _ = get_or_create_snapshot(user,10,43)
        snapshot.sprint_metadata = {**snapshot.sprint_metadata, 'analysis_mapping':{'mapping_version':'test','fields':{
            'points':{'field_id':'customfield_10106','parser_kind':'number','validation_status':'validated'},
            'membership':{'field_id':'customfield_10104','parser_kind':'sprints','validation_status':'validated'}}},
            'analysis_config':{'population_discovery_validated':True,'known_status_ids':['doing','done'],'done_status_ids':['done'],'active_status_ids':['doing']}}
        db.session.commit()
        owner = str(uuid.uuid4()); epoch = jobs.acquire_leadership(owner)
        for _ in range(20):
            job = jobs.claim_job(owner,epoch,'core') or jobs.claim_job(owner,epoch,'enrichment')
            if job is None:
                BackgroundJob.query.filter_by(state='retry_wait').update({'available_at':datetime.now(UTC)-timedelta(seconds=1)})
                db.session.commit()
                job = jobs.claim_job(owner,epoch,'core') or jobs.claim_job(owner,epoch,'enrichment')
            if job is None: break
            jobs.run_job(job,owner,epoch)
        history = published_output(snapshot.id,'history')[1].output
        assert history['analysis_v2']['metrics']['planned_points']['value'] == 3
        assert history['analysis_v2']['rows'][0]['outcome'] == 'done'
        assert published_output(snapshot.id,'comments')[1].output['issues']['2']['relevant_comment_count'] == 1


def test_additive_migration_from_prior_schema_preserves_snapshot(analysis_app):
    from sqlalchemy import text, inspect
    app, _, view_id = analysis_app
    # Only this disposable fixture database is changed to the exact prior table set.
    with app.app_context():
        snapshot_id = db.session.get(ReportView, view_id).snapshot_id
        db.session.remove()
        with db.engine.begin() as connection:
            connection.execute(text('DROP TABLE sprint_review_records'))
            connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
            connection.execute(text("INSERT INTO alembic_version VALUES ('b27d5f8a9c02')"))
    runner = app.test_cli_runner()
    upgrade = runner.invoke(args=['setup-db','--apply'])
    assert upgrade.exit_code == 0, upgrade.output
    with app.app_context():
        assert 'sprint_review_records' in inspect(db.engine).get_table_names()
        assert db.session.get(ReportView, view_id).snapshot_id == snapshot_id
