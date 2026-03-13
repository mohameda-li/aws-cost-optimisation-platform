def estimate_eks_savings(workload_rows: list[dict], recommendations: list[dict]) -> dict:
    targets = {}
    for rec in recommendations:
        if rec["action"] != "reduce_node_count":
            continue
        details = rec.get("details") or {}
        suggested = details.get("suggested_node_count")
        if suggested is not None:
            targets[str(rec["resource_id"])] = float(suggested)

    baseline_total = 0.0
    optimised_total = 0.0
    per_nodegroup_savings = {}
    per_resource_costs = {}

    for row in workload_rows:
        resource_id = f"{row['cluster_name']}/{row['nodegroup_name']}"
        desired_size = float(row["desired_size"])
        hours = float(row["hours_in_period"])
        hourly_rate = float(row["hourly_rate"])
        baseline_cost = float(row["baseline_monthly_cost"])

        suggested_node_count = min(targets.get(resource_id, desired_size), desired_size)
        suggested_node_count = max(suggested_node_count, 0.0)
        optimised_cost = suggested_node_count * hourly_rate * hours

        baseline_total += baseline_cost
        optimised_total += optimised_cost
        saving = baseline_cost - optimised_cost
        per_nodegroup_savings[resource_id] = round(saving, 2)
        per_resource_costs[resource_id] = {
            "baseline_monthly_cost": round(baseline_cost, 2),
            "optimised_monthly_cost": round(optimised_cost, 2),
            "total_monthly_savings": round(saving, 2),
        }

    return {
        "baseline_monthly_cost": round(baseline_total, 2),
        "optimised_monthly_cost": round(optimised_total, 2),
        "total_monthly_savings": round(baseline_total - optimised_total, 2),
        "per_nodegroup_savings": per_nodegroup_savings,
        "per_resource_costs": per_resource_costs,
    }
