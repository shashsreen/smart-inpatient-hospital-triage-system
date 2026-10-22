# Smart Inpatient Monitoring & Clinical Decision Support System

## Overview

A two-part system designed for continuous inpatient monitoring:
1. **C Clinical Engine** (`triage.c`) — The absolute source of truth. Reads patient vitals, calculates vital deviations, categorizes symptoms, applies interaction rules, normalizes the Health Severity Index (HSI), derives likely conditions, assigns doctors (load-balanced), recommends wards, and tracks recovery trends.
2. **Web Dashboard** (`dashboard/index.html`) — An interactive, display-only UI that reads results and allows for patient vitals/symptoms editing (via a Python HTTP server). **Zero medical logic in JavaScript.**

---

## Project Structure

```
HospitalTriage/
│
├── triage.c               ← C Engine (Primary processing)
├── generate_results.py    ← Python fallback (Mirrors C logic exactly)
├── server.py              ← Python HTTP server (Static files & POST APIs)
├── run.bat                ← One-click build + run + server script
│
├── patients.csv           ← Input: 27-field raw patient records
├── doctors.csv            ← Input/Output: Shared state for doctor capacity
├── wards.csv              ← Input/Output: Shared state for ward occupancy
├── results.csv            ← Output: Processed results for dashboard
├── history.csv            ← Output: Append-only assessment history
│
└── dashboard/
    ├── index.html         ← Dashboard UI (6 pages)
    ├── styles.css         ← Dark glassmorphism styling
    └── app.js             ← Display-only JS + Server APIs
```

---

## How to Run

### Windows (One-Click)

Just double-click `run.bat`.
- It will attempt to compile `triage.c` using GCC.
- If GCC is not found, it automatically falls back to `generate_results.py`.
- It copies the output CSVs to the dashboard directory.
- It launches `server.py` and opens the dashboard at `http://localhost:7890`.

### Manual CLI Execution

**1. Run the Engine:**
```bash
# Using C (Recommended)
gcc -Wall -std=c99 -O2 -o triage.exe triage.c -lm
triage.exe patients.csv results.csv doctors.csv wards.csv history.csv

# OR Using Python Fallback
python generate_results.py
```

**2. Start the Server:**
```bash
python server.py
# Open http://localhost:7890 in your browser
```

---

## System Architecture

### 1. Risk Scoring (Health Severity Index - HSI)
The system calculates a raw clinical score based on:
- **Vital Sign Deviations:** (Temp, HR, RR, SpO2, Blood Sugar, Systolic BP)
- **Symptom Categories:** Cardiac, Respiratory, Neurological, Infection, Trauma, General
- **Interaction Rules:** Escalates severity when specific conditions co-occur (e.g., Neurological + Infection).
- **Consciousness & Pain Level**

This raw score is dynamically normalized against the highest current patient score to derive a 0-100 **HSI (Health Severity Index)**.

### 2. Clinical Decision Support
- **Condition Inference:** Infers the likely medical condition based on the most prominent symptom categories.
- **Doctor Assignment:** Assigns patients to specialists based on their condition, respecting the doctor's current availability and maximum capacity.
- **Ward Recommendation:** Recommends ICU, HDU, Observation, or General Ward based on the HSI score and current bed availability.
- **Recovery Trend:** Compares current HSI to past assessments to determine if the patient is *Improving*, *Stable*, or *Worsening*.

---

## Editing Patients

You can edit patient details directly from the Dashboard (using the "Edit Patient Vitals" button in the modal).
When you save:
1. `app.js` sends the update to `server.py` via POST.
2. `server.py` updates `patients.csv` directly.
3. `server.py` immediately re-runs the C Engine.
4. The C Engine recomputes everything and updates `results.csv`.
5. The dashboard reloads the fresh data.

## Architecture Constraint

> **All medical logic, scoring, assignment, and predictions live exclusively in `triage.c`.**
> The dashboard UI and `app.js` contain zero risk calculation or classification code — they exist solely to present data formatted by the C engine.
