def recommend_ecs_optimisations(
    rows: list[dict],
    cpu_threshold: float = 0.30,
    mem_threshold: float = 0.30,
) -> list[dict]:
    if not rows:
        return []

    required = {
        "service_name",
        "reserved_vcpu",
        "reserved_mem_gb",
        "avg_vcpu_used",
        "avg_mem_gb_used",
        "cpu_avg_pct",
        "mem_avg_pct",
    }
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"Missing required columns for ECS recommendations: {sorted(missing)}")

    recommendations = []
    for row in rows:
        reserved_vcpu = float(row["reserved_vcpu"])
        reserved_mem_gb = float(row["reserved_mem_gb"])
        avg_vcpu_used = float(row["avg_vcpu_used"])
        avg_mem_gb_used = float(row["avg_mem_gb_used"])
        cpu_avg_pct = float(row["cpu_avg_pct"])
        mem_avg_pct = float(row["mem_avg_pct"])

        cpu_util = avg_vcpu_used / (reserved_vcpu if reserved_vcpu > 0 else 1.0)
        mem_util = avg_mem_gb_used / (reserved_mem_gb if reserved_mem_gb > 0 else 1.0)
        if cpu_util >= cpu_threshold and mem_util >= mem_threshold:
            continue

        details = []
        if cpu_util < cpu_threshold:
            suggested_cpu = max(round(avg_vcpu_used * 1.5, 2), 0.25)
            details.append(
                {
                    "metric": "cpu",
                    "current_reserved": reserved_vcpu,
                    "current_avg": avg_vcpu_used,
                    "suggested_reserved": min(suggested_cpu, reserved_vcpu),
                    "utilisation": round(cpu_util, 2),
                    "avg_pct": round(cpu_avg_pct, 2),
                }
            )
        if mem_util < mem_threshold:
            suggested_mem = max(round(avg_mem_gb_used * 1.5, 2), 0.50)
            details.append(
                {
                    "metric": "memory",
                    "current_reserved": reserved_mem_gb,
                    "current_avg": avg_mem_gb_used,
                    "suggested_reserved": min(suggested_mem, reserved_mem_gb),
                    "utilisation": round(mem_util, 2),
                    "avg_pct": round(mem_avg_pct, 2),
                }
            )

        recommendations.append(
            {
                "resource_id": str(row["service_name"]),
                "action": "rightsize_service",
                "rationale": "Average utilisation is low compared to reserved resources",
                "details": details,
                "risk_level": "low",
            }
        )

    return recommendations
