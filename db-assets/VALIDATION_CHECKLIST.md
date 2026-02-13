# Seed Data Validation Checklist

## Column Name Validation
- [x] Column names match exactly with database schema
- [x] Reserved keywords are properly bracketed (e.g., `[value]`, `[plan]`, `[key]`, `[order]`)
- [x] ID column naming matches (e.g., `id` vs `item_id` vs `table_item_id`)

## NOT NULL Constraint Validation
- [x] `attribute_code` in product_attributes - Added
- [x] `is_active` in product_reviews - Added
- [x] All required columns have values (not None when NOT NULL)

## Unique Constraint Validation
- [x] customer_preferences: unique (customer_id, preference_key) - uses `used_pairs` pattern
- [x] customer_segment_members: unique (customer_id, segment_id) - uses `used_pairs` pattern
- [x] customer_tag_assignments: unique (customer_id, tag_id) - uses `used_pairs` pattern
- [x] inventory: unique (product_id, variant_id, warehouse_code) - uses `used_pairs` pattern
- [x] product_attribute_values: unique (attribute_id, value_code) - uses `used_pairs` pattern
- [x] product_performance: unique (product_id, period_date) - uses `used_pairs` pattern
- [x] product_variant_attributes: unique (variant_id, attribute_id) - uses `used_pairs` pattern
- [x] customer_lifetime_value: unique (customer_id) - uses `used_customers` pattern

## IDENTITY_INSERT Validation
- [x] Tables with `*_id` first column get IDENTITY_INSERT ON/OFF
- [x] Tables with `id` first column get IDENTITY_INSERT ON/OFF

## Foreign Key Validation
- [x] All FK references use `_get_random_id()` from cached IDs
- [x] FK tables are generated before referencing tables

## Data Type Validation
- [x] Dates use `_random_date()` for DATE columns
- [x] Datetimes use `_random_datetime()` for DATETIME columns
- [x] Booleans use True/False (converted to 1/0 for SQL Server)
- [x] Decimals use `round(value, 2)` for currency

## Reserved Keywords Requiring Bracketing
- `[value]` - conversion_events, vital_readings
- `[plan]` - medical_records, progress_notes

## Banking Domain Unique Constraints (must use used_pairs pattern)
| Table | Unique Columns |
|-------|----------------|
| account_holders | (account_id, customer_id) |
| account_limits | (account_id, limit_type) |
| account_statements | (account_id, statement_date) |
| account_types | type_code |
| accounts | account_number |
| bank_transactions | reference_number |
| bank_user_sessions | session_token |
| bank_users | username |
| billing_codes | (code, code_type) |
| checking_accounts | account_id |
| claims | claim_number |
| compliance_cases | case_number |
| joint_accounts | account_id |
| loan_applications | application_number |
| loan_officers | employee_id |
| loan_schedules | (loan_id, payment_number) |
| loan_types | type_code |
| loans | loan_number |
| money_market_accounts | account_id |

## Healthcare Domain Unique Constraints (must use used_pairs pattern)
| Table | Unique Columns |
|-------|----------------|
| appointment_types | type_code |
| clinical_trials | trial_number |
| health_invoices | invoice_number |
| lab_orders | order_number |
| medical_records | encounter_number |
| pathology_reports | accession_number |
| patient_portal_users | patient_id, username |
| patient_preferences | (patient_id, preference_type) |
| patients | mrn |
| prescriptions | rx_number |

## Identity Column Patterns
- Most tables use `*_id` (e.g., customer_id, order_id)
- Some tables use just `id` (e.g., abandoned_carts, customer_lifetime_value, fulfillment_items)
- Generator checks for both patterns

## Common Column Fixes Applied
| Table | Issue | Fix |
|-------|-------|-----|
| abandoned_carts | Wrong column names | id, recovered_at, reminder_sent_at |
| cart_items | Wrong ID | item_id not cart_item_id |
| conversion_events | Reserved keyword | value (bracketed) |
| customer_lifetime_value | Wrong names | id, avg_order_value |
| customer_notes | Wrong names | created_by_user_id, is_internal |
| customer_preferences | Unique constraint | used_pairs pattern |
| customer_segment_members | Missing source | Added source column |
| fulfillment_items | Wrong ID | id not fulfillment_item_id |
| inventory | Wrong names | quantity_on_hand, quantity_reserved |
| invoice_items | Wrong name | line_total not total |
| invoices | Wrong name | grand_total not total |
| medical_records | Reserved keyword | plan (was treatment_plan) |
| order_discounts | Wrong names | coupon_id, discount_value |
| order_fulfillment | Wrong name | location not warehouse_code |
| order_items | Wrong name | line_total not total_price |
| order_notes | Wrong names | is_customer_visible not note_type |
| order_status_history | Wrong name | changed_at not created_at |
| page_views | Wrong name | referrer_url not referrer |
| payment_plan_installments | Wrong name | paid_date not paid_at |
| payment_plans | Wrong name | installment_count not installments |
| product_attribute_values | Wrong names | value_label, value_code |
| product_attributes | Missing column | Added attribute_code |
| product_bundle_items | Wrong ID | item_id not bundle_item_id |
| product_images | Wrong name | sort_order not position |
| product_performance | Multiple fixes | id, period_date, cart_adds |
| product_reviews | Missing column | Added is_active |
| product_variants | Wrong names | compare_at_price, weight, barcode |
| product_variant_attributes | Wrong ID/names | id, value_id, text_value |
| recommendation_clicks | Missing columns | session_id, converted_at |
| recommendations | Wrong names | customer_segment_id, source_product_id |
| return_items | Wrong ID | id not return_item_id |
| sales_daily | Multiple fixes | id, gross_sales, order_count |
| saved_for_later | Wrong names | id, cart_id not customer_id |
| search_queries | Wrong names | searched_at, clicked_product_id |
| shipment_items | Wrong ID | id not shipment_item_id |
| shopping_carts | Wrong columns | last_activity, abandoned_at |
| transactions | Wrong names | currency_code, gateway_transaction_id |
| wallets | Wrong name | currency_code not currency |

## Automated Validation Script
Run `python validate_schema.py` to check:
- Invalid columns (in seed but not in DB)
- Missing columns (in DB but not in seed) - optional warning only

## SQL Load Test
```bash
sqlcmd -S localhost -d agent_performance_measurement -E -i output\mssql\seed\seed_data.sql
```
Check for:
- Msg 207: Invalid column name
- Msg 515: Cannot insert NULL
- Msg 2627: Duplicate key violation
