from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from modules.config import ConfigLoader
from modules.db import (
    create_db_engine,
    init_schemas,
    log_pipeline_row_counts,
    log_pipeline_run,
)
from modules.migrations import run_migrations
from modules.notifier import send_pipeline_report
from stages.base import StageResult
from stages.bronze_to_silver import BronzeToSilver
from stages.export_box import ExportBox
from stages.ftp_to_extracted import FtpToExtracted
from stages.measures_havi import MeasuresHavi
from stages.promote_havi import PromoteHavi
from stages.sqlite_to_bronze import SqliteToBronze
from stages.transform_havi import TransformHavi

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
)
logger = logging.getLogger(__name__)

STAGE_CLASSES = {
    'ftp_to_extracted': FtpToExtracted,
    'sqlite_to_bronze': SqliteToBronze,
    'bronze_to_silver': BronzeToSilver,
    'transform_havi': TransformHavi,
    'measures_havi': MeasuresHavi,
    'promote_havi': PromoteHavi,
}

STAGE_DEPS = {name: cls.dependencies for name, cls in STAGE_CLASSES.items()}

# Stages excluded from -a (all stages) — must be triggered manually with -p.
MANUAL_STAGE_CLASSES = {
    'export_box': ExportBox,
}


def topological_sort(deps: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm. Returns stages in a valid execution order."""
    in_degree: dict[str, int] = defaultdict(int)
    graph: dict[str, list[str]] = defaultdict(list)

    for name in deps:
        in_degree.setdefault(name, 0)
        for dep in deps[name]:
            graph[dep].append(name)
            in_degree[name] += 1

    queue = deque(n for n in deps if in_degree[n] == 0)
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return order


def build_run_list(
    deps: dict[str, list[str]],
    *,
    run_all: bool,
    pipeline: str | None = None,
) -> list[str]:
    if run_all:
        return topological_sort(deps)
    all_known = {**STAGE_CLASSES, **MANUAL_STAGE_CLASSES}
    if pipeline not in all_known:
        logger.error(f"Unknown stage '{pipeline}'. Valid stages: {sorted(all_known)}")
        sys.exit(1)
    return [pipeline]


def run_pipeline(stages: list[str], config: ConfigLoader, engine) -> None:
    results: dict[str, StageResult] = {}
    failed: set[str] = set()
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    all_classes = {**STAGE_CLASSES, **MANUAL_STAGE_CLASSES}
    for name in stages:
        cls = all_classes[name]
        blocked_by = [d for d in cls.dependencies if d in failed]
        if blocked_by:
            logger.warning(f"Skipping '{name}' — upstream failure(s): {blocked_by}")
            failed.add(name)
            continue

        logger.info(f"=== Running stage: {name} ===")
        stage = cls(config=config, engine=engine)
        stage_started = time.monotonic()
        try:
            result = stage.run()
        except Exception as exc:
            result = StageResult(success=False, errors=[str(exc)])
            logger.exception(f"Stage '{name}' raised an unexpected exception.")
        duration_s = round(time.monotonic() - stage_started, 3)
        result.metadata = {**result.metadata, 'duration_s': duration_s}

        results[name] = result
        logger.info(json.dumps({
            'event': 'stage_complete',
            'run_id': run_id,
            'stage': name,
            'success': result.success,
            'rows_written': result.rows_written,
            'errors': len(result.errors),
            'warnings': len(result.warnings),
            'duration_s': duration_s,
        }))
        if not result.success:
            failed.add(name)
            for err in result.errors:
                logger.error(f"  [{name}] {err}")
        else:
            logger.info(f"  [{name}] OK — {result.rows_written} row(s) written.")

    _log_summary(results, failed)
    log_pipeline_run(engine, run_id, started_at, results, stages)
    log_pipeline_row_counts(engine, run_id)
    send_pipeline_report(results=results, stages=stages, engine=engine, config=config)
    if failed:
        sys.exit(1)


def _log_summary(results: dict[str, StageResult], failed: set[str]) -> None:
    logger.info('=== Pipeline Run Summary ===')
    for name, result in results.items():
        status = 'FAILED' if name in failed else 'OK'
        logger.info(f"  {status:6s}  {name}  ({result.rows_written} rows)")
    skipped = [n for n in STAGE_CLASSES if n not in results]
    for name in skipped:
        logger.info(f"  SKIP    {name}")
    if not failed:
        logger.info('Result: SUCCESS')
    else:
        logger.warning(f'Result: FAILED ({len(failed)} stage(s))')


def main() -> None:
    parser = argparse.ArgumentParser(description='HAVI Entomology ETL orchestrator')
    parser.add_argument('-p', '--pipeline', help='Run a single named stage')
    parser.add_argument('-a', '--all', action='store_true', help='Run all stages')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.all and not args.pipeline:
        parser.error('Specify -a (all stages) or -p <stage_name>')

    config = ConfigLoader('config.json')
    engine = create_db_engine(config)
    init_schemas(engine)
    run_migrations(engine)

    stages = build_run_list(STAGE_DEPS, run_all=args.all, pipeline=args.pipeline)
    run_pipeline(stages, config, engine)


if __name__ == '__main__':
    main()
