import csv


def calculate_eks_cost(
    usage_path: str = "data/eks/eks_usage.csv",
    pricing_path: str = "data/eks/eks_pricing.csv",
) -> list[dict]:
    with open(usage_path, newline="", encoding="utf-8") as handle:
        usage_rows = list(csv.DictReader(handle))
    with open(pricing_path, newline="", encoding="utf-8") as handle:
        pricing_rows = list(csv.DictReader(handle))

    if not pricing_rows:
        raise ValueError("eks_pricing.csv is empty")
    if not usage_rows:
        return []

    usage_required = {
        "cluster_name",
        "nodegroup_name",
        "instance_type",
        "capacity_type",
        "desired_size",
        "min_size",
        "max_size",
    }
    pricing_required = {"instance_type", "hourly_rate"}

    missing_u = usage_required - set(usage_rows[0].keys())
    missing_p = pricing_required - set(pricing_rows[0].keys())
    if missing_u:
        raise ValueError(f"eks_usage.csv missing columns: {sorted(missing_u)}")
    if missing_p:
        raise ValueError(f"eks_pricing.csv missing columns: {sorted(missing_p)}")

    pricing_map = {}
    pricing_model = pricing_rows[0].get("pricing_model", "on_demand_nodes")
    for row in pricing_rows:
        instance_type = str(row["instance_type"]).strip()
        try:
            pricing_map[instance_type] = float(row["hourly_rate"])
        except (TypeError, ValueError):
            raise ValueError(f"Invalid hourly_rate in eks_pricing.csv for instance_type: {instance_type}")

    merged = []
    for row in usage_rows:
        instance_type = str(row["instance_type"]).strip()
        try:
            desired_size = float(row["desired_size"])
            min_size = float(row["min_size"])
            max_size = float(row["max_size"])
            hours_in_period = float(row.get("hours_in_period") or 24 * 30)
        except (TypeError, ValueError):
            key = f"{row.get('cluster_name', '')}/{row.get('nodegroup_name', '')}"
            raise ValueError(f"Invalid numeric values in eks_usage.csv for nodegroups: ['{key}']")

        avg_cpu_utilisation = row.get("avg_cpu_utilisation")
        avg_mem_utilisation = row.get("avg_mem_utilisation")
        try:
            avg_cpu_utilisation = None if avg_cpu_utilisation in ("", None) else float(avg_cpu_utilisation)
            avg_mem_utilisation = None if avg_mem_utilisation in ("", None) else float(avg_mem_utilisation)
        except (TypeError, ValueError):
            avg_cpu_utilisation = None
            avg_mem_utilisation = None

        hourly_rate = pricing_map.get(instance_type)
        if hourly_rate is None:
            raise ValueError(f"Missing pricing for instance_type: ['{instance_type}']")

        merged.append(
            {
                "cluster_name": row["cluster_name"],
                "nodegroup_name": row["nodegroup_name"],
                "instance_type": instance_type,
                "capacity_type": row["capacity_type"],
                "desired_size": desired_size,
                "min_size": min_size,
                "max_size": max_size,
                "avg_cpu_utilisation": avg_cpu_utilisation,
                "avg_mem_utilisation": avg_mem_utilisation,
                "hours_in_period": hours_in_period,
                "hourly_rate": hourly_rate,
                "baseline_monthly_cost": desired_size * hourly_rate * hours_in_period,
                "pricing_model": pricing_model,
                "pricing_source": pricing_path,
            }
        )

    return merged
