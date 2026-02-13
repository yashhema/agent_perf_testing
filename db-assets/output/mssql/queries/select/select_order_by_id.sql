-- Select order by ID
SELECT order_id, order_number, customer_id, order_date, status, grand_total
FROM orders
WHERE order_id = ?