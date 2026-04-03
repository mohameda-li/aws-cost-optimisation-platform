import importlib
import json
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict, List, Tuple

import boto3
from report_generator import generate_report_files

try:
    from botocore.config import Config
except Exception:  # pragma: no cover - botocore may be unavailable in stripped test envs
    Config = None


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
MAX_REPORT_RUNS_PER_CUSTOMER = 20


def _parse_body(resp: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(resp, dict):
        raise ValueError("Handler response must be a dict")
    if resp.get("statusCode") != 200:
        raise ValueError(f"Handler failed with statusCode={resp.get('statusCode')}")
    body = resp.get("body", "{}")
    if isinstance(body, dict):
        return body
    if body in (None, ""):
        return {}
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


def _build_report_links(
    s3_client,
    bucket: str,
    s3_keys: Dict[str, str],
    expires_in: int = 60 * 60 * 24 * 7,
    region: str = "",
) -> Dict[str, str]:
    links = {}
    presign_client = s3_client

    if region:
        client_kwargs = {
            "service_name": "s3",
            "region_name": region,
            "endpoint_url": f"https://s3.{region}.amazonaws.com",
        }
        if Config is not None:
            client_kwargs["config"] = Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
            )
        try:
            presign_client = boto3.client(**client_kwargs)
        except Exception:
            presign_client = s3_client

    html_key = s3_keys.get("html_key")
    if html_key:
        links["html_url"] = presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": html_key},
            ExpiresIn=expires_in,
        )

    json_key = s3_keys.get("json_key")
    if json_key:
        links["json_url"] = presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": json_key},
            ExpiresIn=expires_in,
        )

    return links


def _build_notification_message(payload: Dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    report_files = payload.get("report_files") or {}
    report_links = report_files.get("report_links") or {}
    customer = payload.get("customer", "your organisation")
    total_savings = payload.get("totals", {}).get("total_monthly_savings", 0.0)
    enabled_services = ", ".join(summary.get("enabled_services") or []) or "none"
    html_url = report_links.get("html_url")
    json_url = report_links.get("json_url")

    lines = [
        "Hello,",
        "",
        f"Your scheduled FinOps Automation report for {customer} is now ready.",
        "",
        "Use the links below to open your latest report.",
    ]

    if html_url:
        lines.extend(["", "View report", html_url])
    if json_url:
        lines.extend(["", "Download data (JSON)", json_url])

    lines.extend(
        [
            "",
        "Summary",
        f"- Run ID: {payload.get('run_id', '')}",
        f"- Generated at: {payload.get('timestamp', '')}",
        f"- Enabled services: {enabled_services}",
        f"- Estimated monthly savings: GBP {total_savings:.2f}",
        f"- Partial run: {'Yes' if summary.get('partial_run') else 'No'}",
        ]
    )

    if summary.get("errors"):
        lines.extend(
            [
                "",
                "Items to review",
                *[f"- {item.get('service')}: {item.get('error')}" for item in summary.get("errors", [])],
            ]
        )

    lines.extend(
        [
            "",
            "Thank you,",
            "FinOps Automation",
            "",
            "This is an automated notification.",
        ]
    )

    return "\n".join(lines)


def _build_notification_html(payload: Dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    report_links = (payload.get("report_files") or {}).get("report_links") or {}
    customer = escape(str(payload.get("customer", "your organisation")))
    run_id = escape(str(payload.get("run_id", "")))
    generated_at = escape(str(payload.get("timestamp", "")))
    enabled_services = escape(", ".join(summary.get("enabled_services") or []) or "none")
    total_savings = float(payload.get("totals", {}).get("total_monthly_savings", 0.0) or 0.0)
    partial_run = "Yes" if summary.get("partial_run") else "No"

    actions = []
    html_url = report_links.get("html_url")
    if html_url:
        actions.append(
            f'<a href="{escape(html_url, quote=True)}" '
            'style="display:inline-block;padding:12px 18px;background:#1f6feb;color:#ffffff;'
            'text-decoration:none;border-radius:8px;font-weight:600;margin:0 12px 12px 0;">'
            'View report</a>'
        )
    json_url = report_links.get("json_url")
    if json_url:
        actions.append(
            f'<a href="{escape(json_url, quote=True)}" '
            'style="display:inline-block;padding:12px 18px;background:#eef2ff;color:#1e3a8a;'
            'text-decoration:none;border-radius:8px;font-weight:600;border:1px solid #c7d2fe;'
            'margin:0 12px 12px 0;">Download data</a>'
        )

    error_section = ""
    if summary.get("errors"):
        error_items = "".join(
            f"<li><strong>{escape(str(item.get('service', 'service')))}:</strong> "
            f"{escape(str(item.get('error', 'Unknown error')))}</li>"
            for item in summary.get("errors", [])
        )
        error_section = (
            '<div style="margin-top:24px;">'
            '<h3 style="margin:0 0 8px;font-size:18px;color:#111827;">Items to review</h3>'
            f'<ul style="margin:0;padding-left:20px;color:#374151;">{error_items}</ul>'
            "</div>"
        )

    return (
        "<html><body style=\"margin:0;padding:0;background:#f5f7fb;\">"
        "<div style=\"max-width:640px;margin:0 auto;padding:32px 20px;font-family:Arial,sans-serif;"
        "color:#111827;line-height:1.6;\">"
        "<div style=\"background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;padding:32px;\">"
        "<p style=\"margin:0 0 16px;font-size:16px;\">Hello,</p>"
        f"<p style=\"margin:0 0 20px;font-size:16px;\">Your scheduled FinOps Automation report for "
        f"<strong>{customer}</strong> is now ready.</p>"
        f"<div style=\"margin:24px 0;\">{''.join(actions)}</div>"
        "<h3 style=\"margin:24px 0 8px;font-size:18px;color:#111827;\">Summary</h3>"
        "<ul style=\"margin:0;padding-left:20px;color:#374151;\">"
        f"<li><strong>Run ID:</strong> {run_id}</li>"
        f"<li><strong>Generated at:</strong> {generated_at}</li>"
        f"<li><strong>Enabled services:</strong> {enabled_services}</li>"
        f"<li><strong>Estimated monthly savings:</strong> GBP {total_savings:.2f}</li>"
        f"<li><strong>Partial run:</strong> {partial_run}</li>"
        "</ul>"
        f"{error_section}"
        "<p style=\"margin:24px 0 0;font-size:16px;\">Thank you,<br>FinOps Automation</p>"
        "<p style=\"margin:24px 0 0;color:#6b7280;font-size:13px;\">This is an automated notification.</p>"
        "</div></div></body></html>"
    )


def _send_report_email(payload: Dict[str, Any]) -> Dict[str, Any]:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_sender = os.getenv("SMTP_SENDER", "").strip()
    recipients = [email.strip() for email in os.getenv("NOTIFICATION_EMAIL", "").split(",") if email.strip()]

    if not smtp_host or not smtp_sender or not recipients:
        return {
            "status": "skipped",
            "reason": "SMTP not configured or no notification recipients provided",
        }

    message = EmailMessage()
    message["Subject"] = f"Your scheduled FinOps report is ready - {payload.get('customer', 'Customer')}"
    message["From"] = smtp_sender
    message["To"] = ", ".join(recipients)
    message.set_content(_build_notification_message(payload))
    message.add_alternative(_build_notification_html(payload), subtype="html")

    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except (TypeError, ValueError):
        return {
            "status": "error",
            "reason": "Invalid SMTP port configuration",
        }
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}

    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
        if smtp_use_tls:
            smtp.starttls()
        if smtp_username:
            smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)

    return {
        "status": "sent",
        "recipients": recipients,
        "sender": smtp_sender,
        "subject": message["Subject"],
    }


def _prune_old_reports(s3_client, bucket: str, customer: str, keep_latest: int = MAX_REPORT_RUNS_PER_CUSTOMER) -> Dict[str, Any]:
    prefix = f"reports/{customer}/"
    paginator = s3_client.get_paginator("list_objects_v2")
    objects: List[Dict[str, Any]] = []

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if not key or not (key.endswith(".html") or key.endswith(".json")):
                continue
            objects.append({"Key": key, "LastModified": obj.get("LastModified")})

    run_groups: Dict[str, List[Dict[str, Any]]] = {}
    for obj in objects:
        run_id = Path(obj["Key"]).stem
        run_groups.setdefault(run_id, []).append(obj)

    ordered_runs = sorted(
        run_groups.items(),
        key=lambda item: max((entry.get("LastModified") for entry in item[1]), default=datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )

    stale_runs = ordered_runs[keep_latest:]
    keys_to_delete = [{"Key": entry["Key"]} for _, entries in stale_runs for entry in entries]

    deleted = 0
    if keys_to_delete:
        for idx in range(0, len(keys_to_delete), 1000):
            batch = keys_to_delete[idx : idx + 1000]
            response = s3_client.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
            deleted += len(response.get("Deleted", []))

    return {
        "kept_runs": min(len(ordered_runs), keep_latest),
        "deleted_runs": len(stale_runs),
        "deleted_objects": deleted,
    }


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

        try:
            platform_payload["report_files"]["report_links"] = _build_report_links(
                s3,
                report_bucket,
                report_s3_keys,
                region=region,
            )
        except Exception as e:
            platform_payload["report_files"]["report_links_error"] = str(e)

        try:
            platform_payload["report_files"]["retention"] = _prune_old_reports(
                s3,
                report_bucket,
                customer,
                keep_latest=MAX_REPORT_RUNS_PER_CUSTOMER,
            )
        except Exception as e:
            platform_payload["report_files"]["retention_error"] = str(e)

    try:
        platform_payload["report_files"]["email_notification"] = _send_report_email(platform_payload)
    except Exception as e:
        platform_payload["report_files"]["email_notification_error"] = str(e)

    platform_payload = _normalise_payload(platform_payload)

    return {
        "statusCode": 200,
        "body": json.dumps(platform_payload),
    }
