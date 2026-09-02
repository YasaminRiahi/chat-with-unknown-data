"""Generate a bilingual candidate benchmark from cached schema enrichment.

The generated SQL is schema-grounded but not business-validated. A domain
expert must review every item before moving it from candidate to gold status.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "enrichment" / "test1-1b4f0e9851.json"
OUTPUT = ROOT / "evaluation" / "datasets" / "test1_candidate_bilingual.json"
INTENT_COUNT = 75  # Two languages per intent => 150 benchmark records.

EXCLUDED_SCHEMAS = {"dbo"}
EXCLUDED_NAME_PARTS = {
    "log", "backup", "configuration", "password", "user", "phone",
    "communication", "note", "faq", "template", "version",
}

PERSIAN_ENTITY_NAMES = {
    "Account": "حساب‌ها",
    "Voucher": "اسناد حسابداری",
    "VoucherItem": "اقلام اسناد حسابداری",
    "AccVchHdr": "سرآیند اسناد حسابداری",
    "AccVchItm": "اقلام اسناد حسابداری",
    "GLVoucher": "اسناد دفتر کل",
    "GLVoucherItem": "اقلام اسناد دفتر کل",
    "Asset": "دارایی‌ها",
    "AssetClass": "طبقات دارایی",
    "AssetGroup": "گروه‌های دارایی",
    "AcquisitionReceipt": "رسیدهای تحصیل دارایی",
    "AcquisitionReceiptItem": "اقلام رسید تحصیل دارایی",
    "Depreciation": "استهلاک‌ها",
    "DepreciationItem": "اقلام استهلاک",
    "DepreciationRule": "قواعد استهلاک",
    "Repair": "تعمیرات دارایی",
    "RepairItem": "اقلام تعمیرات دارایی",
    "Sale": "فروش دارایی",
    "SaleItem": "اقلام فروش دارایی",
    "Transfer": "انتقال‌های دارایی",
    "TransferItem": "اقلام انتقال دارایی",
    "Contract": "قراردادها",
    "ContractType": "انواع قرارداد",
    "ContractCoefficientItem": "ضرایب قرارداد",
    "ContractWarrantyItem": "تضمین‌های قرارداد",
    "Coefficient": "ضرایب",
    "Cost": "هزینه‌ها",
    "CostStatement": "صورت‌هزینه‌ها",
    "CostStatementItem": "اقلام صورت‌هزینه",
    "Guarantee": "ضمانت‌نامه‌ها",
    "GuaranteeOperation": "عملیات ضمانت‌نامه",
    "Project": "پروژه‌ها",
    "Settlement": "تسویه‌ها",
    "SettlementItem": "اقلام تسویه",
    "Status": "صورت‌وضعیت‌ها",
    "StatusItem": "اقلام صورت‌وضعیت",
    "Tender": "مناقصه‌ها",
    "Warranty": "انواع تضمین",
    "Workshop": "کارگاه‌ها",
    "Order": "سفارش‌ها",
    "OrderItem": "اقلام سفارش",
    "ReturnOrder": "سفارش‌های برگشتی",
    "ReturnOrderItem": "اقلام سفارش برگشتی",
    "ReturnReason": "دلایل برگشت",
    "SalesLimit": "محدودیت‌های فروش",
    "SalesLimitItem": "اقلام محدودیت فروش",
    "ColdDistribution": "توزیع‌های سرد",
    "HotDistribution": "توزیع‌های گرم",
    "HotDistributionItem": "اقلام توزیع گرم",
    "DebtCollectionList": "فهرست‌های وصول مطالبات",
    "DebtCollectionListInvoice": "فاکتورهای وصول مطالبات",
    "FiscalYear": "سال‌های مالی",
    "Lookup": "مقادیر پایه",
    "Bill": "صورتحساب‌ها",
    "BillItem": "اقلام صورتحساب",
    "CostCenter": "مراکز هزینه",
    "Currency": "ارزها",
    "CurrencyExchangeRate": "نرخ‌های تبدیل ارز",
    "DebitCreditNote": "اعلامیه‌های بدهکار و بستانکار",
    "Invoice": "فاکتورهای فروش",
    "InvoiceItem": "اقلام فاکتور فروش",
    "Quotation": "پیش‌فاکتورها",
    "QuotationItem": "اقلام پیش‌فاکتور",
    "Performa": "پرفرماها",
    "PerformaItem": "اقلام پرفرما",
    "InventoryReceipt": "رسیدهای انبار",
    "InventoryReceiptItem": "اقلام رسید انبار",
    "InventoryDelivery": "حواله‌های انبار",
    "InventoryDeliveryItem": "اقلام حواله انبار",
    "Item": "کالاها",
    "Stock": "انبارها",
    "Party": "طرف‌حساب‌ها",
    "Personnel": "کارکنان",
    "Payroll": "لیست‌های حقوق",
    "PayrollItem": "اقلام حقوق",
}

PERSIAN_COLUMNS = {
    "Date": "تاریخ",
    "CreationDate": "تاریخ ایجاد",
    "StartDate": "تاریخ شروع",
    "EndDate": "تاریخ پایان",
    "Title": "عنوان",
    "Title_En": "عنوان انگلیسی",
    "Number": "شماره",
    "Code": "کد",
    "State": "وضعیت",
    "Type": "نوع",
    "Amount": "مبلغ",
    "Price": "مبلغ",
    "NetPrice": "مبلغ خالص",
    "Quantity": "مقدار",
    "Debit": "بدهکار",
    "Credit": "بستانکار",
    "Percent": "درصد",
    "ExchangeRate": "نرخ تبدیل",
    "CurrencyRate": "نرخ ارز",
    "Rate": "نرخ",
}

DATE_COLUMNS = (
    "Date", "CreationDate", "StartDate", "EndDate", "EffectiveDate",
    "DeliveryDate", "DueDate", "CalculationDate",
)
MEASURE_COLUMNS = (
    "Amount", "Price", "NetPrice", "Quantity", "Debit", "Credit",
    "Percent", "ExchangeRate", "CurrencyRate", "Rate", "TotalCost",
    "SalePrice", "Tax", "Discount", "Fee", "Remain",
)
GROUP_COLUMNS = ("State", "Type", "Status", "Category", "Ctgry")
LABEL_COLUMNS = ("Title", "Title_En", "Name", "Code", "Number")


def humanize(value: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).replace("_", " ")


def first_present(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    folded = {column.casefold(): column for column in columns}
    for candidate in candidates:
        if candidate.casefold() in folded:
            return folded[candidate.casefold()]
    return None


def entity_names(table: str, description: str) -> tuple[str, str]:
    english = description.strip()
    if not english or english.lower().startswith("table for"):
        english = humanize(table)
    persian = PERSIAN_ENTITY_NAMES.get(table, f"رکوردهای {humanize(table)}")
    return persian, english


def identifier_column(table: str, columns: list[str]) -> str:
    candidates = (f"{table}ID", f"{table}Id", "ID", "Id")
    return first_present(columns, candidates) or columns[0]


def build_intent(
    index: int, schema: str, table: str, description: str, columns: list[str]
) -> dict:
    qualified = f"[{schema}].[{table}]"
    entity_fa, entity_en = entity_names(table, description)
    id_column = identifier_column(table, columns)
    date_column = first_present(columns, DATE_COLUMNS)
    measure_column = first_present(columns, MEASURE_COLUMNS)
    group_column = first_present(columns, GROUP_COLUMNS)
    label_column = first_present(columns, LABEL_COLUMNS)
    available_patterns = [0]
    if date_column:
        available_patterns.append(1)
    if measure_column:
        available_patterns.append(2)
    if group_column:
        available_patterns.append(3)
    if label_column:
        available_patterns.append(4)
    available_patterns.append(5)
    pattern = available_patterns[index % len(available_patterns)]

    if pattern == 0:
        question_fa = f"تعداد کل {entity_fa} چقدر است؟"
        question_en = f"How many {entity_en.lower()} records are there?"
        sql = f"SELECT COUNT_BIG(*) AS [RecordCount] FROM {qualified}"
        used_columns: list[str] = []
        category = "count"
    elif pattern == 1:
        question_fa = f"۲۰ مورد آخر {entity_fa} را بر اساس {PERSIAN_COLUMNS.get(date_column, humanize(date_column))} نمایش بده."
        question_en = f"Show the latest 20 {entity_en.lower()} records ordered by {humanize(date_column).lower()}."
        sql = (
            f"SELECT TOP 20 [{id_column}], [{date_column}] FROM {qualified} "
            f"ORDER BY [{date_column}] DESC"
        )
        used_columns = [id_column, date_column]
        category = "temporal_ordering"
    elif pattern == 2:
        measure_fa = PERSIAN_COLUMNS.get(measure_column, humanize(measure_column))
        question_fa = f"مجموع {measure_fa} در {entity_fa} چقدر است؟"
        question_en = f"What is the total {humanize(measure_column).lower()} across {entity_en.lower()}?"
        sql = f"SELECT SUM([{measure_column}]) AS [TotalValue] FROM {qualified}"
        used_columns = [measure_column]
        category = "aggregation"
    elif pattern == 3:
        group_fa = PERSIAN_COLUMNS.get(group_column, humanize(group_column))
        question_fa = f"تعداد {entity_fa} را به تفکیک {group_fa} نمایش بده."
        question_en = f"Show the number of {entity_en.lower()} records grouped by {humanize(group_column).lower()}."
        sql = (
            f"SELECT [{group_column}], COUNT_BIG(*) AS [RecordCount] "
            f"FROM {qualified} GROUP BY [{group_column}] ORDER BY [RecordCount] DESC"
        )
        used_columns = [group_column]
        category = "grouping"
    elif pattern == 4:
        label_fa = PERSIAN_COLUMNS.get(label_column, humanize(label_column))
        question_fa = f"۲۰ {label_fa} اول از {entity_fa} را فهرست کن."
        question_en = f"List the first 20 {humanize(label_column).lower()} values from {entity_en.lower()}."
        sql = (
            f"SELECT TOP 20 [{id_column}], [{label_column}] FROM {qualified} "
            f"ORDER BY [{label_column}]"
        )
        used_columns = list(dict.fromkeys([id_column, label_column]))
        category = "listing"
    else:
        nullable_candidate = label_column or date_column or columns[-1]
        label_fa = PERSIAN_COLUMNS.get(nullable_candidate, humanize(nullable_candidate))
        question_fa = f"چند رکورد از {entity_fa} مقدار {label_fa} ندارند؟"
        question_en = f"How many {entity_en.lower()} records have no {humanize(nullable_candidate).lower()} value?"
        sql = (
            f"SELECT COUNT_BIG(*) AS [MissingCount] FROM {qualified} "
            f"WHERE [{nullable_candidate}] IS NULL"
        )
        used_columns = [nullable_candidate]
        category = "null_check"

    return {
        "intent_id": f"intent_{index + 1:03d}",
        "db_name": "test1",
        "schema": schema,
        "table": table,
        "question_fa": question_fa,
        "question_en": question_en,
        "reference_sql": sql,
        "gold_tables": [f"{schema}.{table}"],
        "gold_columns": [f"{schema}.{table}.{column}" for column in used_columns],
        "category": category,
        "difficulty": "easy" if category in {"count", "listing", "null_check"} else "medium",
        "review_status": "candidate",
        "review_notes": "",
    }


def select_tables(entries: list[dict]) -> list[dict]:
    by_schema: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        by_schema[entry["schema"]].append(entry)

    selected = []
    schemas = sorted(by_schema)
    cursor = 0
    while len(selected) < INTENT_COUNT and schemas:
        schema = schemas[cursor % len(schemas)]
        if by_schema[schema]:
            selected.append(by_schema[schema].pop(0))
        if not by_schema[schema]:
            schemas.remove(schema)
            cursor = 0
        else:
            cursor += 1
    return selected


def main() -> None:
    payload = json.loads(CACHE.read_text(encoding="utf-8"))
    entries = []
    for table_id, value in payload["tables"].items():
        schema, table = table_id.split(".", 1)
        columns = list((
            value.get("column_descriptions_en")
            or value.get("column_descriptions")
            or {}
        ).keys())
        folded_name = table.casefold()
        if (
            schema in EXCLUDED_SCHEMAS
            or value.get("sensitive")
            or len(columns) < 2
            or any(part in folded_name for part in EXCLUDED_NAME_PARTS)
        ):
            continue
        entries.append({
            "schema": schema,
            "table": table,
            "description": (
                value.get("description_en") or value.get("description", "")
            ),
            "columns": columns,
        })

    intents = [
        build_intent(index, **entry)
        for index, entry in enumerate(select_tables(entries))
    ]
    records = []
    for intent in intents:
        common = {key: value for key, value in intent.items() if not key.startswith("question_")}
        records.append({
            "id": f"{intent['intent_id']}_fa",
            "language": "fa",
            "question": intent["question_fa"],
            **common,
        })
        records.append({
            "id": f"{intent['intent_id']}_en",
            "language": "en",
            "question": intent["question_en"],
            **common,
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "metadata": {
                    "database": "test1",
                    "status": "candidate_not_gold",
                    "intent_count": len(intents),
                    "question_count": len(records),
                    "languages": ["fa", "en"],
                    "warning": (
                        "Schema-grounded candidates only. A domain expert must "
                        "validate business meaning, nullability, and reference SQL."
                    ),
                },
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} questions ({len(intents)} intents) to {OUTPUT}")


if __name__ == "__main__":
    main()
