    """
generate_data.py — Regenerates ALL base CSV files from scratch.
Creates 200 patients with realistic, severity-based vitals,
25 doctors (all fully available), 9 wards with plenty of beds,
and a rich history.csv showing day-by-day HSI progression per patient.
"""
import csv, random, os, shutil

random.seed(2026)

BASE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(BASE, 'dashboard')
os.makedirs(DASH, exist_ok=True)

PAT_CSV  = os.path.join(BASE, 'patients.csv')
DOC_CSV  = os.path.join(BASE, 'doctors.csv')
WARD_CSV = os.path.join(BASE, 'wards.csv')
HIST_CSV = os.path.join(BASE, 'history.csv')

def write_csv(path, fields, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f'[WROTE] {path} ({len(rows)} rows)')

# ── WARDS (430 total beds — always plenty available) ──────────────
WARD_SPECS = [
    ('ICU Central',       'ICU',         35),
    ('ICU West',          'ICU',         25),
    ('HDU Alpha',         'HDU',         40),
    ('HDU Beta',          'HDU',         40),
    ('Observation Ward 1','Observation', 50),
    ('Observation Ward 2','Observation', 50),
    ('General Ward A',    'General',     60),
    ('General Ward B',    'General',     60),
    ('General Ward C',    'General',     70),
]
wards = [{'WardName':w[0],'WardType':w[1],'TotalBeds':w[2],'OccupiedBeds':0,'AvailableBeds':w[2]}
         for w in WARD_SPECS]
write_csv(WARD_CSV, ['WardName','WardType','TotalBeds','OccupiedBeds','AvailableBeds'], wards)

# ── DOCTORS (25, all starting at 0 patients, high max capacity) ───
DOC_SPECS = [
    ('D001','Dr. Rajiv Sharma',    'Cardiologist',       18, 30),
    ('D002','Dr. Meena Pillai',    'Pulmonologist',      12, 30),
    ('D003','Dr. Suresh Reddy',    'Neurologist',        15, 30),
    ('D004','Dr. Anita Iyer',      'Infectious Disease', 10, 30),
    ('D005','Dr. Prakash Verma',   'Emergency Medicine',  8, 30),
    ('D006','Dr. Kavita Gupta',    'General Physician',  14, 35),
    ('D007','Dr. Arun Krishnan',   'Cardiologist',       22, 30),
    ('D008','Dr. Sunita Das',      'Pulmonologist',       9, 30),
    ('D009','Dr. Harish Nair',     'Neurologist',        16, 30),
    ('D010','Dr. Priya Menon',     'General Physician',  11, 35),
    ('D011','Dr. Ramesh Rao',      'Cardiologist',       20, 30),
    ('D012','Dr. Deepa Singh',     'Pulmonologist',      13, 30),
    ('D013','Dr. Vikram Joshi',    'Neurologist',        19, 30),
    ('D014','Dr. Lakshmi Mehta',   'Infectious Disease', 11, 30),
    ('D015','Dr. Ananya Patel',    'Emergency Medicine', 14, 30),
    ('D016','Dr. Dinesh Kumar',    'Cardiologist',        7, 30),
    ('D017','Dr. Sanjay Choudhury','Pulmonologist',      10, 30),
    ('D018','Dr. Nalini Bose',     'Neurologist',        12, 30),
    ('D019','Dr. Pooja Sengupta',  'Infectious Disease',  9, 30),
    ('D020','Dr. Naresh Banerjee', 'Emergency Medicine', 17, 30),
    ('D021','Dr. Rekha Verma',     'General Physician',  16, 35),
    ('D022','Dr. Bhaskar Pillai',  'Cardiologist',       24, 30),
    ('D023','Dr. Sarala Reddy',    'Pulmonologist',      18, 30),
    ('D024','Dr. Karan Iyer',      'Neurologist',        13, 30),
    ('D025','Dr. Simran Sharma',   'General Physician',  20, 35),
]
doctors = [{'DoctorID':d[0],'DoctorName':d[1],'Specialization':d[2],
            'ExperienceYears':d[3],'CurrentPatients':0,'MaximumPatients':d[4],'Availability':'Available'}
           for d in DOC_SPECS]
write_csv(DOC_CSV, ['DoctorID','DoctorName','Specialization','ExperienceYears',
                    'CurrentPatients','MaximumPatients','Availability'], doctors)

# ── Name pools ────────────────────────────────────────────────────
FIRST = ['Rajiv','Meena','Suresh','Anita','Prakash','Kavita','Arun','Sunita','Harish','Priya',
         'Ramesh','Deepa','Vikram','Lakshmi','Ananya','Dinesh','Sanjay','Nalini','Pooja','Naresh',
         'Rekha','Bhaskar','Sarala','Karan','Simran','Rahul','Aditi','Mohan','Radha','Tarun',
         'Kavya','Arjun','Divya','Ravi','Amit','Sneha','Rohit','Isha','Vijay','Geeta']
LAST  = ['Sharma','Pillai','Reddy','Iyer','Verma','Gupta','Krishnan','Das','Nair','Menon',
         'Rao','Singh','Joshi','Mehta','Patel','Kumar','Choudhury','Bose','Sengupta','Banerjee',
         'Desai','Shah','Pandey','Mishra','Tiwari','Chauhan','Kapoor','Malhotra','Agarwal']

# ── Condition profiles (condition, symptom_sets, hsi_range) ──────
SYMS = {
    'cardiac': ['Chest Pain','Palpitations','Left Arm Pain','Irregular Heartbeat','Sweating'],
    'resp':    ['Breathlessness','Wheezing','Persistent Cough','Rapid Breathing','Low Oxygen'],
    'neuro':   ['Headache','Dizziness','Confusion','Slurred Speech','Seizures','Unconsciousness'],
    'infect':  ['Fever','Chills','Vomiting','Diarrhea'],
    'trauma':  ['Heavy Bleeding','Burns','Fractures','Head Injury'],
    'general': ['Fatigue','Dehydration','Weakness'],
}
PROFILES = [
    ('Myocardial Infarction',  ['cardiac','general'],        (55,100)),
    ('Arrhythmia',             ['cardiac'],                  (35, 80)),
    ('Pneumonia',              ['resp','infect'],             (40, 90)),
    ('Asthma Exacerbation',    ['resp'],                     (30, 75)),
    ('Stroke',                 ['neuro'],                    (60,100)),
    ('Seizure Disorder',       ['neuro'],                    (45, 88)),
    ('General Infection',      ['infect','general'],         (18, 60)),
    ('Sepsis',                 ['infect','neuro'],           (65,100)),
    ('Gastroenteritis',        ['infect'],                   (12, 45)),
    ('Head Trauma',            ['trauma','neuro'],           (50, 95)),
    ('Burn Injury',            ['trauma'],                   (35, 82)),
    ('Fracture',               ['trauma','general'],         (25, 65)),
    ('Dehydration',            ['general'],                  (10, 38)),
]
COND_SPEC = {
    'Myocardial Infarction':'Cardiologist','Arrhythmia':'Cardiologist',
    'Pneumonia':'Pulmonologist','Asthma Exacerbation':'Pulmonologist',
    'Stroke':'Neurologist','Seizure Disorder':'Neurologist',
    'General Infection':'Infectious Disease','Sepsis':'Infectious Disease','Gastroenteritis':'Infectious Disease',
    'Head Trauma':'Emergency Medicine','Burn Injury':'Emergency Medicine','Fracture':'Emergency Medicine',
    'Dehydration':'General Physician',
}

def cat(hsi): return 'Critical' if hsi>=70 else 'Moderate' if hsi>=40 else 'Stable'
def ward_for_hsi(hsi):
    if hsi>=70:  return random.choice(['ICU Central','ICU West'])
    elif hsi>=60:return random.choice(['HDU Alpha','HDU Beta'])
    elif hsi>=40:return random.choice(['Observation Ward 1','Observation Ward 2'])
    else:        return random.choice(['General Ward A','General Ward B','General Ward C'])
def doc_for_cond(cond):
    spec = COND_SPEC.get(cond,'General Physician')
    pool = [d['DoctorName'] for d in doctors if d['Specialization']==spec]
    return random.choice(pool) if pool else doctors[5]['DoctorName']

# ── PATIENT + HISTORY GENERATION ─────────────────────────────────
PAT_FIELDS = ['PatientID','PatientName','Age','Gender','Ward','BedNumber','DaysAdmitted',
              'Temperature','HeartRate','RespiratoryRate','BloodPressure','SpO2',
              'BloodSugar','PainLevel','ConsciousnessStatus','MobilityStatus',
              'Symptoms','LikelyCondition','RawClinicalScore','HSI','PreviousHSI',
              'PreviousAssessments','EmergencyCategory','AssignedDoctor',
              'WardRecommendation','PatientStatus','RecoveryTrend']
HIST_FIELDS = ['PatientID','AssessmentNumber','DaysAdmitted','RawClinicalScore',
               'HSI','AssignedDoctor','Ward','Category']

patients = []
history_rows = []

for i in range(1, 201):
    pid = f'P{i:03d}'
    profile = random.choice(PROFILES)
    cond, sym_cats, (hmin, hmax) = profile

    name = f'{random.choice(FIRST)} {random.choice(LAST)}'
    age  = random.randint(22, 82)
    gend = random.choice(['Male','Female'])
    days = random.randint(4, 20)

    # Trend: 55% improving, 25% stable, 20% worsening
    trend = random.choices(['improving','stable','worsening'], weights=[55,25,20])[0]

    # Starting HSI (at admission)
    start_hsi = random.uniform(hmin, hmax)

    # Generate assessment days spread across admission period
    n_assessments = min(7, max(3, days // 2))
    if days >= n_assessments:
        raw_days = sorted(random.sample(range(1, days+1), n_assessments-1))
        assess_days = raw_days + [days]
    else:
        assess_days = list(range(1, days+1))
    assess_days = sorted(set(assess_days))

    hsi_path = []
    cur_hsi  = start_hsi

    for j, aday in enumerate(assess_days):
        if j > 0:
            if trend == 'improving':
                delta = random.uniform(5, 14)
                cur_hsi = max(8, cur_hsi - delta)
            elif trend == 'worsening':
                delta = random.uniform(4, 11)
                cur_hsi = min(100, cur_hsi + delta)
            else:
                delta = random.uniform(-5, 5)
                cur_hsi = max(8, min(100, cur_hsi + delta))

        raw = cur_hsi * random.uniform(1.05, 1.15)
        hsi_path.append((aday, cur_hsi, raw))

        history_rows.append({
            'PatientID': pid,
            'AssessmentNumber': j + 1,
            'DaysAdmitted': aday,
            'RawClinicalScore': f'{raw:.2f}',
            'HSI': f'{cur_hsi:.2f}',
            'AssignedDoctor': 'Unassigned',
            'Ward': ward_for_hsi(cur_hsi),
            'Category': cat(cur_hsi),
        })

    # Final state
    n_hist      = len(assess_days)
    final_hsi   = hsi_path[-1][1]
    prev_hsi    = hsi_path[-2][1] if len(hsi_path) >= 2 else start_hsi

    # Vitals consistent with final_hsi severity
    sev = final_hsi / 100.0
    temp  = round(36.1 + sev * 4.2 + random.uniform(-0.3, 0.3), 1)
    hr    = max(55, min(148, int(62 + sev * 75 + random.uniform(-10, 10))))
    rr    = max(12, min(38, int(12 + sev * 20 + random.uniform(-2, 2))))
    spo2  = max(82, min(100, int(100 - sev * 17 + random.uniform(-2, 2))))
    bs    = max(68, min(290, int(88 + sev * 150 + random.uniform(-20, 20))))
    sbp   = max(88, min(185, int(108 + sev * 65 + random.uniform(-10, 10))))
    dbp   = max(58, min(115, int(64 + sev * 42 + random.uniform(-5, 5))))
    pain  = max(0, min(10, int(sev * 10 + random.uniform(-1, 1))))

    if sev > 0.7:
        cons = random.choices(['Alert','Confused','Unresponsive'], weights=[20,55,25])[0]
        mob  = random.choices(['Independent','Assisted','Bedridden'],  weights=[5,35,60])[0]
    elif sev > 0.4:
        cons = random.choices(['Alert','Confused'], weights=[65,35])[0]
        mob  = random.choices(['Independent','Assisted','Bedridden'],  weights=[25,55,20])[0]
    else:
        cons = 'Alert'
        mob  = random.choices(['Independent','Assisted'], weights=[75,25])[0]

    syms = []
    for sc in sym_cats:
        pool = SYMS[sc]
        syms.extend(random.sample(pool, min(len(pool), random.randint(1,3))))
    syms = list(set(syms))

    patients.append({
        'PatientID':pid, 'PatientName':name, 'Age':age, 'Gender':gend,
        'Ward':ward_for_hsi(final_hsi), 'BedNumber':random.randint(1,50), 'DaysAdmitted':days,
        'Temperature':temp, 'HeartRate':hr, 'RespiratoryRate':rr,
        'BloodPressure':f'{sbp}/{dbp}', 'SpO2':spo2, 'BloodSugar':bs,
        'PainLevel':pain, 'ConsciousnessStatus':cons, 'MobilityStatus':mob,
        'Symptoms':','.join(syms), 'LikelyCondition':'', 'RawClinicalScore':'',
        'HSI':'', 'PreviousHSI':round(prev_hsi,1), 'PreviousAssessments':n_hist,
        'EmergencyCategory':'', 'AssignedDoctor':'', 'WardRecommendation':'',
        'PatientStatus':'', 'RecoveryTrend':'',
    })

write_csv(PAT_CSV,  PAT_FIELDS,  patients)
write_csv(HIST_CSV, HIST_FIELDS, history_rows)

# ── Copy everything to dashboard/ so server can serve them ────────
for src in [PAT_CSV, DOC_CSV, WARD_CSV, HIST_CSV]:
    dst = os.path.join(DASH, os.path.basename(src))
    shutil.copy2(src, dst)

print(f'\n[OK] Generated {len(patients)} patients, {len(doctors)} doctors, '
      f'{sum(w["TotalBeds"] for w in wards)} beds across {len(wards)} wards, '
      f'{len(history_rows)} history entries.')
print('[OK] All files copied to dashboard/')
