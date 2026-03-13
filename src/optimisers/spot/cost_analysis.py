import csv


def _to_bool(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def calculate_spot_cost(
    usage_path: str = "data/spot/spot_usage.csv",
    pricing_path: str = "data/spot/spot_pricing.csv",
) -> list[dict]:
    with open(usage_path, newline="", encoding="utf-8") as handle:
        usage_rows = list(csv.DictReader(handle))
    with open(pricing_path, newline="", encoding="utf-8") as handle:
        pricing_rows = list(csv.DictReader(handle))

    if not pricing_rows:
        raise ValueError("spot_pricing.csv is empty")
    if not usage_rows:
        return []

    usage_required = {
        "workload_id",
        "instance_type",
        "hours_used",
        "interruptions_30d",
        "is_stateless",
        "is_batch",
    }
    pricing_required = {"instance_type", "on_demand_per_hour", "spot_per_hour"}

    missing_u = usage_required - set(usage_rows[0].keys())
    missing_p = pricing_required - set(pricing_rows[0].keys())
    if missing_u:
        raise ValueError(f"spot_usage.csv missing columns: {sorted(missing_u)}")
    if missing_p:
        raise ValueError(f"spot_pricing.csv missing columns: {sorted(missing_p)}")

    pricing_map = {}
    for row in pricing_rows:
        instance_type = str(row["instance_type"]).strip()
        try:
            pricing_map[instance_type] = {
                "on_demand_per_hour": float(row["on_demand_per_hour"]),
                "spot_per_hour": float(row["spot_per_hour"]),
            }
        except (TypeError, ValueError):
            raise ValueError(f"Invalid pricing values in spot_pricing.csv for instance_type: {instance_type}")

    merged = []
    for row in usage_rows:
        workload_id = str(row["workload_id"]).strip()
        instance_type = str(row["instance_type"]).strip()
        pricing = pricing_map.get(instance_type)
        if pricing is None:
            raise ValueError(f"Missing pricing for instance_type: ['{instance_type}']")

        try:
            hours_used = float(row["hours_used"])
            interruptions_30d = int(float(row["interruptions_30d"]))
        except (TypeError, ValueError):
            raise ValueError(f"Invalid numeric values in spot_usage.csv for workload_id: {workload_id}")

        on_demand_cost = hours_used * pricing["on_demand_per_hour"]
        spot_cost = hours_used * pricing["spot_per_hour"]
        merged.append(
            {
                "workload_id": workload_id,
                "instance_type": instance_type,
                "hours_used": hours_used,
                "interruptions_30d": interruptions_30d,
                "is_stateless": _to_bool(row["is_stateless"]),
                "is_batch": _to_bool(row["is_batch"]),
                "on_demand_per_hour": pricing["on_demand_per_hour"],
                "spot_per_hour": pricing["spot_per_hour"],
                "on_demand_cost": on_demand_cost,
                "spot_cost": spot_cost,
                "baseline_monthly_cost": on_demand_cost,
                "pricing_model": "spot_vs_on_demand",
                "pricing_source": pricing_path,
            }
        )

    return merged
