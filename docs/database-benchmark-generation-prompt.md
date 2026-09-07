# دستور ساخت مجموعه ارزیابی Text-to-SQL از روی پایگاه داده

این فایل را می‌توان به یک چت‌بات متصل به پایگاه داده داد تا مجموعه‌ای از
سؤال‌های فارسی و انگلیسی همراه با SQL مرجع و metadata لازم برای ارزیابی یک
سامانه Text-to-SQL تولید کند.

## نحوه استفاده

1. چت‌بات باید دسترسی **فقط‌خواندنی** به پایگاه داده داشته باشد.
2. متن بخش «پرامپت آماده» را برای چت‌بات ارسال کنید.
3. مقدار `INTENT_COUNT` را تعیین کنید.
4. خروجی را ابتدا با وضعیت `candidate` ذخیره کنید.
5. پس از بازبینی انسانی، فقط نمونه‌های تأییدشده وارد مجموعه `gold` شوند.

اگر `INTENT_COUNT = 100` باشد و هر intent یک نسخه فارسی و یک نسخه انگلیسی
داشته باشد، خروجی نهایی شامل **۲۰۰ سؤال** خواهد بود. اگر دقیقاً ۱۰۰ سؤال
می‌خواهید، `INTENT_COUNT = 50` قرار دهید.

---

# مفاهیمی که چت‌بات باید بداند

## Intent

یک درخواست معنایی مستقل از زبان است. برای مثال «تعداد قراردادها» یک intent
است که می‌تواند دو صورت زبانی داشته باشد:

- فارسی: تعداد کل قراردادها چقدر است؟
- انگلیسی: How many contracts are there?

هر دو سؤال باید یک `reference_sql` یکسان داشته باشند. این طراحی امکان مقایسه
عملکرد سیستم روی فارسی و انگلیسی را فراهم می‌کند.

## Reference SQL یا Gold SQL

SQL صحیحی است که به‌عنوان پاسخ مرجع سؤال در نظر گرفته می‌شود. این SQL باید:

- روی پایگاه داده فعلی بدون خطا اجرا شود؛
- دقیقاً به معنای سؤال پاسخ دهد؛
- فقط خواندنی باشد؛
- از dialect واقعی پایگاه داده استفاده کند؛
- تا حد امکان ساده، قطعی و کارا باشد؛
- توسط فرد آشنا با schema و منطق کسب‌وکار قابل بازبینی باشد.

وجود SQL مرجع برای محاسبه Execution Accuracy، VES و R-VES ضروری است.

## Gold Tables

فهرست حداقلی جدول‌هایی است که برای پاسخ صحیح به سؤال لازم‌اند. نام هر جدول باید
کاملاً qualified و به شکل `schema.table` باشد:

```json
"gold_tables": [
  "CNT.Contract",
  "CNT.Status"
]
```

جدولی که فقط به‌صورت غیرضروری در یک SQL خاص استفاده شده نباید gold table باشد.
هدف، ثبت **حداقل schema لازم** برای پاسخ است. از این فیلد برای محاسبه Table
Recall و Table Precision لایه RAG استفاده می‌شود.

## Gold Columns

فهرست حداقلی ستون‌های لازم برای filter، join، projection، aggregation، grouping
و ordering است. نام ستون‌ها باید به شکل `schema.table.column` ثبت شود:

```json
"gold_columns": [
  "CNT.Contract.ContractID",
  "CNT.Contract.Title",
  "CNT.Status.ContractRef",
  "CNT.Status.InitialSettledValue"
]
```

ستون‌های زیر باید در صورت استفاده ثبت شوند:

- ستون خروجی `SELECT`؛
- ستون شرط `WHERE`؛
- کلیدهای مورد استفاده در `JOIN`؛
- ستون `GROUP BY`؛
- ستون `ORDER BY`؛
- ستون ورودی توابعی مانند `SUM`، `AVG`، `MIN` و `MAX`.

برای `COUNT(*)` لازم نیست یک ستون مصنوعی در `gold_columns` درج شود.

## Gold Result

نتیجه اجرای SQL مرجع است. ذخیره کامل نتیجه الزامی نیست و برای نتایج بزرگ توصیه
نمی‌شود. evaluator می‌تواند SQL مرجع را هنگام ارزیابی اجرا کند. در صورت نیاز
می‌توان اطلاعات زیر را ذخیره کرد:

```json
"gold_result_summary": {
  "row_count": 1,
  "columns": ["RecordCount"]
}
```

نباید اطلاعات شخصی، رمز، token، شماره حساب یا داده حساس در فایل benchmark
ذخیره شود.

## Difficulty

سطح دشواری بر اساس ساختار SQL تعیین شود، نه طول سؤال:

- `easy`: یک جدول، projection، filter یا aggregation ساده؛
- `medium`: یک join، group by، چند شرط، محاسبه یا بازه زمانی؛
- `hard`: چند join، subquery، CTE، window function یا aggregation چندمرحله‌ای؛
- `very_hard`: چند زیرپرس‌وجو، joinهای چندمرحله‌ای، منطق زمانی یا تحلیلی پیچیده.

## Category

نوع اصلی مهارت مورد نیاز سؤال است. مقادیر پیشنهادی:

- `simple_projection`
- `filter_lookup`
- `aggregation`
- `grouping`
- `multi_table_join`
- `temporal`
- `subquery_cte`
- `window_function`
- `persian_value_lookup`
- `typo_value_recovery`
- `structural_metadata`

اگر سؤال چند مهارت دارد، یک `category` اصلی و چند `tags` ثبت شود.

## Review Status

- `candidate`: توسط چت‌بات تولید شده ولی هنوز بررسی انسانی نشده است؛
- `approved`: سؤال، SQL و metadata توسط بازبین تأیید شده‌اند؛
- `rejected`: نمونه نامعتبر، مبهم، تکراری یا غیرمفید است؛
- `needs_revision`: نمونه نیازمند اصلاح است.

تنها نمونه‌های `approved` باید در محاسبه نهایی معیارها استفاده شوند.

## Expected Empty Result

اگر SQL مرجع به‌صورت طبیعی نتیجه خالی دارد، این موضوع باید مشخص شود:

```json
"expected_empty": true
```

تا زمانی که هدف سؤال مشخصاً آزمون وضعیت خالی نیست، بهتر است سؤال‌هایی تولید شوند
که SQL مرجع حداقل یک سطر برگرداند. نتیجه خالی می‌تواند SQLهای معنایی متفاوت را
به‌اشتباه معادل نشان دهد.

---

# توزیع پیشنهادی ۱۰۰ Intent

هر intent در دو زبان تولید می‌شود؛ بنابراین جدول زیر ۱۰۰ intent و ۲۰۰ سؤال
زبانی ایجاد می‌کند.

| گروه | تعداد intent | فارسی | انگلیسی | سطح غالب |
|---|---:|---:|---:|---|
| تک‌جدولی و projection ساده | 15 | 15 | 15 | easy |
| شرط، جست‌وجوی مقدار و چند شرط | 20 | 20 | 20 | easy/medium |
| aggregation و group by | 15 | 15 | 15 | easy/medium |
| join دو یا چند جدول | 20 | 20 | 20 | medium/hard |
| تاریخ، زمان و بازه زمانی | 10 | 10 | 10 | medium |
| subquery، CTE و window function | 10 | 10 | 10 | hard/very_hard |
| فارسی، غلط املایی و مقدار نزدیک | 10 | 10 | 10 | medium/hard |
| **مجموع** | **100** | **100** | **100** | — |

توزیع سطح دشواری پیشنهادی:

| سطح | درصد هدف |
|---|---:|
| easy | 30% |
| medium | 40% |
| hard | 25% |
| very_hard | 5% |

توزیع schema و جدول نیز باید تا حد امکان متوازن باشد:

- بیش از ۱۵٪ intentها از یک schema نباشند، مگر اینکه پایگاه داده عملاً فقط یک
  schema اصلی داشته باشد.
- بیش از سه intent مشابه برای یک جدول تولید نشود.
- جدول‌های کم‌کاربرد در کنار جدول‌های اصلی پوشش داده شوند.
- حداقل ۲۰٪ intentها به بیش از یک جدول نیاز داشته باشند.
- مسیرهای join یک‌مرحله‌ای و چندمرحله‌ای هر دو پوشش داده شوند.

---

# قواعد تولید سؤال

1. سؤال باید بدون دیدن نام فنی ستون‌ها برای یک کاربر کسب‌وکار قابل‌فهم باشد.
2. نسخه فارسی باید ترجمه طبیعی intent باشد، نه ترجمه کلمه‌به‌کلمه identifierها.
3. نسخه فارسی و انگلیسی باید دقیقاً یک معنا و یک SQL مرجع داشته باشند.
4. سؤال نباید اطلاعاتی را بخواهد که در schema یا داده قابل استنتاج نیست.
5. از ساختن رابطه، جدول، ستون یا قانون کسب‌وکاری غیرواقعی خودداری شود.
6. برای هر join فقط از FK واقعی یا رابطه‌ای که با داده و schema تأیید شده استفاده
   شود.
7. سؤال مبهم نباشد. واژه‌هایی مانند «بهترین»، «مهم‌ترین»، «فعال» یا «فروش» فقط
   وقتی استفاده شوند که تعریف آن‌ها از schema یا مستندات مشخص باشد.
8. در سؤال‌های زمانی، دقت زمان صریح باشد: روز، ماه، سال، ساعت یا بازه.
9. برای سؤال دارای مقدار واقعی، مقدار باید ابتدا با query محدود و read-only از
   همان ستون خوانده شود؛ مقدار حدسی ساخته نشود.
10. داده حساس وارد سؤال نشود. برای اشخاص، کاربران، تلفن، حساب بانکی و موارد
    مشابه از مقدار واقعی استفاده نشود.
11. سؤال‌های تکراری که فقط نام جدولشان تغییر کرده است بیش از حد تولید نشوند.
12. نتیجه SQL مرجع تا حد امکان محدود باشد؛ برای فهرست‌ها از `TOP 20` استفاده
    شود.
13. اگر ترتیب خروجی بخشی از سؤال است، `ORDER BY` الزامی است.
14. اگر ترتیب مهم نیست، سؤال نباید عباراتی مانند «اولین» یا «آخرین» داشته باشد.
15. برای مقادیر فارسی در SQL Server از literal یونیکد مانند `N'تهران'` استفاده
    شود.

---

# قواعد SQL مرجع برای Microsoft SQL Server

1. فقط `SELECT` یا `WITH ... SELECT` مجاز است.
2. استفاده از `INSERT`، `UPDATE`، `DELETE`، `MERGE`، `DROP`، `ALTER`، `TRUNCATE`
   و اجرای procedure ممنوع است.
3. نام schema، جدول و ستون با براکت نوشته شود:

   ```sql
   SELECT [Title] FROM [CNT].[Contract]
   ```

4. برای محدودکردن خروجی از `TOP` استفاده شود، نه `LIMIT`.
5. برای متن فارسی و غیر ASCII از پیشوند `N` استفاده شود:

   ```sql
   WHERE [Title] = N'حسن انجام کار'
   ```

6. join باید شرط مشخص و قابل دفاع داشته باشد؛ `CROSS JOIN` بدون ضرورت ممنوع است.
7. از `SELECT *` خودداری شود، مگر در سؤال ساختاری که همه ستون‌ها صریحاً خواسته
   شده باشند.
8. برای یک روز کامل از بازه نیمه‌باز استفاده شود:

   ```sql
   WHERE [Date] >= '20260101' AND [Date] < '20260102'
   ```

9. روی ستون datetime از `CAST([Date] AS DATE)` در شرط خودداری شود تا index قابل
   استفاده بماند.
10. در محاسبات nullable، تصمیم درباره `COALESCE` باید با معنای کسب‌وکار سازگار
    باشد و خودکار فرض نشود.
11. برای جلوگیری از تقسیم بر صفر از `NULLIF` استفاده شود.
12. SQL مرجع باید timeout معقول داشته و تمام نتیجه آن قابل دریافت باشد.

---

# قالب الزامی خروجی

خروجی یک JSON object معتبر و بدون markdown fence باشد:

```json
{
  "metadata": {
    "database": "نام پایگاه داده",
    "dialect": "mssql",
    "status": "candidate_not_gold",
    "intent_count": 100,
    "question_count": 200,
    "languages": ["fa", "en"],
    "generated_at": "ISO-8601 timestamp"
  },
  "records": [
    {
      "id": "intent_001_fa",
      "intent_id": "intent_001",
      "language": "fa",
      "question": "تعداد کل قراردادها چقدر است؟",
      "reference_sql": "SELECT COUNT_BIG(*) AS [RecordCount] FROM [CNT].[Contract]",
      "gold_tables": ["CNT.Contract"],
      "gold_columns": [],
      "category": "aggregation",
      "tags": ["count", "single_table"],
      "difficulty": "easy",
      "expected_empty": false,
      "review_status": "candidate",
      "review_notes": ""
    },
    {
      "id": "intent_001_en",
      "intent_id": "intent_001",
      "language": "en",
      "question": "How many contracts are there?",
      "reference_sql": "SELECT COUNT_BIG(*) AS [RecordCount] FROM [CNT].[Contract]",
      "gold_tables": ["CNT.Contract"],
      "gold_columns": [],
      "category": "aggregation",
      "tags": ["count", "single_table"],
      "difficulty": "easy",
      "expected_empty": false,
      "review_status": "candidate",
      "review_notes": ""
    }
  ]
}
```

## فیلدهای اختیاری مفید

در صورت امکان، این فیلدها نیز افزوده شوند:

```json
{
  "business_domain": "contract_management",
  "join_path": [
    "CNT.Contract.ContractID = CNT.Status.ContractRef"
  ],
  "result_columns": ["ContractTitle", "StatusCount"],
  "gold_result_summary": {
    "row_count": 10,
    "columns": ["ContractTitle", "StatusCount"]
  },
  "generation_evidence": {
    "foreign_keys_verified": true,
    "reference_sql_executed": true
  }
}
```

---

# کنترل کیفیت الزامی قبل از تحویل

چت‌بات باید برای هر نمونه مراحل زیر را انجام دهد:

1. وجود تمام `gold_tables` را در schema بررسی کند.
2. وجود تمام `gold_columns` را بررسی کند.
3. رابطه تمام joinها را با FK یا metadata معتبر تأیید کند.
4. SQL مرجع را در حالت read-only اجرا کند.
5. خطا و timeout نداشتن SQL را بررسی کند.
6. بررسی کند نتیجه به سؤال پاسخ می‌دهد.
7. بررسی کند نسخه فارسی و انگلیسی یک intent یکسان دارند.
8. سؤال و SQL تکراری نباشند.
9. مقادیر واقعی مورد استفاده در filter در همان ستون وجود داشته باشند.
10. اطلاعات حساس در سؤال یا خروجی ذخیره نشده باشد.
11. توزیع نهایی category، difficulty و schema را گزارش کند.
12. اگر موردی قابل تأیید نیست، آن را حذف نکند؛ با `needs_revision` و توضیح مشخص
    علامت بزند.

نمونه گزارش نهایی:

```json
{
  "validation_summary": {
    "generated_intents": 100,
    "generated_questions": 200,
    "executed_successfully": 94,
    "needs_revision": 6,
    "sensitive_items_removed": 3,
    "duplicate_items_removed": 4,
    "category_distribution": {
      "simple_projection": 15,
      "filter_lookup": 20,
      "aggregation_grouping": 15,
      "multi_table_join": 20,
      "temporal": 10,
      "subquery_cte_window": 10,
      "persian_typo_value": 10
    }
  }
}
```

---

# پرامپت آماده برای ارسال به چت‌بات متصل به دیتابیس

متن زیر را کپی کنید و در صورت نیاز فقط مقادیر داخل `<>` را تغییر دهید:

```text
You are creating a candidate gold benchmark for evaluating a bilingual
Persian/English Text-to-SQL system over the database you are connected to.

Database dialect: Microsoft SQL Server (T-SQL)
INTENT_COUNT: <100>
LANGUAGES: Persian and English

Safety:
- Use read-only schema inspection and SELECT queries only.
- Never execute INSERT, UPDATE, DELETE, MERGE, DROP, ALTER, TRUNCATE, stored
  procedures, dynamic SQL, or any query that can modify state.
- Do not expose passwords, tokens, personal identifiers, phone numbers, bank
  data, addresses, salaries, or other sensitive values.

Definitions:
- An intent is one language-independent information request.
- Produce one natural Persian question and one natural English question for
  every intent. Both versions must use exactly the same reference_sql.
- reference_sql is the verified read-only T-SQL query that correctly answers
  the intent.
- gold_tables is the minimal set of required tables in schema.table form.
- gold_columns is the minimal set of columns required for SELECT, WHERE, JOIN,
  GROUP BY, ORDER BY, or aggregation, in schema.table.column form.
- review_status must initially be candidate. Use needs_revision when a sample
  cannot be fully validated.

Required intent distribution for 100 intents:
- 15 single-table projection questions
- 20 filters, value lookups, or multi-condition questions
- 15 aggregation or GROUP BY questions
- 20 questions requiring joins between two or more tables
- 10 date/time/range questions
- 10 subquery, CTE, or window-function questions
- 10 Persian-value, spelling-variation, or near-value recovery questions

Target difficulty distribution:
- 30% easy
- 40% medium
- 25% hard
- 5% very_hard

Schema coverage:
- Inspect the real schemas, tables, columns, primary keys, foreign keys,
  nullability, and data types before generating questions.
- Do not invent schema elements or business rules.
- Use only verified FK relationships for joins.
- Avoid concentrating more than 15% of intents in one schema when the database
  contains multiple business schemas.
- Avoid more than three semantically similar intents for one table.
- At least 20% of intents must require multiple tables.

Question quality:
- Questions must sound natural to business users and must not merely repeat
  technical column identifiers.
- Persian and English versions must be semantically equivalent.
- Avoid ambiguous terms unless their meaning is documented in the database.
- Prefer reference queries that return at least one row. Mark intentionally
  empty cases with expected_empty=true.
- For real value filters, first retrieve a small bounded sample from the exact
  column and use only a confirmed non-sensitive value.

T-SQL requirements:
- Use [schema].[table] and [column] quoting.
- Use TOP instead of LIMIT.
- Prefix Persian/non-ASCII string literals with N.
- Avoid SELECT *.
- Use index-friendly half-open ranges for datetime periods.
- Add ORDER BY whenever the question requests first, last, highest, lowest,
  latest, or earliest results.
- Keep all reference queries read-only and reasonably bounded.

For every intent:
1. Generate Persian and English questions.
2. Generate one shared reference_sql.
3. Verify every table and column against the live schema.
4. Verify join paths using declared foreign keys or authoritative metadata.
5. Execute the reference SQL read-only and confirm it succeeds.
6. Record minimal gold_tables and gold_columns.
7. Assign category, tags, and difficulty.
8. Mark ambiguous or unverified samples as needs_revision with review_notes.

Return one valid JSON object only, without markdown fences or explanatory text.
Use this record schema:
{
  "id": "intent_001_fa",
  "intent_id": "intent_001",
  "language": "fa|en",
  "question": "...",
  "reference_sql": "...",
  "gold_tables": ["schema.table"],
  "gold_columns": ["schema.table.column"],
  "category": "...",
  "tags": ["..."],
  "difficulty": "easy|medium|hard|very_hard",
  "order_sensitive": false,
  "expected_empty": false,
  "review_status": "candidate|needs_revision",
  "review_notes": ""
}

Return metadata, records, and validation_summary at the top level. Ensure the
number and distribution of generated intents exactly match the requested plan.
```

## پیشنهاد فرایند بازبینی انسانی

برای هر intent، بازبین این موارد را علامت بزند:

```text
[ ] سؤال فارسی طبیعی و بدون ابهام است.
[ ] سؤال انگلیسی دقیقاً همان معنا را دارد.
[ ] SQL مرجع بدون خطا اجرا می‌شود.
[ ] نتیجه SQL واقعاً پاسخ سؤال است.
[ ] جدول‌ها و ستون‌های gold کامل و حداقلی هستند.
[ ] joinها از نظر کسب‌وکاری صحیح‌اند.
[ ] سؤال حاوی اطلاعات حساس نیست.
[ ] category و difficulty درست تعیین شده‌اند.
```

بعد از تأیید همه موارد:

```json
"review_status": "approved"
```

اگر سؤال یا SQL اصلاح شد، هر دو نسخه فارسی و انگلیسی و تمام gold metadata دوباره
بررسی شوند.
