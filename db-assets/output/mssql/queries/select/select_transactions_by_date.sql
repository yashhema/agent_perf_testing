-- Select transactions by date range
SELECT transaction_id, account_id, amount, transaction_date, description, status
FROM bank_transactions
WHERE transaction_date BETWEEN ? AND ?
AND account_id = ?