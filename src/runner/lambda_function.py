import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict, List, Tuple

import boto3
from report_generator import generate_report_files


MONEY_KEYS_EXACT = {
    "baseline_monthly_cost",
    "optimised_monthly_cost",
    "optimized_monthly_cost",
    "total_monthly_savings",
    "estimated_monthly_savings",
    "cost_per_hour",
    "current_cost",
    "projected_cost",
    "estimated_savings",
}

MONEY_KEYS_SUFFIX = ("_cost", "_costs", "_savings")

SERVICE_MODULES = {
    "s3": "s3.lambda_function",
    "rds": "rds.lambda_function",
    "spot": "spot.lambda_function",
    "ecs": "ecs.lambda_function",
    "eks": "eks.lambda_function",
}


def _parse_body(resp: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(resp, dict):
        raise ValueError("Handler response must be a dict")
    if resp.get("statusCode") != 200:
        raise ValueError(f"Handler failed with statusCode={resp.get('statusCode')}")
    body = resp.get("body", "{}")
    return json.loads(body)


def _normalize_service_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten 'savings' into top-level cost fields so aggregation works."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    savings = out.get("savings")
    if isinstance(savings, dict):
        for key in (
            "baseline_monthly_cost",
            "optimised_monthly_cost",
            "optimized_monthly_cost",
            "total_monthly_savings",
        ):
            if key in savings and key not in out:
                out[key] = savings[key]
    return out


def _is_money_key(key: str) -> bool:
    if key in MONEY_KEYS_EXACT:
        return True
    return any(key.endswith(sfx) for sfx in MONEY_KEYS_SUFFIX)


def _round_money(value: Any) -> Any:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return round(float(value), 2)
    except (TypeError, ValueError):
        return value


def _normalise_payload(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out[k] = _normalise_payload(v)
            else:
                out[k] = _round_money(v) if _is_money_key(k) else v
        return out
    if isinstance(obj, list):
        return [_normalise_payload(x) for x in obj]
    return obj


def _safe_call(service_name: str, fn, event: Dict[str, Any], context) -> Dict[str, Any]:
    try:
        return {"status": "ok", "payload": _parse_body(fn(event, context))}
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "payload": {
                "service": service_name,
                "resources_analysed": 0,
                "findings_count": 0,
                "baseline_monthly_cost": 0.0,
                "optimised_monthly_cost": 0.0,
                "total_monthly_savings": 0.0,
                "recommendations": [],
                "per_resource_costs": {},
            },
        }


def _load_service_handler(service_name: str):
    module_name = SERVICE_MODULES.get(service_name)
    if not module_name:
        raise ValueError(f"No handler configured for service '{service_name}'")

    module = importlib.import_module(module_name)
    handler = getattr(module, "handler", None)
    if handler is None:
        raise ValueError(f"Module '{module_name}' does not expose a handler")
    return handler


def _decorate_recommendation_savings(services: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    rds = services.get("rds") or {}
    rds_recs = rds.get("recommendations") or []
    rds_per = rds.get("per_resource_costs") or {}

    if isinstance(rds_recs, list) and isinstance(rds_per, dict):
        for rec in rds_recs:
            if not isinstance(rec, dict):
                continue
            resource_id = rec.get("resource_id") or rec.get("db_instance")
            if resource_id and resource_id in rds_per:
                rec["estimated_monthly_savings"] = rds_per[resource_id].get("total_monthly_savings")
                rec["baseline_monthly_cost"] = rds_per[resource_id].get("baseline_monthly_cost")
                rec["optimised_monthly_cost"] = rds_per[resource_id].get("optimised_monthly_cost")

    eks = services.get("eks") or {}
    eks_recs = eks.get("recommendations") or []
    eks_per = eks.get("per_resource_costs") or {}

    if isinstance(eks_recs, list) and isinstance(eks_per, dict):
        for rec in eks_recs:
            if not isinstance(rec, dict):
                continue
            if rec.get("action") != "reduce_node_count":
                continue
            resource_id = rec.get("resource_id")
            if resource_id and resource_id in eks_per:
                rec["estimated_monthly_savings"] = eks_per[resource_id].get("total_monthly_savings")
                rec["baseline_monthly_cost"] = eks_per[resource_id].get("baseline_monthly_cost")
                rec["optimised_monthly_cost"] = eks_per[resource_id].get("optimised_monthly_cost")

    spot = services.get("spot") or {}
    spot_recs = spot.get("recommendations") or []
    spot_per = spot.get("per_resource_costs") or {}

    if isinstance(spot_recs, list) and isinstance(spot_per, dict):
        for rec in spot_recs:
            if not isinstance(rec, dict):
                continue
            resource_id = rec.get("resource_id")
            if resource_id and resource_id in spot_per:
                rec["estimated_monthly_savings"] = spot_per[resource_id].get("total_monthly_savings")
                rec["baseline_monthly_cost"] = spot_per[resource_id].get("baseline_monthly_cost")
                rec["optimised_monthly_cost"] = spot_per[resource_id].get("optimised_monthly_cost")

    ecs = services.get("ecs") or {}
    ecs_recs = ecs.get("recommendations") or []
    ecs_per = ecs.get("per_resource_costs") or {}

    if isinstance(ecs_recs, list) and isinstance(ecs_per, dict):
        for rec in ecs_recs:
            if not isinstance(rec, dict):
                continue
            resource_id = rec.get("resource_id")
            if resource_id and resource_id in ecs_per:
                rec["estimated_monthly_savings"] = ecs_per[resource_id].get("total_monthly_savings")
                rec["baseline_monthly_cost"] = ecs_per[resource_id].get("baseline_monthly_cost")
                rec["optimised_monthly_cost"] = ecs_per[resource_id].get("optimised_monthly_cost")

    s3 = services.get("s3") or {}
    s3_recs = s3.get("recommendations") or []
    s3_per = s3.get("per_resource_costs") or {}

    if isinstance(s3_recs, list) and isinstance(s3_per, dict):
        for rec in s3_recs:
            if not isinstance(rec, dict):
                continue
            resource_id = rec.get("resource_id") or rec.get("bucket")
            if resource_id and resource_id in s3_per:
                rec["estimated_monthly_savings"] = s3_per[resource_id].get("total_monthly_savings")
                rec["baseline_monthly_cost"] = s3_per[resource_id].get("baseline_monthly_cost")
                rec["optimised_monthly_cost"] = s3_per[resource_id].get("optimised_monthly_cost")

    return services


def _aggregate_totals(services: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    total_baseline = 0.0
    total_optimised = 0.0
    total_savings = 0.0

    for payload in services.values():
        baseline = payload.get("baseline_monthly_cost", 0.0) or 0.0
        optimised = payload.get("optimised_monthly_cost", payload.get("optimized_monthly_cost", 0.0)) or 0.0
        savings = payload.get("total_monthly_savings", 0.0) or 0.0

        total_baseline += float(baseline)
        total_optimised += float(optimised)
        total_savings += float(savings)

    return {
        "baseline_monthly_cost": round(total_baseline, 2),
        "optimised_monthly_cost": round(total_optimised, 2),
        "total_monthly_savings": round(total_savings, 2),
    }


def _top_actions(services: Dict[str, Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    candidates: List[Tuple[float, Dict[str, Any]]] = []

    for service_name, payload in services.items():
        recs = payload.get("recommendations", []) or []
        if not isinstance(recs, list):
            continue

        for rec in recs:
            if not isinstance(rec, dict):
                continue

            est = rec.get("estimated_monthly_savings")
            if est is None:
                b = rec.get("baseline_monthly_cost")
                o = rec.get("optimised_monthly_cost") or rec.get("optimized_monthly_cost")
                if b is not None and o is not None:
                    try:
                        est = float(b) - float(o)
                    except Exception:
                        est = None

            if est is None:
                continue

            try:
                est_val = float(est)
            except Exception:
                continue

            if est_val <= 0:
                continue

            resource_id = (
                rec.get("resource_id")
                or rec.get("bucket")
                or rec.get("db_instance")
                or rec.get("service_name")
                or rec.get("workload_id")
                or "unknown"
            )

            action = (
                rec.get("action")
                or rec.get("recommended_action")
                or rec.get("recommended_storage_class")
                or "recommendation"
            )

            candidates.append(
                (
                    est_val,
                    {
                        "service": service_name,
                        "resource_id": resource_id,
                        "action": action,
                        "risk_level": rec.get("risk_level", "unknown"),
                        "estimated_monthly_savings": est_val,
                    },
                )
            )

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in candidates[:limit]]


def _get_enabled_services_from_env() -> List[str]:
    raw = os.getenv("ENABLED_SERVICES", "")
    services = []
    for item in raw.split(","):
        service = item.strip().lower()
        if service and service not in services:
            services.append(service)
    return services


def handler(event, context):
    event = event or {}
    customer = event.get("customer") or os.getenv("COMPANY_NAME") or "customer"
    mode = (event.get("mode") or "live").lower().strip()

    enabled_services = _get_enabled_services_from_env()

    event_for_services = dict(event)
    event_for_services["customer"] = customer
    event_for_services["mode"] = mode
    event_for_services["enabled_services"] = enabled_services

    calls: Dict[str, Dict[str, Any]] = {}

    for service_name in enabled_services:
        try:
            service_handler = _load_service_handler(service_name)
        except Exception as e:
            calls[service_name] = {
                "status": "error",
                "error": str(e),
                "payload": {
                    "service": service_name,
                    "resources_analysed": 0,
                    "findings_count": 0,
                    "baseline_monthly_cost": 0.0,
                    "optimised_monthly_cost": 0.0,
                    "total_monthly_savings": 0.0,
                    "recommendations": [],
                    "per_resource_costs": {},
                },
            }
            continue

        calls[service_name] = _safe_call(service_name, service_handler, event_for_services, context)

    services = {
        name: _normalize_service_payload(result["payload"])
        for name, result in calls.items()
    }
    services = _decorate_recommendation_savings(services)

    errors = [
        {"service": name, "error": result.get("error")}
        for name, result in calls.items()
        if result.get("status") != "ok"
    ]

    totals = _aggregate_totals(services)

    savings_percent = 0.0
    if totals["baseline_monthly_cost"] > 0:
        savings_percent = round(
            (totals["total_monthly_savings"] / totals["baseline_monthly_cost"]) * 100, 2
        )

    platform_payload = {
        "platform": "finops-automation",
        "runner_version": "1.2",
        "customer": customer,
        "customer_label": str(customer).upper(),
        "run_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "mode": mode,
            "currency": "GBP",
            "enabled_services": enabled_services,
            "total_monthly_savings": totals["total_monthly_savings"],
            "savings_percent": savings_percent,
            "top_actions": _top_actions(services, limit=5),
            "errors": errors,
            "partial_run": len(errors) > 0,
        },
        "service_status": {
            name: result["status"] for name, result in calls.items()
        },
        "service_counts": {
            name: {
                "resources_analysed": result["payload"].get("resources_analysed", 0),
                "findings_count": result["payload"].get("findings_count", 0),
            }
            for name, result in calls.items()
        },
        "services": services,
        "totals": totals,
    }

    report_dir = Path("/tmp/finops_reports")
    report_dir.mkdir(parents=True, exist_ok=True)

    html_path, json_path = generate_report_files(
        payload=platform_payload,
        output_dir=report_dir,
        filename_prefix=f"{customer}_{platform_payload['run_id']}",
    )

    platform_payload["report_files"] = {
        "html_path": str(html_path),
        "json_path": str(json_path),
    }

    report_bucket = os.getenv("REPORT_BUCKET_NAME", "").strip()
    report_s3_keys = {}

    if report_bucket:
        region = os.getenv("AWS_REGION", "eu-west-2")
        run_id = platform_payload["run_id"]
        prefix = f"reports/{customer}/{run_id}"
        s3 = boto3.client("s3", region_name=region)

        try:
            s3.upload_file(
                str(html_path),
                report_bucket,
                f"{prefix}.html",
                ExtraArgs={"ContentType": "text/html; charset=utf-8"},
            )
            report_s3_keys["html_key"] = f"{prefix}.html"
        except Exception as e:
            report_s3_keys["html_upload_error"] = str(e)

        try:
            s3.upload_file(
                str(json_path),
                report_bucket,
                f"{prefix}.json",
                ExtraArgs={"ContentType": "application/json"},
            )
            report_s3_keys["json_key"] = f"{prefix}.json"
        except Exception as e:
            report_s3_keys["json_upload_error"] = str(e)

        platform_payload["report_files"]["s3_bucket"] = report_bucket
        platform_payload["report_files"]["s3_keys"] = report_s3_keys

    platform_payload = _normalise_payload(platform_payload)

    return {
        "statusCode": 200,
        "body": json.dumps(platform_payload),
    }
