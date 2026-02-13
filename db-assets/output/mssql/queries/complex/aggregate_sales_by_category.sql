-- Aggregate sales by category
SELECT c.category_name,
       COUNT(DISTINCT o.order_id) as order_count,
       SUM(oi.quantity) as total_units,
       SUM(oi.line_total) as total_revenue
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN products p ON oi.product_id = p.product_id
JOIN categories c ON p.category_id = c.category_id
WHERE o.order_date BETWEEN ? AND ?
GROUP BY c.category_name
HAVING SUM(oi.line_total) > ?
ORDER BY total_revenue DESC