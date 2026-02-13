-- Select orders by date range
SELECT order_id, order_number, customer_id, order_date, status, grand_total
FROM orders
WHERE order_date BETWEEN ? AND ?
ORDER BY order_date DESC