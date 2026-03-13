def recommend_rds_optimisations(rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    required = {"avg_connections", "avg_cpu_utilisation"}
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"Missing required columns for RDS recommendations: {sorted(missing)}")

    recommendations = []
    for row in rows:
        avg_connections = float(row["avg_connections"])
        avg_cpu_utilisation = float(row["avg_cpu_utilisation"])

        recommended_action = "NO_CHANGE"
        risk_level = "low"
        rationale = "Usage suggests instance is active or required."

        if avg_connections == 0 and avg_cpu_utilisation < 5:
            recommended_action = "STOP"
            risk_level = "medium"
            rationale = "Instance appears idle based on near-zero connections and CPU."
        elif 0 < avg_connections < 5 and avg_cpu_utilisation < 20:
            recommended_action = "DOWNSIZE"
            risk_level = "low"
            rationale = "Instance shows low sustained utilisation and may be suitable for downsizing."

        enriched = dict(row)
        enriched.update(
            {
                "resource_id": row["db_instance"],
                "recommended_action": recommended_action,
                "risk_level": risk_level,
                "rationale": rationale,
            }
        )
        recommendations.append(enriched)

    return recommendations
