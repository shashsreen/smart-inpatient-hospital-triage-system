import csv
d = list(csv.DictReader(open('doctors.csv')))
print('Doctor workloads:')
for r in d[:8]:
    print(f"  {r['DoctorName'][:20]:<22} Current={r['CurrentPatients']} Max={r['MaximumPatients']}")
w = list(csv.DictReader(open('wards.csv')))
print('Ward occupancy:')
for r in w:
    pct = int(r['OccupiedBeds']) / max(int(r['TotalBeds']),1) * 100
    print(f"  {r['WardName']:<25} {r['OccupiedBeds']}/{r['TotalBeds']} beds ({pct:.0f}%)")
