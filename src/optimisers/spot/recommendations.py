def recommend_spot_optimisations(
    rows: list[dict],
    high_risk_spot_share: float = 0.5,
) -> list[dict]:
    if not rows:
        return []

    required = {"workload_id", "interruptions_30d", "is_stateless", "is_batch"}
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"Missing required columns for Spot recommendations: {sorted(missing)}")

    recommendations = []
    for row in rows:
        is_stateless = bool(row["is_stateless"])
        is_batch = bool(row["is_batch"])
        eligible = is_stateless or is_batch
        if not eligible:
            continue

        interruptions_30d = int(row["interruptions_30d"])
        risk_level = "low"
        if interruptions_30d >= 3:
            risk_level = "high"
        elif interruptions_30d >= 1:
            risk_level = "medium"

        if risk_level == "high":
            action = "use_mixed_capacity"
            spot_share = float(high_risk_spot_share)
            rationale = "High interruption rate detected, so mixed On-Demand and Spot capacity is safer."
            mitigations = [
                "Keep a baseline of On-Demand capacity",
                "Use retries and interruption handling",
                "Checkpoint long-running work",
            ]
        else:
            action = "use_spot_instances"
            spot_share = 1.0
            rationale = "Workload is stateless or batch and is suitable for Spot adoption."
            mitigations = [
                "Enable retries and autoscaling",
                "Handle Spot interruption notices gracefully",
            ]

        recommendations.append(
            {
                "resource_id": str(row["workload_id"]),
                "action": action,
                "spot_share": spot_share,
                "risk_level": risk_level,
                "rationale": rationale,
                "mitigations": mitigations,
            }
        )

    return recommendations
