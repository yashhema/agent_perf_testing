-- Select user security info (SENSITIVE)
SELECT user_id, username, email, password_hash,
       last_login_at, failed_login_count
FROM users
WHERE user_id = ?