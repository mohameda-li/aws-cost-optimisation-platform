import csv


def calculate_ecs_cost(
    usage_path: str = "data/ecs/ecs_usage_cloudwatch.csv",
    pricing_path: str = "data/ecs/ecs_pricing.csv",
) -> list[dict]:
    with open(usage_path, newline="", encoding="utf-8") as handle:
        usage_rows = list(csv.DictReader(handle))
    with open(pricing_path, newline="", encoding="utf-8") as handle:
        pricing_rows = list(csv.DictReader(handle))

    if not pricing_rows:
        raise ValueError("ecs_pricing.csv is empty")
    if not usage_rows:
        return []

    pricing_required = {"pricing_model", "vcpu_per_hour", "gb_per_hour"}
    usage_required = {
        "service_name",
        "desired_count",
        "running_count",
        "vcpu_per_task",
        "mem_gb_per_task",
        "cpu_avg_pct",
        "mem_avg_pct",
        "running_hours",
    }

    missing_p = pricing_required - set(pricing_rows[0].keys())
    missing_u = usage_required - set(usage_rows[0].keys())
    if missing_p:
        raise ValueError(f"ecs_pricing.csv missing columns: {sorted(missing_p)}")
    if missing_u:
        raise ValueError(f"ecs_usage_cloudwatch.csv missing columns: {sorted(missing_u)}")

    try:
        vcpu_rate = float(pricing_rows[0]["vcpu_per_hour"])
        gb_rate = float(pricing_rows[0]["gb_per_hour"])
    except (TypeError, ValueError):
        raise ValueError("Invalid vcpu_per_hour or gb_per_hour in ecs_pricing.csv")

    pricing_model = str(pricing_rows[0]["pricing_model"])
    results = []
    for row in usage_rows:
        service_name = str(row["service_name"]).strip()
        try:
            desired_count = float(row["desired_count"])
            running_count = float(row["running_count"])
            vcpu_per_task = float(row["vcpu_per_task"])
            mem_gb_per_task = float(row["mem_gb_per_task"])
            cpu_avg_pct = float(row["cpu_avg_pct"])
            mem_avg_pct = float(row["mem_avg_pct"])
            running_hours = float(row["running_hours"])
        except (TypeError, ValueError):
            raise ValueError(f"Invalid numeric values in ecs usage CSV for service_name: {service_name}")

        reserved_vcpu = vcpu_per_task * desired_count
        reserved_mem_gb = mem_gb_per_task * desired_count
        avg_vcpu_used = reserved_vcpu * (cpu_avg_pct / 100.0)
        avg_mem_gb_used = reserved_mem_gb * (mem_avg_pct / 100.0)
        monthly_cost_cpu = reserved_vcpu * vcpu_rate * running_hours
        monthly_cost_mem = reserved_mem_gb * gb_rate * running_hours

        results.append(
            {
                "service_name": service_name,
                "desired_count": desired_count,
                "running_count": running_count,
                "vcpu_per_task": vcpu_per_task,
                "mem_gb_per_task": mem_gb_per_task,
                "reserved_vcpu": reserved_vcpu,
                "reserved_mem_gb": reserved_mem_gb,
                "cpu_avg_pct": cpu_avg_pct,
                "mem_avg_pct": mem_avg_pct,
                "avg_vcpu_used": avg_vcpu_used,
                "avg_mem_gb_used": avg_mem_gb_used,
                "running_hours": running_hours,
                "monthly_cost_cpu": monthly_cost_cpu,
                "monthly_cost_mem": monthly_cost_mem,
                "baseline_monthly_cost": monthly_cost_cpu + monthly_cost_mem,
                "pricing_model": pricing_model,
                "vcpu_per_hour": vcpu_rate,
                "gb_per_hour": gb_rate,
                "pricing_source": pricing_path,
            }
        )

    return results
