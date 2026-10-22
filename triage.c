/*
 * ============================================================
 *  Smart Inpatient Monitoring & Clinical Decision Support
 *  triage.c  (C99)
 *
 *  Inputs  : patients.csv  doctors.csv  wards.csv
 *  Outputs : results.csv   doctors.csv  wards.csv  history.csv
 *
 *  Architecture: ALL medical calculations live here.
 *  The dashboard is display-only; it never computes scores.
 *
 *  Scoring Model
 *  -------------
 *  1. Vital Deviation Score  (0-60, 6 vitals × 0-10 each)
 *  2. Category Scores        (Cardiac / Respiratory / Neuro /
 *                             Infection / Trauma / General)
 *     Each symptom has a weight 1-5; category score = sum.
 *  3. Pain Level             (0-10 scale)
 *  4. Interaction Rules      (~5 rules, multiplier-based)
 *
 *  raw_score = 0.4*vitalDev + 0.4*categorySum + 0.2*pain*10
 *              + interaction bumps  (clamped to 200)
 *
 *  HSI = (raw_score / max_raw_in_dataset) * 100
 *        >= 70 -> Critical
 *        40-69 -> Moderate
 *        < 40  -> Stable
 *
 *  Recovery Trend
 *  --------------
 *  delta = currentHSI - previousHSI
 *  delta <= -10 -> Improving
 *  -10 < delta < 10 -> Stable
 *  delta >= 10  -> Worsening
 * ============================================================
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <math.h>

/* ── Buffer Sizes ─────────────────────────────────────────── */
#define MAX_PATIENTS  1000
#define MAX_DOCTORS    50
#define MAX_WARDS      20
#define FLEN          256
#define SLEN          768
#define BPLEN          16

/* ── Vital Normal Ranges ──────────────────────────────────── */
#define TEMP_LOW_C   36.1
#define TEMP_HIGH_C  37.2
#define HR_LOW        60
#define HR_HIGH      100
#define RR_LOW        12
#define RR_HIGH       20
#define SPO2_LOW      95   /* below 95 is concern; below 90 critical */
#define BS_LOW        70   /* mg/dL fasting */
#define BS_HIGH      140
#define SBP_LOW       90   /* systolic */
#define SBP_HIGH     140
#define DBP_LOW       60   /* diastolic */
#define DBP_HIGH      90

/* ── Interaction Rule Thresholds ──────────────────────────── */
#define CARDIAC_THRESH    6
#define RESP_THRESH       6
#define NEURO_THRESH      7
#define INFECT_THRESH     5
#define TRAUMA_THRESH     8

/* ── ANSI Colors ──────────────────────────────────────────── */
#define C_RESET  "\x1b[0m"
#define C_RED    "\x1b[1;31m"
#define C_GREEN  "\x1b[1;32m"
#define C_YELLOW "\x1b[1;33m"
#define C_CYAN   "\x1b[1;36m"
#define C_BOLD   "\x1b[1m"

/* ============================================================
 *  DATA STRUCTURES
 * ============================================================ */

typedef struct {
    char id[FLEN];
    char name[FLEN];
    int  age;
    char gender[FLEN];
    char ward[FLEN];
    char bedNumber[FLEN];
    int  daysAdmitted;
    double temperature;   /* Celsius */
    int  heartRate;
    int  respiratoryRate;
    int  systolicBP;
    int  diastolicBP;
    int  spo2;
    int  bloodSugar;
    int  painLevel;
    char consciousnessStatus[FLEN];
    char mobilityStatus[FLEN];
    char symptoms[SLEN];
    char likelyCondition[FLEN];
    double rawClinicalScore;
    double hsi;
    double previousHSI;
    int  previousAssessments;
    char emergencyCategory[FLEN];
    char assignedDoctor[FLEN];
    char wardRecommendation[FLEN];
    char patientStatus[FLEN];
    char recoveryTrend[FLEN];
} Patient;

typedef struct {
    char id[FLEN];
    char name[FLEN];
    char specialization[FLEN];
    int  experienceYears;
    int  currentPatients;
    int  maximumPatients;
    char availability[FLEN];
} Doctor;

typedef struct {
    char wardName[FLEN];
    char wardType[FLEN];
    int  totalBeds;
    int  occupiedBeds;
    int  availableBeds;
} Ward;

/* ── Symptom weight entry ─────────────────────────────────── */
typedef struct {
    const char *keyword;
    int         weight;   /* 1-5 */
} SymWeight;

/* ============================================================
 *  SYMPTOM WEIGHT TABLES  (category-based, not nested if-chains)
 * ============================================================ */

static const SymWeight CARDIAC_SYMS[] = {
    { "chest pain",         4 },
    { "sweating",           2 },
    { "palpitations",       3 },
    { "left arm pain",      4 },
    { "irregular heartbeat",5 },
    { NULL, 0 }
};

static const SymWeight RESP_SYMS[] = {
    { "breathlessness",     4 },
    { "wheezing",           3 },
    { "persistent cough",   2 },
    { "rapid breathing",    3 },
    { "low oxygen",         5 },
    { NULL, 0 }
};

static const SymWeight NEURO_SYMS[] = {
    { "headache",           2 },
    { "dizziness",          2 },
    { "confusion",          4 },
    { "slurred speech",     4 },
    { "unconsciousness",    5 },
    { "seizures",           5 },
    { NULL, 0 }
};

static const SymWeight INFECT_SYMS[] = {
    { "fever",              3 },
    { "chills",             2 },
    { "vomiting",           2 },
    { "diarrhea",           2 },
    { NULL, 0 }
};

static const SymWeight TRAUMA_SYMS[] = {
    { "heavy bleeding",     5 },
    { "burns",              4 },
    { "fractures",          3 },
    { "head injury",        5 },
    { NULL, 0 }
};

static const SymWeight GENERAL_SYMS[] = {
    { "fatigue",            1 },
    { "dehydration",        2 },
    { "weakness",           1 },
    { NULL, 0 }
};

/* ============================================================
 *  CONDITION → SPECIALIZATION LOOKUP TABLE
 * ============================================================ */
typedef struct {
    const char *condition;
    const char *specialization;
} CondSpec;

static const CondSpec COND_SPEC_MAP[] = {
    { "Myocardial Infarction",  "Cardiologist"            },
    { "Arrhythmia",             "Cardiologist"            },
    { "Pneumonia",              "Pulmonologist"           },
    { "Asthma Exacerbation",    "Pulmonologist"           },
    { "Stroke",                 "Neurologist"             },
    { "Seizure Disorder",       "Neurologist"             },
    { "Sepsis",                 "Infectious Disease"      },
    { "Gastroenteritis",        "Infectious Disease"      },
    { "General Infection",      "Infectious Disease"      },
    { "Fracture",               "Emergency Medicine"      },
    { "Burn Injury",            "Emergency Medicine"      },
    { "Head Trauma",            "Emergency Medicine"      },
    { "Dehydration",            "General Physician"       },
    { NULL, NULL }
};

/* ============================================================
 *  STRING UTILITIES
 * ============================================================ */

static void trim(char *s)
{
    char *p = s;
    while (*p && isspace((unsigned char)*p)) p++;
    if (p != s) memmove(s, p, strlen(p) + 1);
    size_t n = strlen(s);
    while (n > 0 && isspace((unsigned char)s[n - 1])) s[--n] = '\0';
    if (n >= 2 && s[0] == '"' && s[n - 1] == '"') {
        s[n - 1] = '\0';
        memmove(s, s + 1, n - 1);
    }
}

/* Case-insensitive substring search */
static int hasSymptom(const char *syms, const char *kw)
{
    char h[SLEN], n[FLEN];
    size_t i;
    strncpy(h, syms, SLEN - 1); h[SLEN - 1] = '\0';
    strncpy(n, kw,   FLEN - 1); n[FLEN - 1] = '\0';
    for (i = 0; h[i]; i++) h[i] = (char)tolower((unsigned char)h[i]);
    for (i = 0; n[i]; i++) n[i] = (char)tolower((unsigned char)n[i]);
    return strstr(h, n) != NULL;
}

/* Minimal RFC-4180 CSV line parser */
static int parseCSVLine(const char *line, char fields[][FLEN], int maxF)
{
    int fi = 0, ci = 0, inq = 0;
    size_t i, n = strlen(line);
    for (i = 0; i < n && fi < maxF; i++) {
        char c = line[i];
        if (c == '"') {
            inq = !inq;
            fields[fi][ci++] = c;
        } else if (c == ',' && !inq) {
            fields[fi][ci] = '\0';
            trim(fields[fi]);
            fi++; ci = 0;
        } else if (c != '\r' && c != '\n') {
            if (ci < FLEN - 1) fields[fi][ci++] = c;
        }
    }
    if (ci > 0 || fi == 0) {
        fields[fi][ci] = '\0';
        trim(fields[fi]);
        fi++;
    }
    return fi;
}

/* ============================================================
 *  VITAL DEVIATION SCORING
 *  Each vital contributes 0-10 based on how far from normal.
 *  Total = sum of all 6 vitals (max 60).
 * ============================================================ */
static double vitalDevScore(const Patient *p)
{
    double score = 0.0;

    /* Temperature (°C): normal 36.1-37.2 */
    if (p->temperature < TEMP_LOW_C) {
        double dev = TEMP_LOW_C - p->temperature;
        score += (dev > 2.0) ? 10.0 : dev * 5.0;
    } else if (p->temperature > TEMP_HIGH_C) {
        double dev = p->temperature - TEMP_HIGH_C;
        score += (dev > 3.0) ? 10.0 : dev * 3.33;
    }

    /* Heart Rate: normal 60-100 bpm */
    if (p->heartRate < HR_LOW) {
        double dev = HR_LOW - p->heartRate;
        score += (dev > 30) ? 10.0 : dev / 3.0;
    } else if (p->heartRate > HR_HIGH) {
        double dev = p->heartRate - HR_HIGH;
        score += (dev > 60) ? 10.0 : dev / 6.0;
    }

    /* Respiratory Rate: normal 12-20 breaths/min */
    if (p->respiratoryRate < RR_LOW) {
        double dev = RR_LOW - p->respiratoryRate;
        score += (dev > 6) ? 10.0 : dev * 1.67;
    } else if (p->respiratoryRate > RR_HIGH) {
        double dev = p->respiratoryRate - RR_HIGH;
        score += (dev > 20) ? 10.0 : dev / 2.0;
    }

    /* SpO2: normal >= 95%; below 90% is critical */
    if (p->spo2 < SPO2_LOW) {
        double dev = SPO2_LOW - p->spo2;
        score += (dev > 15) ? 10.0 : dev * 0.67;
    }

    /* Blood Sugar: normal 70-140 mg/dL */
    if (p->bloodSugar < BS_LOW) {
        double dev = BS_LOW - p->bloodSugar;
        score += (dev > 40) ? 10.0 : dev / 4.0;
    } else if (p->bloodSugar > BS_HIGH) {
        double dev = p->bloodSugar - BS_HIGH;
        score += (dev > 200) ? 10.0 : dev / 20.0;
    }

    /* Systolic Blood Pressure: normal 90-140 mmHg */
    if (p->systolicBP < SBP_LOW) {
        double dev = SBP_LOW - p->systolicBP;
        score += (dev > 40) ? 10.0 : dev / 4.0;
    } else if (p->systolicBP > SBP_HIGH) {
        double dev = p->systolicBP - SBP_HIGH;
        score += (dev > 60) ? 10.0 : dev / 6.0;
    }

    return score;
}

/* ============================================================
 *  CATEGORY SCORING
 *  Uses weight tables; consciousness status folds into neuro.
 * ============================================================ */
static int scoreCategoryTable(const char *syms,
                               const SymWeight *table)
{
    int total = 0;
    int i;
    for (i = 0; table[i].keyword != NULL; i++) {
        if (hasSymptom(syms, table[i].keyword))
            total += table[i].weight;
    }
    return total;
}

/* Consciousness status folds into neuro score */
static int consciousnessBonus(const char *status)
{
    char s[FLEN];
    size_t i;
    strncpy(s, status, FLEN - 1); s[FLEN - 1] = '\0';
    for (i = 0; s[i]; i++) s[i] = (char)tolower((unsigned char)s[i]);
    if (strstr(s, "unresponsive")) return 5;
    if (strstr(s, "unconscious"))  return 5;
    if (strstr(s, "confused"))     return 3;
    return 0;
}

/* ============================================================
 *  RAW SCORE + INTERACTION RULES
 * ============================================================ */
static double computeRawScore(const Patient *p,
                               int *out_cardiac,
                               int *out_resp,
                               int *out_neuro,
                               int *out_infect,
                               int *out_trauma,
                               int *out_general)
{
    double vdev = vitalDevScore(p);

    int cardiac  = scoreCategoryTable(p->symptoms, CARDIAC_SYMS);
    int resp     = scoreCategoryTable(p->symptoms, RESP_SYMS);
    int neuro    = scoreCategoryTable(p->symptoms, NEURO_SYMS)
                   + consciousnessBonus(p->consciousnessStatus);
    int infect   = scoreCategoryTable(p->symptoms, INFECT_SYMS);
    int trauma   = scoreCategoryTable(p->symptoms, TRAUMA_SYMS);
    int general  = scoreCategoryTable(p->symptoms, GENERAL_SYMS);

    if (out_cardiac)  *out_cardiac  = cardiac;
    if (out_resp)     *out_resp     = resp;
    if (out_neuro)    *out_neuro    = neuro;
    if (out_infect)   *out_infect   = infect;
    if (out_trauma)   *out_trauma   = trauma;
    if (out_general)  *out_general  = general;

    double catSum = (double)(cardiac + resp + neuro + infect + trauma + general);

    /* Base formula: weights w1=0.4, w2=0.4, w3=0.2 */
    double raw = 0.4 * vdev
               + 0.4 * catSum * 4.0   /* scale category sum to similar range as vdev */
               + 0.2 * p->painLevel * 6.0;

    /* ── Interaction Rules ──────────────────────────────── */

    /* Rule 1: Cardiac + Respiratory compound event (×1.3) */
    if (cardiac >= CARDIAC_THRESH && resp >= RESP_THRESH)
        raw *= 1.3;

    /* Rule 2: Neuro + Infection (possible sepsis-related neuro, ×1.2) */
    if (neuro >= NEURO_THRESH && infect >= INFECT_THRESH)
        raw *= 1.2;

    /* Rule 3: Major trauma - flat priority bump */
    if (trauma >= TRAUMA_THRESH)
        raw += 20.0;

    /* Rule 4: Unconscious/Unresponsive - always escalates severity */
    if (hasSymptom(p->symptoms, "unconsciousness") ||
        consciousnessBonus(p->consciousnessStatus) >= 5)
        raw += 15.0;

    /* Rule 5: Head Injury always escalates (time-critical) */
    if (hasSymptom(p->symptoms, "head injury"))
        raw += 12.0;

    /* Clamp to max 200 */
    if (raw > 200.0) raw = 200.0;
    if (raw < 0.0)   raw = 0.0;

    return raw;
}

/* ============================================================
 *  HSI NORMALIZATION  (two-pass over all patients)
 * ============================================================ */
static void normalizeHSI(Patient *pts, int n)
{
    double maxRaw = 0.0;
    int i;
    for (i = 0; i < n; i++) {
        if (pts[i].rawClinicalScore > maxRaw)
            maxRaw = pts[i].rawClinicalScore;
    }
    for (i = 0; i < n; i++) {
        if (maxRaw > 0.0)
            pts[i].hsi = (pts[i].rawClinicalScore / maxRaw) * 100.0;
        else
            pts[i].hsi = 0.0;
    }
}

/* ============================================================
 *  EMERGENCY CATEGORY  (from HSI)
 * ============================================================ */
static void classifyHSI(double hsi, char *cat)
{
    if (hsi >= 70.0)       strcpy(cat, "Critical");
    else if (hsi >= 40.0)  strcpy(cat, "Moderate");
    else                   strcpy(cat, "Stable");
}

/* ============================================================
 *  CONDITION INFERENCE
 *  Dominant category + consciousness -> fixed condition list
 * ============================================================ */
static void inferCondition(const Patient *p,
                            int cardiac, int resp,
                            int neuro, int infect,
                            int trauma, char *cond)
{
    /* Trauma takes priority (time-critical) */
    if (trauma >= 5) {
        if (hasSymptom(p->symptoms, "head injury"))
            strcpy(cond, "Head Trauma");
        else if (hasSymptom(p->symptoms, "burns"))
            strcpy(cond, "Burn Injury");
        else if (hasSymptom(p->symptoms, "heavy bleeding") ||
                 hasSymptom(p->symptoms, "fractures"))
            strcpy(cond, "Fracture");
        else
            strcpy(cond, "Head Trauma");
        return;
    }

    /* Neuro + Infection -> Sepsis */
    if (neuro >= 4 && infect >= 3) {
        strcpy(cond, "Sepsis");
        return;
    }

    /* Find dominant category */
    int scores[6] = {cardiac, resp, neuro, infect, trauma, 0};
    int dom = 0, j;
    for (j = 1; j < 5; j++) {
        if (scores[j] > scores[dom]) dom = j;
    }

    switch (dom) {
        case 0: /* Cardiac */
            if (hasSymptom(p->symptoms, "irregular heartbeat"))
                strcpy(cond, "Arrhythmia");
            else
                strcpy(cond, "Myocardial Infarction");
            break;
        case 1: /* Respiratory */
            if (hasSymptom(p->symptoms, "wheezing"))
                strcpy(cond, "Asthma Exacerbation");
            else
                strcpy(cond, "Pneumonia");
            break;
        case 2: /* Neuro */
            if (hasSymptom(p->symptoms, "seizures"))
                strcpy(cond, "Seizure Disorder");
            else
                strcpy(cond, "Stroke");
            break;
        case 3: /* Infection */
            if (hasSymptom(p->symptoms, "vomiting") ||
                hasSymptom(p->symptoms, "diarrhea"))
                strcpy(cond, "Gastroenteritis");
            else
                strcpy(cond, "General Infection");
            break;
        default:
            strcpy(cond, "Dehydration");
    }
}

/* ============================================================
 *  RECOVERY TREND
 * ============================================================ */
static void computeRecoveryTrend(double currentHSI,
                                  double previousHSI,
                                  int    previousAssessments,
                                  char  *trend)
{
    if (previousAssessments == 0) {
        strcpy(trend, "Stable"); /* First assessment, no prior data */
        return;
    }
    double delta = currentHSI - previousHSI;
    if (delta <= -10.0)     strcpy(trend, "Improving");
    else if (delta >= 10.0) strcpy(trend, "Worsening");
    else                    strcpy(trend, "Stable");
}

/* ============================================================
 *  DOCTOR ASSIGNMENT
 * ============================================================ */
static const char *conditionToSpecialization(const char *cond)
{
    int i;
    for (i = 0; COND_SPEC_MAP[i].condition != NULL; i++) {
        if (strcmp(cond, COND_SPEC_MAP[i].condition) == 0)
            return COND_SPEC_MAP[i].specialization;
    }
    return "General Physician";
}

static int assignDoctor(const char *requiredSpec,
                         Doctor *docs, int nDocs,
                         char *assignedName)
{
    /* Phase 1: match specialization + available + capacity */
    int bestIdx = -1;
    int bestLoad = 9999;
    int i;
    for (i = 0; i < nDocs; i++) {
        if (strcmp(docs[i].availability, "Available") != 0) continue;
        if (docs[i].currentPatients >= docs[i].maximumPatients) continue;
        if (strcmp(docs[i].specialization, requiredSpec) == 0) {
            if (docs[i].currentPatients < bestLoad) {
                bestLoad = docs[i].currentPatients;
                bestIdx  = i;
            }
        }
    }

    /* Phase 2: fallback to General Physician */
    if (bestIdx < 0) {
        for (i = 0; i < nDocs; i++) {
            if (strcmp(docs[i].availability, "Available") != 0) continue;
            if (docs[i].currentPatients >= docs[i].maximumPatients) continue;
            if (strcmp(docs[i].specialization, "General Physician") == 0) {
                if (docs[i].currentPatients < bestLoad) {
                    bestLoad = docs[i].currentPatients;
                    bestIdx  = i;
                }
            }
        }
    }

    if (bestIdx >= 0) {
        strcpy(assignedName, docs[bestIdx].name);
        docs[bestIdx].currentPatients++;
        return bestIdx;
    }

    strcpy(assignedName, "Unassigned");
    return -1;
}

/* ============================================================
 *  WARD RECOMMENDATION
 * ============================================================ */
static void recommendWard(double hsi, const char *currentWard, Ward *wards, int nWards,
                           char *wardRec)
{
    /* Priority order based on HSI */
    const char *preferred[4];
    if      (hsi >= 80.0) { preferred[0]="ICU"; preferred[1]="HDU"; preferred[2]="Observation"; preferred[3]="General"; }
    else if (hsi >= 60.0) { preferred[0]="HDU"; preferred[1]="ICU"; preferred[2]="Observation"; preferred[3]="General"; }
    else if (hsi >= 40.0) { preferred[0]="Observation"; preferred[1]="HDU"; preferred[2]="General"; preferred[3]="ICU"; }
    else                  { preferred[0]="General"; preferred[1]="Observation"; preferred[2]="HDU"; preferred[3]="ICU"; }

    /* Try to keep them in their current ward if it matches the best type and has beds */
    int i;
    for (i = 0; i < nWards; i++) {
        if (strcmp(wards[i].wardName, currentWard) == 0 &&
            strcmp(wards[i].wardType, preferred[0]) == 0) {
            strcpy(wardRec, "Remain in Current");
            return;
        }
    }

    int p;
    for (p = 0; p < 4; p++) {
        for (i = 0; i < nWards; i++) {
            if (strcmp(wards[i].wardType, preferred[p]) == 0 &&
                wards[i].availableBeds > 0) {
                if (strcmp(wards[i].wardName, currentWard) == 0) {
                    strcpy(wardRec, "Remain in Current");
                } else {
                    sprintf(wardRec, "Transfer to %s", wards[i].wardName);
                }
                wards[i].occupiedBeds++;
                wards[i].availableBeds--;
                return;
            }
        }
    }
    /* No beds available anywhere */
    strcpy(wardRec, "No Bed Available");
}

/* ============================================================
 *  INPUT VALIDATION (expanded for all 27 fields)
 * ============================================================ */
static int validatePatient(const Patient *p, int lineNum)
{
    if (!p->id[0]) {
        fprintf(stderr, "[WARN] Line %d: empty PatientID - skipped\n", lineNum);
        return 0;
    }
    if (p->age < 0 || p->age > 130) {
        fprintf(stderr, "[WARN] %s: invalid age %d - skipped\n", p->id, p->age);
        return 0;
    }
    if (p->temperature < 30.0 || p->temperature > 45.0) {
        fprintf(stderr, "[WARN] %s: invalid temperature %.1f°C - skipped\n",
                p->id, p->temperature);
        return 0;
    }
    if (p->heartRate < 20 || p->heartRate > 300) {
        fprintf(stderr, "[WARN] %s: invalid heart rate %d - skipped\n",
                p->id, p->heartRate);
        return 0;
    }
    if (p->respiratoryRate < 5 || p->respiratoryRate > 60) {
        fprintf(stderr, "[WARN] %s: invalid respiratory rate %d - skipped\n",
                p->id, p->respiratoryRate);
        return 0;
    }
    if (p->spo2 < 0 || p->spo2 > 100) {
        fprintf(stderr, "[WARN] %s: invalid SpO2 %d - skipped\n",
                p->id, p->spo2);
        return 0;
    }
    if (p->bloodSugar < 0 || p->bloodSugar > 1000) {
        fprintf(stderr, "[WARN] %s: invalid blood sugar %d - skipped\n",
                p->id, p->bloodSugar);
        return 0;
    }
    if (p->painLevel < 0 || p->painLevel > 10) {
        fprintf(stderr, "[WARN] %s: invalid pain level %d - skipped\n",
                p->id, p->painLevel);
        return 0;
    }
    return 1;
}

/* ============================================================
 *  CSV READERS
 * ============================================================ */

/* Parse blood pressure "systolic/diastolic" */
static void parseBP(const char *bp, int *sys, int *dia)
{
    *sys = 0; *dia = 0;
    char tmp[BPLEN];
    strncpy(tmp, bp, BPLEN - 1); tmp[BPLEN - 1] = '\0';
    char *slash = strchr(tmp, '/');
    if (slash) {
        *slash = '\0';
        *sys = atoi(tmp);
        *dia = atoi(slash + 1);
    } else {
        *sys = atoi(tmp);
    }
}

static int readPatients(const char *fn, Patient *pts, int maxP)
{
    FILE *fp = fopen(fn, "r");
    if (!fp) { fprintf(stderr, "[ERROR] Cannot open %s\n", fn); return -1; }

    char line[4096];
    int count = 0, ln = 0, first = 1;

    while (fgets(line, sizeof(line), fp)) {
        ln++;
        if (line[0] == '\r' || line[0] == '\n') continue;
        if (first) { first = 0; continue; } /* skip header */
        if (count >= maxP) { fprintf(stderr, "[WARN] Max patients reached\n"); break; }

        char f[27][FLEN];
        memset(f, 0, sizeof(f));
        int nf = parseCSVLine(line, f, 27);
        if (nf < 17) {
            fprintf(stderr, "[WARN] Line %d: expected >=17 fields, got %d - skipped\n", ln, nf);
            continue;
        }

        Patient *pt = &pts[count];
        memset(pt, 0, sizeof(Patient));

        strncpy(pt->id,                  f[0],  FLEN - 1);
        strncpy(pt->name,                f[1],  FLEN - 1);
        pt->age = atoi(f[2]);
        strncpy(pt->gender,              f[3],  FLEN - 1);
        strncpy(pt->ward,                f[4],  FLEN - 1);
        strncpy(pt->bedNumber,           f[5],  FLEN - 1);
        pt->daysAdmitted    = atoi(f[6]);
        pt->temperature     = atof(f[7]);
        pt->heartRate       = atoi(f[8]);
        pt->respiratoryRate = atoi(f[9]);
        parseBP(f[10], &pt->systolicBP, &pt->diastolicBP);
        pt->spo2        = atoi(f[11]);
        pt->bloodSugar  = atoi(f[12]);
        pt->painLevel   = atoi(f[13]);
        strncpy(pt->consciousnessStatus, f[14], FLEN - 1);
        strncpy(pt->mobilityStatus,      f[15], FLEN - 1);
        strncpy(pt->symptoms,            f[16], SLEN - 1);

        /* Fields 17-26 may be pre-filled or blank (C engine will overwrite) */
        if (nf > 17) strncpy(pt->likelyCondition,    f[17], FLEN - 1);
        if (nf > 20) pt->previousHSI         = atof(f[20]);
        if (nf > 21) pt->previousAssessments = atoi(f[21]);
        if (nf > 23) strncpy(pt->assignedDoctor,     f[23], FLEN - 1);

        if (!validatePatient(pt, ln)) continue;
        count++;
    }
    fclose(fp);
    printf("[INFO] Read %d valid patient(s) from '%s'\n", count, fn);
    return count;
}

static int readDoctors(const char *fn, Doctor *docs, int maxD)
{
    FILE *fp = fopen(fn, "r");
    if (!fp) { fprintf(stderr, "[ERROR] Cannot open %s\n", fn); return -1; }

    char line[1024];
    int count = 0, ln = 0, first = 1;

    while (fgets(line, sizeof(line), fp)) {
        ln++;
        if (line[0] == '\r' || line[0] == '\n') continue;
        if (first) { first = 0; continue; }
        if (count >= maxD) break;

        char f[7][FLEN];
        memset(f, 0, sizeof(f));
        int nf = parseCSVLine(line, f, 7);
        if (nf < 7) continue;

        Doctor *d = &docs[count];
        strncpy(d->id,             f[0], FLEN - 1);
        strncpy(d->name,           f[1], FLEN - 1);
        strncpy(d->specialization, f[2], FLEN - 1);
        d->experienceYears  = atoi(f[3]);
        d->currentPatients  = atoi(f[4]);
        d->maximumPatients  = atoi(f[5]);
        strncpy(d->availability,   f[6], FLEN - 1);
        count++;
    }
    fclose(fp);
    printf("[INFO] Read %d doctor(s) from '%s'\n", count, fn);
    return count;
}

static int readWards(const char *fn, Ward *wards, int maxW)
{
    FILE *fp = fopen(fn, "r");
    if (!fp) { fprintf(stderr, "[ERROR] Cannot open %s\n", fn); return -1; }

    char line[1024];
    int count = 0, ln = 0, first = 1;

    while (fgets(line, sizeof(line), fp)) {
        ln++;
        if (line[0] == '\r' || line[0] == '\n') continue;
        if (first) { first = 0; continue; }
        if (count >= maxW) break;

        char f[5][FLEN];
        memset(f, 0, sizeof(f));
        int nf = parseCSVLine(line, f, 5);
        if (nf < 5) continue;

        Ward *w = &wards[count];
        strncpy(w->wardName, f[0], FLEN - 1);
        strncpy(w->wardType, f[1], FLEN - 1);
        w->totalBeds    = atoi(f[2]);
        w->occupiedBeds = atoi(f[3]);
        w->availableBeds= atoi(f[4]);
        count++;
    }
    fclose(fp);
    printf("[INFO] Read %d ward(s) from '%s'\n", count, fn);
    return count;
}

/* ============================================================
 *  CSV WRITERS
 * ============================================================ */

static int writeResults(const char *fn, const Patient *pts, int n)
{
    FILE *fp = fopen(fn, "w");
    if (!fp) { fprintf(stderr, "[ERROR] Cannot open %s\n", fn); return 0; }

    /* Header */
    fprintf(fp, "PatientID,PatientName,Age,Gender,Ward,BedNumber,DaysAdmitted,"
                "Temperature,HeartRate,RespiratoryRate,BloodPressure,SpO2,"
                "BloodSugar,PainLevel,ConsciousnessStatus,MobilityStatus,"
                "Symptoms,LikelyCondition,RawClinicalScore,HSI,PreviousHSI,"
                "PreviousAssessments,EmergencyCategory,AssignedDoctor,"
                "WardRecommendation,PatientStatus,RecoveryTrend\n");

    int i;
    for (i = 0; i < n; i++) {
        const Patient *p = &pts[i];
        fprintf(fp,
            "%s,\"%s\",%d,%s,%s,%s,%d,"
            "%.1f,%d,%d,%d/%d,%d,"
            "%d,%d,%s,%s,"
            "\"%s\",%s,%.2f,%.2f,%.2f,"
            "%d,%s,\"%s\","
            "\"%s\",%s,%s\n",
            p->id, p->name, p->age, p->gender, p->ward, p->bedNumber, p->daysAdmitted,
            p->temperature, p->heartRate, p->respiratoryRate,
            p->systolicBP, p->diastolicBP, p->spo2,
            p->bloodSugar, p->painLevel, p->consciousnessStatus, p->mobilityStatus,
            p->symptoms, p->likelyCondition,
            p->rawClinicalScore, p->hsi, p->previousHSI,
            p->previousAssessments, p->emergencyCategory, p->assignedDoctor,
            p->wardRecommendation, p->patientStatus, p->recoveryTrend);
    }
    fclose(fp);
    printf("[INFO] Results saved to '%s'\n", fn);
    return 1;
}

static int writeDoctors(const char *fn, const Doctor *docs, int n)
{
    FILE *fp = fopen(fn, "w");
    if (!fp) { fprintf(stderr, "[ERROR] Cannot open %s for write\n", fn); return 0; }
    fprintf(fp, "DoctorID,DoctorName,Specialization,ExperienceYears,"
                "CurrentPatients,MaximumPatients,Availability\n");
    int i;
    for (i = 0; i < n; i++) {
        fprintf(fp, "%s,\"%s\",%s,%d,%d,%d,%s\n",
            docs[i].id, docs[i].name, docs[i].specialization,
            docs[i].experienceYears, docs[i].currentPatients,
            docs[i].maximumPatients, docs[i].availability);
    }
    fclose(fp);
    printf("[INFO] Updated doctor workloads in '%s'\n", fn);
    return 1;
}

static int writeWards(const char *fn, const Ward *wards, int n)
{
    FILE *fp = fopen(fn, "w");
    if (!fp) { fprintf(stderr, "[ERROR] Cannot open %s for write\n", fn); return 0; }
    fprintf(fp, "WardName,WardType,TotalBeds,OccupiedBeds,AvailableBeds\n");
    int i;
    for (i = 0; i < n; i++) {
        fprintf(fp, "%s,%s,%d,%d,%d\n",
            wards[i].wardName, wards[i].wardType,
            wards[i].totalBeds, wards[i].occupiedBeds, wards[i].availableBeds);
    }
    fclose(fp);
    printf("[INFO] Updated ward occupancy in '%s'\n", fn);
    return 1;
}

/* Append one row per patient to history.csv but avoid duplicates */
static void appendHistory(const char *fn, const Patient *pts, int n)
{
    /* Read existing history to find highest AssessmentNumber per patient */
    FILE *rf = fopen(fn, "r");
    int needHeader = 1;
    char line[1024];
    int maxAssess[MAX_PATIENTS] = {0};
    
    if (rf) {
        needHeader = 0;
        /* skip header */
        fgets(line, sizeof(line), rf);
        while (fgets(line, sizeof(line), rf)) {
            char pid[64];
            int an = 0;
            if (sscanf(line, "%63[^,],%d", pid, &an) == 2) {
                /* Find index in pts */
                for(int i=0; i<n; i++) {
                    if (strcmp(pts[i].id, pid) == 0) {
                        if (an > maxAssess[i]) maxAssess[i] = an;
                        break;
                    }
                }
            }
        }
        fclose(rf);
    }

    FILE *fp = fopen(fn, "a");
    if (!fp) { fprintf(stderr, "[WARN] Cannot open history file %s\n", fn); return; }

    if (needHeader)
        fprintf(fp, "PatientID,AssessmentNumber,DaysAdmitted,"
                    "RawClinicalScore,HSI,AssignedDoctor,Ward,Category\n");

    int appended = 0;
    for (int i = 0; i < n; i++) {
        const Patient *p = &pts[i];
        int newAssess = p->previousAssessments + 1;
        /* Only append if this assessment number is new */
        if (newAssess > maxAssess[i]) {
            fprintf(fp, "%s,%d,%d,%.2f,%.2f,\"%s\",%s,%s\n",
                p->id,
                newAssess,
                p->daysAdmitted,
                p->rawClinicalScore,
                p->hsi,
                p->assignedDoctor,
                p->ward,
                p->emergencyCategory);
            appended++;
        }
    }
    fclose(fp);
    printf("[INFO] %d new assessment records appended to '%s'\n", appended, fn);
}

/* ============================================================
 *  CONSOLE SUMMARY
 * ============================================================ */
static void printSummary(const Patient *pts, int n)
{
    int crit = 0, mod = 0, stab = 0, i;
    for (i = 0; i < n; i++) {
        if      (strcmp(pts[i].emergencyCategory, "Critical")  == 0) crit++;
        else if (strcmp(pts[i].emergencyCategory, "Moderate")  == 0) mod++;
        else                                                           stab++;
    }

    printf("\n" C_CYAN "+----------------------------------------------------------+" C_RESET "\n");
    printf(C_CYAN "|" C_BOLD "   INPATIENT MONITORING — ASSESSMENT SUMMARY              " C_RESET C_CYAN "|" C_RESET "\n");
    printf(C_CYAN "+----------------------------------------------------------+" C_RESET "\n");
    printf(C_CYAN "|" C_RESET "  Total Patients : %-38d " C_CYAN "|" C_RESET "\n", n);
    printf(C_CYAN "|" C_RESET "  Critical       : " C_RED "%-38d" C_RESET C_CYAN " |" C_RESET "\n", crit);
    printf(C_CYAN "|" C_RESET "  Moderate       : " C_YELLOW "%-38d" C_RESET C_CYAN " |" C_RESET "\n", mod);
    printf(C_CYAN "|" C_RESET "  Stable         : " C_GREEN "%-38d" C_RESET C_CYAN " |" C_RESET "\n", stab);
    printf(C_CYAN "+----------------------------------------------------------+" C_RESET "\n");
    printf(C_CYAN "|" C_BOLD "  ID     Name               HSI    Cat       Trend      " C_RESET C_CYAN "|" C_RESET "\n");
    printf(C_CYAN "+----------------------------------------------------------+" C_RESET "\n");

    for (i = 0; i < n; i++) {
        const Patient *p = &pts[i];
        const char *color = C_GREEN;
        if      (strcmp(p->emergencyCategory, "Critical") == 0) color = C_RED;
        else if (strcmp(p->emergencyCategory, "Moderate") == 0) color = C_YELLOW;

        printf(C_CYAN "|" C_RESET "  %-6s %-18s %5.1f  %s%-9s" C_RESET "  %-9s " C_CYAN "|" C_RESET "\n",
               p->id, p->name, p->hsi,
               color, p->emergencyCategory,
               p->recoveryTrend);
    }
    printf(C_CYAN "+----------------------------------------------------------+" C_RESET "\n\n");
}

/* ============================================================
 *  PATIENT STATUS DERIVATION
 * ============================================================ */
static void derivePatientStatus(Patient *p)
{
    if (strcmp(p->emergencyCategory, "Critical") == 0) {
        strcpy(p->patientStatus, "Critical");
    } else if (strcmp(p->emergencyCategory, "Moderate") == 0) {
        if (strcmp(p->recoveryTrend, "Improving") == 0)
            strcpy(p->patientStatus, "Recovering");
        else
            strcpy(p->patientStatus, "Observation");
    } else {
        if (strcmp(p->recoveryTrend, "Improving") == 0)
            strcpy(p->patientStatus, "Recovering");
        else
            strcpy(p->patientStatus, "Stable");
    }
}

/* ============================================================
 *  MAIN
 * ============================================================ */
int main(int argc, char *argv[])
{
    const char *patFile  = (argc > 1) ? argv[1] : "patients.csv";
    const char *resFile  = (argc > 2) ? argv[2] : "results.csv";
    const char *docFile  = (argc > 3) ? argv[3] : "doctors.csv";
    const char *wardFile = (argc > 4) ? argv[4] : "wards.csv";
    const char *histFile = (argc > 5) ? argv[5] : "history.csv";

    printf("\n=== Smart Inpatient Monitoring & Clinical Decision Support ===\n\n");

    /* ── Load all datasets ──────────────────────────────── */
    static Patient patients[MAX_PATIENTS];
    static Doctor  doctors[MAX_DOCTORS];
    static Ward    wards[MAX_WARDS];
    memset(patients, 0, sizeof(patients));
    memset(doctors,  0, sizeof(doctors));
    memset(wards,    0, sizeof(wards));

    int nPat = readPatients(patFile,  patients, MAX_PATIENTS);
    int nDoc = readDoctors(docFile,   doctors,  MAX_DOCTORS);
    int nWard= readWards(wardFile,    wards,    MAX_WARDS);

    if (nPat <= 0) {
        fprintf(stderr, "[ERROR] No valid patients found.\n");
        return EXIT_FAILURE;
    }

    /* ── CRITICAL FIX: Reset doctor and ward counts before assignment ── */
    int i;
    for (i = 0; i < nDoc; i++) {
        doctors[i].currentPatients = 0;
    }
    for (i = 0; i < nWard; i++) {
        wards[i].occupiedBeds = 0;
        wards[i].availableBeds = wards[i].totalBeds;
    }

    /* ── Pass 1: compute raw scores + category scores ─── */
    printf("\n[PASS 1] Computing clinical scores...\n");
    for (i = 0; i < nPat; i++) {
        Patient *p = &patients[i];
        int cardiac, resp, neuro, infect, trauma, general;

        p->rawClinicalScore = computeRawScore(p,
                                               &cardiac, &resp, &neuro,
                                               &infect, &trauma, &general);

        /* Infer likely condition from dominant category */
        inferCondition(p, cardiac, resp, neuro, infect, trauma,
                        p->likelyCondition);

        printf("  [%s] %-18s Raw=%.1f  Condition: %s\n",
               p->id, p->name, p->rawClinicalScore, p->likelyCondition);
    }

    /* ── Pass 2: normalize HSI ──────────────────────────── */
    printf("\n[PASS 2] Normalizing HSI across all patients...\n");
    normalizeHSI(patients, nPat);

    /* ── Pass 3: classify + assign + recommend + trend ─── */
    printf("\n[PASS 3] Classifying, assigning, recommending...\n");
    for (i = 0; i < nPat; i++) {
        Patient *p = &patients[i];

        /* Emergency category from HSI */
        classifyHSI(p->hsi, p->emergencyCategory);

        /* Recovery trend from previous HSI */
        computeRecoveryTrend(p->hsi, p->previousHSI,
                              p->previousAssessments, p->recoveryTrend);

        /* Doctor assignment (updates doctor workload) */
        if (strlen(p->assignedDoctor) == 0 || strcmp(p->assignedDoctor, "Unassigned") == 0) {
            strcpy(p->assignedDoctor, "Unassigned");
        } else {
            for (int d = 0; d < nDoc; d++) {
                if (strcmp(doctors[d].name, p->assignedDoctor) == 0) {
                    doctors[d].currentPatients++;
                    break;
                }
            }
        }

        /* Ward recommendation (updates ward bed count) */
        recommendWard(p->hsi, p->ward, wards, nWard, p->wardRecommendation);

        /* Patient status */
        derivePatientStatus(p);

        /* Increment assessment count */
        p->previousAssessments++;

        const char *color = C_GREEN;
        if      (strcmp(p->emergencyCategory, "Critical") == 0) color = C_RED;
        else if (strcmp(p->emergencyCategory, "Moderate") == 0) color = C_YELLOW;
        
        if (i == 0) {
            printf("\n%s+-------------------------------------------------------------------------------------------------------------------+%s\n", C_CYAN, C_RESET);
            printf("%s| %s %-6s | %-18s | %-5s | %-10s | %-20s | %-25s |%s\n", C_CYAN, C_BOLD, "ID", "Patient Name", "HSI", "Category", "Doctor", "Ward Action", C_RESET);
            printf("%s+-------------------------------------------------------------------------------------------------------------------+%s\n", C_CYAN, C_RESET);
        }

        printf("%s|%s %-6s | %-18.18s | %5.1f | %s%-10s%s | %-20.20s | %-25.25s %s|%s\n",
               C_CYAN, C_RESET, p->id, p->name, p->hsi, color, p->emergencyCategory, C_RESET,
               p->assignedDoctor, p->wardRecommendation, C_CYAN, C_RESET);
        
        if (i == nPat - 1) {
            printf("%s+-------------------------------------------------------------------------------------------------------------------+%s\n", C_CYAN, C_RESET);
        }
    }

    /* ── Write all outputs ──────────────────────────────── */
    printf("\n[OUTPUT] Writing results...\n");
    if (!writeResults(resFile, patients, nPat)) return EXIT_FAILURE;
    
    /* CRITICAL FIX: Overwrite patients.csv with results so PreviousAssessments increments properly */
    writeResults(patFile, patients, nPat);

    writeDoctors(docFile,  doctors,  nDoc);
    writeWards(wardFile,   wards,    nWard);
    appendHistory(histFile, patients, nPat);

    printSummary(patients, nPat);

    printf("[DONE] Open dashboard/index.html or run server.py\n\n");
    return EXIT_SUCCESS;
}