-- Update order status
UPDATE orders
SET status = ?, updated_at = CURRENT_TIMESTAMP
WHERE order_id = ?