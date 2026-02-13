-- Delete cart item
DELETE FROM cart_items
WHERE cart_id = ? AND product_id = ?