"""Typed, read-only store analytics for the authenticated owner assistant."""

from __future__ import annotations

import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Intent = Literal[
    "overview",
    "order_status_summary",
    "revenue_summary",
    "date_range_comparison",
    "low_stock",
    "low_stock_restock_summary",
    "out_of_stock",
    "top_selling_products",
    "unsold_products",
    "category_summary",
    "product_lookup",
    "restock_recommendations",
    "recent_orders",
    "discounted_products",
    "price_extremes",
    "unsupported_question",
    "clarification",
]

MAX_RESULT_ITEMS = 20
DEFAULT_LOW_STOCK_THRESHOLD = 5
MAX_STOCK_THRESHOLD = 1000
SALES_WINDOW_DAYS = 30
REVENUE_DEFINITION = "Delivered order totals (orders with status delivered), grouped by order creation date; amounts follow the dashboard's INR display and demo checkout is not payment processing."


class AgentResult(BaseModel):
    """Validated API data contract returned by the existing owner chat route."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    answer: str = Field(min_length=1, max_length=2000)
    supporting_data: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    metric_definitions: list[str] = Field(default_factory=list, max_length=20)
    clarification: str | None = Field(default=None, max_length=500)


class OwnerAgentResponse(AgentResult):
    explanation: str | None = Field(default=None, max_length=1500)
    mode: Literal["ai", "faq_fallback"]


def _month_bounds(value: date) -> tuple[date, date]:
    return value.replace(day=1), value.replace(day=monthrange(value.year, value.month)[1])


def _previous_month_bounds(value: date) -> tuple[date, date]:
    first = value.replace(day=1)
    last_previous = first - timedelta(days=1)
    return _month_bounds(last_previous)


def _safe_variants(value: str | None) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, dict)]


def _products(connection: Any, store_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT id, name, category, price, original_price, discount_percent,
                  stock, sku, variants_json
           FROM products WHERE store_id = ? ORDER BY name COLLATE NOCASE LIMIT 1000""",
        (store_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_order_summary(
    connection: Any,
    store_id: int,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Shared store-scoped order/revenue summary used by dashboard and agent."""
    clauses = ["store_id = ?"]
    params: list[Any] = [store_id]
    if start is not None:
        clauses.append("date(created_at) >= ?")
        params.append(start.isoformat())
    if end is not None:
        clauses.append("date(created_at) <= ?")
        params.append(end.isoformat())
    row = connection.execute(
        """SELECT COUNT(*) AS total_orders,
                  COALESCE(SUM(CASE WHEN status = 'delivered' THEN subtotal ELSE 0 END), 0) AS delivered_revenue,
                  COALESCE(SUM(CASE WHEN status IN ('placed','packed','shipped') THEN subtotal ELSE 0 END), 0) AS pending_revenue,
                  SUM(CASE WHEN status = 'placed' THEN 1 ELSE 0 END) AS placed,
                  SUM(CASE WHEN status = 'packed' THEN 1 ELSE 0 END) AS packed,
                  SUM(CASE WHEN status = 'shipped' THEN 1 ELSE 0 END) AS shipped,
                  SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered,
                  SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled
           FROM orders WHERE """ + " AND ".join(clauses),
        params,
    ).fetchone()
    statuses = {
        status: int(row[status] or 0)
        for status in ("placed", "packed", "shipped", "delivered", "cancelled")
    }
    return {
        "total_orders": int(row["total_orders"] or 0),
        "delivered_revenue": round(float(row["delivered_revenue"] or 0), 2),
        "pending_revenue": round(float(row["pending_revenue"] or 0), 2),
        "orders_by_status": statuses,
    }


def _inventory_entries(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for product in products:
        variants = _safe_variants(product.get("variants_json"))
        if variants:
            for variant in variants:
                try:
                    stock = max(0, int(variant.get("stock", 0)))
                except (TypeError, ValueError):
                    stock = 0
                entries.append({
                    "product_id": product["id"],
                    "product_name": product["name"],
                    "category": product["category"],
                    "sku": product.get("sku"),
                    "variant_name": str(variant.get("name", ""))[:50],
                    "variant_value": str(variant.get("value", ""))[:100],
                    "stock": stock,
                })
        else:
            entries.append({
                "product_id": product["id"],
                "product_name": product["name"],
                "category": product["category"],
                "sku": product.get("sku"),
                "variant_name": None,
                "variant_value": None,
                "stock": max(0, int(product.get("stock", 0))),
            })
    return entries


def _count_delivered_orders(connection: Any, store_id: int) -> int:
    return get_order_summary(connection, store_id)["orders_by_status"]["delivered"]


def _status_counts(connection: Any, store_id: int) -> dict[str, int]:
    return get_order_summary(connection, store_id)["orders_by_status"]


def _revenue_for_range(
    connection: Any, store_id: int, start: date | None, end: date | None,
) -> dict[str, Any]:
    summary = get_order_summary(connection, store_id, start, end)
    revenue = summary["delivered_revenue"]
    count = summary["orders_by_status"]["delivered"]
    return {
        "from": start.isoformat() if start else None,
        "to": end.isoformat() if end else None,
        "revenue": revenue,
        "orders": count,
        "delivered_revenue": revenue,
        "delivered_orders": count,
        "average_delivered_order_value": round(revenue / count, 2) if count else None,
    }


def _classify(message: str, today: date) -> tuple[Intent, dict[str, Any]]:
    text = " ".join(message.casefold().split())
    numbers = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)

    low_stock_cues = ("low stock", "low on stock", "running low", "running out of stock", "stock running low", "stock alert", "inventory alert", "below stock", "stock below", "inventory below")
    restock_cue = any(term in text for term in ("restock", "reorder", "re-stock"))
    if restock_cue and any(term in text for term in low_stock_cues):
        match = re.search(r"(?:below|under|less than|at most|no more than)\s+(\d{1,5})|\b(\d{1,5})\s+(?:or fewer|or less)\b", text)
        threshold = int(next(group for group in match.groups() if group is not None)) if match else DEFAULT_LOW_STOCK_THRESHOLD
        if not 1 <= threshold <= MAX_STOCK_THRESHOLD:
            return "clarification", {"message": f"Choose a stock threshold from 1 to {MAX_STOCK_THRESHOLD} units."}
        strict_below = bool(match and re.search(r"(?:below|under|less than)\s+\d", text))
        return "low_stock_restock_summary", {"threshold": threshold, "inclusive": not strict_below}

    if any(word in text for word in ("compare", "comparison", "versus", " vs ", "month over month", "week over week")):
        if len(numbers) >= 2:
            try:
                start, end = date.fromisoformat(numbers[0]), date.fromisoformat(numbers[1])
            except ValueError:
                return "clarification", {"message": "Use valid dates in YYYY-MM-DD format."}
            if start > end:
                return "clarification", {"message": "The comparison start date must be on or before its end date."}
            days = (end - start).days + 1
            return "date_range_comparison", {
                "periods": ((start, end), (start - timedelta(days=days), start - timedelta(days=1))),
                "period_label": "the requested range and the immediately preceding range of equal length",
            }
        if "month" in text:
            current_start, _ = _month_bounds(today)
            previous_start, _ = _previous_month_bounds(today)
            previous_end = previous_start.replace(
                day=min(today.day, monthrange(previous_start.year, previous_start.month)[1])
            )
            return "date_range_comparison", {
                "periods": ((current_start, today), (previous_start, previous_end)),
                "period_label": "this month to date and the same calendar dates in the previous month",
            }
        if "week" in text:
            current = (today - timedelta(days=today.weekday()), today)
            elapsed_days = (current[1] - current[0]).days + 1
            previous_end = current[0] - timedelta(days=1)
            previous = (previous_end - timedelta(days=elapsed_days - 1), previous_end)
            return "date_range_comparison", {
                "periods": (current, previous),
                "period_label": "this week to date and the same number of days in the previous week",
            }
        return "clarification", {"message": "Which periods should I compare? Try ‘this month with last month’ or provide two YYYY-MM-DD dates."}

    if restock_cue:
        return "restock_recommendations", {}
    if any(term in text for term in ("never sold", "unsold", "not sold", "no sales")):
        period = re.search(r"(?:last|past|in the last|in|during the last)\s+(\d{1,4})\s+days", text)
        if period:
            days = int(period.group(1))
            if not 1 <= days <= 3650:
                return "clarification", {"message": "Choose an unsold-product period from 1 to 3650 days."}
            return "unsold_products", {"period_days": days}
        return "unsold_products", {}
    if any(term in text for term in ("out of stock", "out-of-stock", "sold out", "no stock")):
        return "out_of_stock", {}
    if any(term in text for term in ("top selling", "best selling", "best-selling", "most popular", "top products", "sold the most")):
        return "top_selling_products", {}
    if any(term in text for term in ("category summary", "best-selling categor", "best selling categor", "sales by categor", "products by categor", "category performance")):
        return "category_summary", {}
    if any(term in text for term in ("low stock", "low on stock", "running low", "running out of stock", "stock running low", "stock alert", "inventory alert", "below stock", "stock below", "inventory below")):
        match = re.search(r"(?:below|under|less than|at most|no more than)\s+(\d{1,5})|\b(\d{1,5})\s+(?:or fewer|or less)\b", text)
        if not match:
            return "low_stock", {"threshold": DEFAULT_LOW_STOCK_THRESHOLD, "inclusive": True}
        threshold = int(next(group for group in match.groups() if group is not None))
        if not 1 <= threshold <= MAX_STOCK_THRESHOLD:
            return "clarification", {"message": f"Choose a stock threshold from 1 to {MAX_STOCK_THRESHOLD} units."}
        strict_below = bool(re.search(r"(?:below|under|less than)\s+\d", text))
        return "low_stock", {"threshold": threshold, "inclusive": not strict_below}

    if any(term in text for term in ("discounted", "discount", "on sale", "sale items")):
        return "discounted_products", {}
    if any(term in text for term in ("highest price", "most expensive", "lowest price", "least expensive", "cheapest")):
        return "price_extremes", {"direction": "lowest" if any(term in text for term in ("lowest price", "least expensive", "cheapest")) else "highest"}
    if any(term in text for term in ("average order value", "average order")):
        return "revenue_summary", {"period": "all_time", "include_average": True}
    if any(term in text for term in ("pending orders", "orders by status", "order status", "order statuses", "how many orders", "orders need attention", "need attention", "pending")):
        return "order_status_summary", {"attention": any(term in text for term in ("need attention", "needs attention", "attention"))}
    if any(term in text for term in ("recent orders", "latest orders", "recent activity", "summarize my recent")):
        return "recent_orders", {}

    product_cue = any(term in text for term in (
        "price of", "cost of", "stock for", "stock of", "availability of", "how much is", "how many left for",
    ))
    if product_cue:
        return "product_lookup", {}

    if "revenue" in text or "sales" in text or "income" in text:
        if len(numbers) >= 2:
            try:
                start, end = date.fromisoformat(numbers[0]), date.fromisoformat(numbers[1])
            except ValueError:
                return "clarification", {"message": "Use valid dates in YYYY-MM-DD format."}
            if start > end:
                return "clarification", {"message": "The start date must be on or before the end date."}
            return "revenue_summary", {"period": "custom", "start": start, "end": end}
        if "this month" in text or "month to date" in text or "monthly" in text:
            return "revenue_summary", {"period": "month", "start": _month_bounds(today)[0], "end": today}
        if "last month" in text:
            start, end = _previous_month_bounds(today)
            return "revenue_summary", {"period": "month", "start": start, "end": end}
        if "this week" in text or "week to date" in text:
            return "revenue_summary", {"period": "week", "start": today - timedelta(days=today.weekday()), "end": today}
        return "revenue_summary", {"period": "all_time"}

    if any(term in text for term in ("store overview", "summarize my store", "store performance", "how is my store performing", "store summary", "overall performance")):
        return "overview", {}
    if any(term in text for term in ("categories", "category", "products by category", "inventory by category")):
        return "category_summary", {}
    return "unsupported_question", {}


def _row_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _answer(intent: Intent, answer: str, data: list[dict[str, Any]], definitions: list[str] | None = None, clarification: str | None = None) -> dict[str, Any]:
    return AgentResult(
        intent=intent,
        answer=answer,
        supporting_data=data[:MAX_RESULT_ITEMS],
        metric_definitions=(definitions or [])[:20],
        clarification=clarification,
    ).model_dump()


def route_store_question(
    connection: Any,
    store_id: int,
    message: str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Classify one question and run only fixed, parameterized queries for store_id."""
    reference_day = today or datetime.now(timezone.utc).date()
    intent, options = _classify(message, reference_day)
    if intent == "clarification":
        prompt = options["message"]
        return _answer(intent, prompt, [], clarification=prompt)
    if intent == "unsupported_question":
        sensitive_request = any(term in message.casefold() for term in (
            "password", "api key", "secret", "token", "customer email", "customer phone",
        ))
        return _answer(
            intent,
            "I don't have that data." if sensitive_request else "I can answer store overview, order status and revenue, inventory, top-selling or unsold products, category performance, product price/stock, discounts, recent orders, and restocking questions. Try one of those.",
            [],
        )

    if intent == "low_stock_restock_summary":
        threshold = int(options["threshold"])
        operator = "below" if not options["inclusive"] else "at most"
        low = route_store_question(
            connection,
            store_id,
            f"low stock {operator} {threshold}",
            today=reference_day,
        )
        restock = route_store_question(connection, store_id, "restock recommendations", today=reference_day)
        answer = f"{low['answer']} {restock['answer']}"
        return _answer(
            "low_stock_restock_summary",
            answer,
            [{"low_stock": low["supporting_data"], "restock_recommendations": restock["supporting_data"]}],
            low["metric_definitions"] + restock["metric_definitions"],
        )

    if intent == "overview":
        counts = _status_counts(connection, store_id)
        products = _products(connection, store_id)
        inventory = _inventory_entries(products)
        revenue = _revenue_for_range(connection, store_id, None, None)
        facts = {
            "catalog_product_count": len(products),
            "total_orders": sum(counts.values()),
            "orders_by_status": counts,
            "pending_orders": counts["placed"] + counts["packed"] + counts["shipped"],
            "delivered_revenue": revenue["delivered_revenue"],
            "low_stock_entries_at_or_below_5": sum(entry["stock"] <= 5 for entry in inventory),
            "out_of_stock_entries": sum(entry["stock"] == 0 for entry in inventory),
            "inventory_entry_definition": "A simple product is one entry; a product with variants contributes one entry per variant.",
        }
        answer = (
            f"Your catalog has {facts['catalog_product_count']} products and {facts['total_orders']} recorded orders. "
            f"There are {facts['pending_orders']} pending orders, {counts['delivered']} delivered, and "
            f"{counts['cancelled']} cancelled. Delivered order value is {revenue['delivered_revenue']:.2f}; "
            f"{facts['low_stock_entries_at_or_below_5']} inventory entries have 5 or fewer units, "
            f"including {facts['out_of_stock_entries']} out of stock."
        )
        return _answer("overview", answer, [facts], [
            REVENUE_DEFINITION,
            facts["inventory_entry_definition"],
            "The catalog has no active/inactive product flag, so the product count means all records in this store's catalog.",
        ])

    if intent == "order_status_summary":
        counts = _status_counts(connection, store_id)
        pending = counts["placed"] + counts["packed"] + counts["shipped"]
        if options.get("attention"):
            rows = connection.execute(
                """SELECT public_ref, status, subtotal, created_at
                   FROM orders WHERE store_id = ? AND status IN ('placed','packed','shipped')
                   ORDER BY created_at ASC, id ASC LIMIT ?""",
                (store_id, MAX_RESULT_ITEMS),
            ).fetchall()
            facts = _row_dicts(rows)
            summary = "; ".join(
                f"{row['public_ref']} ({row['status']}, INR {float(row['subtotal']):.2f})"
                for row in facts[:5]
            )
            answer = (
                f"{pending} orders are still in progress (placed, packed, or shipped). "
                + (f"Oldest first: {summary}." if facts else "There are no open orders needing attention.")
            )
            return _answer("order_status_summary", answer, facts, ["In-progress orders are placed, packed, or shipped; cancelled and delivered orders are excluded."])
        facts = [{"orders_by_status": counts, "pending_orders": pending, "total_orders": sum(counts.values())}]
        answer = f"There are {pending} pending orders: {counts['placed']} placed, {counts['packed']} packed, and {counts['shipped']} shipped. {counts['delivered']} are delivered and {counts['cancelled']} cancelled."
        return _answer("order_status_summary", answer, facts, ["Pending means placed, packed, or shipped."])

    if intent == "recent_orders":
        rows = connection.execute(
            """SELECT public_ref, status, subtotal, created_at FROM orders
               WHERE store_id = ? ORDER BY created_at DESC, id DESC LIMIT ?""",
            (store_id, 10),
        ).fetchall()
        facts = _row_dicts(rows)
        summary = "; ".join(f"{row['public_ref']} ({row['status']}, INR {float(row['subtotal']):.2f})" for row in facts[:5])
        answer = "No orders are recorded yet." if not facts else f"Most recent orders: {summary}. Customer contact details are not included."
        return _answer("recent_orders", answer, facts, ["Order values are demo checkout totals; no payments are processed."])

    if intent == "revenue_summary":
        summary = _revenue_for_range(connection, store_id, options.get("start"), options.get("end"))
        period = options.get("period", "all_time")
        label = {
            "all_time": "all recorded time",
            "month": "the requested calendar-month period",
            "week": "this week to date",
            "custom": "the requested date range",
        }.get(period, "the requested period")
        if options.get("include_average"):
            answer = f"Delivered order value over {label} is {summary['delivered_revenue']:.2f} across {summary['delivered_orders']} orders. Average delivered order value is {summary['average_delivered_order_value']:.2f}."
        else:
            answer = f"Delivered order value for {label} is {summary['delivered_revenue']:.2f} across {summary['delivered_orders']} delivered orders."
        return _answer("revenue_summary", answer, [summary], [REVENUE_DEFINITION, "Average order value is delivered revenue divided by delivered order count; it is unavailable when there are no delivered orders."])

    if intent == "date_range_comparison":
        first_range, second_range = options["periods"]
        first = _revenue_for_range(connection, store_id, *first_range)
        second = _revenue_for_range(connection, store_id, *second_range)
        difference = round(first["delivered_revenue"] - second["delivered_revenue"], 2)
        facts = [{
            "period_label": options["period_label"],
            "current_period": first,
            "comparison_period": second,
            "previous_period": second,
            "revenue_change": difference,
            "revenue_status": "delivered orders only",
        }]
        direction = "higher" if difference > 0 else "lower" if difference < 0 else "unchanged"
        answer = f"Delivered order value for {options['period_label']} was {first['delivered_revenue']:.2f} versus {second['delivered_revenue']:.2f}, a {abs(difference):.2f} {direction} difference."
        return _answer("date_range_comparison", answer, facts, [REVENUE_DEFINITION])

    products = _products(connection, store_id)
    inventory = _inventory_entries(products)

    if intent in ("low_stock", "out_of_stock"):
        threshold = int(options.get("threshold", DEFAULT_LOW_STOCK_THRESHOLD))
        inclusive = bool(options.get("inclusive", True))
        if intent == "out_of_stock":
            selected = [entry for entry in inventory if entry["stock"] == 0]
            definitions = ["Products with variants are counted per variant using variant stock; products without variants use product stock."]
        else:
            selected = [entry for entry in inventory if entry["stock"] <= threshold] if inclusive else [entry for entry in inventory if entry["stock"] < threshold]
            operator = "at or below" if inclusive else "below"
            definitions = ["Products with variants are counted per variant using variant stock; products without variants use product stock."]
        operator = "out of stock" if intent == "out_of_stock" else f"{operator} {threshold} units"
        labels = [
            f"{entry['product_name']}" + (f" ({entry['variant_name']}: {entry['variant_value']})" if entry["variant_name"] is not None else "") + f": {entry['stock']} left"
            for entry in selected[:5]
        ]
        if not selected:
            answer = "No inventory entries are out of stock." if intent == "out_of_stock" else f"No inventory entries are {operator}."
        elif intent == "out_of_stock":
            answer = f"{len(selected)} inventory entries are out of stock: " + "; ".join(labels) + "."
        else:
            answer = f"{len(selected)} inventory entries are {operator}: " + "; ".join(labels) + "."
        simple_products = [
            {"product_name": entry["product_name"], "stock": entry["stock"], "sku": entry["sku"]}
            for entry in selected if entry["variant_name"] is None
        ]
        variants = [
            {
                "product_name": entry["product_name"],
                "variant": f"{entry['variant_name']}: {entry['variant_value']}",
                "stock": entry["stock"],
                "sku": entry["sku"],
            }
            for entry in selected if entry["variant_name"] is not None
        ]
        facts = [{
            "threshold": 0 if intent == "out_of_stock" else threshold,
            "inclusive": inclusive,
            "products": simple_products[:MAX_RESULT_ITEMS],
            "variants": variants[:MAX_RESULT_ITEMS],
            "entries": selected[:MAX_RESULT_ITEMS],
            "total_matching_entries": len(selected),
        }]
        if len(selected) > MAX_RESULT_ITEMS:
            answer += f" Showing the first {MAX_RESULT_ITEMS}."
        return _answer(intent, answer, facts, definitions)

    if intent == "top_selling_products":
        rows = connection.execute(
            """SELECT oi.product_name, SUM(oi.quantity) AS units_sold
               FROM order_items AS oi JOIN orders AS o ON o.id = oi.order_id
               WHERE o.store_id = ? AND o.status = 'delivered'
               GROUP BY oi.product_id, oi.product_name
               ORDER BY units_sold DESC, oi.product_name COLLATE NOCASE LIMIT ?""",
            (store_id, MAX_RESULT_ITEMS),
        ).fetchall()
        facts = _row_dicts(rows)
        answer = "No delivered product sales are recorded yet." if not facts else "Top products by delivered units sold: " + "; ".join(f"{row['product_name']} ({row['units_sold']} units)" for row in facts[:5]) + "."
        return _answer("top_selling_products", answer, facts, ["Units sold count delivered order items only; cancelled and not-yet-delivered orders are excluded."])

    if intent == "unsold_products":
        period_days = options.get("period_days")
        start = reference_day - timedelta(days=period_days - 1) if period_days else None
        period_filter = " AND date(o.created_at) BETWEEN ? AND ?" if period_days else ""
        params: list[Any] = [store_id]
        if period_days:
            params.extend([start.isoformat(), reference_day.isoformat()])
        params.append(MAX_RESULT_ITEMS)
        rows = connection.execute(
            f"""SELECT p.id, p.name, p.category, p.sku, COUNT(*) OVER() AS total_matching_products FROM products AS p
               WHERE p.store_id = ? AND NOT EXISTS (
                   SELECT 1 FROM order_items AS oi JOIN orders AS o ON o.id = oi.order_id
                   WHERE o.store_id = p.store_id AND o.status = 'delivered'
                     AND (oi.product_id = p.id OR (oi.product_id IS NULL AND oi.product_name = p.name))
                     {period_filter}
               ) ORDER BY p.name COLLATE NOCASE LIMIT ?""",
            params,
        ).fetchall()
        total_matching = int(rows[0]["total_matching_products"]) if rows else 0
        facts = [
            {key: value for key, value in dict(row).items() if key != "total_matching_products"}
            for row in rows
        ]
        if period_days:
            delivered_count_row = connection.execute(
                "SELECT COUNT(*) AS count FROM orders WHERE store_id = ? AND status = 'delivered' AND date(created_at) BETWEEN ? AND ?",
                (store_id, start.isoformat(), reference_day.isoformat()),
            ).fetchone()
            delivered_count = int(delivered_count_row["count"] or 0)
        else:
            delivered_count = _count_delivered_orders(connection, store_id)
        if not delivered_count:
            answer = (f"There are no delivered orders recorded in the last {period_days} days, so this dataset shows no delivered product sales in that period." if period_days else "There is no delivered order history to establish which products have sold.")
        elif not facts:
            answer = (f"Every catalog product has at least one recorded delivered sale in the last {period_days} days." if period_days else "Every catalog product has at least one recorded delivered sale.")
        else:
            names = ", ".join(row["name"] for row in facts[:10])
            period_label = f" in the last {period_days} days" if period_days else " in the order history available to this store"
            answer = f"{total_matching} products have no matching delivered sales{period_label}: {names}."
            if total_matching > len(facts):
                answer += f" Showing {len(facts)} of {total_matching}."
        definition = "‘No recorded sales’ means no matching product line in available delivered orders; this does not establish sales history outside this database."
        if period_days:
            definition += f" The requested window is {start.isoformat()} through {reference_day.isoformat()} ({period_days} days)."
        return _answer("unsold_products", answer, facts, [definition])

    if intent == "category_summary":
        product_counts = connection.execute(
            "SELECT category, COUNT(*) AS products FROM products WHERE store_id = ? GROUP BY category COLLATE NOCASE ORDER BY category COLLATE NOCASE LIMIT ?",
            (store_id, MAX_RESULT_ITEMS),
        ).fetchall()
        sales = connection.execute(
            """SELECT oi.category, SUM(oi.quantity) AS delivered_units,
                      ROUND(SUM(oi.line_total), 2) AS delivered_value
               FROM order_items AS oi JOIN orders AS o ON o.id = oi.order_id
               WHERE o.store_id = ? AND o.status = 'delivered'
               GROUP BY oi.category COLLATE NOCASE""",
            (store_id,),
        ).fetchall()
        sales_by_category = {row["category"].casefold(): dict(row) for row in sales}
        inventory_by_category: dict[str, int] = {}
        for entry in inventory:
            key = entry["category"].casefold()
            inventory_by_category[key] = inventory_by_category.get(key, 0) + entry["stock"]
        facts = []
        for row in product_counts:
            value = sales_by_category.get(row["category"].casefold(), {})
            facts.append({
                "category": row["category"],
                "product_count": int(row["products"]),
                "current_stock_units": inventory_by_category.get(row["category"].casefold(), 0),
                "delivered_units": int(value.get("delivered_units") or 0),
                "delivered_value": round(float(value.get("delivered_value") or 0), 2),
            })
        category_text = "; ".join(
            f"{row['category']}: {row['product_count']} products, {row['current_stock_units']} stock units, {row['delivered_units']} delivered units"
            for row in facts[:8]
        )
        return _answer("category_summary", f"Category summary: {category_text}." if facts else "No catalog categories or products are recorded yet.", facts, ["Sales are based on delivered order item snapshots and grouped by the category recorded at checkout."])

    if intent == "product_lookup":
        lowered = " ".join(message.casefold().split())
        exact = [product for product in products if product["name"].casefold() in lowered]
        if exact:
            matches = exact
        else:
            tokens = {token for token in re.findall(r"[\w-]+", lowered) if len(token) > 2 and token not in {"what", "price", "cost", "stock", "for", "the", "does", "have", "how", "much", "many", "left", "available", "availability", "product", "is", "of"}}
            matches = [product for product in products if tokens & set(re.findall(r"[\w-]+", product["name"].casefold()))]
        if len(matches) > 1:
            names = [product["name"] for product in matches[:5]]
            prompt = "Which product do you mean? I found: " + ", ".join(names) + "."
            return _answer("clarification", prompt, [], clarification=prompt)
        if not matches:
            return _answer("product_lookup", "I couldn't match that to a product in this store's catalog.", [])
        product = matches[0]
        variants = _safe_variants(product.get("variants_json"))
        fact = {
            "product_id": product["id"], "name": product["name"], "category": product["category"],
            "price": round(float(product["price"]), 2), "discount_percent": product.get("discount_percent"),
            "effective_price": round(float(product["price"]) * (1 - float(product.get("discount_percent") or 0) / 100), 2),
            "stock": product["stock"] if not variants else None,
            "variants": [{"name": v.get("name", ""), "value": v.get("value", ""), "stock": int(v.get("stock", 0))} for v in variants[:50]],
            "sku": product.get("sku"),
        }
        price_text = f"INR {fact['effective_price']:.2f} after discount" if fact["discount_percent"] else f"INR {fact['price']:.2f}"
        if variants:
            stock_text = "; ".join(f"{variant.get('name', '')}: {variant.get('value', '')} has {int(variant.get('stock', 0))}" for variant in variants[:5])
            answer = f"{product['name']} is listed at {price_text}. Variant stock: {stock_text}."
        else:
            answer = f"{product['name']} is listed at {price_text} with {fact['stock']} in stock."
        return _answer("product_lookup", answer, [fact], ["For products with variants, variant stock is authoritative; product-level stock is omitted to avoid double-counting."])

    if intent == "restock_recommendations":
        start = reference_day - timedelta(days=SALES_WINDOW_DAYS - 1)
        sales_rows = connection.execute(
            """SELECT oi.product_id, oi.product_name, oi.variant_json, SUM(oi.quantity) AS units_sold
               FROM order_items AS oi JOIN orders AS o ON o.id = oi.order_id
               WHERE o.store_id = ? AND o.status = 'delivered'
                 AND date(o.created_at) BETWEEN ? AND ?
               GROUP BY oi.product_id, oi.product_name, oi.variant_json
               ORDER BY units_sold DESC LIMIT 500""",
            (store_id, start.isoformat(), reference_day.isoformat()),
        ).fetchall()
        sold: dict[tuple[int | None, str | None, str | None], int] = {}
        for row in sales_rows:
            try:
                variant = json.loads(row["variant_json"]) if row["variant_json"] else None
            except json.JSONDecodeError:
                variant = None
            key = (
                row["product_id"],
                str(variant.get("name")) if isinstance(variant, dict) else None,
                str(variant.get("value")) if isinstance(variant, dict) else None,
            )
            sold[key] = sold.get(key, 0) + int(row["units_sold"])
        recommendations = []
        for entry in inventory:
            key = (entry["product_id"], entry["variant_name"], entry["variant_value"])
            units = sold.get(key, 0)
            if units <= 0:
                continue
            velocity = units / SALES_WINDOW_DAYS
            recommendations.append({
                **entry,
                "delivered_units_last_30_days": units,
                "average_daily_delivered_units": round(velocity, 3),
                "estimated_days_of_stock_at_recent_velocity": round(entry["stock"] / velocity, 1),
            })
        recommendations.sort(key=lambda row: (row["estimated_days_of_stock_at_recent_velocity"], row["stock"], row["product_name"].casefold()))
        selected = recommendations[:MAX_RESULT_ITEMS]
        if not selected and not sales_rows:
            answer = "I don't have enough recent delivered sales history to rank restock priorities. No demand estimate is inferred."
        elif not selected:
            answer = "No catalog items matched recent delivered sales, so I can't rank a restock priority from this history."
        else:
            summary = "; ".join(
                f"{row['product_name']}" + (f" ({row['variant_value']})" if row["variant_value"] else "")
                + f": {row['estimated_days_of_stock_at_recent_velocity']:.1f} estimated days left"
                for row in selected[:5]
            )
            answer = "Restock priorities by estimated days remaining: " + summary + ". This is a heuristic, not a forecast."
        return _answer("restock_recommendations", answer, selected, [f"Uses delivered unit sales from {start.isoformat()} through {reference_day.isoformat()} ({SALES_WINDOW_DAYS} days). Estimated days of cover = current product or variant stock divided by average daily delivered units. This is a simple heuristic, not a guaranteed prediction."])

    if intent == "discounted_products":
        selected = [product for product in products if product.get("discount_percent") is not None and float(product["discount_percent"]) > 0]
        facts = [{"name": product["name"], "category": product["category"], "price": round(float(product["price"]), 2), "discount_percent": float(product["discount_percent"]), "effective_price": round(float(product["price"]) * (1 - float(product["discount_percent"]) / 100), 2)} for product in selected[:MAX_RESULT_ITEMS]]
        names = "; ".join(f"{fact['name']} (INR {fact['effective_price']:.2f})" for fact in facts[:8])
        answer = f"{len(selected)} discounted catalog products: {names}." if facts else "No discounted catalog products are recorded."
        return _answer("discounted_products", answer, facts)

    if intent == "price_extremes":
        if not products:
            return _answer("price_extremes", "No catalog products are recorded yet.", [])
        ordered = sorted(products, key=lambda item: (float(item["price"]), item["name"].casefold()), reverse=options.get("direction") == "highest")
        facts = [{"name": product["name"], "category": product["category"], "price": round(float(product["price"]), 2)} for product in ordered[:5]]
        direction = options.get("direction", "highest")
        summary = "; ".join(f"{fact['name']} (INR {fact['price']:.2f})" for fact in facts)
        return _answer("price_extremes", f"The {direction}-priced products are: {summary}.", facts, ["Prices are catalog base prices before any discount."])

    return _answer("unsupported_question", "I couldn't route that question to a supported store-data query.", [])


def canonical_ai_question(result: dict[str, Any]) -> str:
    """Build a bounded, non-user-controlled prompt topic for the existing AI adapter."""
    intent = result["intent"]
    return {
        "overview": "Summarize the store overview facts.",
        "order_status_summary": "Summarize order counts and statuses.",
        "revenue_summary": "Explain the delivered revenue metrics and period.",
        "date_range_comparison": "Compare the two delivered revenue periods using the supplied values.",
        "low_stock": "Summarize the low-stock entries and threshold.",
        "low_stock_restock_summary": "Summarize the low-stock entries and evidence-based restock priorities.",
        "out_of_stock": "Summarize the out-of-stock entries.",
        "top_selling_products": "Summarize top products by delivered units sold.",
        "unsold_products": "Explain products without recorded delivered sales in the available history.",
        "category_summary": "Summarize product counts and delivered sales by category.",
        "product_lookup": "Summarize the matched catalog product facts.",
        "restock_recommendations": "Explain the restock priority heuristic and its supplied evidence.",
        "recent_orders": "Summarize the recent order status and totals without customer details.",
        "discounted_products": "Summarize the listed discounted catalog products.",
        "price_extremes": "Summarize the listed catalog price extremes.",
    }.get(intent, "Summarize only the supplied store facts.")
