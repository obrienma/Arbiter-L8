"""`arbiter-l8` console script — run an offline run_eval() from the shell.

Wires a fixture (EvalDataset JSON) to a real adapter
(adapters.sentinel_l7 / adapters.synapse_l4) and prints the resulting
EvalReport. This is the offline (ground-truth) path only — online scoring
(online.pipeline.evaluate_item) has no CLI surface, since it's meant to be
wired into a caller's own sampling/production loop, not run as a one-shot
command.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from arbiter_l8.adapters.sentinel_l7 import SentinelL7Error, make_sentinel_l7_system_under_test
from arbiter_l8.adapters.synapse_l4 import SynapseL4Error, make_synapse_l4_system_under_test
from arbiter_l8.harness import SystemUnderTest, run_eval
from arbiter_l8.models import EvalDataset, EvalPrediction, EvalReport


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arbiter-l8",
        description=(
            "Score a labeled fixture against a real Sentinel-L7 or Synapse-L4 "
            "instance via the offline (ground-truth) harness."
        ),
    )
    parser.add_argument(
        "--system",
        required=True,
        choices=["sentinel-l7", "synapse-l4"],
        help="Which system-under-test to call.",
    )
    parser.add_argument(
        "--fixture",
        required=True,
        type=Path,
        help="Path to a labeled EvalDataset JSON fixture whose `input` shape "
        "matches the chosen system's adapter contract.",
    )
    parser.add_argument(
        "--driver",
        choices=["gemini", "openrouter", "ollama"],
        default=None,
        help="Sentinel-L7 only: force a specific ComplianceManager driver via "
        "the per-request override, bypassing the semantic cache.",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Override the system's base/MCP URL (defaults to config.py's "
        "env-var-with-default).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only score the first N examples of the fixture.",
    )
    parser.add_argument(
        "--binary",
        action="store_true",
        help="Sentinel-L7 only: collapse a predicted label to 'high' unless "
        "it's exactly 'low' before scoring, matching "
        "TransactionProcessorService::gradeAiResult(). Only meaningful "
        "against binary-labeled fixtures such as sentinel_l7_ground_truth.json.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON instead of a text summary.",
    )
    return parser


def _collapse_binary(sut: SystemUnderTest) -> SystemUnderTest:
    def wrapped(input_data: dict) -> EvalPrediction:
        prediction = sut(input_data)
        if prediction.label != "low":
            prediction = prediction.model_copy(update={"label": "high"})
        return prediction

    return wrapped


def _print_report(report: EvalReport) -> None:
    print(f"accuracy: {report.correct}/{report.total} ({report.accuracy:.1%})")
    print()
    print(f"{'label':<12}{'precision':>11}{'recall':>11}{'f1':>11}{'support':>9}")
    for lm in report.per_label:
        print(
            f"{lm.label:<12}{lm.precision:>11.2f}{lm.recall:>11.2f}"
            f"{lm.f1:>11.2f}{lm.support:>9}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.driver is not None and args.system != "sentinel-l7":
        parser.error("--driver is only valid with --system sentinel-l7")
    if args.binary and args.system != "sentinel-l7":
        parser.error("--binary is only valid with --system sentinel-l7")

    dataset = EvalDataset.model_validate_json(args.fixture.read_text())
    if args.limit is not None:
        dataset = EvalDataset(examples=dataset.examples[: args.limit])

    if args.system == "sentinel-l7":
        sut = make_sentinel_l7_system_under_test(mcp_url=args.url, driver=args.driver)
    else:
        sut = make_synapse_l4_system_under_test(base_url=args.url)

    if args.binary:
        sut = _collapse_binary(sut)

    try:
        report = run_eval(sut, dataset)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        print(f"error: could not reach {args.system} — {exc}", file=sys.stderr)
        return 1
    except (SentinelL7Error, SynapseL4Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
