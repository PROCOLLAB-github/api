"""Publish the paired GitHub runner's mixed results to the job summary."""

import json
import os
from pathlib import Path

SCENARIO_OVERVIEW = "management_analytics_overview"
SCENARIO_ACCEPTANCE = "participant_export_acceptance"


def measure(value):
    return "—" if value is None else f"{value:.2f}"


def mixed_results(path):
    if not path.is_file():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    phase = next((phase for phase in report["phases"] if phase["name"] == "mixed"), {})
    if not phase:
        return None
    scenarios = {scenario["name"]: scenario for scenario in phase["scenarios"]}
    overview = scenarios[SCENARIO_OVERVIEW]
    acceptance = scenarios.get(SCENARIO_ACCEPTANCE, {})
    exports = phase["exports"]
    return [
        measure(overview["median_ms"]),
        measure(overview["latency_ms"]["p95"]),
        measure(acceptance.get("median_ms")),
        measure(acceptance.get("latency_ms", {}).get("p95")),
        measure(exports["all_downloaded_seconds"]),
        measure(exports["all_validated_seconds"]),
        str(exports["verified_files"]),
        str(exports["overview_requests_overlapping_export"]),
        str(phase["peak_in_flight_requests"]),
        str(exports["peak_overlapping_export_windows"]),
        str(sum(phase["errors"].values()) + len(report["errors"])),
    ]


def main():
    lines = [
        f'## Participant export queue comparison ({os.environ["PROCOLLAB_PERF_ORDER"]})',
        "",
        "| Mode | Overview median ms | Overview p95 ms | POST median ms | POST p95 ms "
        "| All downloaded s | All validated s | Verified files | Overlapping Overview requests "
        "| Peak HTTP | Peak export windows | Errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    results = Path("perf-results")
    for mode in os.environ["PROCOLLAB_PERF_MODES"].split():
        row = mixed_results(results / f"mixed-{mode}.json")
        lines.append("| " + " | ".join([mode, *(row or ["—"] * 11)]) + " |")
    lines.extend(
        [
            "",
            "Export windows use HTTP request times for sync and worker timestamps for queued. "
            "Workbook validation begins after the HTTP phase.",
            "",
        ]
    )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines))


if __name__ == "__main__":
    main()
