"""Healthcare domain models (60 tables).

Categories:
- Patients (12): patients, patient_contacts, patient_insurance, emergency_contacts, patient_allergies,
                 patient_medications, patient_immunizations, patient_consents, patient_documents,
                 patient_preferences, patient_portal_users, patient_communication_log
- Medical Records (18): medical_records, diagnoses, procedures, lab_results, lab_orders, prescriptions,
                        prescription_fills, vitals, vital_readings, clinical_notes, radiology_orders,
                        radiology_results, pathology_reports, surgical_history, family_history,
                        social_history, condition_history, progress_notes
- Appointments (10): appointments, appointment_types, providers, provider_schedules, rooms,
                     waiting_lists, appointment_reminders, no_shows, cancellations, telehealth_sessions
- Billing (12): claims, claim_items, claim_status_history, insurance_payments, patient_payments,
                billing_codes, charge_master, payment_plans_health, invoices_health, statements_health,
                collections, write_offs
- Clinical (8): treatment_plans, care_teams, care_team_members, referrals, clinical_trials,
                trial_participants, quality_measures, outcome_tracking
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Numeric, Date, Time,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, AuditMixin


# ============================================================================
# Patients (12 tables)
# ============================================================================

class Patient(Base, AuditMixin):
    """Patient demographics."""
    __tablename__ = 'patients'

    patient_id = Column(Integer, primary_key=True, autoincrement=True)
    mrn = Column(String(20), nullable=False, unique=True)  # Medical Record Number
    ssn = Column(String(11))
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    middle_name = Column(String(100))
    date_of_birth = Column(Date, nullable=False)
    gender = Column(String(10))
    race = Column(String(50))
    ethnicity = Column(String(50))
    preferred_language = Column(String(50), default='English')
    marital_status = Column(String(20))
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(50))
    zip_code = Column(String(20))
    country = Column(String(50), default='USA')
    phone_home = Column(String(20))
    phone_mobile = Column(String(20))
    phone_work = Column(String(20))
    email = Column(String(255))
    primary_care_provider_id = Column(Integer, ForeignKey('providers.provider_id'))
    preferred_pharmacy = Column(String(200))
    status = Column(String(20), default='ACTIVE')
    death_date = Column(Date)
    medicare_id = Column(String(20))

    # Relationships
    contacts = relationship("PatientContact", back_populates="patient")
    insurance = relationship("PatientInsurance", back_populates="patient")
    allergies = relationship("PatientAllergy", back_populates="patient")
    appointments = relationship("Appointment", back_populates="patient")
    medical_records = relationship("MedicalRecord", back_populates="patient")

    __table_args__ = (
        Index('ix_patients_name', 'last_name', 'first_name'),
        Index('ix_patients_dob', 'date_of_birth'),
    )


class PatientContact(Base, TimestampMixin):
    """Patient emergency and other contacts."""
    __tablename__ = 'patient_contacts'

    contact_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    contact_type = Column(String(20), nullable=False)  # EMERGENCY, GUARANTOR, NEXT_OF_KIN
    relation_type = Column(String(50))  # e.g., SPOUSE, PARENT, CHILD, SIBLING
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(20))
    email = Column(String(255))
    address = Column(Text)
    is_primary = Column(Boolean, default=False)

    # Relationships
    patient = relationship("Patient", back_populates="contacts")


class PatientInsurance(Base, AuditMixin):
    """Patient insurance information."""
    __tablename__ = 'patient_insurance'

    insurance_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    insurance_type = Column(String(20), nullable=False)  # PRIMARY, SECONDARY, TERTIARY
    payer_id = Column(String(50), nullable=False)
    payer_name = Column(String(200), nullable=False)
    plan_name = Column(String(200))
    policy_number = Column(String(50), nullable=False)
    group_number = Column(String(50))
    subscriber_id = Column(String(50))
    subscriber_name = Column(String(200))
    subscriber_relationship = Column(String(20))
    effective_date = Column(Date, nullable=False)
    termination_date = Column(Date)
    copay_amount = Column(Numeric(10, 2))
    deductible = Column(Numeric(10, 2))
    deductible_met = Column(Numeric(10, 2), default=0)
    out_of_pocket_max = Column(Numeric(10, 2))
    out_of_pocket_met = Column(Numeric(10, 2), default=0)
    authorization_required = Column(Boolean, default=False)

    # Relationships
    patient = relationship("Patient", back_populates="insurance")


class EmergencyContact(Base, TimestampMixin):
    """Emergency contacts (separate for compliance)."""
    __tablename__ = 'emergency_contacts'

    contact_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    contact_name = Column(String(200), nullable=False)
    relationship = Column(String(50), nullable=False)
    phone_primary = Column(String(20), nullable=False)
    phone_secondary = Column(String(20))
    is_legal_guardian = Column(Boolean, default=False)
    priority = Column(Integer, default=1)


class PatientAllergy(Base, AuditMixin):
    """Patient allergies."""
    __tablename__ = 'patient_allergies'

    allergy_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    allergen_type = Column(String(50), nullable=False)  # DRUG, FOOD, ENVIRONMENTAL
    allergen_name = Column(String(200), nullable=False)
    allergen_code = Column(String(20))
    reaction = Column(Text)
    severity = Column(String(20))  # MILD, MODERATE, SEVERE, LIFE_THREATENING
    onset_date = Column(Date)
    verified = Column(Boolean, default=False)
    verified_by = Column(Integer)
    status = Column(String(20), default='ACTIVE')

    # Relationships
    patient = relationship("Patient", back_populates="allergies")


class PatientMedication(Base, AuditMixin):
    """Patient current medications."""
    __tablename__ = 'patient_medications'

    medication_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    drug_name = Column(String(200), nullable=False)
    drug_code = Column(String(20))  # NDC, RxNorm
    dosage = Column(String(100))
    frequency = Column(String(100))
    route = Column(String(50))
    prescriber_id = Column(Integer, ForeignKey('providers.provider_id'))
    start_date = Column(Date)
    end_date = Column(Date)
    indication = Column(String(255))
    status = Column(String(20), default='ACTIVE')
    is_prn = Column(Boolean, default=False)
    refills_remaining = Column(Integer)
    pharmacy = Column(String(200))


class PatientImmunization(Base, TimestampMixin):
    """Patient immunization records."""
    __tablename__ = 'patient_immunizations'

    immunization_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    vaccine_name = Column(String(200), nullable=False)
    vaccine_code = Column(String(20))  # CVX code
    manufacturer = Column(String(100))
    lot_number = Column(String(50))
    expiration_date = Column(Date)
    administration_date = Column(Date, nullable=False)
    site = Column(String(50))
    route = Column(String(50))
    dose_number = Column(Integer)
    administrator_id = Column(Integer)
    facility = Column(String(200))
    reaction = Column(Text)


class PatientConsent(Base, AuditMixin):
    """Patient consents and authorizations."""
    __tablename__ = 'patient_consents'

    consent_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    consent_type = Column(String(100), nullable=False)
    description = Column(Text)
    effective_date = Column(Date, nullable=False)
    expiration_date = Column(Date)
    granted = Column(Boolean, nullable=False)
    signed_by = Column(String(200))
    witness = Column(String(200))
    document_url = Column(String(500))
    revoked = Column(Boolean, default=False)
    revoked_date = Column(Date)


class PatientDocument(Base, TimestampMixin):
    """Patient documents (scans, forms, etc.)."""
    __tablename__ = 'patient_documents'

    document_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    document_type = Column(String(50), nullable=False)
    document_name = Column(String(255), nullable=False)
    description = Column(Text)
    file_path = Column(String(500))
    file_size = Column(Integer)
    mime_type = Column(String(100))
    uploaded_date = Column(DateTime, nullable=False)
    uploaded_by = Column(Integer)
    encounter_id = Column(Integer)
    category = Column(String(50))


class PatientPreference(Base, TimestampMixin):
    """Patient preferences."""
    __tablename__ = 'patient_preferences'

    preference_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    preference_type = Column(String(50), nullable=False)
    preference_value = Column(Text)

    __table_args__ = (
        UniqueConstraint('patient_id', 'preference_type', name='uq_patient_preference'),
    )


class PatientPortalUser(Base, AuditMixin):
    """Patient portal accounts."""
    __tablename__ = 'patient_portal_users'

    portal_user_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False, unique=True)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    email_verified = Column(Boolean, default=False)
    phone_verified = Column(Boolean, default=False)
    mfa_enabled = Column(Boolean, default=False)
    last_login = Column(DateTime)
    status = Column(String(20), default='ACTIVE')


class PatientCommunicationLog(Base):
    """Patient communication history."""
    __tablename__ = 'patient_communication_log'

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    communication_type = Column(String(20), nullable=False)  # PHONE, EMAIL, SMS, LETTER
    direction = Column(String(10), nullable=False)  # INBOUND, OUTBOUND
    subject = Column(String(255))
    content = Column(Text)
    sent_at = Column(DateTime, nullable=False)
    sent_by = Column(Integer)
    status = Column(String(20))
    response_received = Column(Boolean, default=False)


# ============================================================================
# Medical Records (18 tables)
# ============================================================================

class MedicalRecord(Base, AuditMixin):
    """Medical records / encounters."""
    __tablename__ = 'medical_records'

    record_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    encounter_number = Column(String(20), nullable=False, unique=True)
    encounter_type = Column(String(50), nullable=False)  # OFFICE, INPATIENT, EMERGENCY, TELEHEALTH
    admission_date = Column(DateTime, nullable=False)
    discharge_date = Column(DateTime)
    provider_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    facility = Column(String(200))
    department = Column(String(100))
    chief_complaint = Column(Text)
    history_present_illness = Column(Text)
    physical_exam = Column(Text)
    assessment = Column(Text)
    plan = Column(Text)
    status = Column(String(20), nullable=False)  # IN_PROGRESS, COMPLETED, SIGNED

    # Relationships
    patient = relationship("Patient", back_populates="medical_records")
    diagnoses = relationship("Diagnosis", back_populates="record")
    procedures = relationship("Procedure", back_populates="record")
    vitals = relationship("Vital", back_populates="record")

    __table_args__ = (
        Index('ix_medical_records_patient_id', 'patient_id'),
        Index('ix_medical_records_date', 'admission_date'),
    )


class Diagnosis(Base, TimestampMixin):
    """Diagnoses."""
    __tablename__ = 'diagnoses'

    diagnosis_id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'), nullable=False)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    diagnosis_code = Column(String(20), nullable=False)  # ICD-10
    diagnosis_description = Column(Text, nullable=False)
    diagnosis_type = Column(String(20))  # PRIMARY, SECONDARY, ADMITTING
    onset_date = Column(Date)
    resolution_date = Column(Date)
    status = Column(String(20), default='ACTIVE')
    severity = Column(String(20))
    diagnosed_by = Column(Integer, ForeignKey('providers.provider_id'))

    # Relationships
    record = relationship("MedicalRecord", back_populates="diagnoses")


class Procedure(Base, TimestampMixin):
    """Medical procedures."""
    __tablename__ = 'procedures'

    procedure_id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'), nullable=False)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    procedure_code = Column(String(20), nullable=False)  # CPT/HCPCS
    procedure_description = Column(Text, nullable=False)
    procedure_date = Column(DateTime, nullable=False)
    performing_provider_id = Column(Integer, ForeignKey('providers.provider_id'))
    facility = Column(String(200))
    modifiers = Column(String(50))
    quantity = Column(Integer, default=1)
    notes = Column(Text)
    status = Column(String(20))
    outcome = Column(Text)

    # Relationships
    record = relationship("MedicalRecord", back_populates="procedures")


class LabOrder(Base, AuditMixin):
    """Laboratory orders."""
    __tablename__ = 'lab_orders'

    order_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    order_number = Column(String(20), nullable=False, unique=True)
    ordering_provider_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    order_date = Column(DateTime, nullable=False)
    priority = Column(String(20), default='ROUTINE')
    fasting_required = Column(Boolean, default=False)
    clinical_notes = Column(Text)
    status = Column(String(20), nullable=False)
    collection_date = Column(DateTime)
    received_date = Column(DateTime)
    completed_date = Column(DateTime)

    # Relationships
    results = relationship("LabResult", back_populates="order")


class LabResult(Base, TimestampMixin):
    """Laboratory results."""
    __tablename__ = 'lab_results'

    result_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('lab_orders.order_id'), nullable=False)
    test_code = Column(String(20), nullable=False)
    test_name = Column(String(200), nullable=False)
    result_value = Column(String(100))
    result_unit = Column(String(50))
    reference_range = Column(String(100))
    abnormal_flag = Column(String(10))  # H, L, HH, LL, N
    result_status = Column(String(20))
    performed_date = Column(DateTime)
    performed_by = Column(String(100))
    notes = Column(Text)

    # Relationships
    order = relationship("LabOrder", back_populates="results")


class Prescription(Base, AuditMixin):
    """Prescriptions."""
    __tablename__ = 'prescriptions'

    prescription_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    rx_number = Column(String(20), nullable=False, unique=True)
    prescriber_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    drug_name = Column(String(200), nullable=False)
    drug_code = Column(String(20))  # NDC
    strength = Column(String(50))
    dosage_form = Column(String(50))
    quantity = Column(Numeric(10, 2), nullable=False)
    days_supply = Column(Integer)
    sig = Column(Text)  # Directions
    refills_authorized = Column(Integer, default=0)
    refills_remaining = Column(Integer, default=0)
    daw_code = Column(String(1))  # Dispense As Written
    written_date = Column(Date, nullable=False)
    effective_date = Column(Date)
    expiration_date = Column(Date)
    status = Column(String(20), nullable=False)
    pharmacy_id = Column(String(50))
    pharmacy_name = Column(String(200))


class PrescriptionFill(Base, TimestampMixin):
    """Prescription fills/refills."""
    __tablename__ = 'prescription_fills'

    fill_id = Column(Integer, primary_key=True, autoincrement=True)
    prescription_id = Column(Integer, ForeignKey('prescriptions.prescription_id'), nullable=False)
    fill_number = Column(Integer, nullable=False)
    fill_date = Column(Date, nullable=False)
    quantity_dispensed = Column(Numeric(10, 2), nullable=False)
    days_supply = Column(Integer)
    pharmacy_id = Column(String(50))
    pharmacy_name = Column(String(200))
    pharmacist = Column(String(100))
    dispensed_drug_code = Column(String(20))
    dispensed_drug_name = Column(String(200))
    copay = Column(Numeric(10, 2))


class Vital(Base, TimestampMixin):
    """Vital signs sessions."""
    __tablename__ = 'vitals'

    vital_id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    recorded_date = Column(DateTime, nullable=False)
    recorded_by = Column(Integer)
    location = Column(String(100))

    # Relationships
    record = relationship("MedicalRecord", back_populates="vitals")
    readings = relationship("VitalReading", back_populates="vital")


class VitalReading(Base, TimestampMixin):
    """Individual vital sign readings."""
    __tablename__ = 'vital_readings'

    reading_id = Column(Integer, primary_key=True, autoincrement=True)
    vital_id = Column(Integer, ForeignKey('vitals.vital_id'), nullable=False)
    vital_type = Column(String(50), nullable=False)  # BP, TEMP, PULSE, RESP, O2SAT, HEIGHT, WEIGHT
    value = Column(String(50), nullable=False)
    unit = Column(String(20))
    position = Column(String(20))  # SITTING, STANDING, LYING
    notes = Column(Text)

    # Relationships
    vital = relationship("Vital", back_populates="readings")


class ClinicalNote(Base, AuditMixin):
    """Clinical notes."""
    __tablename__ = 'clinical_notes'

    note_id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    note_type = Column(String(50), nullable=False)  # PROGRESS, CONSULT, DISCHARGE, HPI
    author_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    note_date = Column(DateTime, nullable=False)
    note_text = Column(Text, nullable=False)
    status = Column(String(20), default='DRAFT')
    signed_date = Column(DateTime)
    cosigner_id = Column(Integer)
    cosigned_date = Column(DateTime)
    addendum = Column(Text)
    addendum_date = Column(DateTime)


class RadiologyOrder(Base, AuditMixin):
    """Radiology/imaging orders."""
    __tablename__ = 'radiology_orders'

    order_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    order_number = Column(String(20), nullable=False, unique=True)
    ordering_provider_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    order_date = Column(DateTime, nullable=False)
    modality = Column(String(20), nullable=False)  # XR, CT, MRI, US, NM, PET
    body_part = Column(String(100), nullable=False)
    laterality = Column(String(10))  # LEFT, RIGHT, BILATERAL
    contrast = Column(Boolean, default=False)
    priority = Column(String(20), default='ROUTINE')
    clinical_indication = Column(Text)
    status = Column(String(20), nullable=False)
    scheduled_date = Column(DateTime)
    performed_date = Column(DateTime)


class RadiologyResult(Base, TimestampMixin):
    """Radiology results/reports."""
    __tablename__ = 'radiology_results'

    result_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('radiology_orders.order_id'), nullable=False)
    accession_number = Column(String(20), nullable=False, unique=True)
    study_date = Column(DateTime, nullable=False)
    reading_physician_id = Column(Integer, ForeignKey('providers.provider_id'))
    technique = Column(Text)
    findings = Column(Text, nullable=False)
    impression = Column(Text, nullable=False)
    comparison = Column(Text)
    status = Column(String(20), nullable=False)
    critical_finding = Column(Boolean, default=False)
    critical_communicated = Column(Boolean, default=False)
    communicated_to = Column(String(100))
    communicated_date = Column(DateTime)


class PathologyReport(Base, AuditMixin):
    """Pathology reports."""
    __tablename__ = 'pathology_reports'

    report_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    accession_number = Column(String(20), nullable=False, unique=True)
    specimen_type = Column(String(100), nullable=False)
    specimen_site = Column(String(100))
    collection_date = Column(DateTime, nullable=False)
    received_date = Column(DateTime)
    pathologist_id = Column(Integer, ForeignKey('providers.provider_id'))
    gross_description = Column(Text)
    microscopic_description = Column(Text)
    diagnosis = Column(Text, nullable=False)
    additional_tests = Column(Text)
    status = Column(String(20), nullable=False)
    signed_date = Column(DateTime)


class SurgicalHistory(Base, TimestampMixin):
    """Patient surgical history."""
    __tablename__ = 'surgical_history'

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    procedure_name = Column(String(255), nullable=False)
    procedure_code = Column(String(20))
    procedure_date = Column(Date)
    surgeon = Column(String(200))
    facility = Column(String(200))
    notes = Column(Text)
    complications = Column(Text)
    source = Column(String(50))


class FamilyHistory(Base, TimestampMixin):
    """Patient family medical history."""
    __tablename__ = 'family_history'

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    relationship = Column(String(50), nullable=False)
    condition = Column(String(255), nullable=False)
    condition_code = Column(String(20))
    onset_age = Column(Integer)
    deceased = Column(Boolean, default=False)
    cause_of_death = Column(String(255))
    notes = Column(Text)


class SocialHistory(Base, AuditMixin):
    """Patient social history."""
    __tablename__ = 'social_history'

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    smoking_status = Column(String(50))
    tobacco_use = Column(String(50))
    packs_per_day = Column(Numeric(4, 2))
    years_smoked = Column(Integer)
    quit_date = Column(Date)
    alcohol_use = Column(String(50))
    drinks_per_week = Column(Integer)
    drug_use = Column(Text)
    occupation = Column(String(100))
    education_level = Column(String(50))
    living_situation = Column(String(100))
    exercise_frequency = Column(String(50))
    diet = Column(String(100))
    sexual_activity = Column(String(50))


class ConditionHistory(Base, TimestampMixin):
    """Patient problem/condition list."""
    __tablename__ = 'condition_history'

    condition_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    condition_code = Column(String(20))
    condition_name = Column(String(255), nullable=False)
    onset_date = Column(Date)
    resolved_date = Column(Date)
    status = Column(String(20), default='ACTIVE')
    severity = Column(String(20))
    verified = Column(Boolean, default=False)
    source = Column(String(50))


class ProgressNote(Base, AuditMixin):
    """Progress notes."""
    __tablename__ = 'progress_notes'

    note_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    author_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    note_date = Column(DateTime, nullable=False)
    subjective = Column(Text)
    objective = Column(Text)
    assessment = Column(Text)
    plan = Column(Text)
    status = Column(String(20), default='DRAFT')
    signed_date = Column(DateTime)


# ============================================================================
# Appointments (10 tables)
# ============================================================================

class AppointmentType(Base, TimestampMixin):
    """Appointment type definitions."""
    __tablename__ = 'appointment_types'

    type_id = Column(Integer, primary_key=True, autoincrement=True)
    type_code = Column(String(20), nullable=False, unique=True)
    type_name = Column(String(100), nullable=False)
    description = Column(Text)
    duration_minutes = Column(Integer, nullable=False)
    category = Column(String(50))
    color = Column(String(7))
    is_telehealth = Column(Boolean, default=False)


class Provider(Base, AuditMixin):
    """Healthcare providers."""
    __tablename__ = 'providers'

    provider_id = Column(Integer, primary_key=True, autoincrement=True)
    npi = Column(String(10), nullable=False, unique=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    credentials = Column(String(50))  # MD, DO, NP, PA
    specialty = Column(String(100))
    subspecialty = Column(String(100))
    department = Column(String(100))
    email = Column(String(255))
    phone = Column(String(20))
    accepting_patients = Column(Boolean, default=True)
    status = Column(String(20), default='ACTIVE')
    hire_date = Column(Date)
    termination_date = Column(Date)

    # Relationships
    schedules = relationship("ProviderSchedule", back_populates="provider")


class ProviderSchedule(Base, AuditMixin):
    """Provider schedules."""
    __tablename__ = 'provider_schedules'

    schedule_id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Sunday, 6=Saturday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    location = Column(String(100))
    room_id = Column(Integer, ForeignKey('rooms.room_id'))
    effective_date = Column(Date, nullable=False)
    end_date = Column(Date)
    appointment_types = Column(Text)

    # Relationships
    provider = relationship("Provider", back_populates="schedules")


class Room(Base, TimestampMixin):
    """Exam/procedure rooms."""
    __tablename__ = 'rooms'

    room_id = Column(Integer, primary_key=True, autoincrement=True)
    room_number = Column(String(20), nullable=False)
    room_name = Column(String(100))
    location = Column(String(100))
    room_type = Column(String(50))  # EXAM, PROCEDURE, IMAGING, LAB
    capacity = Column(Integer, default=1)
    equipment = Column(Text)
    is_available = Column(Boolean, default=True)


class Appointment(Base, AuditMixin):
    """Patient appointments."""
    __tablename__ = 'appointments'

    appointment_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    provider_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    appointment_type_id = Column(Integer, ForeignKey('appointment_types.type_id'), nullable=False)
    scheduled_date = Column(Date, nullable=False)
    scheduled_time = Column(Time, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    room_id = Column(Integer, ForeignKey('rooms.room_id'))
    status = Column(String(20), nullable=False)  # SCHEDULED, CONFIRMED, CHECKED_IN, COMPLETED, CANCELLED, NO_SHOW
    reason = Column(Text)
    notes = Column(Text)
    check_in_time = Column(DateTime)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    is_telehealth = Column(Boolean, default=False)
    telehealth_url = Column(String(500))
    confirmation_sent = Column(Boolean, default=False)
    reminder_sent = Column(Boolean, default=False)

    # Relationships
    patient = relationship("Patient", back_populates="appointments")

    __table_args__ = (
        Index('ix_appointments_patient_id', 'patient_id'),
        Index('ix_appointments_provider_id', 'provider_id'),
        Index('ix_appointments_date', 'scheduled_date'),
    )


class WaitingList(Base, TimestampMixin):
    """Appointment waiting list."""
    __tablename__ = 'waiting_lists'

    waitlist_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    provider_id = Column(Integer, ForeignKey('providers.provider_id'))
    appointment_type_id = Column(Integer, ForeignKey('appointment_types.type_id'), nullable=False)
    preferred_dates = Column(Text)
    preferred_times = Column(Text)
    reason = Column(Text)
    priority = Column(Integer, default=0)
    added_date = Column(DateTime, nullable=False)
    contacted_date = Column(DateTime)
    status = Column(String(20), default='WAITING')


class AppointmentReminder(Base, TimestampMixin):
    """Appointment reminders."""
    __tablename__ = 'appointment_reminders'

    reminder_id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey('appointments.appointment_id'), nullable=False)
    reminder_type = Column(String(20), nullable=False)  # EMAIL, SMS, PHONE
    scheduled_date = Column(DateTime, nullable=False)
    sent_date = Column(DateTime)
    status = Column(String(20))
    response = Column(String(50))


class NoShow(Base, TimestampMixin):
    """No-show tracking."""
    __tablename__ = 'no_shows'

    no_show_id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey('appointments.appointment_id'), nullable=False)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    no_show_date = Column(Date, nullable=False)
    reason = Column(Text)
    contacted = Column(Boolean, default=False)
    rescheduled = Column(Boolean, default=False)
    fee_charged = Column(Numeric(10, 2))


class Cancellation(Base, TimestampMixin):
    """Appointment cancellations."""
    __tablename__ = 'cancellations'

    cancellation_id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey('appointments.appointment_id'), nullable=False)
    cancelled_date = Column(DateTime, nullable=False)
    cancelled_by = Column(String(50))  # PATIENT, PROVIDER, SYSTEM
    reason = Column(Text)
    notice_hours = Column(Integer)
    rescheduled = Column(Boolean, default=False)
    reschedule_appointment_id = Column(Integer)


class TelehealthSession(Base, AuditMixin):
    """Telehealth session details."""
    __tablename__ = 'telehealth_sessions'

    session_id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey('appointments.appointment_id'), nullable=False)
    platform = Column(String(50))
    session_url = Column(String(500))
    patient_joined = Column(DateTime)
    provider_joined = Column(DateTime)
    session_start = Column(DateTime)
    session_end = Column(DateTime)
    duration_minutes = Column(Integer)
    technical_issues = Column(Boolean, default=False)
    issue_notes = Column(Text)
    recording_url = Column(String(500))


# ============================================================================
# Billing (12 tables)
# ============================================================================

class BillingCode(Base, TimestampMixin):
    """Billing codes reference."""
    __tablename__ = 'billing_codes'

    code_id = Column(Integer, primary_key=True, autoincrement=True)
    code_type = Column(String(20), nullable=False)  # CPT, HCPCS, ICD10, DRG
    code = Column(String(20), nullable=False)
    description = Column(Text, nullable=False)
    short_description = Column(String(100))
    effective_date = Column(Date)
    termination_date = Column(Date)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint('code_type', 'code', name='uq_billing_code'),
    )


class ChargeMaster(Base, AuditMixin):
    """Charge master / fee schedule."""
    __tablename__ = 'charge_master'

    charge_id = Column(Integer, primary_key=True, autoincrement=True)
    code_id = Column(Integer, ForeignKey('billing_codes.code_id'), nullable=False)
    description = Column(String(255), nullable=False)
    department = Column(String(100))
    revenue_code = Column(String(10))
    standard_charge = Column(Numeric(14, 2), nullable=False)
    cash_price = Column(Numeric(14, 2))
    minimum_negotiated = Column(Numeric(14, 2))
    maximum_negotiated = Column(Numeric(14, 2))
    effective_date = Column(Date, nullable=False)
    end_date = Column(Date)


class Claim(Base, AuditMixin):
    """Insurance claims."""
    __tablename__ = 'claims'

    claim_id = Column(Integer, primary_key=True, autoincrement=True)
    claim_number = Column(String(20), nullable=False, unique=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    insurance_id = Column(Integer, ForeignKey('patient_insurance.insurance_id'), nullable=False)
    claim_type = Column(String(20), nullable=False)  # PROFESSIONAL, INSTITUTIONAL
    service_date = Column(Date, nullable=False)
    submission_date = Column(Date)
    total_charge = Column(Numeric(14, 2), nullable=False)
    total_allowed = Column(Numeric(14, 2))
    total_paid = Column(Numeric(14, 2), default=0)
    patient_responsibility = Column(Numeric(14, 2), default=0)
    status = Column(String(20), nullable=False)
    payer_claim_number = Column(String(50))
    billing_provider_id = Column(Integer, ForeignKey('providers.provider_id'))
    rendering_provider_id = Column(Integer, ForeignKey('providers.provider_id'))
    facility_code = Column(String(10))
    place_of_service = Column(String(10))

    # Relationships
    items = relationship("ClaimItem", back_populates="claim")
    status_history = relationship("ClaimStatusHistory", back_populates="claim")

    __table_args__ = (
        Index('ix_claims_patient_id', 'patient_id'),
        Index('ix_claims_status', 'status'),
    )


class ClaimItem(Base, TimestampMixin):
    """Claim line items."""
    __tablename__ = 'claim_items'

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey('claims.claim_id'), nullable=False)
    line_number = Column(Integer, nullable=False)
    service_date = Column(Date, nullable=False)
    procedure_code = Column(String(20), nullable=False)
    modifiers = Column(String(50))
    diagnosis_codes = Column(String(100))
    quantity = Column(Integer, default=1)
    charge_amount = Column(Numeric(14, 2), nullable=False)
    allowed_amount = Column(Numeric(14, 2))
    paid_amount = Column(Numeric(14, 2), default=0)
    adjustment_amount = Column(Numeric(14, 2), default=0)
    adjustment_reason = Column(String(100))
    patient_amount = Column(Numeric(14, 2), default=0)
    status = Column(String(20))

    # Relationships
    claim = relationship("Claim", back_populates="items")


class ClaimStatusHistory(Base):
    """Claim status history."""
    __tablename__ = 'claim_status_history'

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey('claims.claim_id'), nullable=False)
    status = Column(String(20), nullable=False)
    status_date = Column(DateTime, nullable=False)
    reason = Column(String(255))
    notes = Column(Text)
    user_id = Column(Integer)

    # Relationships
    claim = relationship("Claim", back_populates="status_history")


class InsurancePayment(Base, TimestampMixin):
    """Insurance payments (EOBs/ERAs)."""
    __tablename__ = 'insurance_payments'

    payment_id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey('claims.claim_id'), nullable=False)
    payer_id = Column(String(50), nullable=False)
    check_number = Column(String(50))
    check_date = Column(Date)
    payment_date = Column(Date, nullable=False)
    payment_amount = Column(Numeric(14, 2), nullable=False)
    adjustment_amount = Column(Numeric(14, 2), default=0)
    era_file = Column(String(500))
    processed_date = Column(DateTime)


class PatientPayment(Base, TimestampMixin):
    """Patient payments."""
    __tablename__ = 'patient_payments_health'

    payment_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    claim_id = Column(Integer, ForeignKey('claims.claim_id'))
    statement_id = Column(Integer)
    payment_date = Column(Date, nullable=False)
    payment_amount = Column(Numeric(14, 2), nullable=False)
    payment_method = Column(String(20))  # CASH, CHECK, CARD, ACH
    reference_number = Column(String(50))
    applied_to = Column(String(50))
    processed_by = Column(Integer)
    notes = Column(Text)


class HealthPaymentPlan(Base, AuditMixin):
    """Patient payment plans."""
    __tablename__ = 'health_payment_plans'

    plan_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    total_balance = Column(Numeric(14, 2), nullable=False)
    monthly_amount = Column(Numeric(14, 2), nullable=False)
    number_of_payments = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    remaining_balance = Column(Numeric(14, 2), nullable=False)
    status = Column(String(20), nullable=False)
    payment_day = Column(Integer)  # Day of month


class HealthInvoice(Base, AuditMixin):
    """Patient invoices."""
    __tablename__ = 'health_invoices'

    invoice_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    invoice_number = Column(String(20), nullable=False, unique=True)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    total_charges = Column(Numeric(14, 2), nullable=False)
    insurance_paid = Column(Numeric(14, 2), default=0)
    adjustments = Column(Numeric(14, 2), default=0)
    patient_paid = Column(Numeric(14, 2), default=0)
    balance_due = Column(Numeric(14, 2), nullable=False)
    status = Column(String(20), nullable=False)


class HealthStatement(Base, TimestampMixin):
    """Patient statements."""
    __tablename__ = 'health_statements'

    statement_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    statement_date = Column(Date, nullable=False)
    period_start = Column(Date)
    period_end = Column(Date)
    previous_balance = Column(Numeric(14, 2), default=0)
    new_charges = Column(Numeric(14, 2), default=0)
    payments_received = Column(Numeric(14, 2), default=0)
    adjustments = Column(Numeric(14, 2), default=0)
    current_balance = Column(Numeric(14, 2), nullable=False)
    amount_due = Column(Numeric(14, 2), nullable=False)
    due_date = Column(Date)
    sent_date = Column(Date)
    delivery_method = Column(String(20))


class Collection(Base, AuditMixin):
    """Collections."""
    __tablename__ = 'collections'

    collection_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    account_number = Column(String(20), nullable=False)
    original_balance = Column(Numeric(14, 2), nullable=False)
    current_balance = Column(Numeric(14, 2), nullable=False)
    placed_date = Column(Date, nullable=False)
    agency_name = Column(String(200))
    agency_account = Column(String(50))
    status = Column(String(20), nullable=False)
    last_payment_date = Column(Date)
    payments_received = Column(Numeric(14, 2), default=0)
    settlement_amount = Column(Numeric(14, 2))
    closed_date = Column(Date)


class WriteOff(Base, AuditMixin):
    """Write-offs and adjustments."""
    __tablename__ = 'write_offs'

    writeoff_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'))
    claim_id = Column(Integer, ForeignKey('claims.claim_id'))
    writeoff_date = Column(Date, nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    reason_code = Column(String(20), nullable=False)
    reason_description = Column(String(255))
    approved_by = Column(Integer)
    notes = Column(Text)


# ============================================================================
# Clinical (8 tables)
# ============================================================================

class TreatmentPlan(Base, AuditMixin):
    """Treatment plans."""
    __tablename__ = 'treatment_plans'

    plan_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    plan_name = Column(String(255), nullable=False)
    primary_diagnosis = Column(String(200))
    goals = Column(Text)
    interventions = Column(Text)
    start_date = Column(Date, nullable=False)
    target_end_date = Column(Date)
    actual_end_date = Column(Date)
    status = Column(String(20), nullable=False)
    created_by = Column(Integer, ForeignKey('providers.provider_id'))
    reviewed_date = Column(Date)
    reviewed_by = Column(Integer)


class CareTeam(Base, AuditMixin):
    """Care teams."""
    __tablename__ = 'care_teams'

    team_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    team_name = Column(String(100))
    primary_provider_id = Column(Integer, ForeignKey('providers.provider_id'))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    status = Column(String(20), default='ACTIVE')
    notes = Column(Text)

    # Relationships
    members = relationship("CareTeamMember", back_populates="team")


class CareTeamMember(Base, TimestampMixin):
    """Care team members."""
    __tablename__ = 'care_team_members'

    member_id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey('care_teams.team_id'), nullable=False)
    provider_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    role = Column(String(100), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    is_primary = Column(Boolean, default=False)

    # Relationships
    team = relationship("CareTeam", back_populates="members")


class Referral(Base, AuditMixin):
    """Patient referrals."""
    __tablename__ = 'referrals'

    referral_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    referring_provider_id = Column(Integer, ForeignKey('providers.provider_id'), nullable=False)
    referred_to_provider_id = Column(Integer, ForeignKey('providers.provider_id'))
    referred_to_facility = Column(String(200))
    specialty = Column(String(100))
    referral_date = Column(Date, nullable=False)
    expiration_date = Column(Date)
    priority = Column(String(20))
    reason = Column(Text)
    diagnosis_codes = Column(String(200))
    authorization_number = Column(String(50))
    status = Column(String(20), nullable=False)
    appointment_date = Column(Date)
    notes = Column(Text)


class ClinicalTrial(Base, AuditMixin):
    """Clinical trials."""
    __tablename__ = 'clinical_trials'

    trial_id = Column(Integer, primary_key=True, autoincrement=True)
    trial_number = Column(String(50), nullable=False, unique=True)
    trial_name = Column(String(255), nullable=False)
    sponsor = Column(String(200))
    phase = Column(String(20))
    status = Column(String(20), nullable=False)
    start_date = Column(Date)
    end_date = Column(Date)
    description = Column(Text)
    eligibility_criteria = Column(Text)
    principal_investigator_id = Column(Integer, ForeignKey('providers.provider_id'))
    target_enrollment = Column(Integer)
    current_enrollment = Column(Integer, default=0)


class TrialParticipant(Base, AuditMixin):
    """Clinical trial participants."""
    __tablename__ = 'trial_participants'

    participant_id = Column(Integer, primary_key=True, autoincrement=True)
    trial_id = Column(Integer, ForeignKey('clinical_trials.trial_id'), nullable=False)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    enrollment_date = Column(Date, nullable=False)
    randomization_date = Column(Date)
    arm = Column(String(50))
    status = Column(String(20), nullable=False)
    withdrawal_date = Column(Date)
    withdrawal_reason = Column(Text)
    consent_date = Column(Date)
    consent_version = Column(String(20))


class QualityMeasure(Base, TimestampMixin):
    """Quality measures tracking."""
    __tablename__ = 'quality_measures'

    measure_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    measure_code = Column(String(20), nullable=False)
    measure_name = Column(String(255), nullable=False)
    measure_period = Column(String(20))  # e.g., "2024-Q1"
    numerator = Column(Boolean)
    denominator = Column(Boolean)
    exclusion = Column(Boolean)
    exception = Column(Boolean)
    performance_met = Column(Boolean)
    calculated_date = Column(DateTime)
    provider_id = Column(Integer, ForeignKey('providers.provider_id'))


class OutcomeTracking(Base, TimestampMixin):
    """Patient outcomes tracking."""
    __tablename__ = 'outcome_tracking'

    outcome_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    record_id = Column(Integer, ForeignKey('medical_records.record_id'))
    outcome_type = Column(String(50), nullable=False)
    outcome_date = Column(Date, nullable=False)
    score = Column(Numeric(10, 2))
    score_type = Column(String(50))
    baseline_score = Column(Numeric(10, 2))
    target_score = Column(Numeric(10, 2))
    notes = Column(Text)
    measured_by = Column(Integer, ForeignKey('providers.provider_id'))


# Export all models
__all__ = [
    # Patients
    'Patient', 'PatientContact', 'PatientInsurance', 'EmergencyContact', 'PatientAllergy',
    'PatientMedication', 'PatientImmunization', 'PatientConsent', 'PatientDocument',
    'PatientPreference', 'PatientPortalUser', 'PatientCommunicationLog',
    # Medical Records
    'MedicalRecord', 'Diagnosis', 'Procedure', 'LabOrder', 'LabResult', 'Prescription',
    'PrescriptionFill', 'Vital', 'VitalReading', 'ClinicalNote', 'RadiologyOrder',
    'RadiologyResult', 'PathologyReport', 'SurgicalHistory', 'FamilyHistory',
    'SocialHistory', 'ConditionHistory', 'ProgressNote',
    # Appointments
    'AppointmentType', 'Provider', 'ProviderSchedule', 'Room', 'Appointment',
    'WaitingList', 'AppointmentReminder', 'NoShow', 'Cancellation', 'TelehealthSession',
    # Billing
    'BillingCode', 'ChargeMaster', 'Claim', 'ClaimItem', 'ClaimStatusHistory',
    'InsurancePayment', 'PatientPayment', 'HealthPaymentPlan', 'HealthInvoice',
    'HealthStatement', 'Collection', 'WriteOff',
    # Clinical
    'TreatmentPlan', 'CareTeam', 'CareTeamMember', 'Referral', 'ClinicalTrial',
    'TrialParticipant', 'QualityMeasure', 'OutcomeTracking',
]
