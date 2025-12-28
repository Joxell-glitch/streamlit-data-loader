from __future__ import annotations

import time
from typing import Any, Dict

from src.db.models import RunMetadata


def create_run_metadata(session, run_id: str, config_snapshot: Dict[str, Any]) -> RunMetadata:
    run_metadata = RunMetadata(
        run_id=run_id,
        start_timestamp=time.time(),
        end_timestamp=None,
        config_snapshot=config_snapshot,
    )
    session.add(run_metadata)
    session.commit()
    return run_metadata


def update_run_metadata_end(session, run_id: str) -> None:
    run_metadata = session.query(RunMetadata).filter(RunMetadata.run_id == run_id).one_or_none()
    if run_metadata is None:
        return
    run_metadata.end_timestamp = time.time()
    session.commit()
