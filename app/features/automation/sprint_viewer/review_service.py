from datetime import date
from urllib.parse import urlparse

from .schemas import InputValidationError


def validate_record(kind, payload):
    if kind not in {'assessment', 'action', 'disposition', 'issue_review', 'context'}:
        raise InputValidationError('Unknown review record kind.')
    allowed = {'title', 'state', 'note', 'owner', 'due_date', 'evidence_url', 'source_evidence', 'completed_at', 'issue_id', 'goal_linked', 'acceptance', 'scope_reason'}
    value = {key: payload[key] for key in allowed if key in payload}
    for key, item in value.items():
        if key == 'goal_linked':
            if not isinstance(item, bool):
                raise InputValidationError('goal_linked must be true or false.')
        elif not isinstance(item, str) or len(item) > (4000 if key in {'note', 'scope_reason'} else 500):
            raise InputValidationError(f'{key} has an invalid value or exceeds the length limit.')
    url = value.get('evidence_url')
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in {'https', 'http'} or not parsed.netloc or parsed.username or parsed.password:
            raise InputValidationError('Evidence URL must be an HTTP or HTTPS link without credentials.')
    if kind == 'assessment' and value.get('state') not in {'Not assessed', 'Achieved', 'Partially achieved', 'Not achieved'}:
        raise InputValidationError('Choose an explicit goal assessment.')
    if kind == 'action':
        if any(not value.get(key, '').strip() for key in ('title', 'owner', 'due_date')):
            raise InputValidationError('Action title, owner and due date are required.')
        if value.get('state') not in {'Open', 'In progress', 'Done', 'Archived'}:
            raise InputValidationError('Invalid action state.')
        try:
            date.fromisoformat(value['due_date'])
        except ValueError as exc:
            raise InputValidationError('Invalid due date.') from exc
    if kind == 'disposition' and value.get('state') not in {'Open', 'Dismissed', 'Action created'}:
        raise InputValidationError('Invalid observation disposition.')
    if kind == 'issue_review' and value.get('acceptance') not in {'Accepted', 'Pending review', 'Rejected', 'Not ready', 'Not recorded'}:
        raise InputValidationError('Invalid acceptance state.')
    return value
