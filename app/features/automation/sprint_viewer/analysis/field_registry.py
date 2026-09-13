"""Allowlisted, immutable extraction; catalogue IDs alone do not validate a parser."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

PARSERS = {'number', 'text', 'option', 'options', 'user', 'users', 'sprints', 'timestamp', 'date', 'boolean'}
CONFIGURED = {'validated', 'photo_confirmed'}


def default_document(config):
    # User-provided IDs are usable configuration. Runtime shape checks still apply;
    # confirming an ID does not assert complete history or validate workflow semantics.
    fields = {
        'points': ('JIRA_STORY_POINTS_FIELD', 'customfield_10106', 'number'),
        'membership': (None, 'customfield_10104', 'sprints'),
        'application': ('JIRA_APPLICATION_FIELD', 'customfield_11700', 'option'),
        'feature': ('JIRA_EPIC_LINK_FIELD', 'customfield_10100', 'text'),
    }
    return {'mapping_version': 'user-photo-ids-v1', 'fields': {
        name: {'field_id': config.get(setting) or field_id, 'parser_kind': parser,
               'validation_status': 'photo_confirmed', 'history_identifiers': []}
        for name, (setting, field_id, parser) in fields.items()
    }}


def parse_value(kind, value):
    if value is None:
        return {'value': None, 'reason': 'present_null'}
    valid = False
    if kind == 'number':
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    elif kind == 'text':
        valid = isinstance(value, str)
    elif kind == 'boolean':
        valid = isinstance(value, bool)
    elif kind in {'option', 'user'}:
        valid = isinstance(value, dict) and any(value.get(k) is not None for k in ('id', 'key', 'accountId'))
    elif kind in {'options', 'users'}:
        valid = isinstance(value, list) and all(parse_value('option' if kind == 'options' else 'user', v)['reason'] == 'known' for v in value)
    elif kind == 'sprints':
        valid = isinstance(value, list) and all(isinstance(v, dict) and str(v.get('id', '')).isdigit() for v in value)
        if valid:
            value = [int(v['id']) for v in value]
    elif kind in {'timestamp', 'date'}:
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            valid = isinstance(value, str) and (parsed.tzinfo is not None if kind == 'timestamp' else bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)))
        except (ValueError, TypeError, AttributeError):
            pass
    return {'value': deepcopy(value) if valid else None, 'reason': 'known' if valid else 'invalid_shape'}


class FieldRegistry:
    def __init__(self, document=None):
        self.document = deepcopy(document or {})
        self.fields = self.document.get('fields', {})
        if not isinstance(self.fields, dict):
            raise ValueError('fields must be an object')
        for spec in self.fields.values():
            if spec.get('parser_kind') not in PARSERS:
                raise ValueError('Unsupported field parser')
            field_id = spec.get('field_id')
            if field_id is not None and not re.fullmatch(r'(customfield_[1-9][0-9]*|[a-zA-Z][a-zA-Z0-9]*)', field_id):
                raise ValueError('Invalid Jira field ID')
        self.version = str(self.document.get('mapping_version') or 'unconfigured')
        self.digest = hashlib.sha256(json.dumps(self.document, sort_keys=True).encode()).hexdigest()

    def requested_fields(self):
        return sorted({s['field_id'] for s in self.fields.values() if s.get('validation_status') in CONFIGURED and s.get('field_id')})

    def for_scope(self, board_id, project_key=None, source_id=None):
        document = deepcopy(self.document)
        def matches(scope):
            return (not scope.get('board_ids') or str(board_id) in {str(v) for v in scope['board_ids']}) and (not scope.get('project_ids') or str(project_key) in {str(v) for v in scope['project_ids']}) and (not scope.get('jira_instance_scope') or scope['jira_instance_scope'] == source_id)
        if not matches(document):
            for spec in document.get('fields', {}).values():
                spec['validation_status'] = 'out_of_scope'
        else:
            candidates = sorted(document.get('overrides', []), key=lambda s: (bool(s.get('board_ids')), bool(s.get('project_ids'))))
            resolved = {}
            for override in candidates:
                if matches(override):
                    rank = (bool(override.get('board_ids')), bool(override.get('project_ids')))
                    for name in override.get('fields', {}):
                        if resolved.get(name) == rank:
                            raise ValueError('Ambiguous scoped field mapping')
                        resolved[name] = rank
                    document['fields'].update(deepcopy(override.get('fields', {})))
        return FieldRegistry(document)

    def extract(self, issue):
        result = {}
        for name, spec in self.fields.items():
            field_id = spec.get('field_id')
            issue_type = str(((issue.get('fields') or {}).get('issuetype') or {}).get('id', ''))
            if spec.get('issue_type_ids') and issue_type not in {str(v) for v in spec['issue_type_ids']}:
                value = {'value': None, 'reason': 'not_applicable'}
            elif spec.get('validation_status') not in CONFIGURED or not field_id:
                value = {'value': None, 'reason': 'mapping_unvalidated'}
            elif field_id not in (issue.get('fields') or {}):
                value = {'value': None, 'reason': 'missing_key'}
            else:
                value = parse_value(spec['parser_kind'], issue['fields'][field_id])
            result[name] = {**value, 'field_id': field_id, 'mapping_version': self.version, 'time_basis': 'collection'}
        return result


def load_registry(config):
    path = config.get('SPRINT_VIEWER_FIELD_MAPPING_FILE')
    document = json.loads(Path(path).read_text(encoding='utf-8')) if path else default_document(config)
    document.setdefault('analysis_config', config.get('SPRINT_VIEWER_ANALYSIS_CONFIG') or {})
    document['legacy_inputs'] = {key: config.get(key) for key in ('JIRA_STORY_POINTS_FIELD', 'JIRA_APPLICATION_FIELD', 'JIRA_EPIC_LINK_FIELD')}
    return FieldRegistry(document)
