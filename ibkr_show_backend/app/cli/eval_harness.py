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


def _build_failure_mining_service():  # type: ignore[no-untyped-def]
    from app.clients.es_client import ElasticsearchClient
    from app.core.config import get_settings
    from app.services.eval_failure_mining_repository import SyntheticFailureMiningRepository
    from app.services.eval_failure_mining_service import SyntheticFailureMiningService
    from app.services.eval_simulation_repository import SyntheticSimulationRepository

    settings = get_settings()
    es_client = ElasticsearchClient(settings)
    return SyntheticFailureMiningService(
        failure_repository=SyntheticFailureMiningRepository(es_client, settings),
        simulation_repository=SyntheticSimulationRepository(es_client, settings),
    )


def _build_simulation_service(use_in_memory: bool = False):  # type: ignore[no-untyped-def]
    from app.clients.es_client import ElasticsearchClient
    from app.core.config import get_settings
    from app.services.eval_simulation_repository import InMemorySyntheticSimulationRepository, SyntheticSimulationRepository
    from app.services.eval_simulation_service import SyntheticSimulationService

    if use_in_memory:
        return SyntheticSimulationService(InMemorySyntheticSimulationRepository())

    settings = get_settings()
    es_client = ElasticsearchClient(settings)
    return SyntheticSimulationService(SyntheticSimulationRepository(es_client, settings))


def _build_failure_to_case_service():  # type: ignore[no-untyped-def]
    from app.clients.es_client import ElasticsearchClient
    from app.core.config import get_settings
    from app.services.agent_eval_repository import EvalCaseRepository
    from app.services.eval_failure_mining_repository import SyntheticFailureMiningRepository
    from app.services.eval_failure_to_case_service import FailureToEvalCaseService
    from app.services.eval_simulation_repository import SyntheticSimulationRepository

    settings = get_settings()
    es_client = ElasticsearchClient(settings)
    return FailureToEvalCaseService(
        failure_repository=SyntheticFailureMiningRepository(es_client, settings),
        simulation_repository=SyntheticSimulationRepository(es_client, settings),
        case_repository=EvalCaseRepository(es_client, settings),
    )


def _build_baseline_health_report_service():  # type: ignore[no-untyped-def]
    from app.clients.es_client import ElasticsearchClient
    from app.core.config import get_settings
    from app.services.agent_eval_repository import EvalCaseRepository
    from app.services.eval_baseline_health_repository import BaselineHealthReportRepository
    from app.services.eval_baseline_health_service import BaselineHealthReportService
    from app.services.eval_failure_mining_repository import SyntheticFailureMiningRepository
    from app.services.eval_simulation_repository import SyntheticSimulationRepository

    settings = get_settings()
    es_client = ElasticsearchClient(settings)
    return BaselineHealthReportService(
        report_repository=BaselineHealthReportRepository(es_client, settings),
        simulation_repository=SyntheticSimulationRepository(es_client, settings),
        failure_repository=SyntheticFailureMiningRepository(es_client, settings),
        case_repository=EvalCaseRepository(es_client, settings),
        agent_eval_service=None,
    )


def _build_judge_calibration_service():  # type: ignore[no-untyped-def]
    from app.clients.es_client import ElasticsearchClient
    from app.core.config import get_settings
    from app.services.agent_eval_repository import EvalCaseRepository
    from app.services.eval_baseline_health_repository import BaselineHealthReportRepository
    from app.services.eval_failure_mining_repository import SyntheticFailureMiningRepository
    from app.services.eval_judge_calibration_repository import JudgeCalibrationRepository
    from app.services.eval_judge_calibration_service import JudgeCalibrationService
    from app.services.eval_simulation_repository import SyntheticSimulationRepository

    settings = get_settings()
    es_client = ElasticsearchClient(settings)
    return JudgeCalibrationService(
        calibration_repository=JudgeCalibrationRepository(es_client, settings),
        failure_repository=SyntheticFailureMiningRepository(es_client, settings),
        simulation_repository=SyntheticSimulationRepository(es_client, settings),
        baseline_report_repository=BaselineHealthReportRepository(es_client, settings),
        case_repository=EvalCaseRepository(es_client, settings),
    )


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


def synthetic_scenarios(args: argparse.Namespace) -> int:
    from app.agents.eval_simulation_scenarios import filter_synthetic_scenarios, summarize_synthetic_scenarios

    items = filter_synthetic_scenarios(
        agent_name=args.agent_name,
        tag=args.tag,
        severity=args.severity,
        category=args.category,
        limit=args.limit,
    )
    summary = summarize_synthetic_scenarios()
    if args.output == "json":
        data = {"items": items}
        if args.summary:
            data["summary"] = summary
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if args.summary:
        print(f"Synthetic scenarios: {summary['total_count']}")
        print("By agent:")
        for agent_name, count in sorted(summary["by_agent"].items()):
            print(f"  - {agent_name}: {count}")
        print()
    for item in items:
        print(f"{item['scenario_id']} {item['agent_name']} {item['severity']} {item['category']} - {item['title']}")
    return 0


def simulation_run(args: argparse.Namespace) -> int:
    service = _build_simulation_service(use_in_memory=args.in_memory)
    try:
        result = service.run_scenarios(
            scenario_ids=list(args.scenario_id) if args.scenario_id else None,
            agent_name=args.agent_name,
            tag=args.tag,
            severity=args.severity,
            category=args.category,
            limit=args.limit,
            dry_run=args.dry_run,
            executor_mode=args.executor_mode,
            name=args.name,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(text, encoding="utf-8")
            print(f"Written to {args.output_file}")
        else:
            print(text)
        return 0

    run = result.get("simulation_run") or {}
    summary = run.get("summary") or {}
    print(f"Simulation Run: {run.get('simulation_run_id')}")
    print(f"Name: {run.get('name')}")
    print(f"Status: {run.get('status')}")
    print(f"Dry run: {summary.get('dry_run')}")
    print(f"Scenarios: {summary.get('scenario_count', 0)}")
    print(f"Executed: {summary.get('executed_count', 0)}")
    print(f"Skipped: {summary.get('skipped_count', 0)}")
    print(f"Errors: {summary.get('error_count', 0)}")
    for item in result.get("results") or []:
        print(f"  - {item['scenario_id']} {item['agent_name']} {item['status']}")
    return 0


def failure_mining(args: argparse.Namespace) -> int:
    service = _build_failure_mining_service()
    try:
        result = service.mine_simulation_run(
            args.simulation_run_id,
            include_dry_run_results=args.include_dry_run_results,
            include_judge=args.include_judge,
            min_severity=args.min_severity,
            max_failures=args.max_failures,
            deduplicate=args.deduplicate,
            name=args.name,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(text, encoding="utf-8")
            print(f"Written to {args.output_file}")
        else:
            print(text)
        return 0

    run = result.get("failure_mining_run") or {}
    summary = result.get("summary") or {}
    print(f"Failure Mining Run: {run.get('failure_mining_run_id')}")
    print(f"Simulation Run: {run.get('simulation_run_id')}")
    print(f"Status: {run.get('status')}")
    print(f"Failures: {summary.get('failure_count', 0)}")
    print(f"Critical: {summary.get('critical_count', 0)}")
    print(f"High: {summary.get('high_count', 0)}")
    print(f"Suggested eval cases: {summary.get('suggested_eval_case_count', 0)}")
    for item in result.get("failures") or []:
        print(f"  - {item['failure_id']} {item['agent_name']} {item['severity']} {item['failure_type']}")
    return 0


def failure_to_case(args: argparse.Namespace) -> int:
    actions = [bool(args.preview), bool(args.convert), bool(args.batch)]
    if sum(actions) != 1:
        print("Error: choose exactly one of --preview, --convert, or --batch", file=sys.stderr)
        return 2
    if (args.preview or args.convert) and not args.failure_id:
        print("Error: --failure-id is required for --preview/--convert", file=sys.stderr)
        return 2
    if args.batch and not (args.failure_mining_run_id or args.failure_id):
        print("Error: --failure-mining-run-id or --failure-id is required for --batch", file=sys.stderr)
        return 2

    service = _build_failure_to_case_service()
    try:
        failure_id = args.failure_id[0] if args.failure_id else None
        if args.preview:
            result = service.preview_case_from_failure(failure_id, enabled=args.enabled)
        elif args.convert:
            result = service.convert_failure_to_case(failure_id, enabled=args.enabled, force=args.force)
        else:
            result = service.batch_convert_failures(
                failure_mining_run_id=args.failure_mining_run_id,
                failure_ids=list(args.failure_id) if args.failure_id else None,
                min_priority=args.min_priority,
                max_cases=args.max_cases,
                enabled=args.enabled,
                force=args.force,
            )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(text, encoding="utf-8")
            print(f"Written to {args.output_file}")
        else:
            print(text)
        return 0

    if args.preview:
        draft = result.get("draft") or {}
        print(f"Draft: {draft.get('draft_id')}")
        print(f"Failure: {draft.get('failure_id')}")
        print(f"Quality: {draft.get('quality_score')}")
        print(f"Eligible: {(result.get('quality') or {}).get('eligible')}")
    elif args.convert:
        print(f"Status: {result.get('status')}")
        print(f"Case: {result.get('case_id')}")
        print(f"Reason: {result.get('reason')}")
    else:
        print(f"Converted: {result.get('converted_count', 0)}")
        print(f"Skipped: {result.get('skipped_count', 0)}")
        print(f"Duplicate: {result.get('duplicate_count', 0)}")
        print(f"Errors: {result.get('error_count', 0)}")
    return 0


def baseline_health_report(args: argparse.Namespace) -> int:
    service = _build_baseline_health_report_service()
    try:
        report = service.generate_report(
            simulation_run_id=args.simulation_run_id,
            failure_mining_run_id=args.failure_mining_run_id,
            include_converted_cases=args.include_converted_cases,
            include_correctness_summary=args.include_correctness_summary,
            name=args.name,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 1

    if args.output == "markdown":
        text = report.get("markdown_report") or ""
    elif args.output == "json":
        text = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        summary = report.get("summary") or {}
        text = "\n".join([
            f"Baseline Health Report: {report.get('report_id')}",
            f"Status: {report.get('status')}",
            f"Overall health score: {summary.get('overall_health_score')}",
            f"Failures: {summary.get('failure_count')}",
            f"Suggested EvalCases: {summary.get('suggested_eval_case_count')}",
        ])
    if args.output_file:
        Path(args.output_file).write_text(text, encoding="utf-8")
        print(f"Written to {args.output_file}")
    else:
        print(text)
    return 0


def judge_calibration(args: argparse.Namespace) -> int:
    service = _build_judge_calibration_service()
    try:
        result = service.detect_calibration_signals(
            failure_mining_run_id=args.failure_mining_run_id,
            baseline_report_id=args.baseline_report_id,
            agent_name=args.agent_name,
            min_priority=args.min_priority,
            deduplicate=args.deduplicate,
            name=args.name,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        run_data = result.get("calibration_run") or {}
        summary = result.get("summary") or {}
        text = "\n".join([
            f"Judge Calibration Run: {run_data.get('calibration_run_id')}",
            f"Source: {run_data.get('source_type')} {run_data.get('source_id')}",
            f"Status: {run_data.get('status')}",
            f"Signals: {summary.get('signal_count', 0)}",
            f"Case candidates: {summary.get('case_candidate_count', 0)}",
        ])
    if args.output_file:
        Path(args.output_file).write_text(text, encoding="utf-8")
        print(f"Written to {args.output_file}")
    else:
        print(text)
    return 0


def judge_calibration_case(args: argparse.Namespace) -> int:
    actions = [bool(args.preview), bool(args.create), bool(args.batch)]
    if sum(actions) != 1:
        print("Error: choose exactly one of --preview, --create, or --batch", file=sys.stderr)
        return 2
    if (args.preview or args.create) and not args.signal_id:
        print("Error: --signal-id is required for --preview/--create", file=sys.stderr)
        return 2
    if args.batch and not args.calibration_run_id:
        print("Error: --calibration-run-id is required for --batch", file=sys.stderr)
        return 2

    service = _build_judge_calibration_service()
    try:
        if args.preview:
            result = service.preview_calibration_case(args.signal_id, enabled=args.enabled)
        elif args.create:
            result = service.create_calibration_case(args.signal_id, enabled=args.enabled, force=args.force)
        else:
            result = service.batch_create_calibration_cases(
                calibration_run_id=args.calibration_run_id,
                min_priority=args.min_priority,
                max_cases=args.max_cases,
                enabled=args.enabled,
                force=args.force,
            )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        text = json.dumps(result, ensure_ascii=False, indent=2)
    elif args.preview:
        draft = result.get("draft") or {}
        text = "\n".join([
            f"Draft: {draft.get('draft_id')}",
            f"Signal: {draft.get('signal_id')}",
            f"Quality: {draft.get('quality_score')}",
            f"Eligible: {(result.get('quality') or {}).get('eligible')}",
        ])
    elif args.create:
        text = "\n".join([
            f"Status: {result.get('status')}",
            f"Case: {result.get('case_id')}",
            f"Reason: {result.get('reason')}",
        ])
    else:
        text = "\n".join([
            f"Created: {result.get('created_count', 0)}",
            f"Skipped: {result.get('skipped_count', 0)}",
            f"Duplicate: {result.get('duplicate_count', 0)}",
            f"Errors: {result.get('error_count', 0)}",
        ])
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

    scenario_parser = sub.add_parser("synthetic-scenarios", help="List synthetic user simulation scenarios")
    scenario_parser.add_argument("--agent-name", default=None, help="Filter by agent name")
    scenario_parser.add_argument("--tag", default=None, help="Filter by tag")
    scenario_parser.add_argument("--severity", default=None, help="Filter by severity")
    scenario_parser.add_argument("--category", default=None, help="Filter by category")
    scenario_parser.add_argument("--limit", type=int, default=100, help="Max scenarios")
    scenario_parser.add_argument("--summary", action="store_true", help="Include scenario summary")
    scenario_parser.add_argument("--output", default="text", choices=["text", "json"], help="Output format")

    simulation_parser = sub.add_parser("simulation-run", help="Run synthetic user simulation scenarios")
    simulation_parser.add_argument("--scenario-id", action="append", default=None, help="Scenario ID (repeatable)")
    simulation_parser.add_argument("--agent-name", default=None, help="Filter by agent name")
    simulation_parser.add_argument("--tag", default=None, help="Filter by tag")
    simulation_parser.add_argument("--severity", default=None, help="Filter by severity")
    simulation_parser.add_argument("--category", default=None, help="Filter by category")
    simulation_parser.add_argument("--limit", type=int, default=20, help="Max scenarios")
    simulation_parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Do not call real agents")
    simulation_parser.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="Allow non-dry-run execution")
    simulation_parser.add_argument("--executor-mode", default="auto", choices=["auto", "fake", "real"], help="Executor mode")
    simulation_parser.add_argument("--in-memory", action="store_true", help="Use an in-memory repository instead of Elasticsearch")
    simulation_parser.add_argument("--name", default=None, help="Simulation run name")
    simulation_parser.add_argument("--output", default="text", choices=["text", "json"], help="Output format")
    simulation_parser.add_argument("--output-file", default=None, help="Write JSON output to file")

    mining_parser = sub.add_parser("failure-mining", help="Mine failures from a synthetic simulation run")
    mining_parser.add_argument("--simulation-run-id", required=True, help="Simulation run ID")
    mining_parser.add_argument("--include-judge", dest="include_judge", action="store_true", default=False, help="Run LLM-as-Judge")
    mining_parser.add_argument("--no-include-judge", dest="include_judge", action="store_false", help="Disable LLM-as-Judge")
    mining_parser.add_argument("--include-dry-run-results", dest="include_dry_run_results", action="store_true", default=False, help="Evaluate dry-run/fake simulation results")
    mining_parser.add_argument("--no-include-dry-run-results", dest="include_dry_run_results", action="store_false", help="Skip dry-run/fake simulation results")
    mining_parser.add_argument("--min-severity", default=None, choices=["low", "medium", "high", "critical"], help="Minimum failure severity")
    mining_parser.add_argument("--max-failures", type=int, default=100, help="Maximum failures")
    mining_parser.add_argument("--deduplicate", dest="deduplicate", action="store_true", default=True, help="Deduplicate failures")
    mining_parser.add_argument("--no-deduplicate", dest="deduplicate", action="store_false", help="Do not deduplicate failures")
    mining_parser.add_argument("--name", default=None, help="Failure mining run name")
    mining_parser.add_argument("--output", default="text", choices=["text", "json"], help="Output format")
    mining_parser.add_argument("--output-file", default=None, help="Write JSON output to file")

    failure_case_parser = sub.add_parser("failure-to-case", help="Preview or convert mined failures to EvalCase")
    failure_case_parser.add_argument("--failure-id", action="append", default=None, help="Failure ID (repeatable for --batch)")
    failure_case_parser.add_argument("--failure-mining-run-id", default=None, help="Failure mining run ID for batch conversion")
    failure_case_parser.add_argument("--preview", action="store_true", help="Preview case payload without saving")
    failure_case_parser.add_argument("--convert", action="store_true", help="Convert one failure to an EvalCase")
    failure_case_parser.add_argument("--batch", action="store_true", help="Batch convert failures")
    failure_case_parser.add_argument("--enabled", dest="enabled", action="store_true", default=False, help="Save enabled EvalCase")
    failure_case_parser.add_argument("--disabled", dest="enabled", action="store_false", help="Save disabled EvalCase")
    failure_case_parser.add_argument("--force", action="store_true", help="Bypass quality/duplicate gates")
    failure_case_parser.add_argument("--min-priority", type=int, default=80, help="Minimum conversion priority for batch")
    failure_case_parser.add_argument("--max-cases", type=int, default=20, help="Maximum cases for batch")
    failure_case_parser.add_argument("--output", default="text", choices=["text", "json"], help="Output format")
    failure_case_parser.add_argument("--output-file", default=None, help="Write JSON output to file")

    baseline_parser = sub.add_parser("baseline-health-report", help="Generate Eval P3.5 baseline health report")
    baseline_parser.add_argument("--simulation-run-id", default=None, help="Simulation run ID")
    baseline_parser.add_argument("--failure-mining-run-id", default=None, help="Failure mining run ID")
    baseline_parser.add_argument("--name", default=None, help="Report name")
    baseline_parser.add_argument("--include-converted-cases", dest="include_converted_cases", action="store_true", default=True)
    baseline_parser.add_argument("--no-include-converted-cases", dest="include_converted_cases", action="store_false")
    baseline_parser.add_argument("--include-correctness-summary", dest="include_correctness_summary", action="store_true", default=True)
    baseline_parser.add_argument("--no-include-correctness-summary", dest="include_correctness_summary", action="store_false")
    baseline_parser.add_argument("--output", default="text", choices=["text", "json", "markdown"], help="Output format")
    baseline_parser.add_argument("--output-file", default=None, help="Write output to file")

    judge_calibration_parser = sub.add_parser("judge-calibration", help="Detect LLM-as-Judge calibration signals")
    judge_calibration_parser.add_argument("--failure-mining-run-id", default=None, help="Failure mining run ID")
    judge_calibration_parser.add_argument("--baseline-report-id", default=None, help="Baseline health report ID")
    judge_calibration_parser.add_argument("--agent-name", default=None, help="Filter by agent name")
    judge_calibration_parser.add_argument("--min-priority", type=int, default=50, help="Minimum signal priority")
    judge_calibration_parser.add_argument("--deduplicate", dest="deduplicate", action="store_true", default=True, help="Deduplicate calibration signals")
    judge_calibration_parser.add_argument("--no-deduplicate", dest="deduplicate", action="store_false", help="Do not deduplicate signals")
    judge_calibration_parser.add_argument("--name", default=None, help="Calibration run name")
    judge_calibration_parser.add_argument("--output", default="text", choices=["text", "json"], help="Output format")
    judge_calibration_parser.add_argument("--output-file", default=None, help="Write output to file")

    judge_case_parser = sub.add_parser("judge-calibration-case", help="Preview or create judge calibration EvalCases")
    judge_case_parser.add_argument("--signal-id", default=None, help="Calibration signal ID")
    judge_case_parser.add_argument("--calibration-run-id", default=None, help="Calibration run ID for batch create")
    judge_case_parser.add_argument("--preview", action="store_true", help="Preview case payload without saving")
    judge_case_parser.add_argument("--create", action="store_true", help="Create one disabled EvalCase by default")
    judge_case_parser.add_argument("--batch", action="store_true", help="Batch create calibration EvalCases")
    judge_case_parser.add_argument("--enabled", dest="enabled", action="store_true", default=False, help="Save enabled EvalCase")
    judge_case_parser.add_argument("--disabled", dest="enabled", action="store_false", help="Save disabled EvalCase")
    judge_case_parser.add_argument("--force", action="store_true", help="Bypass quality/duplicate gates")
    judge_case_parser.add_argument("--min-priority", type=int, default=70, help="Minimum priority for batch")
    judge_case_parser.add_argument("--max-cases", type=int, default=20, help="Maximum cases for batch")
    judge_case_parser.add_argument("--output", default="text", choices=["text", "json"], help="Output format")
    judge_case_parser.add_argument("--output-file", default=None, help="Write output to file")

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
    if args.command == "synthetic-scenarios":
        return synthetic_scenarios(args)
    if args.command == "simulation-run":
        return simulation_run(args)
    if args.command == "failure-mining":
        return failure_mining(args)
    if args.command == "failure-to-case":
        return failure_to_case(args)
    if args.command == "baseline-health-report":
        return baseline_health_report(args)
    if args.command == "judge-calibration":
        return judge_calibration(args)
    if args.command == "judge-calibration-case":
        return judge_calibration_case(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
