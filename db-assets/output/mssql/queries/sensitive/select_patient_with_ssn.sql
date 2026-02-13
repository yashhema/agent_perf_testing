-- Select patient with SSN (SENSITIVE)
SELECT patient_id, first_name, last_name, ssn, date_of_birth,
       medicare_id, address_line1, city, state, zip_code
FROM patients
WHERE patient_id = ?