# Sonoma Racing Coach (ApexAI)

ApexAI is an end-to-end, real-time AI coaching application designed for professional track-day drivers. It ingests high-frequency racing telemetry, processes it against ideal theoretical racing lines, and leverages an on-device Edge LLM to deliver predictive, actionable audio feedback to the driver at 150+ mph.

The system is designed to run entirely offline at the edge (in-car) to avoid cloud connectivity latency and ensure safety and thermal reliability during aggressive track sessions.

---

## What Makes the ApexAI Implementation Unique
### Brain-to-Edge Memory Transfer

A key aspect of our implementation is the tight integration between the coaching dashboard, the driver, and the AI assistant through a structured memory bank workflow. The dashboard enables coaches and drivers to collaboratively build personalized memory banks based on previous driving sessions, telemetry data, racing scenarios, and coaching feedback.
The memory entries can initially be generated using AI to accelerate the process, but they are designed to be reviewed, refined, and validated by the coach. This human-in-the-loop approach ensures that expert knowledge, driving strategy, and real-world racing experience remain central to the system rather than relying solely on automated generation.
Once the coach and driver agree on the coaching guidance and racing strategies, the finalized memory bank is exported as a structured JSON file and imported into the mobile edge application. On-device, the in-phone AI assistant uses this memory bank as contextual knowledge to provide real-time predictive coaching, proactive recommendations, and direct driving commands during a session.
This architecture also enables multiple coaches to create and manage their own independent memory banks, allowing different coaching styles, strategies, and expertise to be incorporated into the driver experience. We are currently planning to extend the platform to support loading and combining multiple memory banks simultaneously within a single mobile session, enabling the AI assistant to leverage knowledge from multiple coaches and racing scenarios dynamically.
By running inference locally on the mobile device, the system can deliver low-latency assistance while maintaining a more deterministic and controllable behavior. This approach allows coaching expertise to be efficiently packaged into portable JSON-based memory banks and consistently delivered to the driver through the mobile application in real time.


![ApexAI system architecture](images/apexai.png)

## 🏗️ System Architecture

The ecosystem operates across three distinct architectural flows, separating offline pedagogical planning from real-time, in-car execution:

## 📅 Implementation Timeline & Code Change Log

This timeline is grounded in the component contracts documented in the root `README.md`, `dashboard/README.md`, and `mobile/README.md`.

| Date / Phase | Implementation Milestone | Important Code Changes |
| :--- | :--- | :--- |
| **Project start** | Telemetry replay foundation | Built the FastAPI telemetry simulation layer around Racelogic VBOX replay, normalized `.vbo` packets, and established the replay contract that later served both dashboard and mobile clients. |
| **April 29** | Architecture/code review & travel approval | Reviewed the first deliverable architecture: `src/apexai/server/` for telemetry ingestion/replay, `ui/` for simulator visualization, and `mobile/` as the target Android edge runtime for real-time coaching. |
| **Pre-field-test integration** | Memory bank generator and edge coach split | Implemented the dashboard workflow described in `dashboard/README.md`: React/Vite map UI, Express API orchestration, Rust `data-engine` parsing, WASM rule evaluation, deterministic rule generation, Gemini-assisted recommendations, screenshot context, and `latest.json` memory export. |
| **May 23** | Field test at Sonoma Raceway | Successfully tested the application at Sonoma Raceway: the mobile app worked, consumed telemetry, loaded memory-bank context, and proved the driver-facing coaching loop under real track conditions. The main issue found was GPS-dependent sector lookup across two same-day driving sections with different sky conditions. |
| **May 30** | Project concludes | Finalized the post-Sonoma architecture around three components: memory generation, telemetry simulation, and mobile edge coaching. Documented VBOX/CAN replay, decoded CAN streaming, dual mobile coaches, memory-bank selection, GPS-based sector matching, LiteRT Gemma inference, cooldowns, Android TextToSpeech delivery, and the need to improve GPS resilience. |

The timeline also marks the key implementation shift: early work centered on replaying telemetry; the first deliverable proved the simulator/dashboard path; the field-test work connected that path to memory-bank generation and Android edge coaching; and the final project state documents the system as a three-component architecture.

## 🏁 Updates After the Sonoma Field Test

The Sonoma Raceway field test validated the core ApexAI premise under real trackside conditions: the system can ingest real driving telemetry, prepare coaching context before a run, and keep the in-car coaching loop focused on low-latency, offline execution. The post-test work concentrated on hardening the data path, separating analysis-time tooling from in-car runtime behavior, and making the coaching memory workflow easier to inspect and transfer.

Most importantly, the application was successfully tested in the field and the end-to-end coaching flow worked. The Android app could receive telemetry, use the selected memory bank, map the car to track sectors, and produce driver-facing coaching output. This confirmed that the core architecture is viable beyond simulation.

The field test also exposed the most important reliability challenge: the current memory activation path relies heavily on GPS quality to extract sector-level notes from the memory bank. On the same Sonoma field-test day, the driver completed two driving sections under different conditions. During the cloudy section, the GPS signal was not strong enough to consistently support reliable sector matching. During the sunny, open-sky section, GPS behavior improved substantially and the sector lookup worked as expected. This means the current design works well under good satellite visibility, but it needs a stronger fallback strategy before it can be considered robust for all track conditions.

Key updates made after the field test:

- **Telemetry source hardening:** The backend now supports both legacy Racelogic VBOX `.vbo` replay and raw CAN hex chunk replay, allowing developers to reproduce Sonoma sessions from recorded files while preserving the byte-level shape of CAN captures.
- **Decoded CAN stream support:** The telemetry server can decode CAN logs into vehicle parameters such as RPM, gear, brake pressure, and water temperature while still keeping raw replay available for adapter-level testing.
- **Trackside simulation loop:** The root telemetry dashboard now acts as both an inspection surface and a simulator, so the mobile app can be tested against replayed Sonoma data before returning to the car.
- **Memory bank export path:** Coaching notes generated from the dashboard are packaged as structured JSON memory payloads that can be loaded into the Android app for offline use.
- **Dual mobile coach path:** The Android app now documents both `HeuristicBaseAICoach` for deterministic threshold rules and `GemmaCoach` for LiteRT-LM JSON decisions grounded in triggered memory notes.
- **Sector-aware mobile evaluation:** The mobile app uses `track_sectors.json`, haversine lookup, an 80-meter sector acceptance threshold, sector telemetry metrics, priority/frequency selection, and 12-second sector/command cooldowns.
- **Audio delivery path:** The mobile runtime turns selected commands into driver-facing audio with Android `TextToSpeech`, keeping the coaching output concise and local to the device.
- **GPS resilience requirement:** Because memory notes are currently selected by GPS-to-sector matching, future work should add fallback sector estimation using telemetry continuity, lap progress, speed/distance integration, heading, CAN-derived signals, or confidence scoring when GPS quality drops.

The field test also clarified the boundary between development-time simulation and production in-car execution. Cloud services and dashboards are useful for preparation, replay, and deployment, but the actual driver-facing loop remains local to the car and phone.

## 🔁 Overall Architecture & Component Changes

After Sonoma, the system was reorganized around three primary components with clearer responsibilities:

1. **Memory Bank Generator (`dashboard/`)**: A coach-facing analysis environment for turning telemetry, screenshots, sector deltas, and human feedback into structured coaching memories. This component owns the React/Vite map UI, Express API orchestration, Rust VBOX parsing, deterministic and Gemini-assisted rule generation, WASM rule evaluation, GCS `latest.json` export, and optional audio enrichment.
2. **Telemetry and Simulation Dashboard (`src/`, `ui/`)**: A replay and inspection layer that normalizes VBOX and CAN data, broadcasts telemetry over SSE and WebSockets, and provides a desktop simulator for validating the mobile app against captured sessions.
3. **Mobile AI Coaching App (`mobile/`)**: The in-car runtime that receives live or simulated telemetry, loads the exported memory bank, maps GPS to sectors, runs deterministic rules or Gemma-based coaching locally, and delivers concise audio coaching through Android Text-to-Speech.

The main architectural change is the split between **offline pedagogical planning** and **real-time edge coaching**. The dashboard side can perform heavier analysis, generate memory payloads, and visualize telemetry in detail. The mobile side stays deliberately narrow: ingest telemetry, select the relevant memory context, evaluate sector rules, decide whether Gemma should speak, and deliver only actionable guidance.

This separation gives the project a more reliable field-test loop:

```mermaid
graph TD
    Sonoma["Sonoma Field Data"]
    Replay["Telemetry Replay & Simulation"]
    Analysis["Dashboard Analysis"]
    Memories["Memory Bank Export"]
    Mobile["Android Edge Coach"]
    Driver["Predictive Audio Guidance"]

    Sonoma --> Replay
    Replay --> Analysis
    Analysis --> Memories
    Memories --> Mobile
    Replay -- "WebSocket / SSE test stream" --> Mobile
    Mobile --> Driver
```

### 1. Offline Analysis & Memory Generation
Before heading to the track, the driving coach or engineer uses pre-recorded telemetry to build a strategic plan ("memories") for the driver.

```mermaid
graph TD
    subgraph Local Environment
        VBO[".vbo Telemetry Files"]
    end

    subgraph Backend [ApexAI Server / Car Simulator]
        Parser["Telemetry Parser (vbo_parser.py)"]
        Streamer["FastAPI Broadcaster"]
        VBO --> Parser
        Parser --> Streamer
    end

    subgraph WebUI [Dashboard Web UI]
        Rust["Rust Static Data Engine"]
        Next["Next.js Application"]
        Memories["Coaching Memories Builder"]
        
        Streamer -- "SSE Stream" --> Next
        Rust -- "Ideal Racing Line (JSON)" --> Next
        Next --> Memories
        Memories -- "Export" --> JSON["memories.json"]
    end
```

### 2. Publishing Memories to the Android App
The generated memory bank encapsulates the hyper-specific coaching heuristics (e.g., "brake 50m earlier at Turn 3"). This cloud synchronization path is now implemented: the dashboard exports mobile-compatible `latest.json` memory banks to Google Cloud Storage with driver and car identifiers, and the Android app lists, downloads, inspects, and selects those `latest.json` files from the same bucket before live coaching.

```mermaid
graph LR
    JSON["latest.json (from Dashboard)"]
    GCS["Google Cloud Storage"]
    Store["Android MemoryBankFileStore"]
    Storage["Android App Storage"]
    
    JSON --> GCS
    GCS --> Store
    Store --> Storage
```

### 3. Realtime Coaching (Production Environment)
During the actual track session, the system operates **entirely offline** within the vehicle. Telemetry flows directly from the car's hardware to the Android device, utilizing the pre-loaded memories to generate predictive coaching audio.

```mermaid
graph TD
    subgraph Racing Vehicle
        CAN["Car CAN Bus / OBD-II"]
        Adapter["CAN-to-USB/WiFi Adapter"]
        CAN --> Adapter
    end

    subgraph MobileApp [Android Edge App]
        Ingest["Telemetry Ingestion Service"]
        MemoryBank["Memory Bank (memories.json)"]
        Gate["Gated Inference Engine"]
        LLM["LiteRT-LM (Gemma 4:E2B)"]
        TTS["Android TTS (Audio Delivery)"]
        
        Adapter -- "Raw Telemetry Stream" --> Ingest
        Ingest --> Gate
        MemoryBank --> LLM
        Gate -- "Straightaway Detected" --> LLM
        LLM -- "JSON Command" --> TTS
    end
```

---

## 🛠️ Technology Stack & Unique Innovations

The project synthesizes bleeding-edge technologies across Python, Rust, TypeScript, and Kotlin. Here are the core stacks and unique engineering solutions used:

### Backend (ApexAI Server)
- **Tech Stack:** Python 3.11, FastAPI, Uvicorn.
- **Unique Innovations:**
  - **Dual-Protocol Broadcasting:** Seamlessly transmits live telemetry across both **Server-Sent Events (SSE)** (for stateless web UIs) and **WebSockets** (for low-latency mobile edge apps) concurrently.
  - **CAN Raw Chunk & Legacy VBOX Support:** Replays recorded CAN raw hex chunks without transforming them, while normalizing legacy Racelogic `.vbo` text files into `TelemetryPacket` objects.

### Data Engineering (Static Asset Engine)
- **Tech Stack:** Rust (`serde`, `serde_json`).
- **Unique Innovations:**
  - **Rust VBO-to-JSON Pipeline:** A custom `data-engine` written in Rust aggressively parses massive `.vbo` datasets into heavily optimized, lightweight JSON structures. This entirely eliminates dynamic backend loads when plotting the Ideal Racing Line, making the UI deployable as a high-speed static asset.

### Web Dashboard (Coaching UI)
- **Tech Stack:** TypeScript, React, Next.js.
- **Unique Innovations:**
  - **10Hz Spatial Matching:** Executes high-frequency mathematical distance calculations (Haversine formula) purely on the client-side to instantly detect where the car is relative to the pre-computed track sectors.
  - **Dynamic Environment Binding:** Intelligently switches telemetry source bindings based on `window.location.hostname`, seamlessly shifting from local `127.0.0.1` dev environments to deployed Google Cloud Run containers without `.env` management.

### Mobile Edge App (In-Car Coach)
- **Tech Stack:** Native Android Kotlin, Jetpack Compose, Google LiteRT-LM, OkHttp.
- **Unique Innovations:**
  - **Thermal-Aware Gated Inference:** The app mathematically monitors steering variance to detect cornering phases. It suppresses all LLM computation mid-corner, only unlocking the Gemma 4:E2B model on stable straightaways to prevent thermal CPU throttling in hot racing cabins.
  - **Strict JSON LLM Prompting:** The `Gemma4Manager` enforces hard metric generation instead of conversational chat, extracting distinct scalar values (e.g., "0.05 bar throttle") to construct authoritative Text-to-Speech instructions.

---

## 🏎️ Component 1: ApexAI Telemetry Simulation Server

**Role:** The foundational backend responsible for interpreting raw vehicle data and streaming it to downstream clients via high-throughput HTTP streams.

### Key Features & Implementation
- **Framework:** Python, FastAPI, and `uvicorn`.
- **Sources:** Supports recorded Racelogic VBOX `.vbo` files and recorded CAN raw hex chunk files.
- **Streaming Protocols:** Telemetry is broadcast simultaneously via **Server-Sent Events (SSE)** (for the Dashboard) and **WebSockets** (for the mobile app).
- **Hardened Configuration:** The server can stream a selected `.vbo` or `can_raw_hex_chunks*.txt` file, and still supports directory-based VBOX replay.

### Core Algorithms
- **Coordinate Normalization:** Raw VBO datasets can export GPS coordinates as pure minutes or as degrees plus decimal minutes. The server's `vbo_parser.py` handles both:
  - Pure minutes: `Decimal Degrees = abs(Minutes) / 60.0`
  - Degrees plus minutes: `Decimal Degrees = degrees + minutes / 60.0`
  - *Sign Correction:* VBOX standard uses positive numbers for Western longitudes. The parser inverts the longitude sign to conform to standard GPS (WGS84) conventions, accurately placing the telemetry at Sonoma Raceway.
- **Time Interpolation:** Replays recorded data at true-to-life cadence or fixed streaming intervals (e.g., 10Hz) to replicate live hardware environments.

---

## 📊 Component 2: Coaching Dashboard

**Role:** A visualization and pedagogical tool used to review sessions, benchmark performance against the Ideal Racing Line, and build contextual "memories" for the LLM.

### Key Features & Implementation
- **Framework:** React and Next.js, with static site generation for deployment portability.
- **Dynamic Endpoint Routing:** A unified frontend implementation dynamically routes SSE connections between a local development server (`127.0.0.1`) and the production Google Cloud Run endpoint based on `window.location.hostname`.
- **Pre-computed Asset Bundling:** To overcome Firebase Hosting constraints with large datasets, raw `.vbo` files are pre-processed into lightweight `.json` files via a high-performance **Rust-based Data Engine**, avoiding dynamic API calls and accelerating map rendering.

### Core Algorithms
- **Real-time Spatial Matching (Haversine Formula):** The dashboard computes the shortest spherical distance between the live streaming vehicle coordinates and the pre-computed static Ideal Racing Line to map the car to the correct track segment.
- **Telemetry Delta Calculation:** Extracts live velocity, throttle, brake, and gear from the stream and compares it instantly against the ideal line's telemetry vectors, surfacing micro-errors (e.g., "Braking 50m too early").

---

## 📱 Component 3: Mobile Edge Coaching App

**Role:** An Android application strapped inside the vehicle that serves as the AI racing coach. It operates completely disconnected from the cloud, utilizing on-device ML to ensure absolute privacy, zero latency variation, and robust thermal performance.

### Key Features & Implementation
- **Framework:** Native Android Kotlin with Jetpack Compose.
- **On-Device Inference:** Uses **Google's LiteRT-LM** to host a quantized **Gemma 4:E2B** model locally.
- **Pedagogical Delivery:** Instructions are formatted via strict JSON generation enforcing exact metric outputs (e.g., "Apply 0.05 bar throttle") rather than generic advice.

### Core Algorithms
- **Gated Inference Engine:** Operating an LLM at 10Hz inside a hot racing cabin risks severe thermal throttling. The application implements steering variance monitoring:
  - The Gemma LLM is *strictly prevented* from executing mid-corner.
  - Compute cycles are only triggered during stable straightaway segments.
- **Predictive Audio Queuing:** Mid-corner audio cues are a severe safety hazard. By running inference upon corner exit, Text-to-Speech instructions are queued and delivered 2-3 seconds prior to the *next* corner entry.
- **Latency Tracker:** A dedicated logging module that tracks the exact delta between receiving the WebSocket packet to the release of the audio buffer, ensuring the pipeline remains within the strict 2-3 second latency budget required for a 150+ mph field test.

---

## 🧠 Coaching Memory Hierarchy & Activation Logic

The system utilizes a 3-tier coaching recommendation architecture. These "memories" provide the context for the LLM to generate highly relevant feedback.

1. **Tier 1: Physics-Based:** Generated continuously by evaluating dynamic vehicle limits (e.g., traction circles, braking thresholds).
2. **Tier 2: Ideal-Run-Based:** Generated by comparing real-time spatial trajectories against the pre-loaded static Ideal Racing Line.
3. **Tier 3: Driver-Annotated:** Manual heuristic notes inputted by the engineer from the dashboard (e.g., "avoid curb at Turn 2").

### Activation Logic
To ensure cognitive safety and thermal reliability, these memories do not trigger instantly. They are processed through the `GatedInferenceEngine`:

```mermaid
graph TD
    subgraph Memory Tiers
        T1["Tier 1: Physics Limits"]
        T2["Tier 2: Ideal-Run Deltas"]
        T3["Tier 3: Driver Annotations"]
    end

    subgraph ActivationGate [Activation Gate / GatedInferenceEngine]
        Wait["Mid-Corner (Blocked)"]
        Trigger["Corner Exit / Straightaway (Active)"]
    end

    subgraph LLMDelivery [LLM & Delivery]
        Context["Prompt Context Builder"]
        LLM["Gemma 4:E2B Inference"]
        Queue["Predictive Audio Queue"]
    end

    T1 --> Context
    T2 --> Context
    T3 --> Context
    
    Context --> Wait
    Wait -- "Steering Variance Drops" --> Trigger
    Trigger --> LLM
    LLM -- "JSON Generated" --> Queue
    Queue -- "2-3 seconds before NEXT corner" --> TTS["Text-to-Speech Output"]
```

---

## 📋 The Unified Schema Definition

To eliminate separate type interfaces and distinct file columns, a single data contract represents all three recommendation types:

| Field Name | Type | Allowed Values | Nullable / Optional | Description |
| :--- | :--- | :--- | :--- | :--- |
| **`id`** | String | Unique string | No | Unique ID (prefixed by source, e.g. `physics-`, `gemini-`, `driver-`). |
| **`ruleType`** | String | `'Physics' \| 'Ideal' \| 'Driver'` | No | The source type of the coaching rule. |
| **`sector_id`** | Integer | `1` to `50` | No | Track sector segment ID. |
| **`tag`** | String | Category name | No | Category (e.g. `Speed`, `Braking`, `Acceleration`, `Gearing`, `Line`, `Traction`, `Stability`, `Transition`). |
| **`title`** | String | Text instruction | No | Short actionable instruction to the driver. |
| **`description`** | String | Text detail | Yes (Empty string in CSV) | Multi-sentence detailed telemetry analysis and coaching advice. |
| **`metric`** | String | Metric key | Yes (Empty string in CSV) | Telemetry metric basis key (e.g., `min_speed`, `brake_lockup`, `throttle_dips`). |
| **`operator`** | String | `'<' \| '>' \| '!=' \| '='` | Yes (Empty string in CSV) | Comparison operator for rule validation. |
| **`threshold`** | Float | Decimal value | Yes (Empty string in CSV) | Numerical metric trigger threshold. |
| **`optimal_value`** | Float | Decimal value | Yes (Empty string in CSV) | Reference high-performance benchmark value. |
| **`average_value`** | Float | Decimal value | Yes (Empty string in CSV) | Reference user average performance value. |
| **`frequency`** | Float | `0.0` to `1.0` | Yes (Empty string in CSV) | Estimated check occurrence frequency. |
| **`priority`** | Integer | Positive integer | Yes (Empty string in CSV) | Sequential stack rank priority order (1 is highest). |
| **`audio_file`** | String | GCS Audio Path | Yes (Empty string in CSV) | Reference path to cloud-synthesized text-to-speech audio file. |

---

## 🗺️ Rule Type Source Mappings

Each of the three coaching recommendations sources maps its native parameters to the unified schema fields as follows:

```mermaid
graph TD
    subgraph Rust WASM Physics Engine
        A[Physics Rules] -->|ruleType: 'Physics'| U[Unified Schema]
    end
    subgraph Gemini AI Generator
        B[AI Ideal Rules] -->|ruleType: 'Ideal'| U
    end
    subgraph Custom Driver Notes
        C[Driver Notes] -->|ruleType: 'Driver'| U
    end
    U -->|JSON Payload| D[latest.json Push]
    U -->|CSV Generation| E[coaching_recommendations.csv]
```

### Mapping Matrix
| Unified Schema Field | 🏎️ Rust WASM Physics Rule | 🤖 Gemini AI Rule | 📝 Custom Driver Note |
| :--- | :--- | :--- | :--- |
| **`id`** | `"physics-[metric]-[sector]"` | `"gemini-[sector]-[index]"` | `"driver-[timestamp]"` |
| **`ruleType`** | `'Physics'` | `'Ideal'` | `'Driver'` |
| **`tag`** | `tag` | `tag` | `tag` |
| **`title`** | `title` | `title` | `title` |
| **`description`** | Dynamic analytical string | Generative visual detail | Manual user entry |
| **`metric`** | Physics telemetry metric name | AI selected performance metric | `'geolocation'` |
| **`operator`** | Evaluated condition operator | Statistical boundary operator | `null` / `""` |
| **`threshold`** | Pre-calculated physical limit | Calculated delta boundary | `null` / `""` |
| **`optimal_value`** | Baseline benchmark target | Fastest average benchmark target | `null` / `""` |
| **`average_value`** | Current user sector average | Average sector user average | `null` / `""` |
| **`frequency`** | `1.0` (evaluated continuously) | Percentage of user laps violating delta | `null` / `""` |
| **`priority`** | Physics priority (1, 2, or 3) | Statistical priority (1, 2, or 3) | Stack rank position index |
| **`audio_file`** | TTS path for physics instruction | TTS path for Gemini instruction | TTS path for driver text note |

---

## 🚀 Deployment & DevOps

The ecosystem is engineered for seamless cloud deployment to complement the offline edge applications.

- **Containerization:** The `apexai` backend is packaged inside a Docker image that leverages `uv sync --frozen` for deterministic, lightweight dependency resolution.
- **Cloud Run Orchestration:** Both the backend simulation server and the static Next.js dashboard are deployed via `Makefile` recipes directly to **Google Cloud Run**, automatically injecting cloud-assigned `PORT` configurations for seamless routing.
- **Unified Repository:** While organized into `ui/`, `mobile/`, and server modules, the repository relies on root-level `.gitignore` rules and strict separation of concerns, maintaining a clean CI/CD pipeline.

## ✅ Implemented Cloud Memory Synchronization

- **Cloud Memory Synchronization:** The memory sync path is implemented. The dashboard normalizes generated coaching rules into mobile-compatible records, exports `${driver}/${car}/latest.json` plus timestamped backups to Google Cloud Storage, and can enrich commands with generated audio files. The Android app uses `MemoryBankFileStore` to list available non-backup `latest.json` files from the ApexAI bucket, download the selected memory bank into app storage, inspect the JSON, and use it as the live memory source for both the heuristic and Gemma coaches.
- **Remaining reliability work:** The cloud memory path removes the need for wired ADB side-loading during normal operation. The more important next improvement is GPS resilience for sector-level memory activation when satellite signal quality drops on track.

## 🚀 Future Improvements

- **GPS resilience for memory-note activation:** Added GPS resilience as a required improvement for memory-note activation on track. Because sector-level notes are currently selected through GPS-to-sector matching, future work should add fallback sector estimation when GPS signal quality drops. Candidate improvements include telemetry continuity, lap-progress tracking, speed/distance integration, heading, CAN-derived signals, and confidence scoring before activating a sector-specific memory note.

---

## 🌟 Sonoma & Ideal Line 1 Insights Generation

We have successfully executed the end-to-end telemetry insight generation pipeline!

### 1. Robust API Graceful Fallback
* **Bulletproof Scripting**: Modified `generate_coaching_rules_gemini.py` to gracefully handle environments without `GOOGLE_API_KEY` or `GEMINI_API_KEY` (and missing screenshot clients) without module-level or execution-time crashes.
* **Deterministic Fallback Engine**: If the API keys are missing or API calls fail, the script automatically falls back to generating high-fidelity statistical recommendations (`deterministic_fallback_rules`) derived directly from the optimal vs average speed, pacing, and time traversals of the 118 laps in our training corpus.

### 2. Pipeline Execution & Merging Results
* **Successful Execution**: Triggered the live generation script `generate_coaching_rules_gemini.py` utilizing the new Google **Gemini 3.5 Flash** model (`gemini-3.5-flash`) via the modern, upgraded `google-genai` (v2.6.0) SDK client and our newly authorized API key.
* **Massive Telemetry Processing**:
  * Scanned **80 training telemetry `.vbo` files** from the Sonoma intermediate course corpus.
  * Successfully extracted and analyzed **118 valid racing laps**!
  * Evaluated and synthesized **126 new `Ideal` coaching recommendations** across all 50 track sectors using the Gemini 3.5 Flash model with multi-modal map screenshots for spatial geometry context.
* **Intelligent Rules Merging**: Read existing rule types (retaining our 60 Physics rules and other custom driver notes intact), merged them with the 126 new `Ideal` rules, and wrote exactly **186 consolidated rules** back to `coaching_rules.json`. All legacy/untyped rules were cleaned up seamlessly.
