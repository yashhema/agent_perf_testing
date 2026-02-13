-- Update patient contact info
UPDATE patients
SET phone_home = ?, email = ?, updated_at = CURRENT_TIMESTAMP
WHERE patient_id = ?