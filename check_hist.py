import csv
rows = list(csv.DictReader(open('history.csv')))
p1 = [r for r in rows if r['PatientID']=='P001']
print('P001 History:')
for r in p1:
    print(f"  Day {r['DaysAdmitted']} Assess#{r['AssessmentNumber']} HSI={r['HSI']} Cat={r['Category']}")
print(f"Total rows: {len(rows)}, Unique patients: {len(set(r['PatientID'] for r in rows))}")
