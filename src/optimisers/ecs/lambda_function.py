import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

try:
    from .cost_analysis import calculate_ecs_cost
    from .recommendations import recommend_ecs_optimisations
    from .savings import estimate_ecs_savings
except ImportError:
    from cost_analysis import calculate_ecs_cost
    from recommendations import recommend_ecs_optimisations
    from savings import estimate_ecs_savings


AWS_REGION = os.getenv("AWS_REGION", "eu-west-2")
ECS_CLUSTER = os.getenv("ECS_CLUSTER", "")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "7"))
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "0.30"))
MEM_THRESHOLD = float(os.getenv("MEM_THRESHOLD", "0.30"))

_BOTO_CFG = Config(retries={"max_attempts": 8, "mode": "standard"})

ecs = boto3.client("ecs", region_name=AWS_REGION, config=_BOTO_CFG)
cw = boto3.client("cloudwatch", region_name=AWS_REGION, config=_BOTO_CFG)


def _empty_response(reason: str, status_code: int = 200):
    return {
        "statusCode": status_code,
        "body": json.dumps({
            "service": "ecs",
            "resources_analysed": 0,
            "findings_count": 0,
            "baseline_monthly_cost": 0.0,
            "optimised_monthly_cost": 0.0,
            "total_monthly_savings": 0.0,
            "recommendations": [],
            "details": {
                "reason": reason,
                "region": AWS_REGION,
                "cluster": ECS_CLUSTER,
            },
        })
    }


def _cw_avg_pct(namespace: str, metric: str, dims: list[dict], start: datetime, end: datetime) -> Optional[float]:
    try:
        resp = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric,
            Dimensions=dims,
            StartTime=start,
            EndTime=end,
            Period=3600,
            Statistics=["Average"],
        )
    except (ClientError, BotoCoreError):
        return None

    datapoints = resp.get("Datapoints", []) or []
    if not datapoints:
        return None

    values = [float(point["Average"]) for point in datapoints if "Average" in point]
    if not values:
        return None

    return sum(values) / len(values)


def _service_cpu_mem_avg(cluster: str, service_name: str) -> Tuple[Optional[float], Optional[float]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)

    dims = [
        {"Name": "ClusterName", "Value": cluster},
        {"Name": "ServiceName", "Value": service_name},
    ]

    cpu = _cw_avg_pct("ECS/ContainerInsights", "CPUUtilization", dims, start, end)
    mem = _cw_avg_pct("ECS/ContainerInsights", "MemoryUtilization", dims, start, end)
    return cpu, mem


def _list_all_services(cluster: str) -> list[str]:
    arns = []
    token = None
    while True:
        kwargs = {"cluster": cluster}
        if token:
            kwargs["nextToken"] = token
        resp = ecs.list_services(**kwargs)
        arns.extend(resp.get("serviceArns", []) or [])
        token = resp.get("nextToken")
        if not token:
            break
    return arns


def _chunks(items, size=10):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _parse_taskdef_cpu_mem(task_def: dict) -> Tuple[Optional[float], Optional[float]]:
    cpu_units = task_def.get("cpu")
    mem_mib = task_def.get("memory")

    def to_float(value):
        try:
            return float(value)
        except Exception:
            return None

    cpu_units_f = to_float(cpu_units)
    mem_mib_f = to_float(mem_mib)

    if cpu_units_f is None or mem_mib_f is None:
        cdefs = task_def.get("containerDefinitions", []) or []

        if cpu_units_f is None:
            cpu_sum = 0.0
            got = False
            for c in cdefs:
                value = to_float(c.get("cpu"))
                if value is not None:
                    cpu_sum += value
                    got = True
            cpu_units_f = cpu_sum if got else None

        if mem_mib_f is None:
            mem_sum = 0.0
            got = False
            for c in cdefs:
                value = to_float(c.get("memory"))
                if value is None:
                    value = to_float(c.get("memoryReservation"))
                if value is not None:
                    mem_sum += value
                    got = True
            mem_mib_f = mem_sum if got else None

    vcpu = (cpu_units_f / 1024.0) if cpu_units_f is not None else None
    mem_gb = (mem_mib_f / 1024.0) if mem_mib_f is not None else None
    return vcpu, mem_gb


def _write_live_usage_csv() -> str:
    if not ECS_CLUSTER.strip():
        raise ValueError("ECS_CLUSTER environment variable is required")

    out_dir = Path("/tmp/ecs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "ecs_usage_live.csv"
    running_hours = LOOKBACK_DAYS * 24

    service_arns = _list_all_services(ECS_CLUSTER)

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "service_name",
            "desired_count",
            "running_count",
            "vcpu_per_task",
            "mem_gb_per_task",
            "cpu_avg_pct",
            "mem_avg_pct",
            "running_hours",
        ])

        if not service_arns:
            return str(out_csv)

        for batch in _chunks(service_arns, size=10):
            resp = ecs.describe_services(cluster=ECS_CLUSTER, services=batch)
            services = resp.get("services", []) or []

            for service in services:
                service_name = service.get("serviceName", "")
                desired = int(service.get("desiredCount") or 0)
                running = int(service.get("runningCount") or 0)

                vcpu_per_task = None
                mem_gb_per_task = None
                task_def_arn = service.get("taskDefinition")

                if task_def_arn:
                    try:
                        task_def = ecs.describe_task_definition(taskDefinition=task_def_arn).get("taskDefinition") or {}
                        vcpu_per_task, mem_gb_per_task = _parse_taskdef_cpu_mem(task_def)
                    except Exception:
                        vcpu_per_task, mem_gb_per_task = None, None

                cpu_avg, mem_avg = _service_cpu_mem_avg(ECS_CLUSTER, service_name)

                writer.writerow([
                    service_name,
                    desired,
                    running,
                    round(vcpu_per_task, 2) if vcpu_per_task is not None else "",
                    round(mem_gb_per_task, 2) if mem_gb_per_task is not None else "",
                    round(cpu_avg, 2) if cpu_avg is not None else "",
                    round(mem_avg, 2) if mem_avg is not None else "",
                    running_hours,
                ])

    return str(out_csv)


def handler(event, context):
    try:
        usage_path = _write_live_usage_csv()
        pricing_path = os.getenv("ECS_PRICING_PATH", "data/ecs/ecs_pricing.csv")

        cost_df = calculate_ecs_cost(
            usage_path=usage_path,
            pricing_path=pricing_path,
        )

        if not cost_df:
            return _empty_response("No ECS services found to analyse.")

        recommendations_df = recommend_ecs_optimisations(
            cost_df,
            cpu_threshold=CPU_THRESHOLD,
            mem_threshold=MEM_THRESHOLD,
        )

        ecs_savings = estimate_ecs_savings(cost_df, recommendations_df)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "service": "ecs",
                "resources_analysed": int(len(cost_df)),
                "findings_count": int(len(recommendations_df)),
                "baseline_monthly_cost": float(ecs_savings.get("baseline_monthly_cost", 0.0)),
                "optimised_monthly_cost": float(ecs_savings.get("optimised_monthly_cost", 0.0)),
                "total_monthly_savings": float(ecs_savings.get("total_monthly_savings", 0.0)),
                "recommendations": recommendations_df,
                "per_resource_costs": ecs_savings.get("per_resource_costs", {}),
                "details": {
                    "region": AWS_REGION,
                    "cluster": ECS_CLUSTER,
                    "lookback_days": LOOKBACK_DAYS,
                    "cpu_threshold": CPU_THRESHOLD,
                    "mem_threshold": MEM_THRESHOLD,
                    "note": (
                        "Container Insights is required for CPUUtilization and MemoryUtilization metrics. "
                        "If metrics are missing, services may not produce useful recommendations."
                    ),
                },
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "service": "ecs",
                "error": "ECS optimiser failed",
                "details": str(e),
            })
        }
