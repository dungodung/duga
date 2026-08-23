"""Write-path audit logging (SPEC.md guardrail 11: log every write to
audit_log before and after). Call from inside the same transaction as the
write it's recording -- this only stages the row; the caller's own
db.session.commit() writes it alongside whatever it's logging.
"""
import json
from datetime import datetime, timezone

from .extensions import db
from .models import AuditLog


def log(actor, action, entity_type, entity_id, before=None, after=None):
    db.session.add(
        AuditLog(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before_json=json.dumps(before) if before is not None else None,
            after_json=json.dumps(after) if after is not None else None,
            created_at=datetime.now(timezone.utc),
        )
    )
