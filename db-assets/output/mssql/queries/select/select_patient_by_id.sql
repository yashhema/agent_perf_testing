-- Select patient by ID
SELECT patient_id, mrn, first_name, last_name, date_of_birth, ssn, medicare_id
FROM patients
WHERE patient_id = ?