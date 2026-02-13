-- Select account by account number
SELECT account_id, account_number, routing_number, current_balance, status
FROM accounts
WHERE account_number = ?