-- Patient visit history with diagnoses
SELECT p.patient_id, p.first_name, p.last_name,
       m.encounter_type, m.admission_date,
       d.diagnosis_code, d.diagnosis_description
FROM patients p
JOIN medical_records m ON p.patient_id = m.patient_id
LEFT JOIN diagnoses d ON m.record_id = d.record_id
WHERE p.patient_id = ?
ORDER BY m.admission_date DESC