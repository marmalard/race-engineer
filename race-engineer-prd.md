# Race Engineer — Product Requirements Document

## Vision

Race Engineer is a personal racing engineer for iRacing that knows you as a driver — your tendencies, your progression, your strengths and weaknesses — and gives you the experience of having a knowledgeable engineer in your corner.

It is not a dashboard full of charts. It is not a data dump. It is an opinionated, personalized coaching system that tells you what you don't know and prioritizes what matters most for getting faster.

## Core Philosophy

- **Opinionated over comprehensive.** Surface the 2-3 things that matter, not everything that's measurable.
- **Coaching over data.** "Brake at the 3 marker and carry more speed through the apex" not "your braking point is 12m later than the benchmark."
- **Personal over generic.** The system should understand *your* driving and get smarter over time.
- **Actionable over interesting.** Every insight should change what you do in the next session.
- **Fun over clinical.** This should make sim racing more enjoyable, not feel like homework.

## Users

Primary user: intermediate iRacing drivers (iRating 1000-2500) who practice regularly and want structured improvement. Drivers at this level have 2-4 seconds of improvement available through technique and the gains are concentrated in coachable areas.

## Feature 1: Scouting Report

### Purpose
Prepare the driver for a track before they turn a single lap. Answer the question: "What do I need to know about this track in this car, and what's a competitive time?"

### Experience
The driver selects a car and track combo (or the system detects it from their upcoming series schedule). They receive a one-page briefing they can glance at on their second monitor before a practice session. Target reading time: under 10 minutes.

### Report Structure

**Pace Context**
- Competitive time window for the driver's iRating range at this car/track combo
- Target ladder: where peers are, where the next level is, what fast looks like
- Source: iRacing Data API — qualifying and race results for the current/recent season

**Track Overview**
- Overall character: momentum track vs. point-and-shoot, what it rewards and punishes
- Surface and elevation notes
- Tire wear characteristics for this car
- Source: web search + community knowledge synthesis

**Key Corners (3-5 most important)**
For each corner:
- Corner name and number
- What makes it tricky
- The common mistake
- One concrete thing to focus on
- Source: community track guides, YouTube content, forum knowledge

**Car-Specific Notes**
- How this car behaves at this track
- Known handling tendencies
- Setup considerations if relevant
- Source: web search, community knowledge

**Personal History (if returning to track)**
- Previous pace and when you last ran it
- What you struggled with before
- What improved
- Source: driver profile / session history

### Technical Requirements
- iRacing Data API integration for pace context
- Web search and AI synthesis for community knowledge
- Track database lookup for corner names and characteristics
- Driver profile lookup for personal history
- Output: rendered in Streamlit, designed for quick consumption

---

## Feature 2: Lap Coaching

### Purpose
After a session, analyze the driver's telemetry and tell them where they're leaving time and what to do about it. Answer the question: "What should I work on to get faster?"

### Experience
The driver uploads an IBT file (or points to a session directory). The system analyzes their laps, identifies the biggest opportunities, and delivers prioritized coaching. Not a wall of charts — a focused debrief.

### Analysis Approach

**Self-Referential Benchmarking (Primary)**
- Compare the driver's laps against their own best performance
- Theoretical best lap: stitch together the driver's best corners across all laps in the session
- Identify corners where performance varies most (consistency issues) vs. corners that are consistently slow (technique issues)
- "You nailed T3 on lap 12 and T7 on lap 28 — if you put those together you're a 1:22 driver"

**External Benchmark (Optional)**
- Garage 61 CSV import for when the driver wants to study a faster driver's approach
- Manual upload, not automated — this is a power-user feature for targeted use

**Pace Context**
- Compare session pace to iRating peers (from Data API)
- Track improvement within the session
- Source: iRacing Data API for context, own telemetry for technique

### Coaching Output

**Session Summary**
- Best lap time, theoretical best, consistency score
- Pace relative to iRating peers
- Overall session trajectory (improving, plateauing, degrading)

**Priority Corners (Top 2-3)**
For each corner where the most time is available:
- Corner name (from track database)
- Time left on the table vs. own best
- What's happening: specific diagnosis (late braking + over-slowing, early lift, tight line, etc.)
- What to try: one concrete, actionable coaching tip
- Supporting data: speed trace comparison, braking point delta, minimum speed delta

**Consistency Analysis**
- Corners where performance varies most lap-to-lap
- Pattern identification: are you fast early and fading? Inconsistent in one specific section?

### Technical Requirements
- IBT file parsing and telemetry extraction
- Distance normalization (resample to consistent distance intervals)
- Automated corner detection and segmentation
- Lap-to-lap comparison within a session
- Track database for corner names and context
- AI synthesis layer to turn data into coaching language
- Optional: Garage 61 CSV ingestion and alignment

---

## Future Features (Designed For, Not Built Yet)

### Session-Level Intelligence
- Multi-lap analysis: tire degradation, consistency trends, improvement curves within a session
- Setup correlation: track which setups produce which results over time
- Session type awareness: practice vs. qualifying vs. race performance context

### Driver Profile
- Persistent model of driver tendencies across tracks and sessions
- Pattern recognition: "you consistently carry too little mid-corner speed in long sweepers"
- Strength and weakness mapping by corner type
- Progression tracking over weeks and months

### Season Awareness
- Integration with iRacing series calendar
- Proactive scouting reports for upcoming tracks
- Practice priority suggestions: "Spa is next week and you historically struggle there — here's a focused practice plan"
- Progression narrative: "you've improved 1.2 seconds at Road Atlanta since September"

### Live Session Awareness
- Between-lap coaching: "your last 3 laps you've been braking earlier into T5"
- Stint management: "your lap times are falling off, try relaxing your inputs"
- Not corner-by-corner real-time coaching (too much cognitive load) — strategic nudges between laps
- Potential Crew Chief integration for audio delivery
- Alternatively: TTS via ElevenLabs or OpenAI for voice output

---

## Data Sources

| Source | What It Provides | Integration |
|--------|-----------------|-------------|
| IBT Files (iRacing telemetry) | Throttle, brake, steering, speed, GPS, lap times | Primary. File parsing, always available |
| iRacing Data API | Race results, qualifying times, series schedules, driver stats | API integration. Pace context and calendar |
| Web Search | Community track guides, tips, car handling notes | On-demand AI synthesis for scouting reports |
| Track Database (internal) | Corner names, types, characteristics, segments | Built and maintained internally, seeded from telemetry |
| Driver Profile (internal) | Historical performance, tendencies, progression | Accumulated from sessions over time |
| Garage 61 CSV (optional) | External benchmark telemetry | Manual upload, power-user feature |

---

## Architecture Principles

- **Data foundation first.** The telemetry pipeline, distance normalization, and corner segmentation must be rock solid before building features on top. This is the lesson from v1.
- **Shared data model.** Scouting reports and lap coaching share the same track database, pace context, and driver profile. The scouting report is essentially the coaching engine running without telemetry.
- **Schema for the future.** Design data structures now that support session-level analysis, driver profiles, and longitudinal tracking even if those features aren't built yet.
- **AI as synthesis layer.** The AI doesn't replace analysis — it translates structured analytical output into natural language coaching. Keep the analysis deterministic and the synthesis creative.
- **Progressive complexity.** The system should be useful with just an IBT file and get dramatically better as more data accumulates (sessions, tracks, history).

---

## Tech Stack

- **Python** — core analysis packages
- **Streamlit** — user interface
- **iRacing Data API** — pace context, schedules, results
- **Claude API** — AI synthesis for coaching and scouting reports (with web search for scouting)
- **SQLite or similar** — track database, driver profile, session history
- **pandas / numpy** — telemetry data processing
- **matplotlib / plotly** — visualization for telemetry comparisons

---

## What This Is Not

- Not a telemetry viewer. Garage 61, VRS, and others already do that well.
- Not a setup optimizer. That's a different (harder) problem.
- Not a social platform. This is a personal tool.
- Not trying to replace human coaching. It's trying to give you 80% of the value for drivers who don't have a coach.
- Not a real-time overlay. Live awareness is a future feature, and it's strategic (between laps) not tactical (mid-corner).
