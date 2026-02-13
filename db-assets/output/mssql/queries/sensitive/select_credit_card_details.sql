-- Select credit card details (SENSITIVE)
SELECT card_id, card_number, cvv, expiry_month, expiry_year,
       cardholder_name, credit_limit, current_balance
FROM credit_cards
WHERE account_id = ?