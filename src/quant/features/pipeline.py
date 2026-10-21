"""Read-only source orchestration for the offline feature engine."""

from __future__ import annotations

import hashlib
from datetime import datetime
from io import BytesIO
from pathlib import Path

import polars as pl

from quant.features.engine import calculate_features
from quant.features.manifest import AnomalyManifest


def prepare_feature_snapshot(
    silver_path: Path,
    manifest_path: Path,
    *,
    analysis_as_of: datetime,
    generated_at: datetime,
) -> pl.DataFrame:
    """Read pinned local inputs and return a frame; do not write Gold output."""
    silver_bytes = silver_path.read_bytes()
    source_hash = hashlib.sha256(silver_bytes).hexdigest()
    silver = pl.read_parquet(BytesIO(silver_bytes))
    manifest = AnomalyManifest.load(manifest_path)
    return calculate_features(
        silver,
        manifest,
        analysis_as_of=analysis_as_of,
        generated_at=generated_at,
        source_snapshot_sha256=source_hash,
    )
