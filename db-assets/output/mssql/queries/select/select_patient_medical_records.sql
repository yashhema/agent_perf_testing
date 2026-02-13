-- Select patient with medical records
SELECT p.patient_id, p.first_name, p.last_name, p.date_of_birth,
       m.record_id, m.encounter_type, m.admission_date, m.status
FROM patients p
JOIN medical_records m ON p.patient_id = m.patient_id
WHERE p.patient_id = ?
ORDER BY m.admission_date DESC