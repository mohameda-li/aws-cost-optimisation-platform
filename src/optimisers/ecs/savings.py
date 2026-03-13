def estimate_ecs_savings(service_rows: list[dict], recommendations: list[dict]) -> dict:
    required_s = {
        "service_name",
        "running_hours",
        "reserved_vcpu",
        "reserved_mem_gb",
        "vcpu_per_hour",
        "gb_per_hour",
        "baseline_monthly_cost",
    }
    required_r = {"resource_id", "action", "details"}

    if service_rows:
        missing_s = required_s - set(service_rows[0].keys())
        if missing_s:
            raise ValueError(f"Missing required service columns for ECS savings: {sorted(missing_s)}")
    if recommendations:
        missing_r = required_r - set(recommendations[0].keys())
        if missing_r:
            raise ValueError(f"Missing required recommendation columns for ECS savings: {sorted(missing_r)}")

    targets = {}
    for rec in recommendations:
        if rec["action"] != "rightsize_service":
            continue
        target = targets.setdefault(str(rec["resource_id"]), {})
        for detail in rec.get("details") or []:
            if detail.get("metric") == "cpu":
                target["reserved_vcpu"] = float(detail.get("suggested_reserved", 0.0))
            elif detail.get("metric") == "memory":
                target["reserved_mem_gb"] = float(detail.get("suggested_reserved", 0.0))

    baseline_total = 0.0
    optimised_total = 0.0
    per_service_savings = {}
    per_resource_costs = {}

    for row in service_rows:
        name = str(row["service_name"])
        hours = float(row["running_hours"])
        base_cpu = float(row["reserved_vcpu"])
        base_mem = float(row["reserved_mem_gb"])
        vcpu_rate = float(row["vcpu_per_hour"])
        mem_rate = float(row["gb_per_hour"])

        baseline_cost = (base_cpu * vcpu_rate * hours) + (base_mem * mem_rate * hours)
        target = targets.get(name, {})
        opt_cpu = min(float(target.get("reserved_vcpu", base_cpu)), base_cpu)
        opt_mem = min(float(target.get("reserved_mem_gb", base_mem)), base_mem)
        optimised_cost = (opt_cpu * vcpu_rate * hours) + (opt_mem * mem_rate * hours)

        baseline_total += baseline_cost
        optimised_total += optimised_cost
        saving = baseline_cost - optimised_cost
        per_service_savings[name] = round(saving, 2)
        per_resource_costs[name] = {
            "baseline_monthly_cost": round(baseline_cost, 2),
            "optimised_monthly_cost": round(optimised_cost, 2),
            "total_monthly_savings": round(saving, 2),
        }

    return {
        "baseline_monthly_cost": round(baseline_total, 2),
        "optimised_monthly_cost": round(optimised_total, 2),
        "total_monthly_savings": round(baseline_total - optimised_total, 2),
        "per_service_savings": per_service_savings,
        "per_resource_costs": per_resource_costs,
    }
