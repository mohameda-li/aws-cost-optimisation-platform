def estimate_rds_savings(rows: list[dict]) -> dict:
    baseline_monthly_cost = 0.0
    optimised_monthly_cost = 0.0
    per_resource_costs = {}

    for row in rows:
        if "recommended_action" not in row or "baseline_monthly_cost" not in row:
            raise ValueError("Missing required columns: recommended_action or baseline_monthly_cost")

        baseline = float(row["baseline_monthly_cost"])
        action = row["recommended_action"]
        optimised = baseline
        if action == "STOP":
            optimised = baseline * 0.10
        elif action == "DOWNSIZE":
            optimised = baseline * 0.70

        resource_id = str(row.get("db_instance") or row.get("resource_id"))
        baseline_monthly_cost += baseline
        optimised_monthly_cost += optimised
        per_resource_costs[resource_id] = {
            "baseline_monthly_cost": round(baseline, 2),
            "optimised_monthly_cost": round(optimised, 2),
            "total_monthly_savings": round(baseline - optimised, 2),
        }

    total_monthly_savings = baseline_monthly_cost - optimised_monthly_cost
    return {
        "baseline_monthly_cost": round(baseline_monthly_cost, 2),
        "optimised_monthly_cost": round(optimised_monthly_cost, 2),
        "total_monthly_savings": round(total_monthly_savings, 2),
        "per_resource_costs": per_resource_costs,
    }
