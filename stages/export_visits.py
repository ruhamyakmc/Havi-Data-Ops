from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from modules.box_client import get_box_client
from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)


def build_partial_hhid_report(
    collection_df: pd.DataFrame,
    mrc_sites: dict[str, str],
) -> str:
    """Return a plain-text report listing HLC households with fewer nights than the
    site maximum. These are likely households that were excluded mid-study and replaced.
    """
    lines: list[str] = []
    lines.append('HAVI ETL — Partial / Replaced Households')
    lines.append(f'Generated: {date.today().isoformat()}')
    lines.append('=' * 72)
    lines.append('')
    lines.append('Households that participated in some but not all rounds within the')
    lines.append('export window. A household with fewer collection nights than the site')
    lines.append('maximum was excluded mid-study and replaced by another.')
    lines.append('')

    hlc = collection_df[collection_df['datasource'].astype(str) == '1'] if not collection_df.empty else collection_df
    found_any = False

    for mrc in sorted(mrc_sites.keys(), key=int):
        site_df = hlc[hlc['mrccode'].astype(str) == str(mrc)]
        if site_df.empty:
            continue

        nights_per_hh = (
            site_df.groupby('hhid')['dateofcollection']
            .apply(lambda s: sorted(s.unique().tolist()))
            .to_dict()
        )
        if not nights_per_hh:
            continue

        max_nights = max(len(v) for v in nights_per_hh.values())
        partial = {hh: nights for hh, nights in nights_per_hh.items() if len(nights) < max_nights}
        if not partial:
            continue

        found_any = True
        site_name = mrc_sites[mrc]
        lines.append('-' * 72)
        lines.append(f'MRC {mrc}  {site_name}')
        lines.append('-' * 72)
        lines.append('')

        continuous = sorted(hh for hh in nights_per_hh if hh not in partial)
        lines.append(f'  Continuous households ({max_nights} nights):')
        for hh in continuous:
            lines.append(f'    {hh}')
        lines.append('')

        lines.append(f'  Partial households (< {max_nights} nights — excluded or replaced):')
        for hh in sorted(partial):
            nights = partial[hh]
            n = len(nights)
            first, last = nights[0], nights[-1]
            lines.append(f'    {hh}  —  {n} night(s)  [{first} to {last}]')
            for night in nights:
                lines.append(f'      {night}')
        lines.append('')

    if not found_any:
        lines.append('No partial households detected — all hhids have the maximum night count.')
        lines.append('')

    lines.append('=' * 72)
    lines.append('END OF REPORT')
    return '\n'.join(lines)


def _first_n_sessions(df: pd.DataFrame, date_col: str, n: int) -> pd.Series:
    """Return a boolean mask for rows belonging to the first n distinct nights per hhid."""
    dates = pd.to_datetime(df[date_col], errors='coerce').dt.date
    ranked = (
        df.assign(_date=dates)
        .groupby('hhid')['_date']
        .transform(lambda s: s.rank(method='dense'))
    )
    return ranked <= n


_DROP_COLS = {
    # ETL internals
    'run_uuid', 'file_name', 'file_path', 'extracted_at',
    # Device / app metadata
    'swver', 'survey_id', 'lastmod',
    # Redundant geography (all Uganda, mrccode is sufficient)
    'country', 'community',
    # Barcode decomposition — mosq_barcode has the full value
    'mosq_barcode_num', 'mosq_barcode_num2',
}


# Columns to place immediately before uniqueid in the output
_BEFORE_UNIQUEID = ['aspirations_method', 'rain', 'windforce']


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    """Drop internal columns, fill N/A sentinels, and reorder for export."""
    df = df.drop(columns=[c for c in _DROP_COLS if c in df.columns]).copy()

    # rain / windforce: -6 = N/A (field not collected in earlier form versions)
    for col in ('rain', 'windforce'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(-6).astype(int)

    # Move aspirations_method / rain / windforce to just before uniqueid
    if 'uniqueid' in df.columns:
        move = [c for c in _BEFORE_UNIQUEID if c in df.columns]
        cols = [c for c in df.columns if c not in move]  # all cols without the moved ones
        uid_idx = cols.index('uniqueid')
        cols = cols[:uid_idx] + move + cols[uid_idx:]    # insert before uniqueid
        df = df[cols]

    return df


class ExportVisits(BaseStage):
    name = 'export_visits'
    dependencies: list[str] = []

    def _zip_name(self, n: int) -> str:
        export_cfg = self.config.get('export') or {}
        r = export_cfg.get('round')
        if r is not None:
            return f'havi_ento_round{r}_{date.today().isoformat()}.zip'
        return f'havi_visit{n}_export_{date.today().isoformat()}.zip'

    def _transform_mosquito(
        self, mosquito_df: pd.DataFrame, collection_df: pd.DataFrame, ds: str
    ) -> pd.DataFrame:
        """Hook for subclasses to transform the mosquito DataFrame before export."""
        return mosquito_df

    def _read_silver(self, table: str) -> pd.DataFrame:
        try:
            return pd.read_sql(f'SELECT * FROM silver_havi."{table}"', self.engine)
        except Exception as exc:
            logger.warning("Could not read silver_havi.%s: %s", table, exc)
            return pd.DataFrame()

    def run(self) -> StageResult:
        export_cfg = self.config.get('export') or {}
        n = int(export_cfg.get('n_collections', 3))
        mrccodes: list[str] | None = export_cfg.get('mrccodes') or None
        errors: list[str] = []
        csv_buffers: dict[str, io.StringIO] = {}
        total_rows = 0

        # ── Load silver tables ────────────────────────────────────────────
        collection_df = self._read_silver('ento_collection')
        mosquito_df = self._read_silver('ento_mosquito')
        household_df = self._read_silver('hbo_household')
        person_df = self._read_silver('hbo_person')

        # ── Apply site filter ─────────────────────────────────────────────
        if mrccodes:
            mrccodes_str = [str(m) for m in mrccodes]
            logger.info("Filtering export to MRC(s): %s", mrccodes_str)
            if not collection_df.empty and 'mrccode' in collection_df.columns:
                collection_df = collection_df[collection_df['mrccode'].astype(str).isin(mrccodes_str)]
            if not household_df.empty and 'mrccode' in household_df.columns:
                household_df = household_df[household_df['mrccode'].astype(str).isin(mrccodes_str)]

        # ── Entomology: first n nights per household, split by datasource ──
        # datasource=1 → HLC (Human Landing Catches): hlc_collection / hlc_mosquito
        # datasource=2 → Indoor Aspirations:          aspirations_collection / aspirations_mosquito
        _DS_LABELS = {'1': 'hlc', '2': 'aspirations'}

        _hlc_for_report: list[pd.DataFrame] = []  # filtered HLC rows used for excluded_households.txt

        if not collection_df.empty and 'hhid' in collection_df.columns:
            try:
                datasources = (
                    sorted(collection_df['datasource'].dropna().astype(str).unique())
                    if 'datasource' in collection_df.columns
                    else ['']
                )

                for ds in datasources:
                    label = _DS_LABELS.get(ds, f'ds{ds}')
                    ds_collection = (
                        collection_df[collection_df['datasource'].astype(str) == ds].copy()
                        if ds else collection_df.copy()
                    )

                    # Apply first-n-nights filter independently per datasource so
                    # aspirations dates (later in calendar) are not ranked against HLC nights.
                    # Use dateofcollection (canonical night date) — starttime spans midnight
                    # so indoor morning records would get a different calendar date.
                    date_col = 'dateofcollection' if 'dateofcollection' in ds_collection.columns else 'starttime'
                    mask = _first_n_sessions(ds_collection, date_col, n)
                    ds_collection = ds_collection[mask].copy()

                    # Track filtered HLC rows for the excluded-households report
                    if ds == '1':
                        _hlc_for_report.append(ds_collection)

                    # datasource=1 (HLC): aspirations_method not applicable → -9
                    # datasource=2 (aspirations): clocation not applicable → -9
                    if ds == '1':
                        if 'aspirations_method' in ds_collection.columns:
                            ds_collection['aspirations_method'] = -9
                    elif ds == '2':
                        if 'clocation' in ds_collection.columns:
                            ds_collection['clocation'] = -9

                    col_name = f'{label}_collection.csv'
                    buf = io.StringIO()
                    _prep(ds_collection).to_csv(buf, index=False)
                    csv_buffers[col_name] = buf
                    total_rows += len(ds_collection)
                    logger.info("%s collection: %d row(s) → %s", label, len(ds_collection), col_name)

                    if not mosquito_df.empty and 'session_id' in mosquito_df.columns:
                        ds_sessions = set(ds_collection['session_id'].dropna().astype(str))
                        ds_mosquito = mosquito_df[
                            mosquito_df['session_id'].astype(str).isin(ds_sessions)
                        ].copy()
                        if ds == '1' and 'aspirations_method' in ds_mosquito.columns:
                            ds_mosquito['aspirations_method'] = -9
                        elif ds == '2' and 'clocation' in ds_mosquito.columns:
                            ds_mosquito['clocation'] = -9
                        ds_mosquito = self._transform_mosquito(ds_mosquito, ds_collection, ds)
                        mosq_name = f'{label}_mosquito.csv'
                        buf = io.StringIO()
                        _prep(ds_mosquito).to_csv(buf, index=False)
                        csv_buffers[mosq_name] = buf
                        total_rows += len(ds_mosquito)
                        logger.info("%s mosquito: %d row(s) → %s", label, len(ds_mosquito), mosq_name)

            except Exception as exc:
                msg = f"Entomology export failed: {exc}"
                logger.error(msg)
                errors.append(msg)
        else:
            logger.warning("ento_collection is empty or missing hhid — skipping HLC export.")

        # ── HBO: first n nights per household ────────────────────────────
        if not household_df.empty and 'hhid' in household_df.columns:
            try:
                mask = _first_n_sessions(household_df, 'dateofobservation', n)
                hbo_household = household_df[mask].copy()
                hbo_sessions = set(hbo_household['session_id'].dropna().astype(str))

                # Household CSV
                buf = io.StringIO()
                _prep(hbo_household).to_csv(buf, index=False)
                csv_buffers['hbo_household.csv'] = buf
                total_rows += len(hbo_household)
                logger.info("HBO household: %d row(s).", len(hbo_household))

                # Person CSV — filter by session_id
                if not person_df.empty and 'session_id' in person_df.columns:
                    hbo_person = person_df[
                        person_df['session_id'].astype(str).isin(hbo_sessions)
                    ]
                    buf = io.StringIO()
                    _prep(hbo_person).to_csv(buf, index=False)
                    csv_buffers['hbo_person.csv'] = buf
                    total_rows += len(hbo_person)
                    logger.info("HBO person: %d row(s).", len(hbo_person))

            except Exception as exc:
                msg = f"HBO export failed: {exc}"
                logger.error(msg)
                errors.append(msg)
        else:
            logger.warning("hbo_household is empty or missing hhid — skipping HBO export.")

        if not csv_buffers:
            logger.warning("Nothing to export.")
            return StageResult(success=len(errors) == 0, rows_written=0, errors=errors)

        # ── Build zip ─────────────────────────────────────────────────────
        zip_name = self._zip_name(n)
        zip_buffer = io.BytesIO()

        mrc_sites: dict[str, str] = self.config.get('mrc_sites') or {}
        hlc_export_df = pd.concat(_hlc_for_report, ignore_index=True) if _hlc_for_report else pd.DataFrame()
        partial_report = build_partial_hhid_report(hlc_export_df, mrc_sites)

        with zipfile.ZipFile(zip_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for name, buf in csv_buffers.items():
                zf.writestr(name, buf.getvalue())
            zf.writestr('excluded_households.txt', partial_report)

        zip_size_kb = round(zip_buffer.tell() / 1024, 1)
        logger.info(
            "Created '%s' with %d file(s) (%.1f KB).",
            zip_name, len(csv_buffers), zip_size_kb,
        )

        if errors:
            return StageResult(success=False, rows_written=total_rows, errors=errors)

        # ── Save to disk ──────────────────────────────────────────────────
        output_dir = Path('Output')
        output_dir.mkdir(exist_ok=True)
        local_path = output_dir / zip_name
        local_path.write_bytes(zip_buffer.getvalue())
        logger.info("Saved '%s' to %s.", zip_name, local_path.resolve())

        # ── Upload to Box ─────────────────────────────────────────────────
        folder_id = (self.config.get('box') or {}).get('folder_id')

        if not folder_id:
            logger.info("No Box folder_id configured — zip saved locally only.")
            return StageResult(success=True, rows_written=total_rows)

        client = get_box_client()
        if client is None:
            return StageResult(
                success=False,
                rows_written=total_rows,
                errors=["Box upload configured but credentials/client were unavailable."],
            )

        try:
            zip_buffer.seek(0)
            uploaded = client.folder(folder_id).upload_stream(zip_buffer, zip_name)
            logger.info(
                "Uploaded '%s' to Box folder %s (file ID: %s).",
                zip_name, folder_id, uploaded.id,
            )
        except Exception as exc:
            msg = f"Box upload failed: {exc}"
            logger.error(msg)
            errors.append(msg)

        return StageResult(
            success=len(errors) == 0,
            rows_written=total_rows,
            errors=errors,
        )
