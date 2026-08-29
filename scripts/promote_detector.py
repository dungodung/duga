"""Operator CLI: promotes a detector's maturity after human review, or
demotes it back.

SPEC.md section 11: post-v0.1 detectors ship experimental, and "promotion
to beta/stable is a human decision after review with native speakers of at
least two affected languages". This script exists to make that sentence
enforceable rather than aspirational -- it will not promote anything
without the names of at least two reviewers, and it records them.

Promotion is NOT the same switch as visibility. `enabled` (see
scripts/set_detector_enabled.py) decides whether a detector's gaps are
shown; `maturity` decides how they are labelled AND whether SPEC.md S7
applies:

    jobs/detector_common.py excludes is_living topics from a detector
    while, and only while, its maturity is 'experimental'.

So promoting out of 'experimental' makes living people eligible for that
detector on its next run. That is a real change in what Duga collects
about real people, which is exactly why S7 exists and why this script
prints the number of living topics it would newly expose and requires
--yes to proceed. Demotion back to 'experimental' is unrestricted: making
the handling of living people stricter never needs a ceremony.

Usage:
    python3 scripts/promote_detector.py <detector_key> --to beta \
        --reviewer "Name (sr)" --reviewer "Name (fr)" --by <your-wiki-username> --yes
    python3 scripts/promote_detector.py <detector_key> --to experimental --by <your-wiki-username>
    python3 scripts/promote_detector.py --list
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.audit import log as audit_log  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Detector, Gap, Topic  # noqa: E402

MATURITIES = ("experimental", "beta", "stable")
MIN_REVIEWERS = 2


def list_detectors():
    print(f"{'detector_key':<24}{'maturity':<14}{'enabled':<9}{'gaps':>8}")
    for detector in Detector.query.order_by(Detector.maturity, Detector.detector_key).all():
        gaps = Gap.query.filter_by(detector_key=detector.detector_key).count()
        print(f"{detector.detector_key:<24}{detector.maturity:<14}{str(bool(detector.enabled)):<9}{gaps:>8}")


def living_topic_count():
    """How many in-scope, unsuppressed topics are living people -- i.e. how
    many S7 currently keeps out of every experimental detector."""
    return Topic.query.filter_by(is_living=True, suppressed=False).count()


def promote(detector, to, reviewers, by, confirmed):
    before = detector.maturity
    if before == to:
        print(f"{detector.detector_key}: already {to}, nothing to do")
        return

    loosening = before == "experimental" and to != "experimental"
    if loosening:
        if len(reviewers) < MIN_REVIEWERS:
            print(
                f"Refusing to promote {detector.detector_key} out of 'experimental' with "
                f"{len(reviewers)} reviewer(s). SPEC.md section 11 requires review with native "
                f"speakers of at least {MIN_REVIEWERS} affected languages; pass --reviewer once "
                f"per person, e.g. --reviewer 'Ana (sr)' --reviewer 'Luc (fr)'.",
                file=sys.stderr,
            )
            sys.exit(1)
        living = living_topic_count()
        print(
            f"{detector.detector_key}: {before} -> {to} lifts the SPEC.md S7 exclusion for this "
            f"detector. {living} living topic(s) become eligible for it on its next run."
        )
        if not confirmed:
            print("Re-run with --yes if that is intended.", file=sys.stderr)
            sys.exit(1)

    detector.maturity = to
    audit_log(
        actor=by,
        action="promote_detector" if loosening else "set_detector_maturity",
        entity_type="detector",
        entity_id=detector.detector_key,
        before={"maturity": before},
        after={"maturity": to, "reviewers": reviewers, "s7_exclusion_lifted": loosening},
    )
    db.session.commit()
    print(f"{detector.detector_key}: maturity {before} -> {to} (enabled={bool(detector.enabled)}, unchanged)")
    if reviewers:
        print("reviewers recorded: " + "; ".join(reviewers))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("detector_key", nargs="?")
    parser.add_argument("--to", choices=MATURITIES, help="maturity to set")
    parser.add_argument(
        "--reviewer", action="append", default=[], dest="reviewers",
        help="one native-speaker reviewer, repeatable; at least two are required to promote",
    )
    parser.add_argument("--by", help="your wiki username, recorded in audit_log")
    parser.add_argument("--yes", action="store_true", help="confirm lifting the S7 living-person exclusion")
    parser.add_argument("--list", action="store_true", help="show every detector's maturity and exit")
    args = parser.parse_args()

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        if args.list:
            list_detectors()
            return
        if not args.detector_key or not args.to or not args.by:
            parser.error("detector_key, --to, and --by are required unless --list is given")
        detector = Detector.query.filter_by(detector_key=args.detector_key).first()
        if detector is None:
            print(f"No detector with key={args.detector_key!r} -- has the job ever run?", file=sys.stderr)
            sys.exit(1)
        promote(detector, args.to, args.reviewers, args.by, args.yes)


if __name__ == "__main__":
    main()
