# Step 3 — RAG Retrieval Design

Status: approved, implementing.

## Purpose

Given a graded incident (output of step 2, `src/grade_leak.py`), retrieve the procedural/regulatory
text chunks that justify the grade and response, so step 4 (work-order synthesis) can cite real
source text instead of generating ungrounded safety claims. This step never influences the grade —
it only reads `assigned_grade` to build a search query.

## Corpus scope

Gas-only: `docs/gas-utility-ea-togaf.pdf` and `docs/utility-analytics-ecosystem-wiki (1).md`.
Power/water EA PDFs are excluded from the citeable corpus — they are cross-utility background
reading, not gas leak procedure, and citing them in a gas work order would look wrong.

## Components

### 1. `src/build_corpus.py` — one-time corpus build (re-run when docs change)

- Extract text from the gas EA PDF via `pypdf` (page-by-page, so page numbers are preserved).
- Read the wiki markdown directly, tracking heading path (e.g. `## 5.1 > ### Emergency Response`)
  as a location marker.
- Chunk both sources with a fixed-size sliding window: ~400 words per chunk, ~50-word overlap.
- Embed each chunk with Ollama's `nomic-embed-text` model.
- Upsert into a persistent ChromaDB collection at `data/chroma_db/` (collection name: `l2wo_procedures`).
- Each stored chunk carries metadata: `source_doc`, `location` (page number or heading path), `chunk_id`.

### 2. `src/retrieve_procedures.py` — per-incident retrieval

- Input: `data/grading_output/graded_incidents.json`.
- For each incident, build one templated natural-language query from: `assigned_grade`,
  `detected_route`, `surface_capping_type`, `hca_flag`/`distance_to_building_m`. Example:
  `"Grade 1 gas leak, methane detected, asphalt surface capping, near occupied building, HCA zone — isolation and emergency response procedure."`
- Embed the query with `nomic-embed-text`, query the ChromaDB collection for `top_k=3`.
- Skip incidents with `assigned_grade is None` (hydraulic-check route — not a gas leak, nothing to cite).
- Output: `data/retrieval_output/retrieved_citations.json`, an array of:
  ```json
  {
    "incident_id": "...",
    "query": "...",
    "citations": [
      {"chunk_id": "...", "source_doc": "gas-utility-ea-togaf.pdf", "location": "p.12", "text": "...", "score": 0.83}
    ]
  }
  ```
  This is the exact shape step 4 will consume alongside the incident + grade.

### 3. Evaluation — `data/retrieval_output/retrieval_evaluation.json`

- Coverage check: every non-null-grade incident must have ≥1 citation above a minimum similarity
  floor. Report count of incidents failing this (must be 0 to satisfy the blueprint's "100% of
  work orders cite ≥1 chunk" requirement).
- Spot-check log: for the Grade 1/2/3 example incidents and the soil-vs-asphalt fidelity pair
  (SEG-005A/B), save the top chunk text for manual eyeballing that citations are topically
  appropriate and that soil vs. asphalt incidents retrieve differently.

## Guardrails preserved

- No LLM call anywhere in this step — only embeddings (a fixed vector function, not generation).
- Retrieval reads `assigned_grade`, never writes/overrides it.
- Corpus restricted to gas-relevant docs to avoid cross-utility citation noise.

## Dependencies

- New: `chromadb`, `ollama` (Python client), `pypdf`. No `requirements.txt` exists yet in this repo
  (deps are installed globally, matching how `pandas`/`scikit-learn`/`pandera` are already handled) —
  not introducing one unless asked.
- `nomic-embed-text` pulled via `ollama pull nomic-embed-text` (done).

## Out of scope for this step

- Work-order synthesis (step 4).
- N8N orchestration (step 5).
- Feedback loop appending corrections back into the vector store (blueprint §B.2[5]) — future work, not part of this step.
