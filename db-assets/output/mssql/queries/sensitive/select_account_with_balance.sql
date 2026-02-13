-- Select account with sensitive info (SENSITIVE)
SELECT a.account_id, a.account_number, a.routing_number,
       a.current_balance, a.available_balance
FROM accounts a
WHERE a.account_id = ?