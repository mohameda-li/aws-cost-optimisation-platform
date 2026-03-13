def recommend_eks_optimisations(
    rows: list[dict],
    cpu_threshold: float = 0.35,
    mem_threshold: float = 0.35,
) -> list[dict]:
    if not rows:
        return []

    required = {
        "cluster_name",
        "nodegroup_name",
        "instance_type",
        "capacity_type",
        "desired_size",
        "min_size",
        "max_size",
        "hours_in_period",
        "hourly_rate",
        "baseline_monthly_cost",
    }
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"Missing required columns for EKS recommendations: {sorted(missing)}")

    recommendations = []
    for row in rows:
        resource_id = f"{row['cluster_name']}/{row['nodegroup_name']}"
        avg_cpu = row.get("avg_cpu_utilisation")
        avg_mem = row.get("avg_mem_utilisation")
        desired_size = float(row["desired_size"])
        min_size = float(row["min_size"])

        if avg_cpu is not None and avg_mem is not None and avg_cpu < cpu_threshold and avg_mem < mem_threshold and desired_size > min_size:
            suggested_node_count = int(desired_size - 1)
            recommendations.append(
                {
                    "resource_id": resource_id,
                    "action": "reduce_node_count",
                    "rationale": "Low average CPU and memory utilisation suggests the nodegroup may be over-provisioned",
                    "risk_level": "medium",
                    "details": {
                        "cluster_name": row["cluster_name"],
                        "nodegroup_name": row["nodegroup_name"],
                        "instance_type": row["instance_type"],
                        "capacity_type": row["capacity_type"],
                        "current_node_count": int(desired_size),
                        "min_size": int(min_size),
                        "max_size": int(float(row["max_size"])),
                        "suggested_node_count": suggested_node_count,
                        "avg_cpu_utilisation": float(avg_cpu),
                        "avg_mem_utilisation": float(avg_mem),
                        "hours_in_period": float(row["hours_in_period"]),
                    },
                }
            )

        if str(row["capacity_type"]).upper() == "ON_DEMAND":
            recommendations.append(
                {
                    "resource_id": resource_id,
                    "action": "consider_spot_or_mixed",
                    "rationale": "Nodegroup is ON_DEMAND; consider Spot or Mixed capacity for fault-tolerant workloads",
                    "risk_level": "medium",
                    "details": {
                        "cluster_name": row["cluster_name"],
                        "nodegroup_name": row["nodegroup_name"],
                        "instance_type": row["instance_type"],
                        "capacity_type": row["capacity_type"],
                        "current_node_count": int(desired_size),
                        "scaling": {
                            "min_size": int(min_size),
                            "max_size": int(float(row["max_size"])),
                        },
                        "note": "Savings depend on workload interruption tolerance and chosen Spot or Mixed strategy.",
                    },
                }
            )

    return recommendations
