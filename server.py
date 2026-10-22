"""
server.py
---------
Minimal Python HTTP server for the Smart Inpatient Monitoring dashboard.
Uses only the Python standard library — no pip installs required.

Features:
  - Serves dashboard/ as static files
  - POST /api/save-patient   — update existing patient in patients.csv
  - POST /api/add-patient    — add a brand-new patient to patients.csv
  - POST /api/run-engine     — runs triage.exe (or Python fallback), copies CSVs
  - GET  /api/csv/<filename> — serves CSV files from project root (CORS-safe)

Usage:
    python server.py
Then open: http://localhost:7890
"""

import http.server
import json
import os
import csv
import io
import subprocess
import shutil
import sys
import urllib.parse

# ── Paths ─────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DASH_DIR   = os.path.join(BASE_DIR, "dashboard")
PAT_CSV    = os.path.join(BASE_DIR, "patients.csv")
RES_CSV    = os.path.join(BASE_DIR, "results.csv")
DOC_CSV    = os.path.join(BASE_DIR, "doctors.csv")
WARD_CSV   = os.path.join(BASE_DIR, "wards.csv")
HIST_CSV   = os.path.join(BASE_DIR, "history.csv")

PORT = 7890

# Files that can be served from root via /api/csv/<name>
ALLOWED_CSV = {"results.csv", "doctors.csv", "wards.csv",
               "history.csv", "patients.csv"}

# Full column list that patients.csv must have
PAT_FIELDS = [
    "PatientID","PatientName","Age","Gender","Ward","BedNumber","DaysAdmitted",
    "Temperature","HeartRate","RespiratoryRate","BloodPressure","SpO2",
    "BloodSugar","PainLevel","ConsciousnessStatus","MobilityStatus",
    "Symptoms","LikelyCondition","RawClinicalScore","HSI","PreviousHSI",
    "PreviousAssessments","EmergencyCategory","AssignedDoctor",
    "WardRecommendation","PatientStatus","RecoveryTrend"
]

# ── Engine runner ─────────────────────────────────────────────────
def run_engine():
    """
    Runs triage.exe if available, otherwise falls back to generate_results.py.
    Copies all output CSVs into dashboard/.
    Returns (success: bool, output: str)
    """
    exe  = os.path.join(BASE_DIR, "triage.exe")
    py   = os.path.join(BASE_DIR, "generate_results.py")

    if os.path.exists(exe):
        cmd = [exe,
               PAT_CSV, RES_CSV, DOC_CSV, WARD_CSV, HIST_CSV]
    elif os.path.exists(py):
        cmd = [sys.executable, py]
    else:
        return False, "Neither triage.exe nor generate_results.py found."

    try:
        result = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout + result.stderr
        success = (result.returncode == 0)
    except Exception as e:
        return False, str(e)

    # Copy updated CSVs into dashboard/
    os.makedirs(DASH_DIR, exist_ok=True)
    for src in [RES_CSV, DOC_CSV, WARD_CSV, HIST_CSV]:
        if os.path.exists(src):
            dst = os.path.join(DASH_DIR, os.path.basename(src))
            shutil.copy2(src, dst)

    return success, output

# ── Read patients.csv ──────────────────────────────────────────────
def read_patients():
    """Read all rows and fieldnames from patients.csv. Returns (fieldnames, rows)."""
    if not os.path.exists(PAT_CSV):
        return PAT_FIELDS[:], []
    try:
        with open(PAT_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or PAT_FIELDS)
            rows = list(reader)
        return fieldnames, rows
    except Exception as e:
        return PAT_FIELDS[:], []

# ── Write patients.csv ─────────────────────────────────────────────
def write_patients(fieldnames, rows):
    """Write rows back to patients.csv."""
    try:
        with open(PAT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return True, "OK"
    except Exception as e:
        return False, str(e)

# ── Generate next PatientID ────────────────────────────────────────
def next_patient_id(rows):
    """
    Find the highest numeric PatientID (e.g. P042 → 42) and return P<N+1>.
    Falls back to P001 if no rows.
    """
    max_n = 0
    for r in rows:
        pid = r.get("PatientID", "")
        if pid.upper().startswith("P"):
            try:
                n = int(pid[1:])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return f"P{max_n + 1:03d}"

# ── Patient CSV update ─────────────────────────────────────────────
def save_patient(data: dict) -> tuple:
    """
    Update an existing patient row in patients.csv.
    data must contain PatientID of an existing patient.
    Returns (success: bool, message: str)
    """
    fieldnames, rows = read_patients()

    pid = data.get("PatientID", "").strip()
    if not pid:
        return False, "PatientID is required"

    # Ensure all fields exist in the CSV
    for f in PAT_FIELDS:
        if f not in fieldnames:
            fieldnames.append(f)

    found = False
    for i, row in enumerate(rows):
        if row.get("PatientID", "").strip() == pid:
            # Store current HSI as PreviousHSI before update
            old_hsi = row.get("HSI", "0")
            rows[i] = {**row, **data}
            rows[i]["PreviousHSI"] = old_hsi
            found = True
            break

    if not found:
        return False, f"Patient {pid} not found. Use add-patient to create a new one."

    ok, msg = write_patients(fieldnames, rows)
    if not ok:
        return False, f"Could not write patients.csv: {msg}"
    return True, f"Patient {pid} updated successfully"

# ── Add new patient ────────────────────────────────────────────────
def add_patient(data: dict) -> tuple:
    """
    Add a brand-new patient to patients.csv.
    Auto-generates PatientID if not supplied.
    Returns (success: bool, message: str, assigned_pid: str)
    """
    fieldnames, rows = read_patients()

    # Ensure all fields exist in the CSV schema
    for f in PAT_FIELDS:
        if f not in fieldnames:
            fieldnames.append(f)

    # Determine PatientID
    pid = data.get("PatientID", "").strip()
    if not pid:
        pid = next_patient_id(rows)

    # Check for duplicate
    for r in rows:
        if r.get("PatientID", "").strip() == pid:
            return False, f"Patient {pid} already exists. Use save-patient to update.", pid

    # Build the new row with defaults for computed fields
    new_row = {f: "" for f in fieldnames}
    new_row.update({
        "PatientID":           pid,
        "PatientName":         data.get("PatientName", "Unknown"),
        "Age":                 data.get("Age", "0"),
        "Gender":              data.get("Gender", "Unknown"),
        "Ward":                data.get("Ward", "General Ward A"),
        "BedNumber":           data.get("BedNumber", "0"),
        "DaysAdmitted":        data.get("DaysAdmitted", "1"),
        "Temperature":         data.get("Temperature", "37.0"),
        "HeartRate":           data.get("HeartRate", "80"),
        "RespiratoryRate":     data.get("RespiratoryRate", "16"),
        "BloodPressure":       data.get("BloodPressure", "120/80"),
        "SpO2":                data.get("SpO2", "98"),
        "BloodSugar":          data.get("BloodSugar", "100"),
        "PainLevel":           data.get("PainLevel", "0"),
        "ConsciousnessStatus": data.get("ConsciousnessStatus", "Alert"),
        "MobilityStatus":      data.get("MobilityStatus", "Independent"),
        "Symptoms":            data.get("Symptoms", ""),
        # Computed fields — engine will overwrite these
        "LikelyCondition":     "",
        "RawClinicalScore":    "0",
        "HSI":                 "0",
        "PreviousHSI":         "0",
        "PreviousAssessments": "0",
        "EmergencyCategory":   "Stable",
        "AssignedDoctor":      data.get("AssignedDoctor", "Unassigned"),
        "WardRecommendation":  "",
        "PatientStatus":       "Stable",
        "RecoveryTrend":       "Stable",
    })
    rows.append(new_row)

    ok, msg = write_patients(fieldnames, rows)
    if not ok:
        return False, f"Could not write patients.csv: {msg}", pid
    return True, f"Patient {pid} added successfully", pid

# ── Request Handler ────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Only log API requests
        if self.path.startswith("/api"):
            print(f"  [{self.command}] {self.path}")

    def send_json(self, code: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type",  "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b"{}"
        return json.loads(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path

        # ── CSV passthrough ──────────────────────────────────────
        if path.startswith("/api/csv/"):
            fname = path[len("/api/csv/"):]
            if fname not in ALLOWED_CSV:
                self.send_json(403, {"error": "Not allowed"})
                return
            src = os.path.join(BASE_DIR, fname)
            if not os.path.exists(src):
                self.send_json(404, {"error": f"{fname} not found"})
                return
            with open(src, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type",   "text/csv; charset=utf-8")
            self.send_header("Content-Length",  len(data))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data)
            return

        # ── Static file serving ──────────────────────────────────
        if path == "/":
            path = "/index.html"
        file_path = os.path.join(DASH_DIR, path.lstrip("/"))

        if not os.path.isfile(file_path):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        ext = os.path.splitext(file_path)[1].lower()
        mime = {
            ".html": "text/html; charset=utf-8",
            ".css":  "text/css",
            ".js":   "application/javascript",
            ".csv":  "text/csv",
            ".ico":  "image/x-icon",
        }.get(ext, "application/octet-stream")

        with open(file_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type",   mime)
        self.send_header("Content-Length", len(content))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        # ── POST /api/save-patient ───────────────────────────────
        if path == "/api/save-patient":
            try:
                data = self.read_json_body()
                ok, msg = save_patient(data)
                self.send_json(200 if ok else 400,
                               {"success": ok, "message": msg})
            except Exception as e:
                self.send_json(500, {"success": False, "message": str(e)})
            return

        # ── POST /api/add-patient ────────────────────────────────
        if path == "/api/add-patient":
            try:
                data = self.read_json_body()
                ok, msg, pid = add_patient(data)
                self.send_json(200 if ok else 400,
                               {"success": ok, "message": msg, "patientId": pid})
            except Exception as e:
                self.send_json(500, {"success": False, "message": str(e), "patientId": ""})
            return

        # ── POST /api/run-engine ─────────────────────────────────
        if path == "/api/run-engine":
            try:
                ok, output = run_engine()
                self.send_json(200 if ok else 500,
                               {"success": ok, "output": output})
            except Exception as e:
                self.send_json(500, {"success": False, "message": str(e)})
            return

        self.send_json(404, {"error": "Unknown endpoint"})

# ── Entry Point ────────────────────────────────────────────────────
if __name__ == "__main__":
    # Run engine once at startup so dashboard always has fresh data
    print("[server.py] Running initial engine pass...")
    ok, out = run_engine()
    status = "OK" if ok else "WARNING (check output)"
    print(f"[server.py] Engine: {status}")

    server = http.server.HTTPServer(("", PORT), Handler)
    print(f"\n{'='*54}")
    print(f"  Smart Inpatient Monitoring — Dashboard Server")
    print(f"{'='*54}")
    print(f"  Open: http://localhost:{PORT}")
    print(f"  Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server.py] Stopped.")
