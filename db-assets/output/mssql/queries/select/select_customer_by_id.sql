-- Select customer by ID
SELECT customer_id, email, first_name, last_name, phone, created_at
FROM customers
WHERE customer_id = ?