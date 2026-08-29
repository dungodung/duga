"""Operator CLI: enables or disables a detector, without touching its
maturity.

SPEC.md section 11 ships post-v0.1 detectors "behind maturity =
'experimental', disabled by default", and makes promotion "a human decision
after review with native speakers of at least two affected languages".
Those are two separate switches and this script only moves one of them:

- `enabled` controls whether a detector's gaps are *visible*
  (app/blueprints/main/routes.py:_visible_gaps_query filters out gaps whose
  detector row says enabled=False).
- `maturity` controls how the rows are *labelled*, and -- this is the part
  worth being careful about -- whether SPEC.md S7 applies. jobs/
  detector_common.py excludes `is_living` topics only while maturity is
  'experimental'. Promoting a detector to beta/stable silently switches
  living people back on for it.

So enabling an experimental detector is safe and reversible: the gaps
become visible, every row still reads "experimental", and living people
stay excluded. Promoting one is the decision SPEC.md reserves for humans
with native-speaker review, and this script deliberately cannot do it --
that is scripts/promote_detector.py's job if and when it exists.

Usage:
    python3 scripts/set_detector_enabled.py <detector_key> --on  --by <your-wiki-username>
    python3 scripts/set_detector_enabled.py <detector_key> --off --by <your-wiki-username>
    python3 scripts/set_detector_enabled.py --all-experimental --on --by <your-wiki-username>
    python3 scripts/set_detector_enabled.py --list
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.audit import log as audit_log  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Detector, Gap  # noqa: E402


def list_detectors():
    print(f"{'detector_key':<24}{'maturity':<14}{'enabled':<9}{'gaps':>8}  last run")
    for detector in Detector.query.order_by(Detector.detector_key).all():
        gaps = Gap.query.filter_by(detector_key=detector.detector_key).count()
        print(
            f"{detector.detector_key:<24}{detector.maturity:<14}"
            f"{str(bool(detector.enabled)):<9}{gaps:>8}  "
            f"{detector.last_run_at} ({detector.last_status})"
        )


def set_enabled(detectors, enabled, by):
    if not detectors:
        print("No matching detector rows -- has the job ever run?", file=sys.stderr)
        sys.exit(1)
    for detector in detectors:
        before = bool(detector.enabled)
        if before == enabled:
            print(f"{detector.detector_key}: already {'enabled' if enabled else 'disabled'}, skipped")
            continue
        detector.enabled = enabled
        audit_log(
            actor=by,
            action="enable_detector" if enabled else "disable_detector",
            entity_type="detector",
            entity_id=detector.detector_key,
            before={"enabled": before, "maturity": detector.maturity},
            after={"enabled": enabled, "maturity": detector.maturity},
        )
        gaps = Gap.query.filter_by(detector_key=detector.detector_key).count()
        print(
            f"{detector.detector_key}: enabled={before} -> {enabled} "
            f"(maturity {detector.maturity}, unchanged; {gaps} gap rows affected)"
        )
    db.session.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("detector_key", nargs="?", help="detector to enable/disable")
    parser.add_argument("--all-experimental", action="store_true", help="apply to every experimental detector")
    parser.add_argument("--by", help="your wiki username, recorded in audit_log")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--on", dest="enabled", action="store_true", default=None, help="make its gaps visible")
    group.add_argument("--off", dest="enabled", action="store_false", help="hide its gaps again")
    parser.add_argument("--list", action="store_true", help="show every detector's state and exit")
    args = parser.parse_args()

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        if args.list:
            list_detectors()
            return
        if args.enabled is None:
            parser.error("one of --on or --off is required")
        if not args.by:
            parser.error("--by is required (recorded in audit_log)")
        if args.all_experimental:
            detectors = Detector.query.filter_by(maturity="experimental").order_by(Detector.detector_key).all()
        elif args.detector_key:
            detectors = Detector.query.filter_by(detector_key=args.detector_key).all()
        else:
            parser.error("give a detector_key or --all-experimental")
        set_enabled(detectors, args.enabled, args.by)


if __name__ == "__main__":
    main()
