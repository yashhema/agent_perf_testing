"""Custom Faker providers for realistic data generation."""

import random
from faker import Faker
from faker.providers import BaseProvider


class MedicalProvider(BaseProvider):
    """Custom Faker provider for medical/healthcare data."""

    DIAGNOSES = [
        "Type 2 Diabetes Mellitus",
        "Essential Hypertension",
        "Hyperlipidemia",
        "Chronic Kidney Disease Stage 3",
        "Coronary Artery Disease",
        "Atrial Fibrillation",
        "Congestive Heart Failure",
        "Chronic Obstructive Pulmonary Disease",
        "Osteoarthritis",
        "Major Depressive Disorder",
        "Generalized Anxiety Disorder",
        "Hypothyroidism",
        "Gastroesophageal Reflux Disease",
        "Asthma",
        "Migraine",
        "Rheumatoid Arthritis",
        "Osteoporosis",
        "Obesity",
        "Sleep Apnea",
        "Chronic Pain Syndrome",
        "Anemia",
        "Pneumonia",
        "Urinary Tract Infection",
        "Cellulitis",
        "Acute Bronchitis",
    ]

    ICD10_CODES = [
        "E11.9", "I10", "E78.5", "N18.3", "I25.10",
        "I48.0", "I50.9", "J44.1", "M17.0", "F32.9",
        "F41.1", "E03.9", "K21.0", "J45.20", "G43.909",
        "M06.9", "M81.0", "E66.9", "G47.33", "G89.29",
        "D64.9", "J18.9", "N39.0", "L03.90", "J20.9",
    ]

    TREATMENTS = [
        "Metformin 500mg BID",
        "Lisinopril 10mg daily",
        "Atorvastatin 20mg daily",
        "Aspirin 81mg daily",
        "Metoprolol 25mg BID",
        "Omeprazole 20mg daily",
        "Levothyroxine 50mcg daily",
        "Amlodipine 5mg daily",
        "Gabapentin 300mg TID",
        "Sertraline 50mg daily",
        "Physical therapy 2x weekly",
        "Dietary modification",
        "Exercise program",
        "CPAP therapy",
        "Insulin glargine 20 units daily",
        "Albuterol inhaler PRN",
        "Prednisone taper",
        "Amoxicillin 500mg TID",
        "Azithromycin 250mg daily",
        "Furosemide 40mg daily",
    ]

    PROCEDURES = [
        "Complete Blood Count",
        "Comprehensive Metabolic Panel",
        "Lipid Panel",
        "Hemoglobin A1C",
        "Thyroid Panel",
        "Urinalysis",
        "Chest X-Ray",
        "Echocardiogram",
        "Stress Test",
        "Colonoscopy",
        "Upper Endoscopy",
        "MRI Brain",
        "CT Abdomen",
        "Bone Density Scan",
        "Mammogram",
        "EKG",
        "Pulmonary Function Test",
        "Sleep Study",
    ]

    CPT_CODES = [
        "85025", "80053", "80061", "83036", "84443",
        "81001", "71046", "93306", "93015", "45378",
        "43239", "70553", "74176", "77080", "77067",
        "93000", "94010", "95810",
    ]

    SPECIALTIES = [
        "Internal Medicine",
        "Family Medicine",
        "Cardiology",
        "Endocrinology",
        "Pulmonology",
        "Nephrology",
        "Gastroenterology",
        "Neurology",
        "Orthopedics",
        "Oncology",
        "Psychiatry",
        "Dermatology",
        "Ophthalmology",
        "Urology",
        "Rheumatology",
    ]

    VITAL_TYPES = [
        ("BP", "mmHg"),
        ("TEMP", "F"),
        ("PULSE", "bpm"),
        ("RESP", "breaths/min"),
        ("O2SAT", "%"),
        ("HEIGHT", "in"),
        ("WEIGHT", "lbs"),
    ]

    ALLERGIES = [
        "Penicillin",
        "Sulfa drugs",
        "Aspirin",
        "NSAIDs",
        "Codeine",
        "Morphine",
        "Latex",
        "Peanuts",
        "Shellfish",
        "Eggs",
        "Milk",
        "Soy",
        "Wheat",
        "Tree nuts",
        "Bee stings",
    ]

    def diagnosis(self) -> str:
        """Generate a diagnosis."""
        return self.random_element(self.DIAGNOSES)

    def icd10_code(self) -> str:
        """Generate an ICD-10 code."""
        return self.random_element(self.ICD10_CODES)

    def treatment(self) -> str:
        """Generate a treatment."""
        return self.random_element(self.TREATMENTS)

    def procedure(self) -> str:
        """Generate a procedure name."""
        return self.random_element(self.PROCEDURES)

    def cpt_code(self) -> str:
        """Generate a CPT code."""
        return self.random_element(self.CPT_CODES)

    def specialty(self) -> str:
        """Generate a medical specialty."""
        return self.random_element(self.SPECIALTIES)

    def vital_reading(self) -> tuple:
        """Generate a vital sign type and unit."""
        return self.random_element(self.VITAL_TYPES)

    def allergy(self) -> str:
        """Generate an allergy."""
        return self.random_element(self.ALLERGIES)

    def bp_reading(self) -> str:
        """Generate a blood pressure reading."""
        systolic = random.randint(90, 180)
        diastolic = random.randint(60, 110)
        return f"{systolic}/{diastolic}"

    def temperature(self) -> str:
        """Generate a temperature reading."""
        temp = round(random.uniform(97.0, 103.0), 1)
        return str(temp)

    def pulse(self) -> str:
        """Generate a pulse reading."""
        return str(random.randint(50, 120))

    def oxygen_saturation(self) -> str:
        """Generate an O2 saturation reading."""
        return str(random.randint(88, 100))

    def npi(self) -> str:
        """Generate a National Provider Identifier."""
        return ''.join([str(random.randint(0, 9)) for _ in range(10)])

    def mrn(self) -> str:
        """Generate a Medical Record Number."""
        return f"MRN{random.randint(100000, 999999)}"


class FinancialProvider(BaseProvider):
    """Custom Faker provider for financial/banking data."""

    TRANSACTION_TYPES = [
        "Direct Deposit",
        "ATM Withdrawal",
        "POS Purchase",
        "Online Transfer",
        "Bill Payment",
        "Wire Transfer",
        "Check Deposit",
        "ACH Credit",
        "ACH Debit",
        "Interest Payment",
        "Fee",
        "Refund",
    ]

    ACCOUNT_TYPES = [
        "Checking",
        "Savings",
        "Money Market",
        "Certificate of Deposit",
        "Individual Retirement Account",
        "Brokerage",
    ]

    LOAN_TYPES = [
        "Mortgage",
        "Auto Loan",
        "Personal Loan",
        "Student Loan",
        "Home Equity Line of Credit",
        "Business Loan",
    ]

    CARD_TYPES = ["VISA", "MASTERCARD", "AMEX", "DISCOVER"]

    MERCHANT_CATEGORIES = [
        "Grocery Stores",
        "Restaurants",
        "Gas Stations",
        "Retail",
        "Online Shopping",
        "Travel",
        "Entertainment",
        "Healthcare",
        "Utilities",
        "Insurance",
        "Telecommunications",
        "Education",
    ]

    SEC_CODES = ["PPD", "CCD", "WEB", "TEL"]

    DISPUTE_REASONS = [
        "Unauthorized transaction",
        "Duplicate charge",
        "Amount differs from receipt",
        "Merchandise not received",
        "Defective merchandise",
        "Credit not processed",
        "Incorrect transaction date",
    ]

    def transaction_type(self) -> str:
        """Generate a transaction type."""
        return self.random_element(self.TRANSACTION_TYPES)

    def account_type(self) -> str:
        """Generate an account type."""
        return self.random_element(self.ACCOUNT_TYPES)

    def loan_type(self) -> str:
        """Generate a loan type."""
        return self.random_element(self.LOAN_TYPES)

    def card_type(self) -> str:
        """Generate a card type."""
        return self.random_element(self.CARD_TYPES)

    def merchant_category(self) -> str:
        """Generate a merchant category."""
        return self.random_element(self.MERCHANT_CATEGORIES)

    def sec_code(self) -> str:
        """Generate an ACH SEC code."""
        return self.random_element(self.SEC_CODES)

    def dispute_reason(self) -> str:
        """Generate a dispute reason."""
        return self.random_element(self.DISPUTE_REASONS)

    def account_number(self) -> str:
        """Generate a bank account number."""
        return ''.join([str(random.randint(0, 9)) for _ in range(10)])

    def routing_number(self) -> str:
        """Generate a routing number."""
        return ''.join([str(random.randint(0, 9)) for _ in range(9)])

    def credit_card_number(self, card_type: str = None) -> str:
        """Generate a credit card number."""
        if card_type == "VISA":
            prefix = "4"
            length = 16
        elif card_type == "MASTERCARD":
            prefix = str(random.randint(51, 55))
            length = 16
        elif card_type == "AMEX":
            prefix = random.choice(["34", "37"])
            length = 15
        elif card_type == "DISCOVER":
            prefix = "6011"
            length = 16
        else:
            prefix = "4"
            length = 16

        remaining = length - len(prefix)
        number = prefix + ''.join([str(random.randint(0, 9)) for _ in range(remaining)])
        return number

    def cvv(self, card_type: str = None) -> str:
        """Generate a CVV."""
        length = 4 if card_type == "AMEX" else 3
        return ''.join([str(random.randint(0, 9)) for _ in range(length)])

    def loan_amount(self, loan_type: str = None) -> float:
        """Generate a loan amount based on type."""
        ranges = {
            "Mortgage": (100000, 1000000),
            "Auto Loan": (10000, 75000),
            "Personal Loan": (1000, 50000),
            "Student Loan": (5000, 150000),
            "Home Equity Line of Credit": (25000, 250000),
            "Business Loan": (50000, 500000),
        }
        min_val, max_val = ranges.get(loan_type, (1000, 100000))
        return round(random.uniform(min_val, max_val), 2)

    def interest_rate(self, loan_type: str = None) -> float:
        """Generate an interest rate based on loan type."""
        ranges = {
            "Mortgage": (2.5, 7.5),
            "Auto Loan": (3.0, 12.0),
            "Personal Loan": (5.0, 25.0),
            "Student Loan": (3.0, 8.0),
            "Home Equity Line of Credit": (4.0, 10.0),
            "Business Loan": (5.0, 15.0),
        }
        min_rate, max_rate = ranges.get(loan_type, (3.0, 15.0))
        return round(random.uniform(min_rate, max_rate), 2)

    def swift_code(self) -> str:
        """Generate a SWIFT code."""
        letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        code = ''.join(random.choices(letters, k=4))
        country = random.choice(['US', 'GB', 'DE', 'FR', 'JP', 'CA'])
        city = ''.join(random.choices(letters, k=2))
        branch = ''.join(random.choices(letters + '0123456789', k=3))
        return f"{code}{country}{city}{branch}"


class EcommerceProvider(BaseProvider):
    """Custom Faker provider for e-commerce data."""

    ORDER_STATUSES = ["PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED"]
    PAYMENT_STATUSES = ["PENDING", "COMPLETED", "FAILED", "REFUNDED"]
    SHIPPING_CARRIERS = ["UPS", "FedEx", "USPS", "DHL"]
    PRODUCT_CONDITIONS = ["NEW", "LIKE_NEW", "GOOD", "FAIR"]

    PRODUCT_CATEGORIES = [
        "Electronics",
        "Clothing",
        "Home & Garden",
        "Sports & Outdoors",
        "Books",
        "Toys & Games",
        "Beauty & Personal Care",
        "Automotive",
        "Health & Wellness",
        "Food & Grocery",
    ]

    RETURN_REASONS = [
        "Wrong item received",
        "Item damaged",
        "Item not as described",
        "Changed mind",
        "Better price found",
        "Arrived too late",
        "Ordered by mistake",
    ]

    def order_status(self) -> str:
        """Generate an order status."""
        return self.random_element(self.ORDER_STATUSES)

    def payment_status(self) -> str:
        """Generate a payment status."""
        return self.random_element(self.PAYMENT_STATUSES)

    def shipping_carrier(self) -> str:
        """Generate a shipping carrier."""
        return self.random_element(self.SHIPPING_CARRIERS)

    def product_category(self) -> str:
        """Generate a product category."""
        return self.random_element(self.PRODUCT_CATEGORIES)

    def product_condition(self) -> str:
        """Generate a product condition."""
        return self.random_element(self.PRODUCT_CONDITIONS)

    def return_reason(self) -> str:
        """Generate a return reason."""
        return self.random_element(self.RETURN_REASONS)

    def order_number(self) -> str:
        """Generate an order number."""
        return f"ORD-{random.randint(100000, 999999)}"

    def tracking_number(self, carrier: str = None) -> str:
        """Generate a tracking number."""
        if carrier == "UPS":
            return f"1Z{random.randint(100000000000000, 999999999999999)}"
        elif carrier == "FedEx":
            return str(random.randint(100000000000, 999999999999))
        elif carrier == "USPS":
            return str(random.randint(10000000000000000000, 99999999999999999999))
        else:
            return str(random.randint(1000000000, 9999999999))

    def sku(self) -> str:
        """Generate a product SKU."""
        prefix = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=3))
        number = random.randint(10000, 99999)
        return f"{prefix}-{number}"

    def upc(self) -> str:
        """Generate a UPC code."""
        return ''.join([str(random.randint(0, 9)) for _ in range(12)])


# Create a pre-configured Faker instance with all custom providers
def get_faker() -> Faker:
    """Get a Faker instance with all custom providers registered."""
    fake = Faker()
    fake.add_provider(MedicalProvider)
    fake.add_provider(FinancialProvider)
    fake.add_provider(EcommerceProvider)
    return fake


# Module-level faker instance
fake = get_faker()
