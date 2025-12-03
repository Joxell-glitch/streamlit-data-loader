from __future__ import annotations

import json
from pathlib import Path

from src.analysis.metrics import compute_metrics
from src.analysis.tuning import recommend_parameters


def generate_report(run_id: str, output_dir: str = "analysis_output") -> dict:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    metrics = compute_metrics(run_id)
    recommendations = recommend_parameters(run_id)

    report_path = Path(output_dir) / f"report_{run_id}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Run {run_id} Report\n\n")
        f.write("## Performance Summary\n")
        f.write(f"Total PnL: {metrics['pnl_summary']['total_pnl']:.4f}\n\n")
        f.write(f"Max Drawdown: {metrics['max_drawdown']:.2%}\n\n")
        f.write(f"Trade Frequency (per hour): {metrics['trade_frequency_per_hour']:.2f}\n\n")
        f.write("### Edge Distribution\n")
        f.write(f"{metrics['pnl_summary'].get('edge_distribution', {})}\n\n")
        f.write("## Recommendations\n")
        f.write(recommendations.get("summary_text", ""))

    rec_path = Path(output_dir) / f"recommendations_{run_id}.json"
    with open(rec_path, "w", encoding="utf-8") as f:
        json.dump(recommendations, f, indent=2)

    return {"report_path": str(report_path), "recommendations_path": str(rec_path)}
