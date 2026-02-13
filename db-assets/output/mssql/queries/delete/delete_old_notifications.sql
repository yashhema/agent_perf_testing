-- Delete old notifications
DELETE FROM notifications
WHERE created_at < ? AND is_read = TRUE