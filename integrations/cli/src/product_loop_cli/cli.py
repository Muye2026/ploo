#!/usr/bin/env python3
"""ploo — terminal entrypoint for the Product Loop hardware product workflow.

A thin dispatcher over the provider-neutral, stdlib-only scripts in
``core/scripts/``. The CLI adds no workflow logic of its own: every subcommand
forwards to the matching core script, and the repository checkout is resolved
automatically, so a single installation keeps working after ``git pull``.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

__version__ = "0.1.0"

#: ploo subcommand -> core script (one-to-one, no logic lives here).
SCRIPTS = {
    "validate": "validate_v2.py",
    "validate-bundle": "validate_bundle.py",
    "migrate": "migrate_v1_to_v2.py",
    "run-state": "manage_run_state.py",
    "normalize": "normalize_design_pack.py",
    "review-matrix": "build_review_matrix.py",
    "handoff": "emit_handoff_brief.py",
    "evaluate-behavior": "evaluate_behavior_contracts.py",
}

#: Commands whose arguments are forwarded verbatim (including --flags).
PASSTHROUGH = {name for name in SCRIPTS if name != "validate"}


def find_core(explicit=None):
    """Locate the product-loop core directory (the one containing scripts/).

    Resolution order: ``--core`` flag, ``$PRODUCT_LOOP_CORE``, the checkout
    that installed this package, then every ancestor of the working directory.
    An explicit ``--core`` or ``$PRODUCT_LOOP_CORE`` that does not contain
    ``scripts/`` fails hard instead of silently falling back.
    """
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if (candidate / "scripts").is_dir():
            return candidate
        sys.exit(f"ploo: --core {explicit} does not contain scripts/")
    if os.environ.get("PRODUCT_LOOP_CORE"):
        env = os.environ["PRODUCT_LOOP_CORE"]
        candidate = Path(env).expanduser().resolve()
        if (candidate / "scripts").is_dir():
            return candidate
        sys.exit(f"ploo: $PRODUCT_LOOP_CORE {env} does not contain scripts/")
    package_dir = Path(__file__).resolve().parent
    for ancestor in (package_dir, *package_dir.parents):
        candidate = ancestor / "core"
        if (candidate / "scripts").is_dir():
            return candidate
    for parent in (Path.cwd(), *Path.cwd().parents):
        candidate = parent / "core"
        if (candidate / "scripts").is_dir():
            return candidate
    sys.exit(
        "ploo: cannot locate the product-loop core directory (core/scripts). "
        "Run inside a repository checkout, set PRODUCT_LOOP_CORE, or pass --core DIR."
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="ploo",
        description=(
            "Terminal entrypoint for the Product Loop hardware product workflow. "
            "Every subcommand forwards to the matching script in core/scripts/."
        ),
    )
    parser.add_argument("--version", action="version", version=f"ploo {__version__}")
    parser.add_argument(
        "--core",
        metavar="DIR",
        help="path to the product-loop core directory "
        "(overrides $PRODUCT_LOOP_CORE and repository discovery)",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def passthrough(name, help_text):
        p = sub.add_parser(
            name,
            help=help_text,
            description=help_text
            + " Remaining arguments are forwarded to the core script unchanged.",
        )
        p.add_argument("script_args", nargs=argparse.REMAINDER, metavar="ARGS")
        return p

    p = sub.add_parser("validate", help="validate one V2 artifact against its JSON schema")
    p.add_argument(
        "kind",
        help="document kind (design-pack, electrical-pack, interface-control, run-state, ...)",
    )
    p.add_argument("input", help="path to the V2 JSON document")

    passthrough("validate-bundle", "cross-document validation before freeze or execution")
    passthrough("migrate", "migrate a V1 Design Pack to V2 artifacts")
    passthrough(
        "run-state",
        "inspect or update run-state.v2.json "
        "(validate, resolve-routes, open-decision, resolve-decision, record-execution, "
        "change-route, stale)",
    )
    passthrough("normalize", "normalize a design pack")
    passthrough("review-matrix", "build a review matrix from review results")
    passthrough("handoff", "emit a handoff brief")
    passthrough("evaluate-behavior", "score captured responses against behavior contracts")
    return parser


def run_script(core_override, command, script_args):
    core = find_core(core_override)
    script = core / "scripts" / SCRIPTS[command]
    if not script.is_file():
        sys.exit(f"ploo: missing core script {script}")
    try:
        result = subprocess.run([sys.executable, str(script), *script_args])
    except KeyboardInterrupt:
        return 130
    return result.returncode


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # Consume global flags that precede the subcommand. Passthrough commands
    # forward everything else verbatim, so argparse (which rejects unknown
    # --flags) is bypassed for them.
    core_override = None
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token == "--core":
            if idx + 1 < len(argv) and argv[idx + 1]:
                core_override = argv[idx + 1]
                idx += 2
            else:
                sys.exit("ploo: --core requires a value")
            continue
        if token == "--version":
            print(f"ploo {__version__}")
            return 0
        if token in ("-h", "--help") and idx == 0:
            build_parser().print_help()
            return 0
        break

    rest = argv[idx:]
    if rest and rest[0] in PASSTHROUGH:
        return run_script(core_override, rest[0], rest[1:])

    parser = build_parser()
    ns = parser.parse_args(argv)
    if ns.command == "validate":
        script_args = [ns.kind, ns.input]
    else:
        script_args = ns.script_args
    return run_script(ns.core, ns.command, script_args)


if __name__ == "__main__":
    sys.exit(main())
