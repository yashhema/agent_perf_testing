-- Account balance summary by type
SELECT at.type_name,
       COUNT(a.account_id) as account_count,
       SUM(a.current_balance) as total_balance,
       AVG(a.current_balance) as avg_balance
FROM accounts a
JOIN account_types at ON a.account_type_id = at.type_id
WHERE a.status = ?
GROUP BY at.type_name
ORDER BY total_balance DESC