"""Quality gates — sanity checks on mapping matrix output.

Called after Stage 4 (build matrix) to verify that counts are internally
consistent. Returns structured warnings rather than crashing — the pipeline
continues, but the operator sees what looks wrong.
"""


def check_decisions(matrix_summary):
    """Check mapping matrix summary for internal consistency.

    Args:
        matrix_summary: The summary dict from mapping-matrix.json.

    Returns:
        List of warning dicts: [{severity, code, message, detail}]
    """
    warnings = []
    total = matrix_summary.get("totalConcepts", 0)
    if total == 0:
        warnings.append({
            "severity": "error",
            "code": "QG-001",
            "message": "No concepts in mapping matrix — matrix builder produced empty output.",
            "detail": None,
        })
        return warnings

    # --- QG-002: Action counts must sum to total ---
    action_counts = matrix_summary.get("actionCounts", {})
    accounted = sum(action_counts.values())
    if accounted != total:
        breakdown = ", ".join(f"{k}({v})" for k, v in sorted(action_counts.items()))
        warnings.append({
            "severity": "error",
            "code": "QG-002",
            "message": (
                f"Action counts don't sum to total: "
                f"{breakdown} = {accounted}, expected {total}."
            ),
            "detail": "This indicates a bug in the matrix builder.",
        })

    # --- QG-003: Property stats must be internally consistent ---
    ps = matrix_summary.get("propertyStats")
    if ps:
        ps_total = ps.get("total", 0)
        ps_reuse = ps.get("reuseProperty", 0)
        ps_create = ps.get("createProperty", 0)
        ps_sum = ps_reuse + ps_create
        if ps_total != ps_sum:
            warnings.append({
                "severity": "warning",
                "code": "QG-003",
                "message": (
                    f"Property stats don't sum: "
                    f"reuseProperty({ps_reuse}) + createProperty({ps_create}) "
                    f"= {ps_sum}, expected total({ps_total})."
                ),
                "detail": "This indicates a bug in the matrix builder or an unrecognized property action.",
            })

    return warnings


def format_warnings(warnings):
    """Format warning list for console output.

    Returns a multi-line string, or empty string if no warnings.
    """
    if not warnings:
        return ""

    lines = ["\n  Quality Gate Results:"]
    for w in warnings:
        icon = {"error": "!!", "warning": "!", "info": "-"}.get(w["severity"], "?")
        lines.append(f"    [{icon}] {w['code']}: {w['message']}")
        if w.get("detail"):
            lines.append(f"        {w['detail']}")

    errors = sum(1 for w in warnings if w["severity"] == "error")
    warns = sum(1 for w in warnings if w["severity"] == "warning")
    infos = sum(1 for w in warnings if w["severity"] == "info")
    lines.append(f"    ({errors} errors, {warns} warnings, {infos} info)")
    return "\n".join(lines)
