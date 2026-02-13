-- Update account balance
UPDATE accounts
SET current_balance = ?, available_balance = ?, updated_at = CURRENT_TIMESTAMP
WHERE account_id = ?