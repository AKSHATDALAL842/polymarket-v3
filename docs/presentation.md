# Polymarket Signal Pipeline v3 — Presentation Blueprint

**Duration:** 10-15 minutes + 5 minutes Q&A
**Presenters:** Akshat Dalal (Backend/Infrastructure) & Nikhil Singhal (Frontend/Dashboard)
**Tone:** VC pitch to a Computer Science professor — technically rigorous, evidence-backed, honest about limitations

---

## Slide 1: Title Slide (University Format)

**Visual:** Clean white/light background. University logo top-left. Project title centered in large Times New Roman bold. Student names, roll numbers, department, and supervisor name below. No architecture diagram — this is a formal title slide.

**Content:**
- [University Name]
- [Department of Computer Science / Engineering]
- **Event-Driven NLP Infrastructure for Autonomous Prediction Market Trading**
- A Major Project Report
- Submitted by:
  - **Akshat Dalal** — [Roll Number]
  - **Nikhil Singhal** — [Roll Number]
- Under the guidance of:
  - **[Supervisor Name]** , [Designation]
- [Semester / Academic Year 2025-2026]

**Who speaks:** Akshat — after the title slide displays, stand up and say:

> "Good morning, respected faculty. Our project is an event-driven NLP infrastructure for autonomous trading on prediction markets. Let me give you the one-sentence version: we built a system that reads breaking news from 7 sources, understands which prediction markets the news affects using hybrid semantic matching, classifies the market impact through a 3-tier AI pipeline, and simulates trades — all within 5 seconds — with full replayability, deterministic execution, and a safety framework that prevents autonomous errors from becoming financial losses. I'll walk through the backend and infrastructure; Nikhil will cover the frontend and operational dashboard."

**Duration:** 30 seconds

---

## Slide 2: What This Project Is — The Big Picture

**Visual:** A single clean diagram showing the end-to-end flow as a horizontal pipeline: News Sources → NLP → Market Matching → AI Classification → Edge Model → Execution → Dashboard. No detailed architecture — just the high-level concept. Below it, 3 bullet points with icons.

**Content:**
- **What it does:** Reads breaking news → finds related prediction markets → classifies impact → simulates trades
- **Why it matters:** *"News comes before the market reacts."*  Breaking news hits the wire first — prices move seconds later. A system that reads news in real-time can act during that window, before the crowd catches up.
- **What's novel:** Not just "an AI trading bot." It's infrastructure with deterministic execution, replayability, reconciliation, and a safety framework that gates every trade behind human approval.

**Who speaks:** Akshat — "Here's the core idea: news comes before the market reacts. Breaking news hits the wire — a Fed announcement, an ETF approval — and for a few seconds, the market hasn't adjusted yet. That's the window. Our system reads 7 news sources in real-time, figures out which markets are affected, and makes a decision in under 5 seconds. But the real contribution isn't the trading speed — it's that every decision is traceable, replayable, and gated behind human approval. This is safety-first, not a gambling bot."

**Duration:** 45 seconds

---

## Slide 3: Why Automate This? — Human vs Machine

**Visual:** Two columns side by side. Left: "Human Trader" with red/dim styling. Right: "Our System" with green/bright styling. Three rows of comparison, simple icons, large font.

**Content:**

| | Human Trader | Our System |
|---|-------------|------------|
| **Speed** | Minutes to hours to find and react to news | Under 5 seconds from news to decision |
| **Scale** | Can monitor maybe 5-10 markets at once | Tracks all 27 markets across 2 exchanges simultaneously |
| **Cost** | Full-time trader salary or expensive managed service | Runs on free APIs, $0 operational cost |

**Existing AI bots:** Most are either expensive managed services charging monthly fees, too slow to react to breaking news, or don't process news at all — they only look at price charts.

**Who speaks:** Akshat — "A human trader takes minutes, maybe hours, to find breaking news, figure out which markets are affected, and place a trade. By then, the price has already moved. And they can realistically track maybe 5 to 10 markets at once. Existing AI bots are either expensive, slow, or don't react to news at all — most just look at price charts. Our system reads 7 news sources in real-time, matches headlines to 27 markets across two exchanges, and makes a decision in under 5 seconds. And it costs nothing to run — it's built entirely on free APIs."

---

## Slide 4: Our Approach — Observability First

**Visual:** The same pipeline diagram, but now every stage has a trace ID flowing through it. Red X marks are replaced with red rejection labels showing exact reasons. A dashboard panel showing "NLP_IMPACT_BELOW_THRESHOLD: 96% of rejections."

**Content:**
- Before optimizing: instrument everything
- Every signal gets a globally unique trace_id
- 19 rejection reasons, each with threshold vs actual value
- Complete lifecycle: INGESTED → NLP_PROCESSED → ... → SETTLED
- Discovery: 96% of signals killed by temporal decay at NLP gate

**Who speaks:** Akshat — "Before we changed a single line of trading logic, we built observability. Every signal now carries a unique trace ID through 8 stages. Every rejection records the exact threshold, the actual measured value, and a snapshot of all active config parameters. And the very first thing this showed us..."

---

## Slide 5: System Architecture

**Visual:** Full architecture diagram showing: 7 news sources → NLP enrichment → Market Matcher (semantic + entity + keyword) → 3-Tier Classifier → Edge Model → Ensemble Voting → Portfolio Manager → Execution Engine. Side panel showing the 10 concurrent background tasks.

**Content:**
- 7 concurrent news sources (RSS, NewsAPI, GNews, GDELT, Reddit, Twitter/X, Telegram)
- 10 supervised background tasks
- Polymarket CLOB + Kalshi REST execution
- SQLite WAL for all persistence (15 tables)
- FastAPI + WebSocket backend, React + Vite frontend

**Who speaks:** Nikhil — "While Akshat built the backend pipeline, I designed the operational interface. The system runs 10 concurrent background tasks..."

---

## Slide 6: Signal Pipeline — Deep Dive

**Visual:** Flowchart from news ingestion → NLP → matching → classification → edge model. Show code snippets for the hybrid matching formula and the edge model formula. Show the 3-tier classification table.

**Content:**
```
Hybrid Match Score = max(semantic, keyword) + entity_bonus × 0.25 + keyword_bonus × 0.15

Edge Adjustment = room × (1 − exp(−2 × raw)), capped at 0.12
Position Size = K × EV × confidence × bankroll, drawdown-scaled
```

**Who speaks:** Akshat — "The signal pipeline has four critical stages. First, NLP enrichment using spaCy and our custom 65-pattern regex entity extractor. Second, hybrid market matching combining semantic embeddings with entity and keyword overlap..."

---

## Slide 7: Market Matching — How It Works

**Visual:** A single flowchart: Headline → Extract Entities (show examples: "Bitcoin", "ETF", "SEC") → Semantic Search (sentence-transformers) → Entity Overlap Check → Keyword Match → Combined Score → Best Market. Show one real example: "SEC approves spot Ethereum ETF" matched to a crypto market with the score breakdown.

**Content:**
- We combine three signals to match news to markets:
  - **Semantic similarity** — AI embedding model compares meaning of headline and market question
  - **Entity overlap** — check if named entities (Bitcoin, Fed, SEC) appear in the market question
  - **Keyword overlap** — check if important words overlap
- 65 custom patterns help recognize domain terms the standard AI misses (OpenAI, ETF, FOMC)
- Result: 83% of test headlines correctly matched to relevant markets

**Who speaks:** Akshat — "Here's how the matching works. We don't just use one method — we combine three. First, an AI embedding model compares the meaning of the headline to every market question. Second, we check if named entities like 'Bitcoin' or 'SEC' actually appear in the market. Third, we check keyword overlap. By combining all three, we correctly match 83% of headlines to their relevant markets."

---

## Slide 8: Execution Architecture

**Visual:** Two FSM diagrams side by side. Left: Order FSM (11 states). Right: Position FSM (8 states). Show illegal transitions in red. Show the append-only ledger table schema.

**Content:**
- Order FSM: 11 deterministic states, illegal transitions rejected
- Position FSM: 8 states including ORPHANED → RECONCILING
- SHA256 idempotency keys prevent duplicate orders
- Append-only execution ledger for full audit trail
- Exchange is authoritative; local state is a cached projection

**Who speaks:** Akshat — "Every order in our system goes through a deterministic 11-state finite state machine. You cannot jump from CREATED to FILLED — the system rejects illegal transitions. Every order carries an idempotency key..."

---

## Slide 9: Safety Infrastructure

**Visual:** Dashboard screenshot showing the Risk Control Console. Highlight: Kill Switch button, sliders for MAX_BET_USD/SIZING_K, the "LIVE" indicator dot, the rejection log panel, Active Capital bar.

**Content:**
- 8 circuit breakers (rapid losses, duplicate orders, excessive slippage, etc.)
- Manual approval workflow: propose → review → approve → execute
- Proposal expiry: 5-minute timeout, stale proposals require re-validation
- Emergency hard-stop: one command freezes all execution
- Live constraints: $2 max bet, 1 position, $5 daily loss cap

**Who speaks:** Nikhil — "Safety isn't just a backend concern. The Risk Control Console provides live visibility into every safety mechanism. The Kill Switch button..."

---

## Slide 10: Dashboard & Observability

**Visual:** Full dashboard screenshot showing SignalFeed, HeroCommandCenter, ExecutionPipeline, RiskControlConsole, and OperatorConsole. Arrows pointing to key elements with labels.

**Content:**
- Real-time signal feed via WebSocket
- Live pipeline metrics (uptime, events, signals, rejection rate)
- Risk control console with live backend sync
- Execution pipeline visualization
- Portfolio tracking with mark-to-market PnL
- 12 debug API endpoints + WebSocket

**Who speaks:** Nikhil — "The dashboard is not cosmetic — every control affects backend behavior. Sliders push config changes to the live pipeline via API. The Kill Switch triggers an actual execution freeze. The rejection panel shows live reasons..."

---

## Slide 11: Live Operational Results

**Visual:** Three dashboard-style panels: (1) Pipeline metrics — events processed, signals generated, paper trades. (2) Pre-flight — 9/9 checks all green. (3) System health — zero anomalies, zero errors.

**Content:**
- 228 automated tests, 0 failures
- 83% match rate across test headlines
- 6 paper trades executed during live shadow testing
- 27 markets across Polymarket + Kalshi
- Zero reconciliation anomalies
- Zero dead-letter queue entries
- Pre-flight: 9/9 checks passing

**Who speaks:** Akshat — "Here's the live system in action. 228 tests, all passing. 83% of headlines matched to markets. 27 markets tracked across two exchanges. 6 paper trades completed during shadow testing. Zero errors. Zero anomalies. The pre-flight validation passes all 9 checks every single time."

---

## Slide 12: Failure Mode Discovery

**Visual:** Table titled "Taxonomy of Discovered Failure Modes" with columns: Failure Mode, Discovery Method, Impact, Fix. Highlight the temporal-decay row in red.

**Content:**
- Found 9 distinct failure modes during development
- Most critical: temporal-decay NLP collapse (discovered ONLY in live shadow mode)
- Kalshi parser: 200 markets showing $0 volume (wrong API field names)
- spaCy entity blindness: "OpenAI GPT-5" → zero entities extracted
- `/api` prefix mismatch: all dashboard data fetches returning 404
- Hard-stop file persistence: pipeline blocked on restart

**Who speaks:** Akshat — "We discovered 9 distinct failure modes. The most critical — temporal-decay NLP collapse — was found ONLY during live shadow operation. Offline testing showed 100% NLP pass rate. Live RSS feeds with 1-6 hour article ages had relevance collapsing to near zero..."

---

## Slide 13: Tools & Technology

**Visual:** A tech stack diagram organized in layers: Ingestion → Processing → Execution → Observability → Frontend. Each layer shows the specific libraries/tools.

**Content:**
- **Backend:** Python 3.11+, asyncio, FastAPI, uvicorn, SQLite (WAL)
- **NLP/ML:** spaCy, VADER, sentence-transformers (all-MiniLM-L6-v2), LightGBM
- **LLM:** Groq API (llama-3.3-70b), OpenAI-compatible client
- **Exchange:** Polymarket CLOB (py_clob_client), Kalshi REST (RSA/JWT auth)
- **Frontend:** React 18, Vite, Tailwind CSS, WebSocket
- **Testing:** pytest (228 tests), Rich (terminal dashboards)
- **Data:** httpx, aiohttp, feedparser, websockets

**Who speaks:** Nikhil — "Our technology stack spans five layers. On the frontend, React 18 with Vite and Tailwind CSS..."

---

## Slide 14: Roles & Responsibilities

**Visual:** Two-column layout with photos/icons.

**Content:**

**Akshat Dalal — Backend & Infrastructure**
- Pipeline architecture (pipeline.py, 10 background tasks)
- Signal processing (NLP, matching, classification, edge model)
- Execution engine (order/position FSMs, idempotency, append-only ledger)
- Reconciliation & settlement engines
- Circuit breakers & safety framework
- Observability layer (tracer, rejection analytics, replay)
- 228 automated tests

**Nikhil Singhal — Frontend & Dashboard**
- React dashboard architecture (Vite + Tailwind)
- Real-time WebSocket integration
- Risk Control Console (live backend sync)
- Signal feed, execution pipeline, portfolio views
- Operator console & trading mode controls
- Debug/observability endpoints integration

**Who speaks:** Akshat — "I owned the entire backend pipeline, execution infrastructure, and safety systems." Nikhil — "I designed and built the operational dashboard..."

---

## Slide 15: Pre-Flight & Safety Demo

**Visual:** Terminal screenshot showing `python cli.py preflight` output — all 9 checks PASS. Side panel: "What each check verifies."

**Content:**
- 9-point pre-flight validation before any live execution
- CLOB connectivity, SQLite, circuit breakers, positions, orders, reconciliation, market sync
- `python cli.py hard-stop "reason"` — immediate execution freeze
- `curl :8000/live/pending` — review before approving
- `curl :8000/debug/traces/{id}` — full signal lifecycle

**Who speaks:** Akshat — "Before any live capital is deployed, we run a 9-point pre-flight check. Every check must pass. If any check fails, the system refuses to start..."

---

## Slide 16: Live Demo Flow

**Visual:** Terminal + browser side by side. Terminal showing pipeline logs. Browser showing dashboard with live signal feed.

**Content:**
- Terminal 1: `python api.py` — pipeline starts, 10 background tasks
- Terminal 2: `npm run dev` — dashboard on localhost:3000
- Show: signals flowing through pipeline
- Show: Risk Control Console with live data
- Show: signal feed updating in real-time
- Show: `curl :8000/live/pending` for trade proposals

**Who speaks:** Nikhil — "Let me show you the live system. Terminal one runs the backend with all 10 background tasks..."

---

## Slide 17: Results — Quantitative

**Visual:** Clean dashboard-style cards showing key numbers. Each metric in a large font inside a rounded box. No charts needed.

**Content:**
- 228 automated tests — all passing
- 83% of headlines correctly matched to markets
- 27 markets tracked across 2 exchanges (Polymarket + Kalshi)
- 10 background tasks running concurrently
- 36 API endpoints + 2 WebSocket streams
- 15 database tables for full traceability
- 6 paper trades executed during live shadow testing
- Zero dead-letter queue entries, zero reconciliation anomalies

**Who speaks:** Akshat — "Here are our key numbers. 228 tests, all passing. 83% of news headlines correctly matched to markets. The system tracks 27 markets across Polymarket and Kalshi, runs 10 tasks simultaneously, and exposes 36 API endpoints. During live testing, it executed 6 paper trades with zero errors and zero anomalies."

---

## Slide 18: What We Learned

**Visual:** Six numbered boxes, each with a key lesson.

**Content:**
1. **Observability must precede optimization** — trace IDs revealed the temporal-decay bug
2. **Live shadow operation discovers what offline testing cannot** — temporal decay was invisible offline
3. **Deterministic FSMs catch integration bugs at development time** — illegal transitions flagged immediately
4. **Exchange-authoritative reconciliation is non-negotiable** — local state drifts within minutes
5. **Rule-based fallbacks sustain operations when ML APIs fail** — 6 trades during Groq outage
6. **Manual approval gating prevents autonomous errors** — every live trade requires human sign-off

**Who speaks:** Akshat — "Six lessons. First and most important: observability must come before optimization..."

---

## Slide 19: Limitations

**Visual:** Simple list, no graphics. Professional, transparent.

**Content:**
- Trading is paper-only right now — no real money has been used yet
- The AI that matches news to markets still misses some topics (sports, entertainment)
- Hasn't been tested for 24 hours straight — long-term stability not yet proven
- No profitability claims — we built this for correctness, not returns
- Depends on external APIs — if Polymarket or Groq go down, the system pauses

**Who speaks:** Akshat — "Let me be upfront about what this system doesn't do yet. We've only tested with paper money — no real capital. The news matching works great for politics and crypto but misses some sports and entertainment topics. We haven't run it for 24 hours straight to prove long-term stability. And we make zero claims about making money — we built this to be correct and safe, not profitable."

---

## Slide 20: Future Work

**Visual:** Three large numbered boxes arranged horizontally. Each has one short sentence in large font. Icons optional but keep it clean.

**Content:**
1. **Test it for 24 hours straight** — make sure nothing breaks over time
2. **Improve news understanding** — help it recognize more types of news events
3. **Slowly increase trade amounts** — start at $2, then $5, then $25 only if it's safe

**Who speaks:** Nikhil — "Three things we want to do next. One: run the system for a full day without stopping, to prove it doesn't crash or slow down. Two: teach it to understand more kinds of news — right now it's good at politics and crypto, we want it to handle more. Three: very slowly increase how much we trade, from 2 dollars to 5 to 25, and only after we've proven it's safe at each step."

**Duration:** 20 seconds

---

## Slide 21: Conclusion

**Visual:** Three simple boxes with the key takeaways. Clean, minimal.

**Content:**

**What we built:** A system that reads breaking news, finds the right prediction markets, and simulates trades — all in under 5 seconds.

**How we built it:** With safety first. Every decision is traceable. Every trade needs human approval. The system checks itself before starting.

**What we learned:** In financial systems, being correct matters more than being fast. Transparency matters more than automation. A human in the loop is not a weakness — it's the last line of defense.

**Who speaks:** Akshat — "To wrap up: we built a system that reads news and trades prediction markets in under 5 seconds. But more importantly, we built it to be safe — every decision traceable, every trade human-approved, every failure explainable. The biggest lesson: correctness beats speed, and transparency beats automation. A human in the loop is not a bug — it's the feature."

---

## Slide 22: References

**Visual:** Standard IEEE format reference list.

**Content:**
[1] Hanson, R. "Shall We Vote on Values, But Bet on Beliefs?" Journal of Political Philosophy, 2013.
[2] Wolfers, J. & Zitzewitz, E. "Prediction Markets." Journal of Economic Perspectives, 2004.
[3] Kelly, J.L. "A New Interpretation of Information Rate." Bell System Technical Journal, 1956.
[4] Reimers, N. & Gurevych, I. "Sentence-BERT." EMNLP-IJCNLP, 2019.
[5] Ke, G. et al. "LightGBM: A Highly Efficient Gradient Boosting Decision Tree." NeurIPS, 2017.
[6] Hutto, C.J. & Gilbert, E. "VADER: A Parsimonious Rule-Based Model for Sentiment Analysis." ICWSM, 2014.
[7] Kleppmann, M. "Designing Data-Intensive Applications." O'Reilly, 2017.
[8] Nygard, M.T. "Release It!" Pragmatic Bookshelf, 2007.

**Who speaks:** Nikhil — "Our work builds on established research in prediction markets, NLP, and reliability engineering..."

---

## Slide 23: Thank You & Q&A

**Visual:** Clean slide with project name, GitHub URL, and contact info.

**Content:**
- github.com/AKSHATDALAL842/polymarket-v3
- Questions?

---

# PRESENTATION SCRIPT

## Akshat's Sections (Backend & Infrastructure)

### Slide 1 (Title) — 30 seconds
"Good morning. We built a production-grade event-driven trading infrastructure for binary prediction markets. It ingests breaking news from 7 sources, matches events to markets using hybrid semantic scoring, classifies impact through a 3-tier pipeline, and executes trades through exchange APIs — all under a 5-second latency target. But more importantly, we built it to be observable, replayable, and safe."

### Slide 2 (Problem) — 45 seconds
"Prediction markets aggregate information through prices. A YES contract on 'Will Bitcoin exceed $100K?' trades at $0.62 if the crowd believes there's a 62% chance. When breaking news hits — a Fed announcement, an ETF approval — prices move in seconds. A human trader cannot monitor 7 news sources across 300 markets simultaneously. But automated systems have a darker problem that most people don't talk about."

### Slide 3 (Core Problem) — 45 seconds
"We discovered the hard way that autonomous systems don't fail loudly — they fail silently. Our pipeline processed 136 events per hour. Zero signals generated. And we had absolutely no idea why. There was no observability. No trace of where signals died. No rejection logging. This was our core problem: you cannot fix what you cannot see."

### Slide 4 (Observability First) — 60 seconds
"So before we changed a single line of trading logic, we built observability. Every signal now carries a globally unique trace ID through 8 deterministic stages. Nineteen rejection reasons, each recording the exact threshold, the actual measured value, and a full snapshot of all active config parameters — so you can debug a rejection that happened three hours ago even after someone changed the thresholds. And the very first thing this showed us: 96% of signals were dying at the NLP gate. Not because the NLP was wrong — but because of temporal decay. News articles 1-6 hours old had their relevance scores collapsing to near-zero from an exponential decay function. The offline audit never caught this because it used fresh headlines. Only live operation exposed it."

### Slide 5 (Architecture) — 30 seconds
"The full architecture: 7 concurrent news sources feed into NLP enrichment, then hybrid market matching, a 3-tier classifier, edge modeling, ensemble voting, portfolio management, and execution. Ten supervised background tasks run concurrently — market watcher, news aggregator, reconciliation engine, settlement engine, health monitors. I'll let Nikhil walk through the frontend side."

### Slide 6 (Signal Pipeline) — 60 seconds
"The signal pipeline has four critical stages. First, NLP enrichment using spaCy and our custom 65-pattern regex entity extractor — because we discovered spaCy's standard model could not recognize 'OpenAI,' 'GPT-5,' or 'ETF' as entities. Second, hybrid market matching that combines semantic embeddings with entity and keyword overlap — this took our match rate from 55% to 83%. Third, a 3-tier classifier: watchlist phrases under 1 millisecond, LightGBM under 1 millisecond, and a 3-pass LLM vote via Groq's API. And fourth, a sigmoid-dampened edge model that prevents the LLM's confidence from producing unrealistic price adjustments — hard-capped at 12 percentage points."

### Slide 7 (Market Matching) — 45 seconds
"We combine three signals to match news to markets. First, an AI embedding model compares the meaning of the headline to every market question we track. Second, we check if named entities like Bitcoin, Fed, or SEC actually appear in the market question. Third, we check keyword overlap — do important words match? By combining all three signals, we get an 83% match rate on our test headlines. We also added 65 custom patterns to help the system recognize domain terms like OpenAI, ETF, and FOMC that standard AI models miss."

### Slide 8 (Execution Architecture) — 45 seconds
"Every order in our system goes through a deterministic 11-state finite state machine. You cannot jump from CREATED to FILLED — the system rejects illegal transitions and logs them at ERROR level. Every order carries a SHA256 idempotency key derived from the signal, market, side, size, and price — so retries cannot create duplicate exposure. Every order event is persisted to an append-only ledger. Positions follow an 8-state FSM with explicit orphan detection — if a market closes unexpectedly, the position enters ORPHANED state and triggers reconciliation."

### Slide 11 (Results) — 30 seconds
"Here are our key numbers. 228 tests, all passing. 83% of headlines correctly matched to markets. 27 markets across two exchanges. 6 paper trades executed during live testing. And most importantly — zero errors, zero anomalies across all our validation checks."

### Slide 12 (Failure Modes) — 45 seconds
"We discovered 9 distinct failure modes. The most critical — temporal-decay NLP collapse — was found ONLY during live shadow operation. Other discoveries: the Kalshi API parser was using wrong field names, showing 200 markets at zero dollars volume. spaCy's entity extraction was blind to domain terms. The frontend API prefix mismatch meant every dashboard data fetch returned 404. And a hard-stop file left from testing blocked the pipeline on restart. None of these were visible without systematic observability."

### Slide 18 (Lessons) — 30 seconds
"Six lessons. First: observability must come before optimization. Second: live shadow operation discovers failures that offline testing cannot. Third: deterministic FSMs catch bugs at development time, not in production. Fourth: exchange-authoritative reconciliation is non-negotiable. Fifth: rule-based fallbacks sustain operations when ML APIs fail — we generated 6 trades during a complete Groq outage. Sixth: manual approval gating prevents autonomous errors from becoming financial losses."

### Slide 19 (Limitations) — 20 seconds
"Let me be upfront about what this system doesn't do yet. We've only tested with paper money — no real capital has been used. The news matching works well for politics and crypto but misses some sports and entertainment topics. We haven't run it for 24 hours straight to prove long-term stability. And we make zero claims about profitability — we built this to be correct and safe, not to make money."

### Slide 21 (Conclusion) — 30 seconds
"To wrap up: we built a system that reads breaking news, finds the right prediction markets, and simulates trades — all in under 5 seconds. But more importantly, we built it to be safe. Every decision is traceable. Every trade needs human approval. Every failure is explainable. The biggest lesson we learned: correctness beats speed, and transparency beats automation. A human in the loop is not a weakness — it's the feature."

---

## Nikhil's Sections (Frontend & Dashboard)

### Slide 5 (Architecture — frontend portion) — 20 seconds
"While Akshat built the backend pipeline, I designed the operational interface. The system exposes 36 REST endpoints and 2 WebSocket streams. The frontend is a React application built with Vite and Tailwind CSS, connecting to the backend through a proxy that handles both REST and WebSocket traffic."

### Slide 9 (Safety Infrastructure) — 45 seconds
"Safety isn't just a backend concern. The Risk Control Console provides live visibility into every safety mechanism. The Kill Switch button — previously just a visual toggle — now calls the backend's hard-stop endpoint, which creates a file that the pipeline checks on every event. The sliders for position size, Kelly fraction, and confidence thresholds push changes to the live pipeline through the config override API. Every control in this console has a direct effect on backend behavior — nothing is cosmetic."

### Slide 10 (Dashboard) — 45 seconds
"The dashboard has five key panels. The Signal Feed shows real-time signals via WebSocket with market, direction, edge, and latency. The Hero Command Center shows portfolio value, win rate, and Sharpe ratio. The Execution Pipeline visualizes each stage of signal processing. The Risk Control Console — which we just covered. And the Operator Console shows news sources, queue depths, and system health. Additionally, 12 debug API endpoints expose the full internal state — traces, rejection analytics, pipeline heatmaps, DLQ status, and runtime snapshots."

### Slide 13 (Tools) — 20 seconds
"Our technology stack spans five layers. On the frontend, React 18 with Vite for fast development and Tailwind CSS for styling. The dashboard polls REST endpoints every 5 seconds and maintains a persistent WebSocket connection for real-time signals. The Vite proxy forwards API and WebSocket traffic to the Python backend."

### Slide 16 (Live Demo) — 30 seconds
"Let me show you the live system. Terminal one runs the backend with all 10 background tasks — you can see the pipeline starting, markets loading, and all tasks initializing. Terminal two runs the dashboard dev server. The browser shows real-time signals flowing through the feed. The Risk Control Console shows live exposure data from the portfolio API. And you can see trade proposals appear when the system detects actionable signals."

### Slide 20 (Future Work) — 20 seconds
"Three things we want to do next. One: run the system for a full day without stopping, to prove it doesn't crash or slow down over time. Two: teach it to understand more kinds of news — right now it's good at politics and crypto, we want it to cover more topics. Three: very slowly increase how much we trade, from 2 dollars to 5 dollars to 25 dollars, and only after we've proven it's safe at each level."

### Slide 22 (References) — 15 seconds
"Our work builds on established research in prediction markets, natural language processing, and reliability engineering. Key influences include Hanson and Wolfers on prediction market theory, Kelly on optimal betting fractions, and Kleppmann on distributed systems design."

---

# Q&A PREPARATION

## Questions a CS Professor Would Ask (and Who Should Answer)

### Architecture & Design

**Q1: "Why asyncio instead of a message queue like Kafka or RabbitMQ?"**
**Akshat:** "We chose asyncio for three reasons. First, the latency target is 5 seconds end-to-end — a message queue would add serialization and network overhead. Second, single-process architecture eliminates distributed coordination complexity for our scale — we track fewer than 100 markets. Third, all state lives in-process, making replay and debugging simpler. The trade-off is that we cannot horizontally scale — but for a single-account trading system, horizontal scaling is not the bottleneck. We would migrate to a message queue if we ever needed multi-account execution."

**Q2: "Why SQLite instead of PostgreSQL? What happens at scale?"**
**Akshat:** "SQLite in WAL mode handles our write volume — approximately 10-50 writes per second during peak news ingestion — without contention. The entire database is a single file, making backup, replication, and debugging trivial. The schema is designed for migration: tables are plain SQL, rejection_detail is JSON that becomes JSONB in PostgreSQL, and the append-only ledger pattern maps directly to ClickHouse's MergeTree engine. We would migrate for multi-process access or higher write volumes, but SQLite is the correct choice for single-process deployment."

**Q3: "How do you handle the sentence-transformers model loading in an async context?"**
**Akshat:** "This was actually a non-trivial problem. The model loading triggers tqdm progress bars and HuggingFace Hub callbacks that crash with BrokenPipeError inside asyncio task contexts. We suppress tqdm and HF progress bars via environment variables set before any library imports, and we redirect stderr to /dev/null during the model.load() call. The model is loaded once at startup and cached for the process lifetime."

### ML & NLP

**Q4: "Your match rate is 83.3% on 18 headlines. Is that statistically meaningful?"**
**Akshat:** "Honestly, 18 headlines is a small sample. The 83.3% number is directional, not statistically rigorous. We chose those 18 headlines to cover diverse scenarios — crypto, politics, economics, tech, science, and low-signal noise. The more meaningful metric is the live shadow run: 29 out of 30 real RSS headlines matched to markets. But we absolutely need a larger labeled dataset — 100-300 signals — before making strong precision claims."

**Q5: "Why all-MiniLM-L6-v2? Have you evaluated alternatives?"**
**Akshat:** "We chose it for latency and deployment simplicity — 384 dimensions, no GPU required, loads in under 10 seconds. However, we have observed systematically low cosine similarities for prediction market questions, with a median of 0.20. We have not yet evaluated finance-tuned alternatives like FinBERT variants or domain-adapted sentence transformers. This is explicitly listed as future work."

**Q6: "Your rule-based fallback has a confidence floor of 0.55. How did you choose that?"**
**Akshat:** "The 0.55 floor was chosen pragmatically — it matches the MIN_CONFIDENCE threshold required for a signal to be actionable. Without the floor, rule-based confidence was 0.30-0.44 for RSS sources, which fell below the threshold and killed all signals during Groq outages. The floor is a trade-off: it ensures pipeline liveness at the cost of potentially overconfident classifications. We accept this trade-off because (a) the rule-based classifier is only used when the LLM is unavailable, (b) signals still pass through the edge model and risk gates, and (c) manual approval provides a final safety check."

### Safety & Reliability

**Q7: "Your circuit breakers use fixed thresholds. Why not adaptive thresholds?"**
**Akshat:** "Fixed thresholds are simpler to reason about, test, and audit. Adaptive thresholds require historical baselines that we don't yet have — the system has not run long enough to establish normal operating ranges. Fixed thresholds with human adjustment are the correct starting point. Adaptive thresholds are future work once we have operational data."

**Q8: "What happens if the reconciliation engine and the exchange disagree on a position?"**
**Akshat:** "The exchange is authoritative. If reconciliation detects a divergence — for example, a position exists locally but not on the exchange — the local position is flagged as ORPHANED. If the severity is INFO or WARNING, the system auto-repairs by marking the position closed. If ERROR or CRITICAL, it escalates to human review and the reconciliation engine enters ESCALATED state. All anomalies are journaled with full local and exchange state for post-hoc analysis."

**Q9: "How do you prevent the hard-stop file from being accidentally deleted?"**
**Akshat:** "We don't — the hard-stop file is intentionally easy to delete because the recovery path should be simple. The safety comes from the fact that the hard-stop freezes execution immediately and broadcasts a CRITICAL alert. If someone clears the hard-stop without investigation, the alert trail and runtime snapshot provide evidence. For production, we would add file permissions and audit logging on clear operations."

### Frontend & Integration

**Q10: "How do you handle the WebSocket reconnection on the frontend?"**
**Nikhil:** "The useWebSocket hook implements exponential backoff reconnection with a maximum delay. The dashboard shows connection status in real-time — a green dot when connected, red when disconnected. During disconnection, the REST polling at 5-second intervals provides stale-but-available data so the dashboard never appears empty."

**Q11: "The Risk Control Console sliders — what's the latency from slider change to backend effect?"**
**Nikhil:** "The slider changes are debounced at 400 milliseconds, then POSTed to the config override API. The backend applies the override immediately via setattr on the config module. The config module is imported by all pipeline components, so the next signal processed after the override will use the new value. Total latency: approximately 500 milliseconds from slider release to active effect."

**Q12: "How did you test that the frontend controls actually affect backend behavior?"**
**Nikhil:** "We verified every control end-to-end. For the MAX_BET_USD slider: changing it from $25 to $5 caused the edge model's position sizing function to return $5 instead of $14 for the same EV and confidence inputs. For the Kill Switch: pressing it calls POST /live/hard-stop which creates a .hard_stop file, and the pipeline's event handler checks for this file on every signal. We verified the file creation, pipeline blocking, and recovery path."

### Project & Process

**Q13: "What was the most difficult bug you encountered?"**
**Akshat:** "The task supervisor early-exit bug. The pipeline would start all 10 background tasks and then shut down within 1 second — every single time. The `asyncio.wait(return_when=FIRST_COMPLETED)` in the pipeline's run loop was triggering because the task monitor's `while self._running:` loop defaulted `_running` to False, causing the task to exit immediately. It took tracing through the asyncio task lifecycle to find a one-line fix. This is exactly the kind of bug that would be invisible without systematic observability."

**Q14: "If you had to rebuild this from scratch, what would you do differently?"**
**Akshat:** "Three things. One: build observability from line one, not as a remediation. Two: start with deterministic FSMs rather than retrofitting them — the illegal transition detection caught bugs that would have been silent otherwise. Three: implement reconciliation before any execution logic. Local state drift is inevitable and must be detected, not assumed away."

**Q15: "Is this system ready for real money?"**
**Akshat:** "For Phase 1 constrained deployment — $2 max bet, 1 position, $5 daily loss, manual approval required, circuit breakers active — yes, with the caveat that 24-hour continuous soak testing should be completed first. For anything beyond that — no. Operational trust must be earned through evidence, not assumed from passing tests."

### Questions Specifically for Akshat

1. "Explain the edge model formula and why you chose sigmoid dampening over a linear adjustment."
2. "How does the reconciliation engine handle partial fills?"
3. "What happens if the SQLite database becomes corrupted during a trade?"
4. "Why did you choose 3 LLM passes instead of 1 or 5?"
5. "How do you ensure the idempotency key is truly unique across restarts?"
6. "What's the worst-case financial exposure if all circuit breakers fail simultaneously?"

### Questions Specifically for Nikhil

1. "How does the dashboard handle the case where the backend is down?"
2. "What was the most challenging part of the Risk Control Console implementation?"
3. "How did you test that WebSocket reconnection works correctly?"
4. "Explain the Vite proxy configuration and why the /api prefix is needed."
5. "How do you handle the case where multiple browser tabs are open?"
6. "What accessibility considerations did you make for the dashboard?"
