# Code Review Graph

Use this as the review map for changes in this project. Start at the edited
node, then follow outgoing edges to identify behavior, data, tests, and routes
that should be checked.

## Review Order

1. App setup and route registration: `app/__init__.py`, `app/blueprints/**`.
2. Compatibility aliases: `app/blueprints/aliases/routes.py`.
3. Feature handlers: `app/features/**/routes.py` and adjacent forms.
4. Shared infrastructure: `app/core/**`, `app/extensions.py`, `app/logging_conf.py`.
5. Services and external API clients: `app/services/**`.
6. Persistence model and migrations: `app/models.py`, `migrations/versions/**`.
7. Templates and static assets: `app/templates/**`, `app/static/**`.
8. Focused tests for touched nodes, then route/session smoke coverage.

## Runtime Graph

```mermaid
flowchart TD
    WSGI["wsgi.py"] --> AppFactory["app.create_app"]
    AppFactory --> Extensions["extensions: db, login, csrf, migrate"]
    AppFactory --> Logging["logging_conf + request correlation"]
    AppFactory --> ConfigValidation["core.config_validation"]
    AppFactory --> Blueprints["registered blueprints"]
    AppFactory --> LegacyHeaders["legacy successor/deprecation headers"]
    AppFactory --> ErrorHandlers["403/404/500 handlers"]

    Blueprints --> AuthBP["auth blueprint"]
    Blueprints --> MainBP["main blueprint"]
    Blueprints --> ProfileBP["profile blueprint"]
    Blueprints --> ConfigBP["config blueprint"]
    Blueprints --> AutomationBP["automation blueprint"]
    Blueprints --> TableauBP["tableau_custom_views blueprint"]
    Blueprints --> AliasBP["aliases blueprint"]

    AliasBP --> CanonicalUserRoutes["canonical user routes"]
    AliasBP --> CanonicalApiRoutes["canonical API routes"]
    CanonicalUserRoutes --> ExistingViewFns["existing view functions"]
    CanonicalApiRoutes --> ExistingViewFns
```

## Route And Feature Graph

```mermaid
flowchart LR
    subgraph Canonical["canonical routes"]
        Dashboard["/dashboard"]
        SettingsIntegrations["/settings/integrations"]
        SettingsProjects["/settings/projects-boards"]
        SettingsTableau["/settings/tableau-custom-views"]
        RulePage["/automation/rule-copier"]
        SprintPage["/automation/sprint-viewer"]
        TciPage["/reports/tci"]
        RuleApi["/api/automation/rule-copier/*"]
        SprintApi["/api/automation/sprint-viewer/*"]
        TciApi["/api/reports/tci/link-details"]
        SessionApi["/api/session/*, /api/client-log"]
    end

    subgraph Compatibility["legacy routes"]
        Home["/home"]
        LoginLegacy["/login, /signup, /forgot-password"]
        ConfigLegacy["/config/*"]
        TableauLegacy["/tableau/custom-views*"]
        AutomationLegacy["/automation/* legacy API paths"]
        SessionLegacy["/session/*, /client-log"]
    end

    Home --> Dashboard
    LoginLegacy --> AuthRoutes["app/blueprints/auth/routes.py"]
    ConfigLegacy --> ConfigRoutes["app/blueprints/config/routes.py"]
    TableauLegacy --> TableauRoutes["app/blueprints/tableau_custom_views/routes.py"]
    AutomationLegacy --> AutomationRoutes["app/blueprints/automation/routes.py"]
    SessionLegacy --> MainRoutes["app/blueprints/main/routes.py"]

    Dashboard --> MainRoutes
    SessionApi --> MainRoutes
    SettingsIntegrations --> ConfigRoutes
    SettingsProjects --> ProjectsFeature["features/settings/projects_boards"]
    SettingsTableau --> TableauSettingsFeature["features/settings/tableau_custom_views"]
    RulePage --> RuleFeature["features/automation/rule_copier"]
    RuleApi --> RuleFeature
    SprintPage --> SprintFeature["features/automation/sprint_viewer"]
    SprintApi --> SprintFeature
    TciPage --> TciFeature["features/reports/tci"]
    TciApi --> TciFeature

    ConfigRoutes --> Integrations["Jira/Tableau PAT settings"]
    ConfigRoutes --> ProjectsFeature
    ConfigRoutes --> TableauSettingsFeature
    AutomationRoutes --> RuleFeature
    AutomationRoutes --> SprintFeature
    TableauRoutes --> TciFeature
```

## Service And Data Graph

```mermaid
flowchart TD
    subgraph FeatureHandlers["feature and blueprint handlers"]
        Auth["auth routes"]
        Integrations["settings integrations"]
        Projects["settings projects_boards"]
        TableauSettings["settings tableau_custom_views"]
        RuleCopier["automation rule_copier"]
        SprintViewer["automation sprint_viewer"]
        TCI["reports tci"]
    end

    subgraph Core["shared core"]
        Dependencies["core.dependencies factories"]
        JsonApi["core.api json_ok/json_error"]
        ErrorLogging["core.error_logging"]
        HttpClient["core.http_client.ExternalHttpClient"]
        PatCache["core.jira_pat_validation"]
        DB["extensions.db"]
    end

    subgraph Services["services"]
        Crypto["CryptoService"]
        Jira["JiraService"]
        JiraProjects["JiraProjectsService"]
        RuleSvc["RuleCopierService"]
        SprintSvc["SprintViewerService"]
        TableauSvc["TableauService"]
        JiraLinks["JiraIssueLinksService"]
        ProfileSvc["ProfileService"]
    end

    subgraph Models["models"]
        User["User"]
        UserProject["UserProject"]
        UserBoard["UserBoard"]
        UserBoardSprint["UserBoardSprint"]
        UserTableauCustomView["UserTableauCustomView"]
    end

    Dependencies --> Crypto
    Dependencies --> Jira
    Dependencies --> JiraProjects
    Dependencies --> RuleSvc
    Dependencies --> SprintSvc
    Dependencies --> TableauSvc
    Dependencies --> JiraLinks

    Jira --> HttpClient
    JiraProjects --> HttpClient
    RuleSvc --> HttpClient
    SprintSvc --> HttpClient
    TableauSvc --> HttpClient
    JiraLinks --> HttpClient

    Auth --> Jira
    Auth --> Crypto
    Integrations --> Jira
    Integrations --> TableauSvc
    Integrations --> Crypto
    Projects --> JiraProjects
    Projects --> ProfileSvc
    TableauSettings --> TableauSvc
    RuleCopier --> RuleSvc
    RuleCopier --> JiraProjects
    RuleCopier --> PatCache
    SprintViewer --> SprintSvc
    SprintViewer --> PatCache
    TCI --> TableauSvc
    TCI --> JiraLinks
    TCI --> PatCache

    Auth --> User
    Integrations --> User
    Projects --> UserProject
    Projects --> UserBoard
    TableauSettings --> UserTableauCustomView
    RuleCopier --> UserProject
    RuleCopier --> UserBoard
    SprintViewer --> UserBoard
    SprintViewer --> UserBoardSprint
    TCI --> UserTableauCustomView

    User --> UserProject
    UserProject --> UserBoard
    UserBoardSprint --> User
    UserTableauCustomView --> User

    RuleCopier --> JsonApi
    SprintViewer --> JsonApi
    TCI --> JsonApi
    Auth --> ErrorLogging
    Integrations --> ErrorLogging
    Projects --> ErrorLogging
    TableauSettings --> ErrorLogging
    RuleCopier --> ErrorLogging
    SprintViewer --> ErrorLogging
    TCI --> ErrorLogging
    Auth --> DB
    Integrations --> DB
    Projects --> DB
    TableauSettings --> DB
    SprintViewer --> DB
```

## Template And Static Asset Graph

```mermaid
flowchart LR
    Base["templates/base.html"] --> Toasts["templates/_toasts.html"]
    Base --> AppCss["static/css/app.css"]
    Base --> AppJs["static/js/app.js"]

    AuthRoutes["auth routes"] --> AuthTemplates["templates/auth/*"]
    MainRoutes["main routes"] --> HomeTemplate["templates/main/home.html"]
    ProfileRoutes["profile routes"] --> ProfileTemplate["templates/profile/profile.html"]
    Integrations["settings integrations"] --> IntegrationsTpl["templates/config/integrations.html"]
    Projects["settings projects_boards"] --> ProjectsTpl["templates/config/projects_boards.html"]
    TableauSettings["settings tableau_custom_views"] --> TableauSettingsTpl["templates/config/custom_views.html"]
    RuleCopier["automation rule_copier"] --> RuleTpl["templates/automation/rule_copier.html"]
    SprintViewer["automation sprint_viewer"] --> SprintTpl["templates/automation/sprint_viewer.html"]
    TCI["reports tci"] --> TciTpl["templates/tableau/custom_views.html"]

    ProjectsTpl --> ProjectsJs["static/js/projects_boards.js"]
    TableauSettingsTpl --> TableauSettingsJs["static/js/tableau_custom_view_settings.js"]
    RuleTpl --> RuleJs["static/js/rule_copier.js"]
    SprintTpl --> SprintJs["static/js/sprint_viewer.js"]
    SprintTpl --> SprintCss["static/css/sprint_viewer.css"]
    TciTpl --> TciJs["static/js/tci_custom_views.js"]
```

## Test Anchor Graph

```mermaid
flowchart TD
    AppFactory["app factory, extensions, config"] --> ConfigTests["test_config_validation.py"]
    AppFactory --> LoggingTests["test_logging_conf.py, test_error_logging.py, test_handled_error_logging.py"]

    Routes["registered routes and aliases"] --> RouteTests["test_route_contract.py"]
    Routes --> SessionTests["test_session_and_navigation.py"]
    Routes --> MigrationTests["test_phase8_canonical_route_migration.py"]

    FeatureBoundaries["feature package exports"] --> BoundaryTests["test_feature_boundaries.py"]
    FeatureBoundaries --> Phase3Tests["test_phase3_shared_core_adoption.py"]
    FeatureBoundaries --> Phase4Tests["test_phase4_frontend_modularization.py"]

    ProjectsFeature["settings projects_boards"] --> ProjectTests["test_project_board_management.py"]
    ProjectsFeature --> PerformanceTests["test_phase7_database_performance.py"]

    RuleFeature["automation rule_copier"] --> RuleTests["test_rule_copier_fallback.py"]
    SprintFeature["automation sprint_viewer"] --> SprintTests["test_sprint_viewer_service.py"]
    TciFeature["reports tci"] --> TciTests["test_tableau_forms.py, test_phase6_feature_routes_and_failures.py"]

    CoreApi["core.api/http_client"] --> CoreTests["test_core_api.py, test_core_http_client.py"]
    JiraServices["Jira services"] --> JiraTests["test_jira_service_http_client.py"]
```

## Review Checklist By Change Type

- Route or URL changes: check aliases, legacy deprecation headers, templates, JS fetch targets, and `test_route_contract.py`.
- Feature handler changes: check auth decorators on wrapper routes, JSON shape, handled logging, model writes, and focused phase tests.
- Service changes: check `ExternalHttpClient` error mapping, sanitized snippets, retry/timeout behavior, and mocked HTTP tests.
- Model or migration changes: check uniqueness/indexes, relationship cascade behavior, migrations, and performance tests.
- Frontend changes: check the owning template, matching static file, canonical route URLs, and session/client logging behavior.
- Credential or PAT changes: check encryption/decryption, identity matching, safe flash messages, and no PAT leakage in logs.
