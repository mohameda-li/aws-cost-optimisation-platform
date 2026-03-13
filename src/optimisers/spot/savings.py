def estimate_spot_savings(workload_rows: list[dict], recommendations: list[dict]) -> dict:
    required_w = {"workload_id", "baseline_monthly_cost", "on_demand_cost", "spot_cost"}
    required_r = {"resource_id", "spot_share"}

    if workload_rows:
        missing_w = required_w - set(workload_rows[0].keys())
        if missing_w:
            raise ValueError(f"Missing required workload columns for Spot savings: {sorted(missing_w)}")
    if recommendations:
        missing_r = required_r - set(recommendations[0].keys())
        if missing_r:
            raise ValueError(f"Missing required recommendation columns for Spot savings: {sorted(missing_r)}")

    spot_shares = {}
    for rec in recommendations:
        try:
            spot_share = max(0.0, min(float(rec["spot_share"]), 1.0))
        except (TypeError, ValueError):
            spot_share = 0.0
        spot_shares[str(rec["resource_id"])] = spot_share

    baseline_total = 0.0
    optimised_total = 0.0
    per_workload_savings = {}
    per_resource_costs = {}

    for row in workload_rows:
        workload_id = str(row["workload_id"])
        on_demand_cost = float(row["on_demand_cost"])
        spot_cost = float(row["spot_cost"])
        baseline_cost = float(row["baseline_monthly_cost"])
        spot_share = spot_shares.get(workload_id, 0.0)

        chosen_cost = on_demand_cost * (1.0 - spot_share) + spot_cost * spot_share
        baseline_total += baseline_cost
        optimised_total += chosen_cost

        if spot_share > 0:
            saving = on_demand_cost - chosen_cost
            per_workload_savings[workload_id] = round(saving, 2)
            per_resource_costs[workload_id] = {
                "baseline_monthly_cost": round(on_demand_cost, 2),
                "optimised_monthly_cost": round(chosen_cost, 2),
                "total_monthly_savings": round(saving, 2),
            }

    return {
        "baseline_monthly_cost": round(baseline_total, 2),
        "optimised_monthly_cost": round(optimised_total, 2),
        "total_monthly_savings": round(baseline_total - optimised_total, 2),
        "per_workload_savings": per_workload_savings,
        "per_resource_costs": per_resource_costs,
    }
