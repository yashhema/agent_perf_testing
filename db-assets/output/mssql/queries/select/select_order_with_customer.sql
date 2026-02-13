-- Select order with customer details
SELECT o.order_id, o.order_number, o.order_date, o.status, o.grand_total,
       c.first_name, c.last_name, c.email
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_id = ?