-- Update customer loyalty points
UPDATE customers
SET loyalty_points = ?, loyalty_tier = ?, updated_at = CURRENT_TIMESTAMP
WHERE customer_id = ?