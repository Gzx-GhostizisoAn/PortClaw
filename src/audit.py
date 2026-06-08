from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from .schemas import AuditRecord, DailyBrief


class AuditStore:
    def __init__(self, root: str | Path = "audit_runs"):
        self.root = Path(root)

    def save_daily_run(
        self,
        brief: DailyBrief,
        llm_input: Dict[str, Any] | None = None,
        llm_output: str | None = None,
    ) -> AuditRecord:
        run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        brief_path = run_dir / "daily_brief.json"
        llm_input_path = run_dir / "llm_input.json"
        llm_output_path = run_dir / "llm_output.txt"

        brief_json = brief.model_dump(mode="json")
        brief_path.write_text(json.dumps(brief_json, ensure_ascii=False, indent=2), encoding="utf-8")

        if llm_input is not None:
            llm_input_path.write_text(json.dumps(llm_input, ensure_ascii=False, indent=2), encoding="utf-8")
        if llm_output is not None:
            llm_output_path.write_text(llm_output, encoding="utf-8")

        return AuditRecord(
            audit_id=run_id,
            created_at=datetime.utcnow(),
            portfolio_snapshot_id=brief.portfolio_snapshot.snapshot_id,
            metric_object_ids=[item.symbol for item in brief.asset_metrics],
            signal_ids=[item.signal_id for item in brief.signals],
            risk_theme_ids=[item.theme_id for item in brief.risk_themes],
            llm_input=llm_input,
            llm_output=llm_output,
            storage_paths={
                "daily_brief": str(brief_path),
                "llm_input": str(llm_input_path) if llm_input is not None else "",
                "llm_output": str(llm_output_path) if llm_output is not None else "",
                "brief_hash": self._hash_payload(brief_json),
            },
        )

    def _hash_payload(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
