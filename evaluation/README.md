# اجرای ارزیابی مستقل پروژه

فایل `run_evaluation.py` فقط هنگام اجرای مستقیم فعال می‌شود و هیچ تغییری در
رفتار API یا اجرای عادی پروژه ایجاد نمی‌کند. evaluator سؤال‌ها را از JSON
می‌خواند و نتیجه هر سؤال را بلافاصله در checkpoint ذخیره می‌کند.

## معیارهای گزارش‌شده

- Execution Accuracy قبل و بعد از Self-Correction
- Valid SQL Rate قبل و بعد از Self-Correction
- Table Recall کسری
- Table Precision
- Column Recall
- Self-Correction Success Rate
- Correction Gain
- R-VES مطابق reward bandهای BIRD Mini-Dev
- End-to-End Latency و زمان مراحل
- Token Usage و تعداد فراخوانی مدل

Column Precision و نسخه صفر و یکی Table Recall عمداً محاسبه نمی‌شوند.

## اتصال امن پایگاه داده

بهتر است connection string را در متغیر محیطی همان terminal قرار دهید تا در
فایل گزارش یا history فرمان ثبت نشود:

```powershell
$env:EVALUATION_DATABASE_URL = "mssql+pyodbc://..."
```

evaluator مقدار connection string را داخل manifest، checkpoint یا گزارش ذخیره
نمی‌کند.

## اجرای آزمایشی کم‌هزینه

ابتدا فقط یک یا چند سؤال اجرا کنید:

```powershell
.\.venv\Scripts\python.exe evaluation\run_evaluation.py `
  --dataset evaluation\datasets\test1_candidate_bilingual.json `
  --db-name test1 `
  --db-type mssql `
  --limit 2 `
  --timing-repeats 3 `
  --run-dir evaluation\runs\smoke_test
```

فایل فعلی `test1_candidate_bilingual.json` وضعیت candidate دارد. SQLهای مرجع
و معنای کسب‌وکاری آن‌ها باید پیش از گزارش نهایی تأیید شوند.

## ادامه اجرای متوقف‌شده

```powershell
.\.venv\Scripts\python.exe evaluation\run_evaluation.py `
  --dataset evaluation\datasets\test1_candidate_bilingual.json `
  --db-name test1 `
  --db-type mssql `
  --resume evaluation\runs\smoke_test
```

سؤال‌هایی که شناسه آن‌ها در checkpoint کامل شده است دوباره اجرا نمی‌شوند و
token جدید مصرف نمی‌کنند، حتی اگر دیتاست بعداً ویرایش شود. evaluator هنگام
resume، hash جدید دیتاست را در manifest ثبت می‌کند و سؤال‌های اجرا‌نشده را از
نسخه جدید می‌خواند. برای اجرای دوباره یک سؤال باید رکورد آن عمداً از checkpoint
حذف شود یا گزینه retry مناسب استفاده شود. نام و نوع دیتابیس و نسخه evaluator
همچنان باید با manifest قبلی یکسان باشند.

برای توقف امن می‌توان `Ctrl+C` زد. نتیجه سؤال‌های کامل‌شده باقی می‌ماند و گزارش
تا همان نقطه دوباره ساخته می‌شود.

## محدودکردن مصرف token

```powershell
.\.venv\Scripts\python.exe evaluation\run_evaluation.py `
  --dataset evaluation\datasets\test1_candidate_bilingual.json `
  --db-name test1 `
  --max-token-budget 100000 `
  --run-dir evaluation\runs\budgeted_run
```

بودجه در مرز سؤال‌ها کنترل می‌شود؛ یک فراخوانی در حال اجرا وسط کار قطع نمی‌شود.
پس از رسیدن مجموع tokenهای checkpoint به سقف، اجرا به‌صورت امن متوقف می‌شود.

فیلترهای قابل استفاده:

```text
--language fa
--language en
--category aggregation
--category temporal
--limit 10
--retry-failed
```

برای چند category می‌توان گزینه `--category` را چند بار تکرار کرد.

## بازسازی گزارش از checkpoint

برای هماهنگ‌کردن تمام گزارش‌ها با وضعیت فعلی `checkpoint.jsonl` بدون اتصال به
دیتابیس یا فراخوانی مدل:

```powershell
.\.venv\Scripts\python.exe evaluation\run_evaluation.py `
  --dataset evaluation\datasets\questions_all.json `
  --db-name test1 `
  --db-type mssql `
  --resume evaluation\runs\v1 `
  --reports-only
```

این فرمان آخرین رکورد هر شناسه را از checkpoint انتخاب می‌کند و
`report.html`، `debug.html`، `summary.json`، `debug_eval.json` و
`per_question.csv` را دوباره می‌سازد.

## خروجی هر Run

```text
evaluation/runs/<run-name>/
├── manifest.json
├── checkpoint.jsonl
├── model_calls.jsonl
├── summary.json
├── per_question.csv
├── debug_eval.json
├── debug.html
└── report.html
```

- `checkpoint.jsonl`: نتیجه کامل هر سؤال برای resume
- `model_calls.jsonl`: audit فراخوانی‌های مدل همان run
- `summary.json`: معیارهای تجمیعی و breakdownها
- `per_question.csv`: خروجی مناسب بررسی در Excel
- `debug_eval.json`: داده‌های فشرده عیب‌یابی برای هر سؤال
- `debug.html`: مرور تعاملی و مستقل SQL مرجع، SQL تولیدشده، خطا و retrieval هر
  سؤال؛ evaluator آخرین رکوردهای checkpoint را هنگام ساخت گزارش داخل آن قرار
  می‌دهد تا فایل مستقیماً در مرورگر باز شود.
- `report.html`: گزارش فارسی مستقل با کارت‌ها، نمودارها و موارد ناموفق

## نکات اندازه‌گیری

- نتیجه SQL تولیدشده با نتیجه SQL مرجع مقایسه می‌شود، نه متن SQL.
- اگر SQL مرجع `ORDER BY` نداشته باشد، ترتیب سطرها در مقایسه نادیده گرفته
  می‌شود؛ سطرهای تکراری همچنان حفظ می‌شوند.
- فقط SQLهای read-only پذیرفته می‌شوند.
- R-VES فقط برای SQL دارای نتیجه صحیح محاسبه می‌شود.
- برای R-VES یک warm-up انجام می‌شود و ترتیب SQL مرجع/تولیدی در تکرارها جابه‌جا
  می‌شود.
- هزینه یک‌باره introspection/enrichment در `manifest.json` ثبت می‌شود و با
  latency هر سؤال مخلوط نمی‌شود.
