-- Indexes for POSTGRESQL

-- Index: ix_sessions_user_id on sessions
CREATE INDEX ix_sessions_user_id ON sessions (user_id);

-- Index: ix_sessions_token on sessions
CREATE INDEX ix_sessions_token ON sessions (session_token);

-- Index: ix_login_attempts_user_id on login_attempts
CREATE INDEX ix_login_attempts_user_id ON login_attempts (user_id);

-- Index: ix_login_attempts_ip on login_attempts
CREATE INDEX ix_login_attempts_ip ON login_attempts (ip_address);

-- Index: ix_audit_logs_entity on audit_logs
CREATE INDEX ix_audit_logs_entity ON audit_logs (entity_type, entity_id);

-- Index: ix_audit_logs_performed_at on audit_logs
CREATE INDEX ix_audit_logs_performed_at ON audit_logs (performed_at);

-- Index: ix_audit_logs_user_id on audit_logs
CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id);

-- Index: ix_data_changes_table_record on data_changes
CREATE INDEX ix_data_changes_table_record ON data_changes (table_name, record_id);

-- Index: ix_access_logs_resource on access_logs
CREATE INDEX ix_access_logs_resource ON access_logs (resource_type, resource_id);

-- Index: ix_access_logs_user_id on access_logs
CREATE INDEX ix_access_logs_user_id ON access_logs (user_id);

-- Index: ix_system_events_severity on system_events
CREATE INDEX ix_system_events_severity ON system_events (severity);

-- Index: ix_system_events_type on system_events
CREATE INDEX ix_system_events_type ON system_events (event_type);

-- Index: ix_error_logs_type on error_logs
CREATE INDEX ix_error_logs_type ON error_logs (error_type);

-- Index: ix_error_logs_occurred_at on error_logs
CREATE INDEX ix_error_logs_occurred_at ON error_logs (occurred_at);

-- Index: ix_notifications_type on notifications
CREATE INDEX ix_notifications_type ON notifications (notification_type);

-- Index: ix_notifications_user_id on notifications
CREATE INDEX ix_notifications_user_id ON notifications (user_id);

-- Index: ix_products_category_id on products
CREATE INDEX ix_products_category_id ON products (category_id);

-- Index: ix_products_brand_id on products
CREATE INDEX ix_products_brand_id ON products (brand_id);

-- Index: ix_product_reviews_product_id on product_reviews
CREATE INDEX ix_product_reviews_product_id ON product_reviews (product_id);

-- Index: ix_orders_order_date on orders
CREATE INDEX ix_orders_order_date ON orders (order_date);

-- Index: ix_orders_customer_id on orders
CREATE INDEX ix_orders_customer_id ON orders (customer_id);

-- Index: ix_orders_status on orders
CREATE INDEX ix_orders_status ON orders (status);

-- Index: ix_transactions_order_id on transactions
CREATE INDEX ix_transactions_order_id ON transactions (order_id);

-- Index: ix_page_views_viewed_at on page_views
CREATE INDEX ix_page_views_viewed_at ON page_views (viewed_at);

-- Index: ix_page_views_session_id on page_views
CREATE INDEX ix_page_views_session_id ON page_views (session_id);

-- Index: ix_accounts_account_number on accounts
CREATE INDEX ix_accounts_account_number ON accounts (account_number);

-- Index: ix_bank_transactions_date on bank_transactions
CREATE INDEX ix_bank_transactions_date ON bank_transactions (transaction_date);

-- Index: ix_bank_transactions_account_id on bank_transactions
CREATE INDEX ix_bank_transactions_account_id ON bank_transactions (account_id);

-- Index: ix_credit_cards_last_four on credit_cards
CREATE INDEX ix_credit_cards_last_four ON credit_cards (last_four);

-- Index: ix_card_transactions_card_id on card_transactions
CREATE INDEX ix_card_transactions_card_id ON card_transactions (card_id);

-- Index: ix_patients_name on patients
CREATE INDEX ix_patients_name ON patients (last_name, first_name);

-- Index: ix_patients_dob on patients
CREATE INDEX ix_patients_dob ON patients (date_of_birth);

-- Index: ix_medical_records_patient_id on medical_records
CREATE INDEX ix_medical_records_patient_id ON medical_records (patient_id);

-- Index: ix_medical_records_date on medical_records
CREATE INDEX ix_medical_records_date ON medical_records (admission_date);

-- Index: ix_appointments_provider_id on appointments
CREATE INDEX ix_appointments_provider_id ON appointments (provider_id);

-- Index: ix_appointments_patient_id on appointments
CREATE INDEX ix_appointments_patient_id ON appointments (patient_id);

-- Index: ix_appointments_date on appointments
CREATE INDEX ix_appointments_date ON appointments (scheduled_date);

-- Index: ix_claims_status on claims
CREATE INDEX ix_claims_status ON claims (status);

-- Index: ix_claims_patient_id on claims
CREATE INDEX ix_claims_patient_id ON claims (patient_id);
