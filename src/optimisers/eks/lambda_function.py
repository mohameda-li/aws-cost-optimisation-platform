import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

try:
    from .cost_analysis import calculate_eks_cost
    from .recommendations import recommend_eks_optimisations
    from .savings import estimate_eks_savings
except ImportError:
    from cost_analysis import calculate_eks_cost
    from recommendations import recommend_eks_optimisations
    from savings import estimate_eks_savings


AWS_REGION = os.getenv("AWS_REGION", "eu-west-2")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "7"))
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "0.35"))
MEM_THRESHOLD = float(os.getenv("MEM_THRESHOLD", "0.35"))
TARGET_CLUSTER = os.getenv("TARGET_CLUSTER", "").strip()

_BOTO_CFG = Config(retries={"max_attempts": 8, "mode": "standard"})


def _empty_response(reason: str, status_code: int = 200):
    return {
        "statusCode": status_code,
        "body": json.dumps({
            "service": "eks",
            "resources_analysed": 0,
            "findings_count": 0,
            "baseline_monthly_cost": 0.0,
            "optimised_monthly_cost": 0.0,
            "total_monthly_savings": 0.0,
            "recommendations": [],
            "details": {
                "reason": reason,
                "region": AWS_REGION,
                "lookback_days": LOOKBACK_DAYS,
                "target_cluster": TARGET_CLUSTER or None,
            },
        })
    }


def _cw_avg_pct(cloudwatch, cluster_name: str, nodegroup_name: str, metric_name: str, start: datetime, end: datetime) -> Optional[float]:
    dims = [
        {"Name": "ClusterName", "Value": cluster_name},
        {"Name": "Nodegroup", "Value": nodegroup_name},
    ]

    try:
        response = cloudwatch.get_metric_statistics(
            Namespace="ContainerInsights",
            MetricName=metric_name,
            Dimensions=dims,
            StartTime=start,
            EndTime=end,
            Period=3600,
            Statistics=["Average"],
        )
    except (ClientError, BotoCoreError):
        return None

    datapoints = response.get("Datapoints", []) or []
    values = [float(point["Average"]) for point in datapoints if "Average" in point]
    return (sum(values) / len(values)) if values else None


def _write_live_usage_csv() -> str:
    eks = boto3.client("eks", region_name=AWS_REGION, config=_BOTO_CFG)
    cloudwatch = boto3.client("cloudwatch", region_name=AWS_REGION, config=_BOTO_CFG)

    out_dir = Path("/tmp/eks")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "eks_usage_live.csv"

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    hours_in_period = LOOKBACK_DAYS * 24

    try:
        clusters = eks.list_clusters().get("clusters", [])
    except Exception as e:
        raise RuntimeError(f"Failed to list EKS clusters: {str(e)}")

    if TARGET_CLUSTER:
        clusters = [c for c in clusters if c == TARGET_CLUSTER]

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "cluster_name",
            "nodegroup_name",
            "instance_type",
            "capacity_type",
            "desired_size",
            "min_size",
            "max_size",
            "avg_cpu_utilisation",
            "avg_mem_utilisation",
            "hours_in_period",
        ])

        for cluster_name in clusters:
            try:
                nodegroups = eks.list_nodegroups(clusterName=cluster_name).get("nodegroups", [])
            except Exception:
                continue

            for nodegroup_name in nodegroups:
                try:
                    nodegroup = eks.describe_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=nodegroup_name
                    ).get("nodegroup", {})
                except Exception:
                    continue

                instance_types = nodegroup.get("instanceTypes", []) or []
                instance_type = instance_types[0] if instance_types else ""

                scaling = nodegroup.get("scalingConfig", {}) or {}
                desired_size = scaling.get("desiredSize", 0)
                min_size = scaling.get("minSize", 0)
                max_size = scaling.get("maxSize", 0)
                capacity_type = nodegroup.get("capacityType", "ON_DEMAND")

                avg_cpu = _cw_avg_pct(
                    cloudwatch,
                    cluster_name,
                    nodegroup_name,
                    "node_cpu_utilization",
                    start,
                    end,
                )
                avg_mem = _cw_avg_pct(
                    cloudwatch,
                    cluster_name,
                    nodegroup_name,
                    "node_memory_utilization",
                    start,
                    end,
                )

                writer.writerow([
                    cluster_name,
                    nodegroup_name,
                    instance_type,
                    capacity_type,
                    desired_size,
                    min_size,
                    max_size,
                    round(avg_cpu / 100.0, 4) if avg_cpu is not None else "",
                    round(avg_mem / 100.0, 4) if avg_mem is not None else "",
                    hours_in_period,
                ])

    return str(out_csv)


def handler(event, context):
    try:
        usage_path = _write_live_usage_csv()
        pricing_path = os.getenv("EKS_PRICING_PATH", "data/eks/eks_pricing.csv")

        workloads_df = calculate_eks_cost(
            usage_path=usage_path,
            pricing_path=pricing_path,
        )

        if not workloads_df:
            return _empty_response("No EKS nodegroups found to analyse.")

        recommendations_df = recommend_eks_optimisations(
            workloads_df,
            cpu_threshold=CPU_THRESHOLD,
            mem_threshold=MEM_THRESHOLD,
        )
        savings = estimate_eks_savings(workloads_df, recommendations_df)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "service": "eks",
                "resources_analysed": int(len(workloads_df)),
                "findings_count": int(len(recommendations_df)),
                "baseline_monthly_cost": float(savings.get("baseline_monthly_cost", 0.0)),
                "optimised_monthly_cost": float(savings.get("optimised_monthly_cost", 0.0)),
                "total_monthly_savings": float(savings.get("total_monthly_savings", 0.0)),
                "recommendations": recommendations_df,
                "per_resource_costs": savings.get("per_resource_costs", {}),
                "details": {
                    "region": AWS_REGION,
                    "lookback_days": LOOKBACK_DAYS,
                    "target_cluster": TARGET_CLUSTER or None,
                    "cpu_threshold": CPU_THRESHOLD,
                    "mem_threshold": MEM_THRESHOLD,
                    "note": (
                        "Live utilisation depends on CloudWatch/Container Insights metrics for nodegroups. "
                        "If metrics are missing, only limited recommendations may be produced."
                    ),
                },
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "service": "eks",
                "error": "EKS optimiser failed",
                "details": str(e),
            })
        }
