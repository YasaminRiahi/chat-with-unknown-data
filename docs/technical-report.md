# A Bilingual, Schema-Grounded Text-to-SQL System for Unseen Enterprise Databases

## Technical report

### Abstract

Natural-language interfaces to relational databases can enable non-technical
users to access organizational data without writing SQL. Applying such systems
to previously unseen databases remains difficult, however, because table and
column names, relationships, naming conventions, and domain-specific values are
not known in advance. This report presents **Conversation with Data**, a
bilingual natural-language-to-SQL system that maps English or Persian questions
to read-only Microsoft SQL Server queries over databases whose schemas are
discovered at runtime.

The proposed pipeline dynamically introspects the database and enriches its
schema elements with conservative bilingual descriptions and vector
representations. To construct a compact, query-relevant generation context,
dense multilingual retrieval and BM25 lexical retrieval are combined through
Reciprocal Rank Fusion while primary keys, foreign keys, and required
relationships are preserved. A bounded schema-linking stage then refines the
retrieved candidates before a large language model generates schema-grounded
T-SQL. Every generated or repaired query passes through read-only safety controls
that reject data-changing, administrative, and multi-statement operations.
Execution feedback supports bounded repair of invalid queries and unexpectedly
empty results. Finally, the system produces a concise answer in the question's
language and deterministically selects a KPI, table, bar chart, or line chart
without altering the executed result.

The pipeline was evaluated on an internal set of 200 Persian and English
questions over the previously unseen Sepidar accounting database. Initial
execution accuracy was 90.5% and increased to 95.5% after bounded
self-correction; the final valid-SQL rate was 100%, table recall was 97.0%, and
column recall was 97.1%. These findings demonstrate the practical potential of
combining dynamic schema discovery, hybrid retrieval, schema linking,
constrained query generation, and execution-guided correction for conversational
access to unfamiliar database schemas. Nevertheless, the results apply only to
the tested database and configuration. Evaluation across additional databases,
domains, model providers, and public benchmarks is required before making a
broader generalizability claim.

**Keywords:** natural-language-to-SQL, unknown database schema, schema
introspection, hybrid retrieval, schema linking, bounded self-correction, large
language models, conversational data access

## 1. Introduction

Text-to-SQL is a form of grounded semantic parsing: a natural-language request
must be translated into a formal program whose meaning depends on a particular
relational schema. Cross-domain benchmarks such as Spider emphasize that the
train and test databases should differ, making generalization to new schemas a
first-class problem [1]. BIRD extends the practical setting with larger
databases, real values, external knowledge, and query efficiency [2]. Enterprise
deployments add further complications: schemas are wide, identifiers are often
abbreviated, foreign-key declarations may be incomplete, business terminology
may be multilingual, and a syntactically valid query may still be semantically
wrong.

Conversation with Data addresses the following research question:

> How can an LLM-based system answer bilingual analytical questions over an
> unseen enterprise database while controlling schema context, preserving
> structural fidelity, enforcing read-only execution, and exposing measurable
> failure points?

The system uses no schema-specific fine-tuning. Instead, it discovers metadata
at runtime and constructs a query-specific representation of the database. This
design follows three principles:

1. **Ground before generation.** The model receives retrieved schema elements
   and relationships rather than an unconstrained database description.
2. **Separate failure modes.** Retrieval, linking, generation, execution, and
   presentation are independently observable and testable.
3. **Treat execution as evidence, not permission.** Database feedback may repair
   a bounded query, but every candidate remains subject to the same read-only
   policy.

## 2. Task formulation

Let a database be represented by schema graph

$$G=(V_T \cup V_C, E_{PK} \cup E_{FK}),$$

where $V_T$ is the set of tables, $V_C$ the set of columns, and the edge sets
encode primary-key membership and foreign-key relationships. Given a question
$q$ in English or Persian, the system must produce SQL program $s$ such that:

1. $s$ is valid T-SQL for the target database;
2. $s$ is read-only;
3. executing $s$ returns the intended denotation of $q$; and
4. the returned rows are summarized without introducing unsupported facts.

For a large schema, passing all of $G$ to the language model is undesirable.
The system therefore retrieves a bounded subgraph $G_q \subseteq G$ and
approximates:

$$P(s \mid q,G) \approx P(s \mid q,G_q).$$

This approximation creates a recall--precision trade-off. Excessive pruning can
remove a required table or column; insufficient pruning increases prompt length
and introduces distractors. The retrieval and linking stages are designed to
manage this trade-off explicitly.

## 3. System architecture

The architecture diagram in the project README presents seven **conceptual**
processing stages. The source code exposes seven **implementation** layers, with
slightly different boundaries: schema linking is implemented within `RAGLayer`,
while answer generation and visualization are separate classes. This distinction
does not change the data flow, but documenting it prevents the diagram from
being mistaken for a one-to-one package map.

| Conceptual stage | Primary implementation | Input | Output |
|---|---|---|---|
| 1. Schema introspection | `pipeline/introspection` | Database connection | Authoritative schemas, tables, columns, PKs, FKs |
| 2. Schema enrichment | `pipeline/enrichment` | Introspected metadata | Bilingual descriptions and retrieval text |
| 3. Hybrid retrieval | `pipeline/rag` | Question and enriched metadata | Ranked tables and columns |
| 4. Schema linking | `pipeline/rag` | Candidate schema graph | Small coherent schema subgraph |
| 5. SQL generation | `pipeline/sql_generation` | Question and schema context | Candidate read-only T-SQL |
| 6. Validation, execution, and repair | `pipeline/sql_safety`, `pipeline/self_correction` | Candidate SQL | Executed SQL and rows |
| 7. Answer and visualization | `pipeline/answer_generation`, `pipeline/visualization` | Question, SQL, and rows | Grounded prose and display metadata |

The FastAPI layer manages routing, active-database selection, conversation
context, and model-call logging. Persistent enrichment and embedding caches
reduce repeated setup cost. A deterministic metadata path answers structural
questions such as table counts without invoking embeddings or a chat model.

## 4. Layer-wise methodology

### 4.1 Layer 1: schema introspection

The first layer queries SQLAlchemy's inspection interface to obtain the
database's user schemas, tables, columns, primary keys, foreign keys, types, and
relationships. Introspection is authoritative: later semantic descriptions may
assist retrieval, but they do not replace database metadata.

The result can be interpreted as a typed schema graph. Explicit foreign keys are
particularly valuable because multi-table SQL generation is a graph traversal
problem as well as a language problem. Caching this representation by active
database avoids repeating discovery for each question.

**Theoretical role.** Cross-domain parsers must encode database structure and
align language with schema elements. RAT-SQL demonstrates the importance of
relation-aware schema encoding and linking [3]. This project does not implement
RAT-SQL; it shares the more general premise that relational structure should be
represented explicitly rather than left for a decoder to infer from names.

### 4.2 Layer 2: semantic enrichment

Raw enterprise identifiers can be cryptic. The enrichment layer creates
conservative table and column descriptions and retrieval documents while
preserving the original identifiers. Bilingual descriptions help bridge Persian
questions and predominantly English schema names. Enrichment is cached by a DDL
fingerprint, so unchanged tables are reused and changed tables are recomputed.

The layer follows a provenance rule:

$$\text{authoritative structure} \;>\; \text{generated description}.$$

Generated text may improve retrieval but must not invent columns,
relationships, constraints, or business semantics. This is an important
distinction between semantic augmentation and schema modification.

### 4.3 Layer 3: hybrid schema retrieval

Each metadata document is scored by two complementary retrieval models:

- **Dense retrieval** embeds the question and schema descriptions using the
  multilingual BGE-M3 model, then uses cosine similarity.
- **Lexical retrieval** uses BM25 over prose and tokenized SQL identifiers,
  retaining exact matches that dense representations may blur.

For query vector $x$ and schema-document vector $y$, cosine similarity is

$$\cos(x,y)=\frac{x\cdot y}{\lVert x\rVert_2\lVert y\rVert_2}.$$

BM25 scores term $t$ in document $d$ using term frequency, inverse document
frequency, document length, and saturation parameters [4]. Dense and lexical
scores are not directly comparable, so the system fuses their *ranks* using
Reciprocal Rank Fusion (RRF) [5]:

$$RRF(d)=\sum_{r\in R}\frac{1}{k+rank_r(d)},$$

with $k=60$ in the implementation. Forty fused table candidates are considered
before deterministic identifier and relationship rules. The layer ultimately
selects at most eight tables, expands a bounded number of foreign-key neighbors,
and constructs a schema context capped at 21,000 characters. Narrow tables may
retain all columns; wide tables retain ranked columns plus identifiers and
relationship-bearing fields.

**Theoretical role.** This is schema retrieval-augmented generation: external
database structure is retrieved before generation, analogous to the grounding
principle of RAG [6], but the retrieved objects are schema elements rather than
general passages. BGE-M3 provides multilingual representations [7], while BM25
protects exact identifier evidence.

### 4.4 Layer 4: schema linking

Retrieval asks which elements are individually relevant; schema linking asks
whether the selected elements form a coherent structure capable of expressing
the query. The system presents the top candidates, compact column metadata,
declared foreign keys, and conservative `Ref`-to-`Id` hints to the LLM. The LLM
may select only supplied identifiers, and its output is validated. Invalid JSON,
invented tables, or provider failure causes a fallback to deterministic
retrieval.

This bounded selection is motivated by evidence that schema linking is a major
determinant of Text-to-SQL quality [8]. It also resembles the general strategy
of separating schema selection from SQL decoding, as studied in RESDSQL [9].
Again, the relationship is conceptual: this project does not reproduce either
model's training or architecture.

### 4.5 Layer 5: constrained T-SQL generation

The generation layer receives only the question and selected schema context. Its
prompt specifies Microsoft SQL Server syntax, schema-qualified identifiers,
`TOP` rather than `LIMIT`, Unicode `N'...'` literals for non-ASCII text,
relationship-aware joins, and half-open ranges for calendar periods. It requests
one read-only query without explanatory text.

Task decomposition reduces the burden placed on a single generation call. This
is consistent with the broad motivation of DIN-SQL, which decomposes Text-to-SQL
reasoning and includes self-correction [10], although the present implementation
uses its own prompts, retrieval system, and control flow.

### 4.6 Layer 6: safety, execution, and bounded self-correction

Before execution, a scanner masks literals, comments, and quoted identifiers,
then enforces all of the following:

- the query begins with `SELECT` or a `WITH` clause that produces `SELECT`;
- only one statement is present;
- DML, DDL, administrative commands, `SELECT INTO`, and other forbidden tokens
  are absent; and
- string and identifier delimiters are balanced.

Validation is repeated for repaired queries. The database should still use a
least-privilege, read-only login because application checks are defense in depth,
not a substitute for database authorization.

Two repair paths are bounded:

1. **Execution-error repair.** The model receives the error, original question,
   failed SQL, and selected schema.
2. **Empty-result value repair.** For eligible string equalities, the system
   probes a small set of values from the exact referenced text column, applies
   Persian-aware normalization and fuzzy similarity, and permits substitution
   only with an observed high-confidence value.

The second path grounds corrections in database evidence and treats retrieved
values as untrusted data. The overall approach is related to execution-guided
decoding, where database feedback helps reject or repair invalid programs [11].

### 4.7 Layer 7: grounded answer and visualization

The answer layer receives the original question, executed SQL, and returned
rows. Its contract requires the direct answer first, uses the question's
language, and prohibits facts absent from the result. The visualization layer is
deterministic and never mutates SQL or rows. It chooses among KPI, table, bar,
and line representations using result shape, data types, column names, and the
question's apparent analytical intent.

This separation is epistemically useful: query execution establishes the data;
answer generation verbalizes it; visualization changes only its presentation.

## 5. Reliability model and observable failure modes

The pipeline can be viewed as a sequence of conditional events:

$$P(\text{correct}) \approx
P(R)\,P(L\mid R)\,P(G\mid L)\,P(E\mid G)\,P(A\mid E),$$

where $R$ denotes retrieval of required schema elements, $L$ correct linking,
$G$ semantically correct SQL generation, $E$ successful execution with the
intended denotation, and $A$ a faithful answer. This factorization is not an
independence claim; it is a diagnostic model. It explains why end-to-end
accuracy alone is insufficient: a wrong answer can originate in several layers.

The implementation therefore records or evaluates:

- table and column recall for schema selection;
- valid-SQL rate for syntactic and policy compliance;
- execution accuracy for denotational correctness;
- correction gain and correction success rate;
- SQL and end-to-end latency;
- LLM call counts and token usage; and
- model requests, responses, timing, and status in audit logs.

## 6. Evaluation methodology

### 6.1 Dataset and protocol

The checked-in `v1` run contains 200 questions: 104 English and 96 Persian.
They target one previously unseen accounting database and include aggregation,
grouping, sorting, filtering, joins, temporal operations, null handling, and ten
intentional typo cases. Each question has reference SQL and gold schema elements.

Generated and reference queries are executed on the same database. Correctness
is based on result equivalence rather than SQL string equality because multiple
programs can denote the same answer. When reference SQL has no `ORDER BY`, row
order is ignored but duplicates are preserved. Evaluation accepts only read-only
queries. Timing uses five repetitions according to the run manifest.

### 6.2 Metrics

Execution Accuracy is

$$EX=\frac{1}{N}\sum_{i=1}^{N}\mathbb{1}
[Exec(s_i)=Exec(s_i^*)].$$

Retrieval metrics are

$$\text{Table Recall}=\frac{|T_r\cap T_g|}{|T_g|},\qquad
\text{Table Precision}=\frac{|T_r\cap T_g|}{|T_r|},$$

$$\text{Column Recall}=\frac{|C_r\cap C_g|}{|C_g|}.$$

Correction Gain is $EX_{final}-EX_{initial}$. R-VES follows the reward-based
efficiency formulation used by BIRD Mini-Dev, combining correctness with bounded
relative execution-efficiency rewards. It should be reported separately from
end-to-end latency because model and retrieval time are not database execution
time.

### 6.3 Results

| Metric | Result |
|---|---:|
| Initial execution accuracy | 90.5% |
| Final execution accuracy | **95.5%** |
| Initial/final valid SQL rate | **100% / 100%** |
| Table recall | 97.0% |
| Table precision | 80.1% |
| Column recall | 97.1% |
| Self-correction success rate | 66.7% |
| Correction gain | +5.0 percentage points |
| R-VES | 90.12 |
| English execution accuracy | 97.1% |
| Persian execution accuracy | 93.8% |
| Mean / median end-to-end latency | 38.19 s / 40.43 s |
| P95 end-to-end latency | 61.73 s |
| Average LLM calls per question | 4.03 |
| Average tokens per question | 6,482.67 |

All ten intentional typo questions were recovered after correction. Filter
questions improved from 82.0% to 98.4%, suggesting that grounded value repair is
responsible for much of the aggregate correction gain. By contrast, join
questions achieved 87.7% final execution accuracy and no correction gain in this
run. This is consistent with a structural error pattern: missing or incorrect
join semantics generally cannot be repaired by substituting a text value.

Performance also declined as feature count increased: questions with five
features achieved 85.0%, and those with six achieved 84.6%. These subsets are
small, so the observation is descriptive rather than a statistically established
complexity law.

## 7. Threats to validity

### Internal validity

- Reference SQL and business interpretations may contain annotation errors.
- Result equality on one database instance does not prove semantic equivalence
  on every possible instance. Test-suite accuracy can reduce this weakness [12].
- Cached artifacts, database load, model-provider variability, and network
  conditions can affect latency and generated output.

### External validity

- The reported run uses one accounting database and one system configuration.
- The dataset is project-specific rather than an official Spider or BIRD split.
- English and Persian counts are close but not identical, and language groups
  may differ in difficulty.
- Results should not be compared directly with published benchmark leaderboards
  because schemas, data, prompts, models, and evaluation protocols differ.

### Construct validity

- Execution accuracy can reward an accidentally equivalent result on the
  current data.
- Table/column recall depends on the quality of gold annotations.
- R-VES measures SQL execution efficiency, not total user-perceived latency.
- Valid SQL means executable and policy-compliant, not necessarily correct.

## 8. Recommended research extensions

1. **Multi-database evaluation.** Add databases from different domains and
   report macro-averaged metrics to test schema-level generalization.
2. **Ablation studies.** Compare dense-only, BM25-only, fused retrieval,
   enrichment-disabled, schema-linking-disabled, and correction-disabled
   configurations.
3. **Retrieval curves.** Report table recall at multiple context budgets and
   relate recall to execution accuracy.
4. **Stratified confidence intervals.** Bootstrap execution accuracy by intent,
   language, and database rather than reporting point estimates alone.
5. **Adversarial safety tests.** Expand prompt-injection, obfuscation,
   comment/literal masking, multi-statement, and dialect-specific attack cases.
6. **Semantic equivalence testing.** Evaluate correct queries across multiple
   database instances or distilled test suites.
7. **Latency decomposition.** Separate embedding, retrieval, schema linking,
   generation, correction, SQL execution, and answer-generation latency.
8. **Human evaluation.** Measure usefulness, linguistic quality, trust, and
   perceived correctness of final answers and visualizations.

## 9. Conclusion

Conversation with Data treats Text-to-SQL as a layered grounding and validation
problem rather than a single prompt. Its main contribution is an auditable
engineering architecture for bilingual questions over unseen SQL Server
schemas: authoritative metadata discovery, cached semantic enrichment, hybrid
schema retrieval, bounded linking, read-only generation, execution-grounded
repair, and non-mutating presentation. The checked-in evaluation indicates
strong performance on its target database and exposes where further research is
most valuable, especially multi-table reasoning, broader external validation,
and lower end-to-end latency.

## References

1. T. Yu et al. “Spider: A Large-Scale Human-Labeled Dataset for Complex and
   Cross-Domain Semantic Parsing and Text-to-SQL Task.” EMNLP, 2018.
   [ACL Anthology](https://aclanthology.org/D18-1425/)
2. J. Li et al. “Can LLM Already Serve as A Database Interface? A BIg Bench for
   Large-Scale Database Grounded Text-to-SQLs.” NeurIPS, 2023.
   [Proceedings](https://proceedings.neurips.cc/paper_files/paper/2023/hash/83fc8fab1710363050bbd1d4b8cc0021-Abstract-Datasets_and_Benchmarks.html)
3. B. Wang et al. “RAT-SQL: Relation-Aware Schema Encoding and Linking for
   Text-to-SQL Parsers.” ACL, 2020.
   [ACL Anthology](https://aclanthology.org/2020.acl-main.677/)
4. S. Robertson and H. Zaragoza. “The Probabilistic Relevance Framework: BM25
   and Beyond.” *Foundations and Trends in Information Retrieval*, 2009.
   [DOI](https://doi.org/10.1561/1500000019)
5. G. V. Cormack, C. L. A. Clarke, and S. Buettcher. “Reciprocal Rank Fusion
   Outperforms Condorcet and Individual Rank Learning Methods.” SIGIR, 2009.
   [Publication](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/)
6. P. Lewis et al. “Retrieval-Augmented Generation for Knowledge-Intensive NLP
   Tasks.” NeurIPS, 2020.
   [Proceedings](https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)
7. J. Chen et al. “BGE M3-Embedding: Multi-Lingual, Multi-Functionality,
   Multi-Granularity Text Embeddings Through Self-Knowledge Distillation.” 2024.
   [arXiv](https://arxiv.org/abs/2402.03216)
8. W. Lei et al. “Re-examining the Role of Schema Linking in Text-to-SQL.”
   EMNLP, 2020. [ACL Anthology](https://aclanthology.org/2020.emnlp-main.564/)
9. H. Li et al. “RESDSQL: Decoupling Schema Linking and Skeleton Parsing for
   Text-to-SQL.” AAAI, 2023.
   [AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/26535)
10. M. Pourreza and D. Rafiei. “DIN-SQL: Decomposed In-Context Learning of
    Text-to-SQL with Self-Correction.” 2023.
    [arXiv](https://arxiv.org/abs/2304.11015)
11. C. Wang et al. “Robust Text-to-SQL Generation with Execution-Guided
    Decoding.” 2018. [arXiv](https://arxiv.org/abs/1807.03100)
12. R. Zhong, T. Yu, and D. Klein. “Semantic Evaluation for Text-to-SQL with
    Distilled Test Suites.” EMNLP, 2020.
    [ACL Anthology](https://aclanthology.org/2020.emnlp-main.29/)
