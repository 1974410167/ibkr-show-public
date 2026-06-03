"""CLI entry point for running eval harness from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_service():  # type: ignore[no-untyped-def]
    """Build AgentEvalService with real dependencies."""
    from app.core.config import get_settings
    from app.clients.es_client import ElasticsearchClient
    from app.services.agent_eval_repository import EvalCaseRepository, EvalRunRepository
    from app.services.agent_eval_service import AgentEvalService

    settings = get_settings()
    es_client = ElasticsearchClient(settings)
    case_repo = EvalCaseRepository(es_client, settings)
    run_repo = EvalRunRepository(es_client, settings)

    llm_client = None
    if settings.llm_enable:
        from app.services.llm_service import LLMService
        llm_client = LLMService(settings)

    return AgentEvalService(case_repo, run_repo, llm_client=llm_client)


def _print_text(result: dict, gate: dict) -> None:
    summary = result.get("summary", {})
    print(f"Eval Run: {result.get('eval_run_id', 'unknown')}")
    print(f"Mode: {result.get('config', {}).get('mode', 'unknown')}")
    print(f"Cases: {summary.get('case_count', 0)}")
    print(f"Passed: {summary.get('passed_count', 0)}")
    print(f"Warning: {summary.get('warning_count', 0)}")
    print(f"Failed: {summary.get('failed_count', 0)}")
    print(f"Error: {summary.get('error_count', 0)}")
    print(f"Pass rate: {summary.get('pass_rate', 0):.1%}")
    print(f"Critical failures: {summary.get('critical_failure_count', 0)}")
    print(f"High priority failures: {summary.get('high_priority_failure_count', 0)}")
    print()
    if gate.get("passed"):
        print("PASSED")
    else:
        print("FAILED:")
        for reason in gate.get("reasons", []):
            print(f"  - {reason}")


def _print_json(result: dict, gate: dict, output_file: str | None = None) -> None:
    data = {
        "ok": gate.get("passed", False),
        "eval_run_id": result.get("eval_run_id"),
        "mode": result.get("config", {}).get("mode"),
        "summary": result.get("summary"),
        "gate": gate,
    }
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if output_file:
        Path(output_file).write_text(text, encoding="utf-8")
        print(f"Written to {output_file}")
    else:
        print(text)


def _evaluate_gate(summary: dict, args: argparse.Namespace) -> dict:
    reasons: list[str] = []
    pass_rate = summary.get("pass_rate", 0)
    critical_count = summary.get("critical_failure_count", 0)
    high_count = summary.get("high_priority_failure_count", 0)
    failed_count = summary.get("failed_count", 0) + summary.get("error_count", 0)

    if args.fail_on_critical and critical_count > 0:
        reasons.append(f"critical_failure_count {critical_count} > 0")
    if args.fail_on_high and high_count > 0:
        reasons.append(f"high_priority_failure_count {high_count} > 0")
    if args.max_failed is not None and failed_count > args.max_failed:
        reasons.append(f"failed_count {failed_count} > max_failed {args.max_failed}")
    if args.min_pass_rate is not None and pass_rate < args.min_pass_rate:
        reasons.append(f"pass_rate {pass_rate:.3f} < required {args.min_pass_rate}")

    return {"passed": len(reasons) == 0, "reasons": reasons}


def _build_impact_service():  # type: ignore[no-untyped-def]
    """Build AgentChangeImpactService with real dependencies."""
    from app.clients.es_client import ElasticsearchClient
    from app.core.config import get_settings
    from app.services.agent_change_impact_service import AgentChangeImpactService
    from app.services.agent_eval_repository import RegressionProfileRepository
    from app.services.agent_regression_profile_service import RegressionProfileService

    settings = get_settings()
    es_client = ElasticsearchClient(settings)
    profile_repo = RegressionProfileRepository(es_client, settings)
    profile_service = RegressionProfileService(profile_repo)
    return AgentChangeImpactService(profile_service)


def _build_gate_service():  # type: ignore[no-untyped-def]
    """Build AgentRegressionGateService with real dependencies."""
    from app.clients.es_client import ElasticsearchClient
    from app.core.config import get_settings
    from app.services.agent_change_impact_service import AgentChangeImpactService
    from app.services.agent_eval_repository import EvalCaseRepository, EvalRunRepository, RegressionGateReportRepository, RegressionProfileRepository
    from app.services.agent_eval_service import AgentEvalService
    from app.services.agent_regression_gate_service import AgentRegressionGateService
    from app.services.agent_regression_profile_service import RegressionProfileService

    settings = get_settings()
    es_client = ElasticsearchClient(settings)
    case_repo = EvalCaseRepository(es_client, settings)
    run_repo = EvalRunRepository(es_client, settings)
    profile_repo = RegressionProfileRepository(es_client, settings)
    profile_service = RegressionProfileService(profile_repo)
    report_repo = RegressionGateReportRepository(es_client, settings)
    repo_root = str(Path(__file__).resolve().parents[2])
    impact_service = AgentChangeImpactService(profile_service, repo_root=repo_root)

    llm_client = None
    if settings.llm_enable:
        from app.services.llm_service import LLMService
        llm_client = LLMService(settings)

    eval_service = AgentEvalService(case_repo, run_repo, llm_client=llm_client)
    return AgentRegressionGateService(impact_service, eval_service, report_repository=report_repo)


def regression_gate(args: argparse.Namespace) -> int:
    changed_files: list[str] = list(args.changed_file) if args.changed_file else None

    if not changed_files and not (args.base_ref and args.head_ref):
        print("Error: provide --changed-file or both --base-ref and --head-ref", file=sys.stderr)
        return 2

    service = _build_gate_service()

    metadata = None
    if args.metadata_json:
        import json as _json
        try:
            metadata = _json.loads(args.metadata_json)
        except _json.JSONDecodeError as exc:
            print(f"Error: invalid --metadata-json: {exc}", file=sys.stderr)
            return 2

    try:
        result = service.run_regression_gate(
            changed_files=changed_files,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
            dry_run=args.dry_run,
            run_not_recommended=args.run_not_recommended,
            max_agents=args.max_agents,
            save_report=args.save_report,
            trigger=args.trigger or "cli",
            created_by=args.created_by,
            metadata=metadata,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(text, encoding="utf-8")
        print(f"Written to {args.output_file}")
    elif args.output == "json":
        print(text)
    else:
        _print_gate_text(result)

    return 0 if result["ok"] else 1


def _print_gate_text(result: dict) -> None:
    summary = result.get("summary", {})
    if result.get("report_id"):
        print(f"Regression Gate Report: {result['report_id']}")
    print(f"Regression Gate: {'PASSED' if result['ok'] else 'FAILED'}")
    print(f"Mode: {result.get('mode', 'unknown')}")
    if result.get("dry_run"):
        print("(dry run)")
    if result.get("base_ref"):
        print(f"Base: {result['base_ref']}")
    if result.get("head_ref"):
        print(f"Head: {result['head_ref']}")
    print(f"Changed files: {summary.get('changed_file_count', 0)}")
    print(f"Impacted agents: {summary.get('impacted_agent_count', 0)}")
    print(f"Recommended runs: {summary.get('recommended_run_count', 0)}")
    if not result.get("dry_run"):
        print(f"Executed: {summary.get('executed_run_count', 0)}")
        print(f"Passed: {summary.get('passed_run_count', 0)}")
        print(f"Failed: {summary.get('failed_run_count', 0)}")
    for run in result.get("runs", []):
        status = "dry-run" if run.get("dry_run") else ("passed" if run.get("gate_passed") else "failed")
        print(f"  - {run['agent_name']}: {status}")
    for reason in result.get("reasons", []):
        print(f"  ! {reason}")


def impact_analysis(args: argparse.Namespace) -> int:
    service = _build_impact_service()

    changed_files: list[str] = []
    if args.changed_file:
        changed_files = list(args.changed_file)

    try:
        if changed_files:
            result = service.analyze_changed_files(
                changed_files,
                base_ref=args.base_ref,
                head_ref=args.head_ref,
                include_payload=not args.no_include_payload,
            )
        elif args.base_ref and args.head_ref:
            result = service.analyze_git_diff(
                args.base_ref,
                args.head_ref,
                include_payload=not args.no_include_payload,
            )
        else:
            print("Error: provide --changed-file or both --base-ref and --head-ref", file=sys.stderr)
            return 2
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(text, encoding="utf-8")
        print(f"Written to {args.output_file}")
    else:
        print(text)

    return 0


def run(args: argparse.Namespace) -> int:
    service = _build_service()

    common_kwargs = dict(
        agent_name=args.agent,
        case_ids=list(args.case_id) if args.case_id else None,
        tag=args.case_tag,
        severity=args.severity,
        category=args.category,
        enabled_only=not args.include_disabled,
        limit=args.limit,
    )

    all_cases = service.select_cases_for_eval(**common_kwargs, include_judge=True)
    skipped_judge_count = sum(1 for c in all_cases if c.get("judge_enabled")) if not args.include_judge else 0

    cases = service.select_cases_for_eval(**common_kwargs, include_judge=args.include_judge)

    if not cases:
        print("No eval cases matched.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Dry run: {len(cases)} cases matched")
        for case in cases:
            judge_mark = " [judge]" if case.get("judge_enabled") else ""
            print(f"  - {case['case_id']} {case.get('agent_name', '?')} {case.get('severity', '?')} {case.get('category', '?')}{judge_mark}")
        if skipped_judge_count > 0:
            print(f"  ({skipped_judge_count} judge-enabled cases skipped, use --include-judge to include)")
        return 0

    if skipped_judge_count > 0:
        print(f"Note: {skipped_judge_count} judge-enabled cases skipped (use --include-judge to enable)", file=sys.stderr)

    case_ids = [c["case_id"] for c in cases]
    name = f"CI eval - {len(case_ids)} cases"

    result = service.run_eval(
        case_ids=case_ids,
        mode=args.mode,
        name=name,
    )

    summary = result.get("summary", {})
    gate = _evaluate_gate(summary, args)
    gate["skipped_judge_case_count"] = skipped_judge_count

    if args.output == "json":
        _print_json(result, gate, args.output_file)
    else:
        _print_text(result, gate)

    return 0 if gate["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval_harness", description="Eval Harness CLI")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Run eval cases")
    run_parser.add_argument("--mode", default="static", choices=["static", "live_mock"], help="Eval mode")
    run_parser.add_argument("--agent", default=None, help="Filter by agent name")
    run_parser.add_argument("--case-id", action="append", default=None, help="Specific case ID (repeatable)")
    run_parser.add_argument("--case-tag", default=None, help="Filter by tag")
    run_parser.add_argument("--severity", default=None, help="Filter by severity")
    run_parser.add_argument("--category", default=None, help="Filter by category")
    run_parser.add_argument("--include-disabled", action="store_true", help="Include disabled cases")
    run_parser.add_argument("--limit", type=int, default=100, help="Max cases")
    run_parser.add_argument("--fail-on-critical", action="store_true", help="Fail if any critical failures")
    run_parser.add_argument("--fail-on-high", action="store_true", help="Fail if any high priority failures")
    run_parser.add_argument("--max-failed", type=int, default=None, help="Max allowed failures")
    run_parser.add_argument("--min-pass-rate", type=float, default=None, help="Minimum pass rate")
    run_parser.add_argument("--output", default="text", choices=["text", "json"], help="Output format")
    run_parser.add_argument("--output-file", default=None, help="Write output to file")
    run_parser.add_argument("--include-judge", action="store_true", help="Include LLM judge evaluation")
    run_parser.add_argument("--dry-run", action="store_true", help="Show matched cases without running")

    impact_parser = sub.add_parser("impact-analysis", help="Analyze code change impact for regression")
    impact_parser.add_argument("--changed-file", action="append", default=None, help="Changed file path (repeatable)")
    impact_parser.add_argument("--base-ref", default=None, help="Git base ref for diff")
    impact_parser.add_argument("--head-ref", default=None, help="Git head ref for diff")
    impact_parser.add_argument("--no-include-payload", action="store_true", help="Skip regression payload generation")
    impact_parser.add_argument("--output-file", default=None, help="Write output to file")

    gate_parser = sub.add_parser("regression-gate", help="Run regression gate for deployment")
    gate_parser.add_argument("--changed-file", action="append", default=None, help="Changed file path (repeatable)")
    gate_parser.add_argument("--base-ref", default=None, help="Git base ref for diff")
    gate_parser.add_argument("--head-ref", default=None, help="Git head ref for diff")
    gate_parser.add_argument("--output", default="text", choices=["text", "json"], help="Output format")
    gate_parser.add_argument("--output-file", default=None, help="Write output to file")
    gate_parser.add_argument("--dry-run", action="store_true", help="Only analyze impact, do not run eval")
    gate_parser.add_argument("--run-not-recommended", action="store_true", help="Also run non-recommended agents")
    gate_parser.add_argument("--max-agents", type=int, default=10, help="Max agents to run")
    gate_parser.add_argument("--save-report", action="store_true", help="Persist gate report to Elasticsearch")
    gate_parser.add_argument("--trigger", default="cli", help="Trigger source label (default: cli)")
    gate_parser.add_argument("--created-by", default=None, help="Report creator label")
    gate_parser.add_argument("--metadata-json", default=None, help="Extra metadata as JSON string")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    if args.command == "run":
        return run(args)
    if args.command == "impact-analysis":
        return impact_analysis(args)
    if args.command == "regression-gate":
        return regression_gate(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
