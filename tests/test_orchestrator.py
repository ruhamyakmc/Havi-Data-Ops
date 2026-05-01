import pytest
import json
from havi import topological_sort, build_run_list

_STAGE_DEPS = {
    'ftp_to_extracted': [],
    'sqlite_to_bronze': ['ftp_to_extracted'],
    'bronze_to_silver': ['sqlite_to_bronze'],
    'transform_havi':   ['bronze_to_silver'],
    'measures_havi':    ['transform_havi'],
    'promote_havi':     ['measures_havi'],
}

def test_topological_sort_full_order():
    order = topological_sort(_STAGE_DEPS)
    assert order == [
        'ftp_to_extracted', 'sqlite_to_bronze', 'bronze_to_silver',
        'transform_havi', 'measures_havi', 'promote_havi',
    ]

def test_topological_sort_single_stage():
    order = topological_sort({'only': []})
    assert order == ['only']

def test_build_run_list_all():
    stages = build_run_list(_STAGE_DEPS, run_all=True)
    assert stages == [
        'ftp_to_extracted', 'sqlite_to_bronze', 'bronze_to_silver',
        'transform_havi', 'measures_havi', 'promote_havi',
    ]

def test_build_run_list_single_stage():
    stages = build_run_list(_STAGE_DEPS, run_all=False, pipeline='transform_havi')
    assert stages == ['transform_havi']

def test_build_run_list_unknown_stage_raises():
    with pytest.raises(SystemExit):
        build_run_list(_STAGE_DEPS, run_all=False, pipeline='nonexistent')

from unittest.mock import MagicMock, patch
from stages.base import StageResult
from havi import run_pipeline, STAGE_CLASSES


def test_run_pipeline_skips_downstream_on_failure():
    """A failing stage causes its downstream stages to be skipped."""
    config = MagicMock()
    engine = MagicMock()

    call_log = []

    with patch.object(STAGE_CLASSES['sqlite_to_bronze'], 'run',
                      return_value=StageResult(success=False, errors=['boom'])):
        with patch.object(STAGE_CLASSES['bronze_to_silver'], 'run') as mock_silver:
            with patch('havi.send_pipeline_report'):
                with patch('sys.exit'):
                    run_pipeline(['sqlite_to_bronze', 'bronze_to_silver'], config, engine)

    mock_silver.assert_not_called()


def test_run_pipeline_wraps_unexpected_exception():
    """An unhandled exception from a stage is caught and wrapped, not propagated."""
    config = MagicMock()
    engine = MagicMock()

    with patch.object(STAGE_CLASSES['sqlite_to_bronze'], 'run',
                      side_effect=RuntimeError('unexpected crash')):
        with patch('havi.send_pipeline_report'):
            with patch('sys.exit') as mock_exit:
                run_pipeline(['sqlite_to_bronze'], config, engine)

    mock_exit.assert_called_once_with(1)


def test_run_pipeline_exits_1_on_failure():
    """run_pipeline calls sys.exit(1) when any stage fails."""
    config = MagicMock()
    engine = MagicMock()

    with patch.object(STAGE_CLASSES['sqlite_to_bronze'], 'run',
                      return_value=StageResult(success=False, errors=['fail'])):
        with patch('havi.send_pipeline_report'):
            with patch('sys.exit') as mock_exit:
                run_pipeline(['sqlite_to_bronze'], config, engine)

    mock_exit.assert_called_once_with(1)


def test_run_pipeline_calls_notifier_on_failure():
    """send_pipeline_report is called after a failed run."""
    config = MagicMock()
    engine = MagicMock()

    with patch.object(STAGE_CLASSES['sqlite_to_bronze'], 'run',
                      return_value=StageResult(success=False, errors=['boom'])):
        with patch('havi.send_pipeline_report') as mock_notify:
            with patch('sys.exit'):
                run_pipeline(['sqlite_to_bronze'], config, engine)

    mock_notify.assert_called_once()
    call_kwargs = mock_notify.call_args.kwargs
    assert 'sqlite_to_bronze' in call_kwargs['results']
    assert call_kwargs['stages'] == ['sqlite_to_bronze']


def test_run_pipeline_calls_notifier_on_success():
    """send_pipeline_report is called even on a clean run (it decides internally)."""
    config = MagicMock()
    engine = MagicMock()

    with patch.object(STAGE_CLASSES['sqlite_to_bronze'], 'run',
                      return_value=StageResult(success=True, rows_written=10)):
        with patch('havi.send_pipeline_report') as mock_notify:
            run_pipeline(['sqlite_to_bronze'], config, engine)

    mock_notify.assert_called_once()


def test_run_pipeline_logs_structured_stage_complete(caplog):
    config = MagicMock()
    engine = MagicMock()

    with patch.object(STAGE_CLASSES['sqlite_to_bronze'], 'run',
                      return_value=StageResult(success=True, rows_written=10)):
        with patch('havi.send_pipeline_report'):
            with caplog.at_level('INFO'):
                run_pipeline(['sqlite_to_bronze'], config, engine)

    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith('{')
    ]
    stage_event = next(e for e in events if e.get('event') == 'stage_complete')
    assert stage_event['stage'] == 'sqlite_to_bronze'
    assert stage_event['success'] is True
    assert stage_event['rows_written'] == 10
    assert 'duration_s' in stage_event
