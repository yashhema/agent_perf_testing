"""E-Commerce domain models (60 tables).

Categories:
- Customers (8): customers, customer_addresses, customer_preferences, customer_segments,
                 customer_segment_members, customer_notes, customer_tags, customer_tag_assignments
- Products (12): products, categories, brands, product_images, product_reviews, inventory,
                 product_attributes, product_attribute_values, product_variants, product_variant_attributes,
                 product_bundles, product_bundle_items
- Orders (15): orders, order_items, order_status_history, shipments, shipment_items, returns,
               return_items, order_notes, order_tags, order_discounts, shopping_carts, cart_items,
               saved_for_later, order_fulfillment, fulfillment_items
- Payments (10): payment_methods, transactions, refunds, invoices, invoice_items, gift_cards,
                 gift_card_transactions, payment_plans, payment_plan_installments, wallets
- Marketing (8): campaigns, promotions, coupons, coupon_usage, wishlists, wishlist_items,
                 recommendations, recommendation_clicks
- Analytics (7): page_views, conversion_events, sales_daily, product_performance, search_queries,
                 abandoned_carts, customer_lifetime_value
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Numeric, Date,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, AuditMixin


# ============================================================================
# Customers (8 tables)
# ============================================================================

class Customer(Base, AuditMixin):
    """Customer accounts."""
    __tablename__ = 'customers'

    customer_id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(20))
    date_of_birth = Column(Date)
    gender = Column(String(10))
    loyalty_points = Column(Integer, default=0)
    loyalty_tier = Column(String(20), default='STANDARD')
    referral_code = Column(String(20), unique=True)
    referred_by = Column(Integer, ForeignKey('customers.customer_id'))
    marketing_consent = Column(Boolean, default=False)
    last_order_date = Column(DateTime)
    total_orders = Column(Integer, default=0)
    total_spent = Column(Numeric(12, 2), default=0)

    # Relationships
    addresses = relationship("CustomerAddress", back_populates="customer")
    preferences = relationship("CustomerPreference", back_populates="customer")
    orders = relationship("Order", back_populates="customer")
    wishlists = relationship("Wishlist", back_populates="customer")
    reviews = relationship("ProductReview", back_populates="customer")


class CustomerAddress(Base, TimestampMixin):
    """Customer shipping/billing addresses."""
    __tablename__ = 'customer_addresses'

    address_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    address_type = Column(String(20), nullable=False)  # SHIPPING, BILLING
    is_default = Column(Boolean, default=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    company = Column(String(100))
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255))
    city = Column(String(100), nullable=False)
    state = Column(String(100))
    postal_code = Column(String(20), nullable=False)
    country_code = Column(String(3), nullable=False)
    phone = Column(String(20))

    # Relationships
    customer = relationship("Customer", back_populates="addresses")


class CustomerPreference(Base, TimestampMixin):
    """Customer preferences and settings."""
    __tablename__ = 'customer_preferences'

    preference_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    preference_key = Column(String(50), nullable=False)
    preference_value = Column(String(255))

    # Relationships
    customer = relationship("Customer", back_populates="preferences")

    __table_args__ = (
        UniqueConstraint('customer_id', 'preference_key', name='uq_customer_preference'),
    )


class CustomerSegment(Base, AuditMixin):
    """Customer segmentation for marketing."""
    __tablename__ = 'customer_segments'

    segment_id = Column(Integer, primary_key=True, autoincrement=True)
    segment_name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    criteria = Column(Text)
    is_dynamic = Column(Boolean, default=True)
    member_count = Column(Integer, default=0)


class CustomerSegmentMember(Base, TimestampMixin):
    """Customer segment membership."""
    __tablename__ = 'customer_segment_members'

    member_id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(Integer, ForeignKey('customer_segments.segment_id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    added_at = Column(DateTime)
    source = Column(String(50))

    __table_args__ = (
        UniqueConstraint('segment_id', 'customer_id', name='uq_segment_customer'),
    )


class CustomerNote(Base, TimestampMixin):
    """Notes on customer accounts."""
    __tablename__ = 'customer_notes'

    note_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    note_type = Column(String(50), nullable=False)
    note_text = Column(Text, nullable=False)
    created_by_user_id = Column(Integer)
    is_internal = Column(Boolean, default=True)


class CustomerTag(Base, TimestampMixin):
    """Tags for customer categorization."""
    __tablename__ = 'customer_tags'

    tag_id = Column(Integer, primary_key=True, autoincrement=True)
    tag_name = Column(String(50), nullable=False, unique=True)
    tag_color = Column(String(7))
    description = Column(String(255))


class CustomerTagAssignment(Base, TimestampMixin):
    """Customer tag assignments."""
    __tablename__ = 'customer_tag_assignments'

    assignment_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    tag_id = Column(Integer, ForeignKey('customer_tags.tag_id'), nullable=False)

    __table_args__ = (
        UniqueConstraint('customer_id', 'tag_id', name='uq_customer_tag'),
    )


# ============================================================================
# Products (12 tables)
# ============================================================================

class Category(Base, AuditMixin):
    """Product categories with hierarchy."""
    __tablename__ = 'categories'

    category_id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(Integer, ForeignKey('categories.category_id'))
    category_name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    image_url = Column(String(500))
    sort_order = Column(Integer, default=0)
    is_visible = Column(Boolean, default=True)
    meta_title = Column(String(255))
    meta_description = Column(Text)

    # Relationships
    products = relationship("Product", back_populates="category")


class Brand(Base, AuditMixin):
    """Product brands."""
    __tablename__ = 'brands'

    brand_id = Column(Integer, primary_key=True, autoincrement=True)
    brand_name = Column(String(100), nullable=False, unique=True)
    slug = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    logo_url = Column(String(500))
    website_url = Column(String(500))
    is_featured = Column(Boolean, default=False)

    # Relationships
    products = relationship("Product", back_populates="brand")


class Product(Base, AuditMixin):
    """Products catalog."""
    __tablename__ = 'products'

    product_id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(50), nullable=False, unique=True)
    product_name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    short_description = Column(String(500))
    category_id = Column(Integer, ForeignKey('categories.category_id'))
    brand_id = Column(Integer, ForeignKey('brands.brand_id'))
    price = Column(Numeric(12, 2), nullable=False)
    compare_at_price = Column(Numeric(12, 2))
    cost_price = Column(Numeric(12, 2))
    weight = Column(Numeric(10, 3))
    weight_unit = Column(String(10), default='kg')
    is_taxable = Column(Boolean, default=True)
    tax_code = Column(String(20))
    is_visible = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)
    requires_shipping = Column(Boolean, default=True)
    meta_title = Column(String(255))
    meta_description = Column(Text)
    tags = Column(Text)

    # Relationships
    category = relationship("Category", back_populates="products")
    brand = relationship("Brand", back_populates="products")
    images = relationship("ProductImage", back_populates="product")
    reviews = relationship("ProductReview", back_populates="product")
    inventory = relationship("Inventory", back_populates="product")
    variants = relationship("ProductVariant", back_populates="product")

    __table_args__ = (
        Index('ix_products_category_id', 'category_id'),
        Index('ix_products_brand_id', 'brand_id'),
    )


class ProductImage(Base, TimestampMixin):
    """Product images."""
    __tablename__ = 'product_images'

    image_id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    image_url = Column(String(500), nullable=False)
    alt_text = Column(String(255))
    sort_order = Column(Integer, default=0)
    is_primary = Column(Boolean, default=False)

    # Relationships
    product = relationship("Product", back_populates="images")


class ProductReview(Base, AuditMixin):
    """Product reviews and ratings."""
    __tablename__ = 'product_reviews'

    review_id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    order_id = Column(Integer, ForeignKey('orders.order_id'))
    rating = Column(Integer, nullable=False)
    title = Column(String(255))
    review_text = Column(Text)
    is_verified_purchase = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=False)
    helpful_votes = Column(Integer, default=0)
    unhelpful_votes = Column(Integer, default=0)

    # Relationships
    product = relationship("Product", back_populates="reviews")
    customer = relationship("Customer", back_populates="reviews")

    __table_args__ = (
        Index('ix_product_reviews_product_id', 'product_id'),
    )


class Inventory(Base, TimestampMixin):
    """Product inventory tracking."""
    __tablename__ = 'inventory'

    inventory_id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    variant_id = Column(Integer, ForeignKey('product_variants.variant_id'))
    warehouse_code = Column(String(20), nullable=False)
    quantity_on_hand = Column(Integer, nullable=False, default=0)
    quantity_reserved = Column(Integer, default=0)
    quantity_available = Column(Integer, default=0)
    reorder_point = Column(Integer, default=10)
    reorder_quantity = Column(Integer, default=50)
    last_restock_date = Column(DateTime)

    # Relationships
    product = relationship("Product", back_populates="inventory")

    __table_args__ = (
        UniqueConstraint('product_id', 'variant_id', 'warehouse_code', name='uq_inventory_location'),
    )


class ProductAttribute(Base, TimestampMixin):
    """Product attribute definitions (e.g., Color, Size)."""
    __tablename__ = 'product_attributes'

    attribute_id = Column(Integer, primary_key=True, autoincrement=True)
    attribute_name = Column(String(100), nullable=False, unique=True)
    attribute_code = Column(String(50), nullable=False, unique=True)
    attribute_type = Column(String(20), nullable=False)  # SELECT, TEXT, NUMBER
    is_required = Column(Boolean, default=False)
    is_filterable = Column(Boolean, default=True)
    is_visible = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)


class ProductAttributeValue(Base, TimestampMixin):
    """Predefined values for product attributes."""
    __tablename__ = 'product_attribute_values'

    value_id = Column(Integer, primary_key=True, autoincrement=True)
    attribute_id = Column(Integer, ForeignKey('product_attributes.attribute_id'), nullable=False)
    value_label = Column(String(100), nullable=False)
    value_code = Column(String(50), nullable=False)
    sort_order = Column(Integer, default=0)
    swatch_value = Column(String(100))

    __table_args__ = (
        UniqueConstraint('attribute_id', 'value_code', name='uq_attribute_value_code'),
    )


class ProductVariant(Base, AuditMixin):
    """Product variants (e.g., size/color combinations)."""
    __tablename__ = 'product_variants'

    variant_id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    sku = Column(String(50), nullable=False, unique=True)
    price = Column(Numeric(12, 2))
    compare_at_price = Column(Numeric(12, 2))
    weight = Column(Numeric(10, 3))
    barcode = Column(String(50))
    is_default = Column(Boolean, default=False)

    # Relationships
    product = relationship("Product", back_populates="variants")


class ProductVariantAttribute(Base, TimestampMixin):
    """Attribute values for product variants."""
    __tablename__ = 'product_variant_attributes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    variant_id = Column(Integer, ForeignKey('product_variants.variant_id'), nullable=False)
    attribute_id = Column(Integer, ForeignKey('product_attributes.attribute_id'), nullable=False)
    value_id = Column(Integer, ForeignKey('product_attribute_values.value_id'))
    text_value = Column(String(255))

    __table_args__ = (
        UniqueConstraint('variant_id', 'attribute_id', name='uq_variant_attribute'),
    )


class ProductBundle(Base, AuditMixin):
    """Product bundles/kits."""
    __tablename__ = 'product_bundles'

    bundle_id = Column(Integer, primary_key=True, autoincrement=True)
    bundle_name = Column(String(255), nullable=False)
    description = Column(Text)
    bundle_price = Column(Numeric(12, 2), nullable=False)
    discount_type = Column(String(20))  # FIXED, PERCENTAGE
    discount_value = Column(Numeric(12, 2))


class ProductBundleItem(Base, TimestampMixin):
    """Items in a product bundle."""
    __tablename__ = 'product_bundle_items'

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    bundle_id = Column(Integer, ForeignKey('product_bundles.bundle_id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    variant_id = Column(Integer, ForeignKey('product_variants.variant_id'))
    quantity = Column(Integer, nullable=False, default=1)


# ============================================================================
# Orders (15 tables)
# ============================================================================

class Order(Base, AuditMixin):
    """Customer orders."""
    __tablename__ = 'orders'

    order_id = Column(Integer, primary_key=True, autoincrement=True)
    order_number = Column(String(50), nullable=False, unique=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    order_date = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False)  # PENDING, PROCESSING, SHIPPED, DELIVERED, CANCELLED
    subtotal = Column(Numeric(12, 2), nullable=False)
    discount_total = Column(Numeric(12, 2), default=0)
    tax_total = Column(Numeric(12, 2), default=0)
    shipping_total = Column(Numeric(12, 2), default=0)
    grand_total = Column(Numeric(12, 2), nullable=False)
    currency_code = Column(String(3), default='USD')
    payment_status = Column(String(20), default='PENDING')
    fulfillment_status = Column(String(20), default='UNFULFILLED')
    shipping_address_id = Column(Integer, ForeignKey('customer_addresses.address_id'))
    billing_address_id = Column(Integer, ForeignKey('customer_addresses.address_id'))
    shipping_method = Column(String(50))
    shipping_carrier = Column(String(50))
    tracking_number = Column(String(100))
    notes = Column(Text)
    ip_address = Column(String(45))
    user_agent = Column(String(500))

    # Relationships
    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")
    status_history = relationship("OrderStatusHistory", back_populates="order")

    __table_args__ = (
        Index('ix_orders_customer_id', 'customer_id'),
        Index('ix_orders_order_date', 'order_date'),
        Index('ix_orders_status', 'status'),
    )


class OrderItem(Base, TimestampMixin):
    """Order line items."""
    __tablename__ = 'order_items'

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    variant_id = Column(Integer, ForeignKey('product_variants.variant_id'))
    sku = Column(String(50), nullable=False)
    product_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0)
    tax_amount = Column(Numeric(12, 2), default=0)
    line_total = Column(Numeric(12, 2), nullable=False)
    is_gift = Column(Boolean, default=False)
    gift_message = Column(Text)

    # Relationships
    order = relationship("Order", back_populates="items")


class OrderStatusHistory(Base):
    """Order status change history."""
    __tablename__ = 'order_status_history'

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    status = Column(String(20), nullable=False)
    notes = Column(Text)
    changed_by = Column(Integer)
    changed_at = Column(DateTime, nullable=False)

    # Relationships
    order = relationship("Order", back_populates="status_history")


class Shipment(Base, TimestampMixin):
    """Order shipments."""
    __tablename__ = 'shipments'

    shipment_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    shipment_number = Column(String(50), nullable=False, unique=True)
    carrier = Column(String(50), nullable=False)
    service = Column(String(50))
    tracking_number = Column(String(100))
    tracking_url = Column(String(500))
    status = Column(String(20), nullable=False)
    shipped_at = Column(DateTime)
    delivered_at = Column(DateTime)
    weight = Column(Numeric(10, 3))
    shipping_cost = Column(Numeric(12, 2))


class ShipmentItem(Base, TimestampMixin):
    """Items in a shipment."""
    __tablename__ = 'shipment_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shipment_id = Column(Integer, ForeignKey('shipments.shipment_id'), nullable=False)
    order_item_id = Column(Integer, ForeignKey('order_items.item_id'), nullable=False)
    quantity = Column(Integer, nullable=False)


class Return(Base, AuditMixin):
    """Order returns/RMAs."""
    __tablename__ = 'returns'

    return_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    return_number = Column(String(50), nullable=False, unique=True)
    status = Column(String(20), nullable=False)  # REQUESTED, APPROVED, RECEIVED, REFUNDED, REJECTED
    reason = Column(String(100), nullable=False)
    notes = Column(Text)
    requested_at = Column(DateTime, nullable=False)
    approved_at = Column(DateTime)
    received_at = Column(DateTime)
    refund_amount = Column(Numeric(12, 2))


class ReturnItem(Base, TimestampMixin):
    """Items in a return."""
    __tablename__ = 'return_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    return_id = Column(Integer, ForeignKey('returns.return_id'), nullable=False)
    order_item_id = Column(Integer, ForeignKey('order_items.item_id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    condition = Column(String(20))
    reason = Column(String(100))


class OrderNote(Base, TimestampMixin):
    """Internal notes on orders."""
    __tablename__ = 'order_notes'

    note_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    note_text = Column(Text, nullable=False)
    is_customer_visible = Column(Boolean, default=False)
    created_by = Column(Integer)


class OrderTag(Base, TimestampMixin):
    """Tags for order categorization."""
    __tablename__ = 'order_tags'

    tag_id = Column(Integer, primary_key=True, autoincrement=True)
    tag_name = Column(String(50), nullable=False, unique=True)
    tag_color = Column(String(7))


class OrderDiscount(Base, TimestampMixin):
    """Discounts applied to orders."""
    __tablename__ = 'order_discounts'

    discount_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    coupon_id = Column(Integer, ForeignKey('coupons.coupon_id'))
    discount_type = Column(String(20), nullable=False)
    discount_value = Column(Numeric(12, 2), nullable=False)
    description = Column(String(255))


class ShoppingCart(Base, TimestampMixin):
    """Shopping carts."""
    __tablename__ = 'shopping_carts'

    cart_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'))
    session_id = Column(String(100))
    subtotal = Column(Numeric(12, 2), default=0)
    item_count = Column(Integer, default=0)
    last_activity = Column(DateTime)
    abandoned_at = Column(DateTime)
    recovered_at = Column(DateTime)


class CartItem(Base, TimestampMixin):
    """Items in shopping cart."""
    __tablename__ = 'cart_items'

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    cart_id = Column(Integer, ForeignKey('shopping_carts.cart_id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    variant_id = Column(Integer, ForeignKey('product_variants.variant_id'))
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)


class SavedForLater(Base, TimestampMixin):
    """Items saved for later in cart."""
    __tablename__ = 'saved_for_later'

    id = Column(Integer, primary_key=True, autoincrement=True)
    cart_id = Column(Integer, ForeignKey('shopping_carts.cart_id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    variant_id = Column(Integer, ForeignKey('product_variants.variant_id'))


class OrderFulfillment(Base, TimestampMixin):
    """Order fulfillment tracking."""
    __tablename__ = 'order_fulfillment'

    fulfillment_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    fulfillment_number = Column(String(50), nullable=False, unique=True)
    status = Column(String(20), nullable=False)
    location = Column(String(100))
    assigned_to = Column(Integer)


class FulfillmentItem(Base, TimestampMixin):
    """Items in fulfillment."""
    __tablename__ = 'fulfillment_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fulfillment_id = Column(Integer, ForeignKey('order_fulfillment.fulfillment_id'), nullable=False)
    order_item_id = Column(Integer, ForeignKey('order_items.item_id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    picked_at = Column(DateTime)
    packed_at = Column(DateTime)


# ============================================================================
# Payments (10 tables)
# ============================================================================

class PaymentMethod(Base, AuditMixin):
    """Customer payment methods."""
    __tablename__ = 'payment_methods'

    method_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    method_type = Column(String(20), nullable=False)  # CARD, BANK, WALLET
    provider = Column(String(50))  # STRIPE, PAYPAL, etc.
    token = Column(String(255))
    last_four = Column(String(4))
    expiry_month = Column(Integer)
    expiry_year = Column(Integer)
    card_brand = Column(String(20))
    billing_address_id = Column(Integer, ForeignKey('customer_addresses.address_id'))
    is_default = Column(Boolean, default=False)


class Transaction(Base, TimestampMixin):
    """Payment transactions."""
    __tablename__ = 'transactions'

    transaction_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    payment_method_id = Column(Integer, ForeignKey('payment_methods.method_id'))
    transaction_type = Column(String(20), nullable=False)  # CHARGE, REFUND, VOID
    amount = Column(Numeric(12, 2), nullable=False)
    currency_code = Column(String(3), default='USD')
    status = Column(String(20), nullable=False)  # PENDING, SUCCESS, FAILED
    gateway = Column(String(50))
    gateway_transaction_id = Column(String(100))
    gateway_response = Column(Text)
    error_code = Column(String(50))
    error_message = Column(Text)
    processed_at = Column(DateTime)

    __table_args__ = (
        Index('ix_transactions_order_id', 'order_id'),
    )


class Refund(Base, TimestampMixin):
    """Payment refunds."""
    __tablename__ = 'refunds'

    refund_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    transaction_id = Column(Integer, ForeignKey('transactions.transaction_id'))
    return_id = Column(Integer, ForeignKey('returns.return_id'))
    amount = Column(Numeric(12, 2), nullable=False)
    reason = Column(String(100))
    notes = Column(Text)
    status = Column(String(20), nullable=False)
    processed_at = Column(DateTime)
    processed_by = Column(Integer)


class Invoice(Base, AuditMixin):
    """Order invoices."""
    __tablename__ = 'invoices'

    invoice_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    invoice_number = Column(String(50), nullable=False, unique=True)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date)
    subtotal = Column(Numeric(12, 2), nullable=False)
    tax_total = Column(Numeric(12, 2), default=0)
    discount_total = Column(Numeric(12, 2), default=0)
    grand_total = Column(Numeric(12, 2), nullable=False)
    amount_paid = Column(Numeric(12, 2), default=0)
    amount_due = Column(Numeric(12, 2))
    status = Column(String(20), nullable=False)  # DRAFT, SENT, PAID, VOID


class InvoiceItem(Base, TimestampMixin):
    """Invoice line items."""
    __tablename__ = 'invoice_items'

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey('invoices.invoice_id'), nullable=False)
    description = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    tax_rate = Column(Numeric(5, 2), default=0)
    tax_amount = Column(Numeric(12, 2), default=0)
    line_total = Column(Numeric(12, 2), nullable=False)


class GiftCard(Base, AuditMixin):
    """Gift cards."""
    __tablename__ = 'gift_cards'

    card_id = Column(Integer, primary_key=True, autoincrement=True)
    card_code = Column(String(50), nullable=False, unique=True)
    initial_balance = Column(Numeric(12, 2), nullable=False)
    current_balance = Column(Numeric(12, 2), nullable=False)
    currency_code = Column(String(3), default='USD')
    purchaser_customer_id = Column(Integer, ForeignKey('customers.customer_id'))
    recipient_email = Column(String(255))
    recipient_name = Column(String(100))
    message = Column(Text)
    expires_at = Column(DateTime)
    redeemed_at = Column(DateTime)


class GiftCardTransaction(Base, TimestampMixin):
    """Gift card transactions."""
    __tablename__ = 'gift_card_transactions'

    transaction_id = Column(Integer, primary_key=True, autoincrement=True)
    card_id = Column(Integer, ForeignKey('gift_cards.card_id'), nullable=False)
    order_id = Column(Integer, ForeignKey('orders.order_id'))
    transaction_type = Column(String(20), nullable=False)  # PURCHASE, REDEMPTION, REFUND
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)


class PaymentPlan(Base, AuditMixin):
    """Payment plans (installments)."""
    __tablename__ = 'payment_plans'

    plan_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    total_amount = Column(Numeric(12, 2), nullable=False)
    installment_count = Column(Integer, nullable=False)
    installment_amount = Column(Numeric(12, 2), nullable=False)
    frequency = Column(String(20), nullable=False)  # WEEKLY, BIWEEKLY, MONTHLY
    start_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False)


class PaymentPlanInstallment(Base, TimestampMixin):
    """Payment plan installments."""
    __tablename__ = 'payment_plan_installments'

    installment_id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey('payment_plans.plan_id'), nullable=False)
    installment_number = Column(Integer, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    due_date = Column(Date, nullable=False)
    paid_date = Column(Date)
    status = Column(String(20), nullable=False)  # PENDING, PAID, OVERDUE, FAILED


class Wallet(Base, AuditMixin):
    """Customer wallets/store credit."""
    __tablename__ = 'wallets'

    wallet_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False, unique=True)
    balance = Column(Numeric(12, 2), nullable=False, default=0)
    currency_code = Column(String(3), default='USD')
    last_transaction_at = Column(DateTime)


# ============================================================================
# Marketing (8 tables)
# ============================================================================

class Campaign(Base, AuditMixin):
    """Marketing campaigns."""
    __tablename__ = 'campaigns'

    campaign_id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_name = Column(String(100), nullable=False)
    campaign_type = Column(String(50), nullable=False)  # EMAIL, SMS, SOCIAL, DISPLAY
    description = Column(Text)
    status = Column(String(20), nullable=False)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    budget = Column(Numeric(12, 2))
    spent = Column(Numeric(12, 2), default=0)
    target_segment_id = Column(Integer, ForeignKey('customer_segments.segment_id'))


class Promotion(Base, AuditMixin):
    """Promotions and sales."""
    __tablename__ = 'promotions'

    promotion_id = Column(Integer, primary_key=True, autoincrement=True)
    promotion_name = Column(String(100), nullable=False)
    promotion_type = Column(String(50), nullable=False)  # PERCENTAGE, FIXED, BOGO
    discount_value = Column(Numeric(12, 2))
    min_purchase = Column(Numeric(12, 2))
    max_discount = Column(Numeric(12, 2))
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    applies_to = Column(String(50))  # ALL, CATEGORY, PRODUCT, BRAND
    target_ids = Column(Text)
    is_stackable = Column(Boolean, default=False)


class Coupon(Base, AuditMixin):
    """Discount coupons."""
    __tablename__ = 'coupons'

    coupon_id = Column(Integer, primary_key=True, autoincrement=True)
    coupon_code = Column(String(50), nullable=False, unique=True)
    description = Column(String(255))
    discount_type = Column(String(20), nullable=False)  # PERCENTAGE, FIXED, FREE_SHIPPING
    discount_value = Column(Numeric(12, 2), nullable=False)
    min_purchase = Column(Numeric(12, 2))
    max_discount = Column(Numeric(12, 2))
    usage_limit = Column(Integer)
    usage_count = Column(Integer, default=0)
    per_customer_limit = Column(Integer, default=1)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    first_order_only = Column(Boolean, default=False)


class CouponUsage(Base, TimestampMixin):
    """Coupon usage tracking."""
    __tablename__ = 'coupon_usage'

    usage_id = Column(Integer, primary_key=True, autoincrement=True)
    coupon_id = Column(Integer, ForeignKey('coupons.coupon_id'), nullable=False)
    order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    discount_amount = Column(Numeric(12, 2), nullable=False)


class Wishlist(Base, AuditMixin):
    """Customer wishlists."""
    __tablename__ = 'wishlists'

    wishlist_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    wishlist_name = Column(String(100), default='My Wishlist')
    is_public = Column(Boolean, default=False)
    share_token = Column(String(50))

    # Relationships
    customer = relationship("Customer", back_populates="wishlists")
    items = relationship("WishlistItem", back_populates="wishlist")


class WishlistItem(Base, TimestampMixin):
    """Items in wishlist."""
    __tablename__ = 'wishlist_items'

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    wishlist_id = Column(Integer, ForeignKey('wishlists.wishlist_id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    variant_id = Column(Integer, ForeignKey('product_variants.variant_id'))
    priority = Column(Integer, default=0)
    notes = Column(Text)

    # Relationships
    wishlist = relationship("Wishlist", back_populates="items")

    __table_args__ = (
        UniqueConstraint('wishlist_id', 'product_id', 'variant_id', name='uq_wishlist_product'),
    )


class Recommendation(Base, TimestampMixin):
    """Product recommendations."""
    __tablename__ = 'recommendations'

    recommendation_id = Column(Integer, primary_key=True, autoincrement=True)
    source_product_id = Column(Integer, ForeignKey('products.product_id'))
    target_product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    recommendation_type = Column(String(50), nullable=False)  # SIMILAR, FREQUENTLY_BOUGHT, UPSELL
    score = Column(Numeric(5, 4))
    customer_segment_id = Column(Integer, ForeignKey('customer_segments.segment_id'))


class RecommendationClick(Base):
    """Recommendation click tracking."""
    __tablename__ = 'recommendation_clicks'

    click_id = Column(Integer, primary_key=True, autoincrement=True)
    recommendation_id = Column(Integer, ForeignKey('recommendations.recommendation_id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'))
    session_id = Column(String(100))
    clicked_at = Column(DateTime, nullable=False)
    converted = Column(Boolean, default=False)
    converted_at = Column(DateTime)


# ============================================================================
# Analytics (7 tables)
# ============================================================================

class PageView(Base):
    """Page view tracking."""
    __tablename__ = 'page_views'

    view_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'))
    session_id = Column(String(100), nullable=False)
    page_url = Column(String(500), nullable=False)
    page_type = Column(String(50))  # HOME, CATEGORY, PRODUCT, CART, CHECKOUT
    referrer_url = Column(String(500))
    product_id = Column(Integer, ForeignKey('products.product_id'))
    category_id = Column(Integer, ForeignKey('categories.category_id'))
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    device_type = Column(String(20))
    viewed_at = Column(DateTime, nullable=False)
    time_on_page = Column(Integer)

    __table_args__ = (
        Index('ix_page_views_session_id', 'session_id'),
        Index('ix_page_views_viewed_at', 'viewed_at'),
    )


class ConversionEvent(Base):
    """Conversion event tracking."""
    __tablename__ = 'conversion_events'

    event_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'))
    session_id = Column(String(100), nullable=False)
    event_type = Column(String(50), nullable=False)  # ADD_TO_CART, CHECKOUT_START, PURCHASE
    order_id = Column(Integer, ForeignKey('orders.order_id'))
    product_id = Column(Integer, ForeignKey('products.product_id'))
    value = Column(Numeric(12, 2))
    occurred_at = Column(DateTime, nullable=False)
    attribution_source = Column(String(100))
    attribution_medium = Column(String(50))
    attribution_campaign = Column(String(100))


class SalesDaily(Base):
    """Daily sales aggregation."""
    __tablename__ = 'sales_daily'

    id = Column(Integer, primary_key=True, autoincrement=True)
    sales_date = Column(Date, nullable=False, unique=True)
    order_count = Column(Integer, default=0)
    item_count = Column(Integer, default=0)
    gross_sales = Column(Numeric(14, 2), default=0)
    discount_total = Column(Numeric(14, 2), default=0)
    refund_total = Column(Numeric(14, 2), default=0)
    net_sales = Column(Numeric(14, 2), default=0)
    tax_total = Column(Numeric(14, 2), default=0)
    shipping_total = Column(Numeric(14, 2), default=0)
    new_customer_count = Column(Integer, default=0)
    returning_customer_count = Column(Integer, default=0)


class ProductPerformance(Base):
    """Product performance metrics."""
    __tablename__ = 'product_performance'

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.product_id'), nullable=False)
    period_date = Column(Date, nullable=False)
    views = Column(Integer, default=0)
    cart_adds = Column(Integer, default=0)
    purchases = Column(Integer, default=0)
    revenue = Column(Numeric(14, 2), default=0)
    units_sold = Column(Integer, default=0)
    returns = Column(Integer, default=0)
    conversion_rate = Column(Numeric(5, 4))
    avg_rating = Column(Numeric(3, 2))
    review_count = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('product_id', 'period_date', name='uq_product_performance'),
    )


class SearchQuery(Base):
    """Search query tracking."""
    __tablename__ = 'search_queries'

    query_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'))
    session_id = Column(String(100))
    query_text = Column(String(255), nullable=False)
    result_count = Column(Integer, default=0)
    clicked_product_id = Column(Integer, ForeignKey('products.product_id'))
    searched_at = Column(DateTime, nullable=False)
    converted = Column(Boolean, default=False)


class AbandonedCart(Base, TimestampMixin):
    """Abandoned cart tracking."""
    __tablename__ = 'abandoned_carts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    cart_id = Column(Integer, ForeignKey('shopping_carts.cart_id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'))
    email = Column(String(255))
    cart_value = Column(Numeric(12, 2), nullable=False)
    item_count = Column(Integer, nullable=False)
    abandoned_at = Column(DateTime, nullable=False)
    reminder_sent_at = Column(DateTime)
    reminder_count = Column(Integer, default=0)
    recovered_at = Column(DateTime)
    recovery_order_id = Column(Integer, ForeignKey('orders.order_id'))


class CustomerLifetimeValue(Base, TimestampMixin):
    """Customer lifetime value calculations."""
    __tablename__ = 'customer_lifetime_value'

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False, unique=True)
    first_order_date = Column(Date)
    last_order_date = Column(Date)
    total_orders = Column(Integer, default=0)
    total_revenue = Column(Numeric(14, 2), default=0)
    avg_order_value = Column(Numeric(12, 2))
    purchase_frequency = Column(Numeric(8, 4))
    predicted_ltv = Column(Numeric(14, 2))
    clv_segment = Column(String(20))


# Export all models
__all__ = [
    # Customers
    'Customer', 'CustomerAddress', 'CustomerPreference', 'CustomerSegment',
    'CustomerSegmentMember', 'CustomerNote', 'CustomerTag', 'CustomerTagAssignment',
    # Products
    'Category', 'Brand', 'Product', 'ProductImage', 'ProductReview', 'Inventory',
    'ProductAttribute', 'ProductAttributeValue', 'ProductVariant', 'ProductVariantAttribute',
    'ProductBundle', 'ProductBundleItem',
    # Orders
    'Order', 'OrderItem', 'OrderStatusHistory', 'Shipment', 'ShipmentItem', 'Return',
    'ReturnItem', 'OrderNote', 'OrderTag', 'OrderDiscount', 'ShoppingCart', 'CartItem',
    'SavedForLater', 'OrderFulfillment', 'FulfillmentItem',
    # Payments
    'PaymentMethod', 'Transaction', 'Refund', 'Invoice', 'InvoiceItem', 'GiftCard',
    'GiftCardTransaction', 'PaymentPlan', 'PaymentPlanInstallment', 'Wallet',
    # Marketing
    'Campaign', 'Promotion', 'Coupon', 'CouponUsage', 'Wishlist', 'WishlistItem',
    'Recommendation', 'RecommendationClick',
    # Analytics
    'PageView', 'ConversionEvent', 'SalesDaily', 'ProductPerformance', 'SearchQuery',
    'AbandonedCart', 'CustomerLifetimeValue',
]
