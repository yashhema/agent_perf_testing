-- Select account with recent transactions
SELECT a.account_id, a.account_number, a.current_balance,
       t.transaction_id, t.amount, t.transaction_date, t.description
FROM accounts a
JOIN bank_transactions t ON a.account_id = t.account_id
WHERE a.account_id = ?
ORDER BY t.transaction_date DESC