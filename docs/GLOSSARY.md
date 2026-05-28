# PrismForge AI v4 — Plain English Glossary

Organized from foundational concepts to increasingly complex system behavior.

---

## Part 1 — Core Vocabulary (What Things Are)

**Document** — A plain-text file in the input folder (called the "data room") that the system reads and analyzes. PrismForge only reads files it can decode as text; binary files, images, and system files like `.DS_Store` are silently skipped.

**Data Room** — The directory (folder) of corporate due-diligence documents you hand to the system. It is the starting point for every pipeline run.

**Chunk** — A slice of a document's text, roughly 1,000 words long (about 4,000 characters). Long documents get cut into many chunks so the AI can process them in focused pieces rather than all at once.

**Lens** — A named area of legal or business risk that the AI is told to look for in a chunk. Examples: `IP_Ownership`, `License_Compliance`, `Liability_Cap`, `Data_Privacy`. Each document gets 3–7 lenses chosen to fit its content.

**Semantic Summary** — A dense, 200–400-word description of what a document is about: its key parties, obligations, and risk areas. Generated once per document at the start of processing and used as context for every extraction worker that analyzes that document's chunks.

**Extraction Record** — One piece of structured evidence pulled from a single chunk under a single lens. It contains: what was found, a direct quote supporting it, a risk score from 1–10, and any links to other documents it contradicts or connects with.

**Risk Score (`implied_liability_score`)** — An integer from 1 to 10 assigned by the AI to each extracted finding, indicating how serious the liability risk is. Higher means more dangerous. Used later to prioritize findings if there are too many to synthesize at once.

**Dependency Link** — A structured pointer from one finding to a specific clause or concept in another file. For example, File A's warranty claim pointing to File B's GPL license declaration as a contradiction. These are the "edges" of the cross-document risk graph.

---

## Part 2 — Pipeline Stages (What Happens in Order)

**Directory Crawler** — The first step. Walks the data room folder, opens every file it can read as text, and records the list of successfully read filenames. Files that fail to open (binary, locked, or corrupt) are skipped without crashing the system.

**`crawled_files`** — The list of filenames the crawler successfully read. This list is created once at the start and never changed. It is later used to detect which files produced zero analysis output.

**Router** — The second step, run once per document. Sends the full document text to an AI (Gemini Flash) in a single call and gets back both the semantic summary and the list of lenses for that document at the same time.

**Chunking** — The third step. Splits a document's text into overlapping chunks using a standard library tool (`RecursiveCharacterTextSplitter`). Chunks are ~4,000 characters with ~800 characters of overlap between adjacent chunks so context is not lost at boundaries.

**Fan-Out / Matrix** — The fourth step. Takes every chunk and every lens for a document and creates a job for every combination — one job per chunk-lens pair. If a document has 5 chunks and 4 lenses, this creates 20 jobs. All jobs run in parallel.

**Extraction Worker** — The fifth step, one instance per job. Receives a single chunk plus the document's semantic summary and applies one lens to that chunk. Calls the Claude Sonnet AI to extract structured findings. If anything goes wrong, it quietly returns nothing rather than crashing.

**Handoff Node** — The final step inside each document's processing sub-graph. After all extraction workers finish, this step packages their combined findings and the document's summary and sends them up to the parent system for collection. One handoff per document, always after the workers are done.

**Master Round-Table Node** — Runs once, after every document has finished processing. Takes all findings from all documents, detects coverage gaps, trims the list if it is too long, and calls Claude Sonnet one final time to produce the consolidated risk report.

**Final Risk Report** — The output. A single Markdown document that cross-references findings across all input files, names contradictions, and flags any files that produced no useful output.

---

## Part 3 — State and Memory (How Data Moves)

**State** — The system's memory at any given moment. LangGraph (the orchestration framework) manages state as typed dictionaries that nodes read from and write to.

**`ParentState`** — The top-level memory that persists across the entire pipeline run. Holds the data room path, the list of crawled files, all extraction records collected from every document, all document summaries, and the final report.

**`DocumentSubState`** — A private memory space for processing one document. Holds that document's raw text, its summary, its lens list, its chunks, and the findings collected so far. Discarded after the handoff node runs.

**Reducer** — A rule that tells LangGraph what to do when two parallel processes both try to write to the same memory field at the same time. Without a reducer, the second write overwrites the first, losing data.

**Append Reducer (`add`)** — The reducer used for lists of extraction records. Every worker's findings are added to the end of the list rather than replacing it.

**Merge Reducer** — The reducer used for the document summary store. Each document's summary is added as a new entry in the dictionary rather than replacing the whole dictionary. Without this, only the last document's summary would survive when multiple documents are processed simultaneously.

**`global_inbox`** — The running collection of all `ExtractionRecord` objects across all documents, accumulated using the append reducer.

**`local_inbox`** — The same concept but scoped to a single document's sub-graph. After all workers for that document finish, the local inbox is merged into the global inbox via the handoff node.

**`summary_store`** — A dictionary mapping each document's filename to its semantic summary. Built up gradually as each document finishes, using the merge reducer so summaries from parallel documents accumulate rather than overwrite.

---

## Part 4 — Architecture Patterns (How the System Is Structured)

**LangGraph** — The orchestration framework that defines the pipeline as a graph of nodes (processing steps) connected by edges (transitions). It manages state, concurrency, and the flow of data between steps.

**Node** — One processing step in the graph. A node receives state, does work, and returns an update to state.

**Edge / Conditional Edge** — A connection between nodes that determines what runs next. A conditional edge can look at state and dispatch different next steps based on what it finds — for example, sending each chunk-lens pair to its own worker.

**Sub-graph** — A self-contained mini-pipeline that runs inside the main pipeline, one per document. Has its own state (`DocumentSubState`) and its own sequence of nodes. Runs in parallel with sub-graphs for other documents.

**`Send`** — LangGraph's mechanism for dispatching many parallel jobs at once. The fan-out mapper creates a `Send` object for each chunk-lens pair, and LangGraph runs all of them concurrently up to the concurrency limit.

**`max_concurrency`** — The cap on how many jobs can run at the same time across the entire graph. Set to 50. Prevents flooding the AI provider with too many simultaneous requests.

**Singleton** — An object created exactly once at startup and reused for every operation, rather than recreated each time it is needed. Both AI model connections (`structured_router` and `structured_llm`) are singletons to avoid redundant setup overhead.

**Structured Output** — A way of constraining the AI's response so it must return data in a specific, pre-defined format (a Pydantic schema) rather than free text. Enforced by the AI provider at the API level, eliminating the need to parse or validate the response afterward.

**Pydantic Schema** — A Python class that defines the exact shape and types of a data object, with automatic validation. Every major data structure in PrismForge (summaries, findings, payloads) is defined as a Pydantic schema to prevent malformed data from propagating through the pipeline.

---

## Part 5 — Safety and Failure Handling (What Happens When Things Go Wrong)

**Binary File Filtering** — The directory crawler's protection against non-text files. If a file raises a decode error, directory error, or permission error when opened, it is silently skipped. The pipeline continues with the files that did open.

**Worker `try/except`** — Each extraction worker is wrapped in error handling. If the AI call fails, the response is malformed, or any other exception occurs, the worker returns an empty result rather than crashing the entire parallel pool.

**Blind Spot** — A file that was successfully read by the crawler but produced zero extraction records after all workers ran. This can happen if the document was empty, encoded unusually, or if every worker for it failed.

**`detect_blind_spots()`** — A plain Python function that compares the list of crawled filenames against the set of filenames that appear in the global inbox. Any filename present in the crawl list but absent from the inbox is a blind spot.

**Coverage Gaps Block** — The section prepended to the final report naming every blind-spot file. Ensures that missing coverage is surfaced explicitly in the output rather than silently omitted.

**`compress_inbox()`** — A guard that runs before synthesis. If the total number of extraction records exceeds 500, it sorts them by risk score descending, keeps the top 500, and prepends a warning to the report explaining how many lower-priority records were dropped. Prevents the synthesis prompt from exceeding the AI's practical coherence ceiling.

**Synthesis Truncation Warning** — The Markdown block added to the report when `compress_inbox()` had to trim records. Names how many records were dropped and confirms that high-risk signals were retained.

---

## Part 6 — Deployment and Runtime (How the System Runs)

**Streamlit** — The Python-only web framework used to display the final risk report in a browser. Chosen because it requires no JavaScript, no separate frontend build step, and no network configuration beyond a single port.

**`nest_asyncio`** — A small Python library that patches Streamlit's internal event loop to allow the LangGraph async pipeline to run inside it. Without this patch, calling the async graph from within Streamlit raises a runtime error. Applied once at program startup.

**`asyncio`** — Python's built-in concurrency system. Allows many AI calls to run simultaneously without blocking each other, which is how the parallel worker pool achieves its speed.

**Docker** — A tool that packages the entire application and all its dependencies into a self-contained unit (a container) that runs identically on any machine. Used to deploy the system to a cloud server.

**EC2** — An Amazon Web Services virtual server. The Docker container is run here to make the Streamlit interface publicly accessible.

**API Key Injection** — The practice of passing secret API credentials to the running container via environment variables at startup (`-e ANTHROPIC_API_KEY=...`) rather than storing them in code or files. Keys exist only in process memory and are never written to disk or baked into the container image.

**Gemini Flash** — Google's fast, lower-cost AI model. Used for the router step, where speed and cost efficiency matter more than maximum reasoning depth.

**Claude Sonnet** — Anthropic's frontier AI model. Used for extraction workers and final synthesis, where structured output fidelity and cross-document reasoning quality are critical.
