"""
Command-line interface for local development and demoing the Good
Neighbor Agent.

Usage:
    python -m goodneighbor.cli init-db
    python -m goodneighbor.cli seed
    python -m goodneighbor.cli run-cycle {volunteers|inventory|donations|all}
    python -m goodneighbor.cli show-escalations
    python -m goodneighbor.cli resolve-escalation <id> "<resolution text>"
    python -m goodneighbor.cli digest [--html]
    python -m goodneighbor.cli serve
"""

import argparse
import sys

from . import db
from .seed_data import seed as seed_demo_data
from .escalation import list_pending_escalations, resolve_escalation
from .digest import build_digest, render_markdown, render_html


def cmd_init_db(_args):
    path = db.init_db()
    print(f"Database initialized at {path}")


def cmd_seed(_args):
    seed_demo_data()
    print("Seeded demo scenario for Riverside Community Food Bank.")


def cmd_run_cycle(args):
    from .orchestrator import run_cycle, run_all_cycles

    if args.cycle == "all":
        results = run_all_cycles()
        for cycle, summary in results.items():
            print(f"\n=== {cycle} ===\n{summary}")
    else:
        print(run_cycle(args.cycle))


def cmd_show_escalations(_args):
    pending = list_pending_escalations()
    if not pending:
        print("No pending escalations. Quiet week.")
        return
    for e in pending:
        print(f"\n#{e['id']} [{e['urgency'].upper()}] {e['title']}")
        print(f"  {e['description']}")
        for i, opt in enumerate(e["options"], start=1):
            print(f"  {i}. {opt}")


def cmd_resolve_escalation(args):
    result = resolve_escalation(args.id, args.resolution)
    print(f"Escalation #{result['id']} resolved: {result['resolution']}")


def cmd_digest(args):
    digest = build_digest(period_days=args.days)
    if args.html:
        print(render_html(digest))
    else:
        print(render_markdown(digest))


def cmd_serve(_args):
    import os
    import sys

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from agentcore.app import app  # noqa: local import to avoid AWS deps unless needed

    app.run()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="goodneighbor")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    sub.add_parser("seed").set_defaults(func=cmd_seed)

    p_run = sub.add_parser("run-cycle")
    p_run.add_argument("cycle", choices=["volunteers", "inventory", "donations", "all"])
    p_run.set_defaults(func=cmd_run_cycle)

    sub.add_parser("show-escalations").set_defaults(func=cmd_show_escalations)

    p_resolve = sub.add_parser("resolve-escalation")
    p_resolve.add_argument("id", type=int)
    p_resolve.add_argument("resolution")
    p_resolve.set_defaults(func=cmd_resolve_escalation)

    p_digest = sub.add_parser("digest")
    p_digest.add_argument("--days", type=int, default=7)
    p_digest.add_argument("--html", action="store_true")
    p_digest.set_defaults(func=cmd_digest)

    sub.add_parser("serve").set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
