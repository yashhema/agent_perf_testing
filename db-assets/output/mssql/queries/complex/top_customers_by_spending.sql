-- Top customers by spending
SELECT c.customer_id, c.first_name, c.last_name, c.email,
       COUNT(o.order_id) as order_count,
       SUM(o.grand_total) as total_spent
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
WHERE o.order_date >= ?
GROUP BY c.customer_id, c.first_name, c.last_name, c.email
ORDER BY total_spent DESC