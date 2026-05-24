# Feature-Based Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the app toward feature-based organization while preserving every existing URL and behavior.

**Architecture:** Add canonical route aliases and core infrastructure first, then migrate one feature at a time behind compatibility wrappers. The existing blueprint routes remain active until all templates, tests, and docs use canonical routes.

**Tech Stack:** Flask, Flask-Login, Flask-WTF, SQLAlchemy, Alembic, pytest, Bootstrap, vanilla JavaScript.

---

## Phase 1: Non-Breaking Foundation

- [x] Add route contract tests for canonical user and API routes.
- [x] Add config validation tests.
- [x] Add `app/core/config_validation.py`.
- [x] Add `app/blueprints/aliases` for canonical route aliases.
- [x] Add `.env.example`.
- [x] Add first-time setup, route, architecture, env, and operations docs.

## Phase 2: Feature Package Skeleton

- [x] Add `app/features` package and feature folders.
- [x] Document ownership for each feature folder.
- [x] Keep existing blueprints as compatibility layer during migration.

## Phase 3: One-Feature-At-A-Time Migration

- [x] Move Projects & Boards form/service/route helpers behind `features/settings/projects_boards`.
- [x] Move Tableau Custom View settings form/route helpers behind `features/settings/tableau_custom_views`.
- [x] Move Rule Copier helpers behind `features/automation/rule_copier`.
- [x] Move Sprint Viewer helpers behind `features/automation/sprint_viewer`.
- [x] Move Tableau custom view and TCI report helpers behind `features/reports/tci`.

## Phase 4: Logging And Error Hardening

- [x] Add central API error response helper.
- [x] Add reusable external HTTP client with sanitized service errors.
- [x] Move Jira/Tableau-facing production services onto the reusable external HTTP client.
- [x] Add shared dependency factories for common crypto/Jira/Tableau service construction.
- [x] Use shared API response helpers in migrated feature API routes.
- [x] Normalize handled service error logging with stack traces where diagnostic value is high.
- [x] Add tests for sanitized error responses and request ID propagation.

## Phase 5: Verification

- [x] Run `py -m pytest`.
- [x] Run `node --check app/static/js/app.js`.
- [x] Run `py scripts/smoke_check.py`.
