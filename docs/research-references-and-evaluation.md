# منابع پژوهشی و طرح ارزیابی پروژه Chat with Unknown Data

این سند برای بخش «مرور ادبیات»، توجیه انتخاب‌های معماری و طراحی ارزیابی
پروژه تهیه شده است. موضوع پروژه، تبدیل پرسش فارسی یا انگلیسی به T-SQL روی
پایگاه‌های داده‌ای است که مدل از قبل schema آن‌ها را ندیده است. فرایند فعلی
شامل introspection، غنی‌سازی معنایی schema، بازیابی جدول و ستون، تولید SQL،
اصلاح مبتنی بر اجرا و تولید پاسخ نهایی است.

> نکته استنادی: پروژه حاضر پیاده‌سازی مستقیم RAT-SQL، RESDSQL، DIN-SQL یا
> CHESS نیست. در گزارش بهتر است گفته شود معماری پروژه با ایده‌های schema
> linking، schema pruning، retrieval-augmented generation و execution-based
> correction مرتبط است یا از آن‌ها الهام گرفته است.

## ۱. منابع اصلی Text-to-SQL و مجموعه‌داده‌ها

### 1. Spider

- Tao Yu et al. (2018), *Spider: A Large-Scale Human-Labeled Dataset for
  Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task*, EMNLP.
- کاربرد در پروژه: تعریف مسئله cross-domain و سنجش تعمیم به schemaهای ناشناخته.
- مقاله و اطلاعات استناد: <https://aclanthology.org/D18-1425/>
- وب‌سایت رسمی: <https://yale-lily.github.io/spider>

### 2. BIRD

- Jinyang Li et al. (2023), *Can LLM Already Serve as A Database Interface? A
  BIg Bench for Large-Scale Database Grounded Text-to-SQLs*, NeurIPS.
- کاربرد در پروژه: Execution Accuracy، VES، مقادیر واقعی دیتابیس و کارایی SQL.
- مقاله رسمی: <https://proceedings.neurips.cc/paper_files/paper/2023/file/83fc8fab1710363050bbd1d4b8cc0021-Paper-Datasets_and_Benchmarks.pdf>
- وب‌سایت و leaderboard: <https://bird-bench.github.io/>

### 3. BIRD Mini-Dev و R-VES

- پیاده‌سازی رسمی EX، Soft-F1 و Reward-based Valid Efficiency Score.
- کاربرد در پروژه: مرجع اجرایی برای طراحی evaluator و تکرار اندازه‌گیری زمان.
- مخزن رسمی: <https://github.com/bird-bench/mini_dev>

### 4. Spider 2.0

- *Spider 2.0: Evaluating Language Models on Real-World Enterprise Text-to-SQL
  Workflows* (2025), ICLR.
- کاربرد در پروژه: پایگاه‌های enterprise، schemaهای بزرگ، dialectهای متفاوت و
  workflowهای واقعی.
- مقاله رسمی: <https://proceedings.iclr.cc/paper_files/paper/2025/hash/46c10f6c8ea5aa6f267bcdabcb123f97-Abstract-Conference.html>
- کد و داده: <https://github.com/xlang-ai/Spider2>

### 5. KaggleDBQA

- Chia-Hsuan Lee et al. (2021), *KaggleDBQA: Realistic Evaluation of
  Text-to-SQL Parsers*, ACL-IJCNLP.
- کاربرد در پروژه: schema و مستندات واقعی و فاصله benchmarkهای آزمایشگاهی با
  کاربرد عملی.
- مقاله: <https://aclanthology.org/2021.acl-long.176/>

### 6. Seq2SQL / WikiSQL

- Victor Zhong, Caiming Xiong, and Richard Socher (2017), *Seq2SQL: Generating
  Structured Queries from Natural Language using Reinforcement Learning*.
- کاربرد در پروژه: یکی از کارهای بنیادی تولید SQL و استفاده از reward اجرای
  query.
- مقاله: <https://arxiv.org/abs/1709.00103>

## ۲. Schema linking، نمایش schema و انتخاب عناصر مرتبط

### 7. RAT-SQL

- Bailin Wang et al. (2020), *RAT-SQL: Relation-Aware Schema Encoding and
  Linking for Text-to-SQL Parsers*, ACL.
- کاربرد در پروژه: نمایش روابط PK/FK و اتصال عبارت‌های سؤال به جدول و ستون.
- مقاله و BibTeX: <https://aclanthology.org/2020.acl-main.677/>

### 8. Re-examining the Role of Schema Linking

- Wenqiang Lei et al. (2020), *Re-examining the Role of Schema Linking in
  Text-to-SQL*, EMNLP.
- کاربرد در پروژه: توجیه ارزیابی مستقل Table Recall و Column Recall.
- مقاله و BibTeX: <https://aclanthology.org/2020.emnlp-main.564/>

### 9. RESDSQL

- Haoyang Li et al. (2023), *RESDSQL: Decoupling Schema Linking and Skeleton
  Parsing for Text-to-SQL*, AAAI.
- کاربرد در پروژه: رتبه‌بندی عناصر schema، کاهش schema ورودی و حذف نویز.
- مقاله و BibTeX: <https://ojs.aaai.org/index.php/AAAI/article/view/26535>

### 10. CHESS

- *CHESS: Contextual Harnessing for Efficient SQL Synthesis* (2024).
- کاربرد در پروژه: retrieval سلسله‌مراتبی، schema selection، تولید candidate و
  validation.
- مقاله: <https://arxiv.org/abs/2405.16755>

### 11. Rethinking Schema Linking

- Md Mahadi Hasan Nahid et al. (2026), *Rethinking Schema Linking: A
  Context-Aware Bidirectional Retrieval Approach for Text-to-SQL*, Findings of
  EACL.
- کاربرد در پروژه: بازیابی مرحله‌ای جدول و ستون و تحلیل recall در schemaهای
  بزرگ.
- مقاله و BibTeX: <https://aclanthology.org/2026.findings-eacl.236/>

## ۳. تولید SQL، prompting و اصلاح مبتنی بر اجرا

### 12. DIN-SQL

- Mohammadreza Pourreza and Davood Rafiei (2023), *DIN-SQL: Decomposed
  In-Context Learning of Text-to-SQL with Self-Correction*.
- کاربرد در پروژه: تجزیه فرایند به مراحل کوچک و self-correction.
- مقاله: <https://arxiv.org/abs/2304.11015>

### 13. Execution-Guided Decoding

- Chenglong Wang et al. (2018), *Robust Text-to-SQL Generation with
  Execution-Guided Decoding*.
- کاربرد در پروژه: استفاده از اجرای SQL و خطای موتور دیتابیس برای تشخیص و اصلاح
  خروجی نامعتبر.
- مقاله: <https://arxiv.org/abs/1807.03100>

### 14. PICARD

- Torsten Scholak, Nathan Schucher, and Dzmitry Bahdanau (2021), *PICARD:
  Parsing Incrementally for Constrained Auto-Regressive Decoding from Language
  Models*, EMNLP.
- کاربرد در پروژه: منبع مرتبط برای اعتبارسنجی ساختاری SQL و بخش کارهای آینده.
- مقاله و BibTeX: <https://aclanthology.org/2021.emnlp-main.779/>

### 15. C3

- Xuemei Dong et al. (2023), *C3: Zero-shot Text-to-SQL with ChatGPT*.
- کاربرد در پروژه: zero-shot prompting، calibration و خروجی سازگار.
- مقاله: <https://arxiv.org/abs/2307.07306>

### 16. DAIL-SQL

- Dawei Gao et al. (2023), *Text-to-SQL Empowered by Large Language Models: A
  Benchmark Evaluation*.
- کاربرد در پروژه: مقایسه روش‌های prompt، هزینه token و کارایی روش‌های مبتنی بر
  LLM.
- مقاله: <https://arxiv.org/abs/2308.15363>

## ۴. RAG، embedding و رتبه‌بندی

### 17. Retrieval-Augmented Generation

- Patrick Lewis et al. (2020), *Retrieval-Augmented Generation for
  Knowledge-Intensive NLP Tasks*, NeurIPS.
- کاربرد در پروژه: مرجع پایه retrieval قبل از generation. روش پروژه را می‌توان
  دقیق‌تر «schema retrieval-augmented generation» نامید.
- مقاله رسمی: <https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html>

### 18. BGE-M3

- Jianlv Chen et al. (2024), *BGE M3-Embedding: Multi-Lingual,
  Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge
  Distillation*.
- کاربرد در پروژه: embedding چندزبانه برای سؤال فارسی و metadata انگلیسی.
- مقاله: <https://arxiv.org/abs/2402.03216>

### 19. MIRACL

- Xinyu Zhang et al. (2023), *MIRACL: A Multilingual Retrieval Dataset
  Covering 18 Diverse Languages*, TACL.
- کاربرد در پروژه: مبانی ارزیابی retrieval چندزبانه.
- مقاله و BibTeX: <https://aclanthology.org/2023.tacl-1.63/>

### 20. Reciprocal Rank Fusion

- Gordon V. Cormack, Charles L. A. Clarke, and Stefan Büttcher (2009),
  *Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning
  Methods*, SIGIR.
- کاربرد در پروژه: مرجع مستقیم ترکیب رتبه‌های dense و BM25.
- صفحه انتشار: <https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/>
- PDF: <https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf>

### 21. BM25

- Stephen Robertson and Hugo Zaragoza (2009), *The Probabilistic Relevance
  Framework: BM25 and Beyond*, Foundations and Trends in Information Retrieval.
- کاربرد در پروژه: بازیابی lexical و تطابق دقیق identifierهای جدول و ستون.
- DOI: <https://doi.org/10.1561/1500000019>

### 22. BGE Reranker v2 M3

- مدل cross-encoder چندزبانه مورد استفاده در لایه RAG پروژه.
- کاربرد در پروژه: reranking کاندیداهای بازیابی‌شده پیش از انتخاب نهایی schema.
- Model Card: <https://huggingface.co/BAAI/bge-reranker-v2-m3>

## ۵. منابع روش‌شناسی ارزیابی

### 23. Test-suite Accuracy

- Ruiqi Zhong, Tao Yu, and Dan Klein (2020), *Semantic Evaluation for
  Text-to-SQL with Distilled Test Suites*, EMNLP.
- کاربرد در پروژه: نشان می‌دهد برابری نتیجه روی یک instance دیتابیس همیشه اثبات
  کامل برابری معنایی دو SQL نیست.
- مقاله و BibTeX: <https://aclanthology.org/2020.emnlp-main.29/>

### 24. Improving Text-to-SQL Evaluation Methodology

- Catherine Finegan-Dollak et al. (2018), *Improving Text-to-SQL Evaluation
  Methodology*, ACL.
- کاربرد در پروژه: طراحی split واقع‌گرایانه و جلوگیری از leakage میان سؤال‌های
  train و test.
- مقاله و BibTeX: <https://aclanthology.org/P18-1033/>

### 25. Evaluating Cross-Domain Text-to-SQL Models and Benchmarks

- *Evaluating Cross-Domain Text-to-SQL Models and Benchmarks* (2023), EMNLP.
- کاربرد در پروژه: محدودیت Execution Accuracy، ابهام سؤال‌ها و وجود چند SQL
  معادل.
- مقاله: <https://aclanthology.org/2023.emnlp-main.99/>

### 26. Survey

- Naihao Deng, Yulong Chen, and Yue Zhang (2022), *Recent Advances in
  Text-to-SQL: A Survey of What We Have and What We Expect*, COLING.
- کاربرد در پروژه: منبع مناسب برای ساختار فصل مرور ادبیات و طبقه‌بندی روش‌ها.
- مقاله و BibTeX: <https://aclanthology.org/2022.coling-1.190/>

## ۶. ارزیابی روی پایگاه داده خود پروژه

بله، و برای سنجش کاربرد واقعی سامانه، ارزیابی روی پایگاه داده خود پروژه از
اجرای صرف BIRD مناسب‌تر است. با این حال، برای آن باید یک مجموعه ارزیابی مرجع
(Gold Benchmark) ایجاد شود. برای هر نمونه حداقل اطلاعات زیر لازم است:

```json
{
  "id": "q001",
  "db_name": "AccountingDB",
  "question": "مجموع مبلغ اسناد ثبت‌شده در سال ۱۴۰۳ چقدر است؟",
  "reference_sql": "SELECT ...",
  "gold_tables": ["ACC.Voucher", "ACC.VoucherItem"],
  "gold_columns": [
    "ACC.Voucher.CreationDate",
    "ACC.VoucherItem.Amount"
  ],
  "difficulty": "medium"
}
```

`reference_sql` باید توسط فرد آشنا با منطق کسب‌وکار و schema نوشته یا تأیید
شود. بدون SQL یا پاسخ مرجع، latency و نرخ اجرای بدون خطا قابل‌اندازه‌گیری است،
ولی EX، VES و R-VES معتبر قابل محاسبه نیستند؛ چون مشخص نیست پاسخ تولیدشده صحیح
است یا خیر.

### اندازه پیشنهادی مجموعه ارزیابی

برای نسخه اولیه، حداقل 100 سؤال:

| گروه | تعداد پیشنهادی |
|---|---:|
| تک‌جدولی و projection ساده | 15 |
| filter و جست‌وجوی مقدار | 20 |
| aggregation و group by | 15 |
| join دو یا چند جدول | 20 |
| تاریخ و زمان | 10 |
| subquery، CTE یا query پیچیده | 10 |
| فارسی، غلط املایی و مقدار نزدیک | 10 |

سؤال‌ها باید از نظر سختی، schema و الگوی SQL متنوع باشند. اگر سؤال‌های مشابه
هم در توسعه prompt و هم در test استفاده شوند، نتیجه بیش از حد خوش‌بینانه خواهد
بود؛ بنابراین مجموعه development و test باید جدا باشد.

## ۷. معیارهای قابل محاسبه

### Execution Accuracy

اگر نتیجه SQL مرجع و SQL تولیدشده برابر باشد، نمونه صحیح است:

```text
EX = تعداد SQLهای دارای نتیجه صحیح / تعداد کل سؤال‌ها
```

EX باید معیار اصلی پروژه باشد. Exact Match متن SQL معیار اصلی مناسبی نیست؛ چون
دو SQL با متن متفاوت می‌توانند از نظر معنایی و نتیجه معادل باشند.

### VES اولیه BIRD

```text
VES = (1/N) × Σ correct_i × sqrt(T_reference_i / T_generated_i)
```

SQL اشتباه، timeoutشده یا اجرا‌نشده امتیاز صفر می‌گیرد. اگر SQL تولیدشده صحیح و
سریع‌تر از مرجع باشد، امتیاز نمونه می‌تواند از یک بیشتر شود.

### R-VES

BIRD اکنون برای submissionهای جدید از Reward-based VES استفاده می‌کند. این
نسخه نسبت زمان را به rewardهای کنترل‌شده تبدیل می‌کند تا نوسان زمان و outlierها
اثر نامتناسبی روی نتیجه نداشته باشند. برای مقایسه پژوهشی بهتر است EX، VES قدیمی
و R-VES جداگانه و با نام دقیق گزارش شوند.

### معیارهای RAG

```text
Table Recall = |retrieved tables ∩ gold tables| / |gold tables|
Table Precision = |retrieved tables ∩ gold tables| / |retrieved tables|
Column Recall = |retrieved columns ∩ gold columns| / |gold columns|
```

برای این پروژه `Table Recall@8` اهمیت زیادی دارد؛ چون لایه RAG حداکثر هشت جدول
را انتخاب می‌کند. حذف یک جدول ضروری معمولاً تولید SQL صحیح را غیرممکن می‌کند.

### معیارهای self-correction

```text
Correction Gain = EX_after_correction - EX_before_correction
Correction Success Rate = corrected failures / attempted corrections
```

علاوه بر آن باید متوسط retry، نرخ اصلاح نتیجه خالی و نرخ خراب‌شدن یک SQL صحیح
پس از اصلاح گزارش شود.

### معیارهای عملیاتی

- Valid SQL Rate
- End-to-End Latency
- زمان جداگانه retrieval، LLM، SQL و correction
- تعداد فراخوانی LLM و embedding
- تعداد token ورودی و خروجی
- درصد cache hit در enrichment و embedding

## ۸. پروتکل اندازه‌گیری زمان روی SQL Server

1. SQL مرجع و تولیدشده روی snapshot یکسان داده اجرا شوند.
2. برای هر query یک timeout ثابت تعیین شود.
3. هر SQL حداقل پنج بار اجرا و median زمان‌ها استفاده شود.
4. ترتیب اجرای SQL مرجع و تولیدشده تصادفی یا متناوب باشد.
5. زمان اجرای query تا دریافت کامل سطرها اندازه‌گیری شود.
6. سخت‌افزار، نسخه SQL Server، indexها و بار سیستم ثابت نگه داشته شوند.
7. زمان LLM و RAG وارد VES نشود و جداگانه به‌عنوان end-to-end latency گزارش شود.
8. queryهای تغییردهنده داده مجاز نباشند؛ ارزیابی فقط read-only باشد.

در مقایسه نتایج باید ترتیب سطرها فقط در صورت وجود `ORDER BY` مهم باشد، سطرهای
تکراری حفظ شوند، `NULL` به شکل ثابت مقایسه شود و برای float/decimal tolerance
کوچک و از پیش تعیین‌شده در نظر گرفته شود.

## ۹. آزمایش‌های Ablation پیشنهادی

| آزمایش | Dense | BM25 | RRF | Reranker | Enrichment | Correction |
|---|---:|---:|---:|---:|---:|---:|
| Dense baseline | ✓ | — | — | — | — | — |
| Hybrid retrieval | ✓ | ✓ | ✓ | — | — | — |
| Hybrid + reranker | ✓ | ✓ | ✓ | ✓ | — | — |
| Full retrieval | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Complete pipeline | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

برای هر حالت حداقل EX، R-VES، Table Recall@8، Column Recall، Valid SQL Rate،
end-to-end latency و متوسط مصرف token گزارش شود. این آزمایش‌ها نشان می‌دهند
افزایش دقت واقعاً از کدام جزء معماری حاصل شده است.

## ۱۰. مجموعه نهایی معیارهای پیشنهادی

```text
معیار اصلی:             Execution Accuracy
معیار صحت تکمیلی:       Test-suite Accuracy در صورت امکان
معیار کارایی SQL:       R-VES (و VES برای بازتولید مقاله BIRD)
معیارهای retrieval:     Table Recall@8 و Column Recall
معیار correction:       Correction Gain و Success Rate
معیارهای عملیاتی:       End-to-End Latency، LLM Calls و Token Usage
```

این ترکیب هم امکان مقایسه علمی با BIRD و Spider را فراهم می‌کند و هم کیفیت واقعی
سامانه روی پایگاه داده فارسی و SQL Server خود پروژه را نشان می‌دهد.
