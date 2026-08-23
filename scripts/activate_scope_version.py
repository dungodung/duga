"""Operator CLI: promotes one fetched scope_version to active. A new version
never auto-activates (SPEC.md section 6) -- there's no auth'd admin UI for
this yet (that's M4), so it's a script an operator runs by hand on Toolforge.

Usage:
    python3 scripts/activate_scope_version.py <scope_version_id> --by <your-wiki-username>
    python3 scripts/activate_scope_version.py --list
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import ScopeVersion  # noqa: E402


def list_versions():
    for version in ScopeVersion.query.order_by(ScopeVersion.id.desc()).all():
        marker = "ACTIVE" if version.active else ""
        print(
            f"id={version.id}\trevision={version.revision_id}\t"
            f"rules={len(version.rules)}\tfetched_at={version.fetched_at}\t{marker}"
        )


def activate(version_id: int, activated_by: str):
    version = db.session.get(ScopeVersion, version_id)
    if version is None:
        print(f"No scope_version with id={version_id}", file=sys.stderr)
        sys.exit(1)

    ScopeVersion.query.filter_by(active=True).update({"active": False})
    version.active = True
    version.activated_at = datetime.now(timezone.utc)
    version.activated_by = activated_by
    db.session.commit()
    print(f"Activated scope_version {version_id} (revision {version.revision_id}) as {activated_by!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version_id", type=int, nargs="?", help="scope_version.id to activate")
    parser.add_argument("--by", help="your wiki username, recorded as activated_by")
    parser.add_argument("--list", action="store_true", help="list known scope_versions and exit")
    args = parser.parse_args()

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        if args.list:
            list_versions()
            return
        if args.version_id is None or not args.by:
            parser.error("version_id and --by are required unless --list is given")
        activate(args.version_id, args.by)


if __name__ == "__main__":
    main()
