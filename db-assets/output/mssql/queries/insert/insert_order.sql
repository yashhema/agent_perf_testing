-- Insert new order
INSERT INTO orders (customer_id, order_number, order_date, status, subtotal, tax_total, grand_total)
VALUES (?, ?, ?, ?, ?, ?, ?)