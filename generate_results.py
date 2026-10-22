"""
generate_results.py
-------------------
Python mirror of triage.c logic.
Run this ONLY when GCC is unavailable.
Once you compile triage.exe, use that instead.

Mirrors the Smart Inpatient Monitoring & Clinical Decision Support engine.

Usage:
    python generate_results.py
"""

import csv
import os
import sys
import math

# ── Paths ─────────────────────────────────────────────────────────
BASE      = os.path.dirname(os.path.abspath(__file__))
PAT_CSV   = os.path.join(BASE, "patients.csv")
RES_CSV   = os.path.join(BASE, "results.csv")
DOC_CSV   = os.path.join(BASE, "doctors.csv")
WARD_CSV  = os.path.join(BASE, "wards.csv")
HIST_CSV  = os.path.join(BASE, "history.csv")
DASH_DIR  = os.path.join(BASE, "dashboard")

# ── ANSI Colors ────────────────────────────────────────────────────
C_RESET  = "\033[0m"
C_RED    = "\033[1;31m"
C_GREEN  = "\033[1;32m"
C_YELLOW = "\033[1;33m"
C_CYAN   = "\033[1;36m"
C_BOLD   = "\033[1m"

# ── Normal Vital Ranges ───────────────────────────────────────────
TEMP_LOW_C  = 36.1
TEMP_HIGH_C = 37.2
HR_LOW      = 60;   HR_HIGH  = 100
RR_LOW      = 12;   RR_HIGH  = 20
SPO2_LOW    = 95
BS_LOW      = 70;   BS_HIGH  = 140
SBP_LOW     = 90;   SBP_HIGH = 140
DBP_LOW     = 60;   DBP_HIGH = 90

# ── Interaction thresholds ────────────────────────────────────────
CARDIAC_THRESH = 6
RESP_THRESH    = 6
NEURO_THRESH   = 7
INFECT_THRESH  = 5
TRAUMA_THRESH  = 8

# ── Symptom weight tables ─────────────────────────────────────────
CARDIAC_SYMS  = [("chest pain",4),("sweating",2),("palpitations",3),
                  ("left arm pain",4),("irregular heartbeat",5)]
RESP_SYMS     = [("breathlessness",4),("wheezing",3),("persistent cough",2),
                  ("rapid breathing",3),("low oxygen",5)]
NEURO_SYMS    = [("headache",2),("dizziness",2),("confusion",4),
                  ("slurred speech",4),("unconsciousness",5),("seizures",5)]
INFECT_SYMS   = [("fever",3),("chills",2),("vomiting",2),("diarrhea",2)]
TRAUMA_SYMS   = [("heavy bleeding",5),("burns",4),("fractures",3),("head injury",5)]
GENERAL_SYMS  = [("fatigue",1),("dehydration",2),("weakness",1)]

# ── Condition → Specialization map ───────────────────────────────
COND_SPEC_MAP = {
    "Myocardial Infarction": "Cardiologist",
    "Arrhythmia":            "Cardiologist",
    "Pneumonia":             "Pulmonologist",
    "Asthma Exacerbation":   "Pulmonologist",
    "Stroke":                "Neurologist",
    "Seizure Disorder":      "Neurologist",
    "Sepsis":                "Infectious Disease",
    "Gastroenteritis":       "Infectious Disease",
    "General Infection":     "Infectious Disease",
    "Fracture":              "Emergency Medicine",
    "Burn Injury":           "Emergency Medicine",
    "Head Trauma":           "Emergency Medicine",
    "Dehydration":           "General Physician",
}

# ─────────────────────────────────────────────────────────────────
def has_symptom(syms: str, kw: str) -> bool:
    return kw.lower() in syms.lower()

def parse_bp(bp: str):
    """Parse 'systolic/diastolic' string."""
    parts = bp.split("/")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    try:
        return int(parts[0]), 80
    except ValueError:
        return 120, 80

def score_category(syms: str, table) -> int:
    return sum(w for kw, w in table if has_symptom(syms, kw))

def consciousness_bonus(status: str) -> int:
    s = status.lower()
    if "unresponsive" in s or "unconscious" in s: return 5
    if "confused"    in s:                         return 3
    return 0

# ── Vital Deviation Scoring ───────────────────────────────────────
def vital_dev_score(p: dict) -> float:
    score = 0.0
    temp = float(p.get("Temperature", 37))
    hr   = int(p.get("HeartRate", 80))
    rr   = int(p.get("RespiratoryRate", 16))
    spo2 = int(p.get("SpO2", 98))
    bs   = int(p.get("BloodSugar", 100))
    sbp, dbp = parse_bp(p.get("BloodPressure", "120/80"))

    # Temperature
    if temp < TEMP_LOW_C:
        dev = TEMP_LOW_C - temp
        score += 10.0 if dev > 2.0 else dev * 5.0
    elif temp > TEMP_HIGH_C:
        dev = temp - TEMP_HIGH_C
        score += 10.0 if dev > 3.0 else dev * 3.33

    # Heart Rate
    if hr < HR_LOW:
        dev = HR_LOW - hr
        score += 10.0 if dev > 30 else dev / 3.0
    elif hr > HR_HIGH:
        dev = hr - HR_HIGH
        score += 10.0 if dev > 60 else dev / 6.0

    # Respiratory Rate
    if rr < RR_LOW:
        dev = RR_LOW - rr
        score += 10.0 if dev > 6 else dev * 1.67
    elif rr > RR_HIGH:
        dev = rr - RR_HIGH
        score += 10.0 if dev > 20 else dev / 2.0

    # SpO2
    if spo2 < SPO2_LOW:
        dev = SPO2_LOW - spo2
        score += 10.0 if dev > 15 else dev * 0.67

    # Blood Sugar
    if bs < BS_LOW:
        dev = BS_LOW - bs
        score += 10.0 if dev > 40 else dev / 4.0
    elif bs > BS_HIGH:
        dev = bs - BS_HIGH
        score += 10.0 if dev > 200 else dev / 20.0

    # Systolic BP
    if sbp < SBP_LOW:
        dev = SBP_LOW - sbp
        score += 10.0 if dev > 40 else dev / 4.0
    elif sbp > SBP_HIGH:
        dev = sbp - SBP_HIGH
        score += 10.0 if dev > 60 else dev / 6.0

    return score

# ── Raw Score Computation ─────────────────────────────────────────
def compute_raw_score(p: dict):
    syms   = p.get("Symptoms", "")
    status = p.get("ConsciousnessStatus", "Alert")
    pain   = int(p.get("PainLevel", 0))

    vdev    = vital_dev_score(p)
    cardiac = score_category(syms, CARDIAC_SYMS)
    resp    = score_category(syms, RESP_SYMS)
    neuro   = score_category(syms, NEURO_SYMS) + consciousness_bonus(status)
    infect  = score_category(syms, INFECT_SYMS)
    trauma  = score_category(syms, TRAUMA_SYMS)
    general = score_category(syms, GENERAL_SYMS)

    cat_sum = cardiac + resp + neuro + infect + trauma + general

    raw = 0.4 * vdev + 0.4 * cat_sum * 4.0 + 0.2 * pain * 6.0

    # Interaction rules
    if cardiac >= CARDIAC_THRESH and resp >= RESP_THRESH:
        raw *= 1.3
    if neuro >= NEURO_THRESH and infect >= INFECT_THRESH:
        raw *= 1.2
    if trauma >= TRAUMA_THRESH:
        raw += 20.0
    if has_symptom(syms, "unconsciousness") or consciousness_bonus(status) >= 5:
        raw += 15.0
    if has_symptom(syms, "head injury"):
        raw += 12.0

    raw = min(max(raw, 0.0), 200.0)
    return raw, cardiac, resp, neuro, infect, trauma

# ── Condition Inference ───────────────────────────────────────────
def infer_condition(syms: str, cardiac, resp, neuro, infect, trauma) -> str:
    if trauma >= 5:
        if has_symptom(syms, "head injury"):   return "Head Trauma"
        if has_symptom(syms, "burns"):         return "Burn Injury"
        return "Fracture"
    if neuro >= 4 and infect >= 3:             return "Sepsis"

    dom = max([(cardiac,"cardiac"),(resp,"resp"),(neuro,"neuro"),
                (infect,"infect"),(trauma,"trauma")], key=lambda x: x[0])[1]

    if dom == "cardiac":
        return "Arrhythmia" if has_symptom(syms,"irregular heartbeat") \
               else "Myocardial Infarction"
    if dom == "resp":
        return "Asthma Exacerbation" if has_symptom(syms,"wheezing") \
               else "Pneumonia"
    if dom == "neuro":
        return "Seizure Disorder" if has_symptom(syms,"seizures") else "Stroke"
    if dom == "infect":
        return "Gastroenteritis" if (has_symptom(syms,"vomiting") or
               has_symptom(syms,"diarrhea")) else "General Infection"
    return "Dehydration"

# ── Classification ────────────────────────────────────────────────
def classify_hsi(hsi: float) -> str:
    if hsi >= 70.0: return "Critical"
    if hsi >= 40.0: return "Moderate"
    return "Stable"

# ── Recovery Trend ────────────────────────────────────────────────
def recovery_trend(current_hsi, previous_hsi, previous_assessments) -> str:
    if int(previous_assessments) == 0:
        return "Stable"
    delta = current_hsi - float(previous_hsi or 0)
    if delta <= -10.0: return "Improving"
    if delta >=  10.0: return "Worsening"
    return "Stable"

# ── Patient Status ────────────────────────────────────────────────
def derive_patient_status(category: str, trend: str) -> str:
    if category == "Critical":  return "Critical"
    if category == "Moderate":
        return "Recovering" if trend == "Improving" else "Observation"
    return "Recovering" if trend == "Improving" else "Stable"

# ── Doctor Assignment ─────────────────────────────────────────────
def assign_doctor(condition: str, doctors: list) -> str:
    req_spec = COND_SPEC_MAP.get(condition, "General Physician")

    def try_assign(spec):
        candidates = [d for d in doctors
                      if d["Availability"] == "Available"
                      and d["Specialization"] == spec
                      and int(d["CurrentPatients"]) < int(d["MaximumPatients"])]
        if not candidates:
            return None
        best = min(candidates, key=lambda d: int(d["CurrentPatients"]))
        best["CurrentPatients"] = str(int(best["CurrentPatients"]) + 1)
        return best["DoctorName"]

    result = try_assign(req_spec)
    if result: return result

    # Fallback to General Physician
    result = try_assign("General Physician")
    return result or "Unassigned"

# ── Ward Recommendation ───────────────────────────────────────────
def recommend_ward(hsi: float, current_ward: str, wards: list) -> str:
    if   hsi >= 80.0: order = ["ICU","HDU","Observation","General"]
    elif hsi >= 60.0: order = ["HDU","ICU","Observation","General"]
    elif hsi >= 40.0: order = ["Observation","HDU","General","ICU"]
    else:             order = ["General","Observation","HDU","ICU"]

    # Try to keep them in their current ward if it matches the best type and has beds
    for w in wards:
        if w["WardName"] == current_ward and w["WardType"] == order[0]:
            return "Remain in Current"

    for wtype in order:
        for w in wards:
            if w["WardType"] == wtype and int(w["AvailableBeds"]) > 0:
                if w["WardName"] == current_ward:
                    res = "Remain in Current"
                else:
                    res = f"Transfer to {w['WardName']}"
                w["OccupiedBeds"]  = str(int(w["OccupiedBeds"])  + 1)
                w["AvailableBeds"] = str(int(w["AvailableBeds"]) - 1)
                return res
    return "No Bed Available"

# ── Validation ────────────────────────────────────────────────────
def validate(row, ln) -> bool:
    pid = row.get("PatientID","").strip()
    if not pid:
        print(f"[WARN] Line {ln}: empty PatientID - skipped")
        return False
    try:
        age  = int(row["Age"])
        temp = float(row["Temperature"])
        hr   = int(row["HeartRate"])
        rr   = int(row["RespiratoryRate"])
        spo2 = int(row["SpO2"])
        bs   = int(row["BloodSugar"])
        pain = int(row["PainLevel"])
    except (ValueError, KeyError) as e:
        print(f"[WARN] {pid}: parse error {e} - skipped")
        return False

    checks = [
        (0 <= age <= 130,          f"invalid age {age}"),
        (30.0 <= temp <= 45.0,     f"invalid temperature {temp}°C"),
        (20 <= hr <= 300,          f"invalid heart rate {hr}"),
        (5 <= rr <= 60,            f"invalid respiratory rate {rr}"),
        (0 <= spo2 <= 100,         f"invalid SpO2 {spo2}"),
        (0 <= bs <= 1000,          f"invalid blood sugar {bs}"),
        (0 <= pain <= 10,          f"invalid pain level {pain}"),
    ]
    for ok, msg in checks:
        if not ok:
            print(f"[WARN] {pid}: {msg} - skipped")
            return False
    return True

# ── CSV helpers ───────────────────────────────────────────────────
def read_csv(path):
    if not os.path.exists(path):
        print(f"[ERROR] File not found: {path}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [{k:v.strip() for k,v in row.items()} for row in csv.DictReader(f)]

def write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[INFO] Written: {path}")

def append_history(path, results):
    """Append-only with deduplication — never adds the same (PatientID, AssessmentNumber) twice."""
    existing_keys = set()
    existing_rows = []
    HIST_FIELDS = ['PatientID','AssessmentNumber','DaysAdmitted','RawClinicalScore',
                   'HSI','AssignedDoctor','Ward','Category']

    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            with open(path, newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    key = (row.get('PatientID',''), str(row.get('AssessmentNumber','')))
                    existing_keys.add(key)
                    existing_rows.append(row)
        except Exception:
            pass  # Treat corrupted history as empty

    new_rows = []
    for r in results:
        assess_num = str(r['PreviousAssessments'])
        key = (r['PatientID'], assess_num)
        if key not in existing_keys:
            new_rows.append({
                'PatientID': r['PatientID'], 'AssessmentNumber': assess_num,
                'DaysAdmitted': r['DaysAdmitted'], 'RawClinicalScore': r['RawClinicalScore'],
                'HSI': r['HSI'], 'AssignedDoctor': r['AssignedDoctor'],
                'Ward': r['Ward'], 'Category': r['EmergencyCategory'],
            })

    all_rows = existing_rows + new_rows
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HIST_FIELDS)
        w.writeheader()
        w.writerows(all_rows)
    print(f'[INFO] History: {len(new_rows)} new entries appended (total: {len(all_rows)})')

# ── Main ─────────────────────────────────────────────────────────
def main():
    print("\n=== Smart Inpatient Monitoring (Python Fallback) ===\n")

    # Load datasets
    raw_patients = read_csv(PAT_CSV)
    doctors      = read_csv(DOC_CSV)
    wards        = read_csv(WARD_CSV)

    # ── CRITICAL FIX: Reset counts so they don't accumulate across runs ──
    for d in doctors:
        d['CurrentPatients'] = '0'
    for w in wards:
        w['OccupiedBeds']  = '0'
        w['AvailableBeds'] = str(int(w['TotalBeds']))
    print('[INFO] Doctor and ward counts reset to 0.')

    # Validate patients
    patients = []
    for i, row in enumerate(raw_patients, start=2):
        if validate(row, i):
            patients.append(row)
    print(f"[INFO] Read {len(patients)} valid patient(s)\n")

    if not patients:
        print("[ERROR] No valid patients found.")
        sys.exit(1)

    # Pass 1: raw scores
    print("[PASS 1] Computing clinical scores...")
    for p in patients:
        syms  = p.get("Symptoms","")
        raw, cardiac, resp, neuro, infect, trauma = compute_raw_score(p)
        p["_raw"]     = raw
        p["_cardiac"] = cardiac
        p["_resp"]    = resp
        p["_neuro"]   = neuro
        p["_infect"]  = infect
        p["_trauma"]  = trauma
        cond = infer_condition(syms, cardiac, resp, neuro, infect, trauma)
        p["LikelyCondition"] = cond
        print(f"  [{p['PatientID']}] {p['PatientName']:<18} Raw={raw:.1f}  Condition: {cond}")

    # Pass 2: normalize HSI
    print("\n[PASS 2] Normalizing HSI...")
    max_raw = max((p["_raw"] for p in patients), default=1.0)
    for p in patients:
        p["_hsi"] = (p["_raw"] / max_raw * 100.0) if max_raw > 0 else 0.0

    # Pass 3: classify + assign + recommend + trend
    print("\n[PASS 3] Classifying, assigning, recommending...")
    results = []
    for p in patients:
        hsi      = p["_hsi"]
        raw      = p["_raw"]
        category = classify_hsi(hsi)
        prev_hsi = float(p.get("PreviousHSI", 0) or 0)
        prev_cnt = int(p.get("PreviousAssessments", 0) or 0)
        trend    = recovery_trend(hsi, prev_hsi, prev_cnt)
        
        doctor = str(p.get("AssignedDoctor", "")).strip()
        if not doctor or doctor == "Unassigned":
            doctor = "Unassigned"
        else:
            for d in doctors:
                if d["DoctorName"] == doctor:
                    d["CurrentPatients"] = str(int(d["CurrentPatients"]) + 1)
                    break

        ward_rec = recommend_ward(hsi, p.get("Ward", ""), wards)
        status   = derive_patient_status(category, trend)

        color = C_GREEN
        if category == "Critical": color = C_RED
        elif category == "Moderate": color = C_YELLOW
        
        if p == patients[0]:
            print(f"\n{C_CYAN}+------------------------------------------------------------------------------------------------------------------------+{C_RESET}")
            print(f"{C_CYAN}| {C_BOLD}{'ID':<6} | {'Patient Name':<18} | {'HSI':<5} | {'Category':<10} | {'Doctor':<20} | {'Ward Action':<30} |{C_RESET}")
            print(f"{C_CYAN}+------------------------------------------------------------------------------------------------------------------------+{C_RESET}")

        print(f"{C_CYAN}|{C_RESET} {p['PatientID']:<6} | {p['PatientName']:<18.18} | {hsi:<5.1f} | {color}{category:<10}{C_RESET} | {doctor:<20.20} | {ward_rec:<30.30} {C_CYAN}|{C_RESET}")
        
        if p == patients[-1]:
            print(f"{C_CYAN}+------------------------------------------------------------------------------------------------------------------------+{C_RESET}")

        results.append({
            "PatientID":           p["PatientID"],
            "PatientName":         p["PatientName"],
            "Age":                 p["Age"],
            "Gender":              p.get("Gender",""),
            "Ward":                p.get("Ward",""),
            "BedNumber":           p.get("BedNumber",""),
            "DaysAdmitted":        p.get("DaysAdmitted",""),
            "Temperature":         p.get("Temperature",""),
            "HeartRate":           p.get("HeartRate",""),
            "RespiratoryRate":     p.get("RespiratoryRate",""),
            "BloodPressure":       p.get("BloodPressure",""),
            "SpO2":                p.get("SpO2",""),
            "BloodSugar":          p.get("BloodSugar",""),
            "PainLevel":           p.get("PainLevel",""),
            "ConsciousnessStatus": p.get("ConsciousnessStatus",""),
            "MobilityStatus":      p.get("MobilityStatus",""),
            "Symptoms":            p.get("Symptoms",""),
            "LikelyCondition":     p["LikelyCondition"],
            "RawClinicalScore":    f"{raw:.2f}",
            "HSI":                 f"{hsi:.2f}",
            "PreviousHSI":         p.get("PreviousHSI","0"),
            "PreviousAssessments": str(prev_cnt + 1),
            "EmergencyCategory":   category,
            "AssignedDoctor":      doctor,
            "WardRecommendation":  ward_rec,
            "PatientStatus":       status,
            "RecoveryTrend":       trend,
        })

    # Write outputs
    print("\n[OUTPUT] Writing results...")
    RES_FIELDS = [
        "PatientID","PatientName","Age","Gender","Ward","BedNumber","DaysAdmitted",
        "Temperature","HeartRate","RespiratoryRate","BloodPressure","SpO2",
        "BloodSugar","PainLevel","ConsciousnessStatus","MobilityStatus",
        "Symptoms","LikelyCondition","RawClinicalScore","HSI","PreviousHSI",
        "PreviousAssessments","EmergencyCategory","AssignedDoctor",
        "WardRecommendation","PatientStatus","RecoveryTrend"
    ]
    write_csv(RES_CSV, RES_FIELDS, results)

    # Copy to dashboard
    os.makedirs(DASH_DIR, exist_ok=True)
    import shutil
    for src in [RES_CSV, DOC_CSV, WARD_CSV]:
        dst = os.path.join(DASH_DIR, os.path.basename(src))
        shutil.copy2(src, dst)
        print(f"[INFO] Copied to dashboard: {dst}")

    # Write updated doctors + wards
    DOC_FIELDS  = ["DoctorID","DoctorName","Specialization","ExperienceYears",
                   "CurrentPatients","MaximumPatients","Availability"]
    WARD_FIELDS = ["WardName","WardType","TotalBeds","OccupiedBeds","AvailableBeds"]
    write_csv(DOC_CSV,  DOC_FIELDS,  doctors)
    write_csv(WARD_CSV, WARD_FIELDS, wards)

    # CRITICAL FIX: Copy results.csv back to patients.csv so PreviousAssessments
    # is updated for the next run, preventing repeated history entries.
    shutil.copy2(RES_CSV, PAT_CSV)
    print(f"[INFO] Updated patients.csv with latest results (assessment counts incremented)")

    # Append history
    append_history(HIST_CSV, results)

    # Copy ALL updated files to dashboard for serving
    for src in [RES_CSV, DOC_CSV, WARD_CSV, HIST_CSV]:
        if os.path.exists(src):
            dst = os.path.join(DASH_DIR, os.path.basename(src))
            shutil.copy2(src, dst)
    print(f"[INFO] All CSVs synced to dashboard/")

    # Summary
    crit  = sum(1 for r in results if r["EmergencyCategory"]=="Critical")
    mod   = sum(1 for r in results if r["EmergencyCategory"]=="Moderate")
    stab  = sum(1 for r in results if r["EmergencyCategory"]=="Stable")

    print(f"\n{C_CYAN}+----------------------------------------------------------+{C_RESET}")
    print(f"{C_CYAN}|{C_BOLD}   INPATIENT MONITORING — ASSESSMENT SUMMARY              {C_RESET}{C_CYAN}|{C_RESET}")
    print(f"{C_CYAN}+----------------------------------------------------------+{C_RESET}")
    print(f"{C_CYAN}|{C_RESET}  Total Patients : {len(results):<38} {C_CYAN}|{C_RESET}")
    print(f"{C_CYAN}|{C_RESET}  Critical       : {C_RED}{crit:<38}{C_RESET} {C_CYAN}|{C_RESET}")
    print(f"{C_CYAN}|{C_RESET}  Moderate       : {C_YELLOW}{mod:<38}{C_RESET} {C_CYAN}|{C_RESET}")
    print(f"{C_CYAN}|{C_RESET}  Stable         : {C_GREEN}{stab:<38}{C_RESET} {C_CYAN}|{C_RESET}")
    print(f"{C_CYAN}+----------------------------------------------------------+{C_RESET}")
    print(f"{C_CYAN}+----------------------------------------------------------+{C_RESET}\n")
    print("[DONE] Open dashboard/index.html or run server.py\n")

if __name__ == "__main__":
    main()
