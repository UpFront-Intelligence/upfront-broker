from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, ARRAY, Date, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

PROPERTY_TYPES = [
    "Office", "Industrial", "Retail", "Land", "Multifamily",
    "STNL", "Self Storage", "Hospitality", "Medical"
]

class Property(Base):
    __tablename__ = "properties"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"),    nullable=False)
    account_id  = Column(Integer, ForeignKey("accounts.id"), nullable=True)  # current owner entity

    # Linked parties (accounts) — separate from owner_id, which is the broker
    recorded_owner_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    manager_account_id        = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    tax_bill_account_id       = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)

    # Identity
    name        = Column(String)
    building_name = Column(Text, nullable=True)  # official building name, e.g. "One Towne Square"
    park_name     = Column(Text, nullable=True)  # business/industrial park, e.g. "Galleria Officentre"
    address     = Column(String, nullable=False)
    city        = Column(String, nullable=False)
    state       = Column(String, nullable=False)
    zip         = Column(String)
    county      = Column(String)

    # Classification
    property_type   = Column(String)   # Office, Industrial, Retail, etc.
    subtype         = Column(String)   # e.g. "Flex", "Strip Center", "Garden"
    status          = Column(String, default="Active")  # Active, Off Market, Sold, Leased
    market          = Column(String, nullable=True)
    submarket       = Column(String, nullable=True)

    # Physical
    year_built      = Column(Integer)
    year_renovated  = Column(Integer, nullable=True)
    sf_rentable     = Column(Float)
    sf_land         = Column(Float)
    units           = Column(Integer)   # multifamily
    stories         = Column(Integer)
    construction_type = Column(String, nullable=True)
    zoning          = Column(String)
    parking_ratio   = Column(Float)
    parking_spaces  = Column(Integer, nullable=True)
    occupancy_pct   = Column(Float)

    # Financial
    asking_price        = Column(Float)
    asking_price_per_sf = Column(Float)
    assessed_value      = Column(Float)
    tax_amount          = Column(Float)
    tax_year            = Column(Integer)
    cap_rate            = Column(Float)
    noi                 = Column(Float)

    # Public records
    parcel_id       = Column(String, index=True)
    legal_desc      = Column(Text)

    # Media
    photo_urls      = Column(ARRAY(String), default=[])

    # Geocoordinates (auto-set by Nominatim on save)
    lat             = Column(Float, nullable=True)
    lng             = Column(Float, nullable=True)

    # Sale history
    last_sale_price = Column(Float, nullable=True)
    last_sale_date  = Column(Date, nullable=True)

    # Tenant / occupant
    tenant          = Column(String, nullable=True)

    # ── Industrial fields ────────────────────────────────────────────────────
    clear_height_min  = Column(Float, nullable=True)
    clear_height_max  = Column(Float, nullable=True)
    dock_doors        = Column(Integer, nullable=True)
    drive_in_doors    = Column(Integer, nullable=True)
    rail_service      = Column(Boolean, nullable=True)
    rail_service_type = Column(String, nullable=True)
    power_amps        = Column(String, nullable=True)
    power_volts       = Column(String, nullable=True)
    power_phase       = Column(String, nullable=True)
    column_spacing    = Column(String, nullable=True)
    floor_thickness   = Column(Float, nullable=True)
    floor_load        = Column(Float, nullable=True)
    sprinklers        = Column(Boolean, nullable=True)
    sprinkler_type    = Column(String, nullable=True)
    crane_capacity    = Column(Float, nullable=True)
    crane_height      = Column(Float, nullable=True)
    office_pct        = Column(Float, nullable=True)
    office_sf         = Column(Float, nullable=True)
    yard_area         = Column(Float, nullable=True)
    secured_yard      = Column(Boolean, nullable=True)
    cross_dock        = Column(Boolean, nullable=True)

    # ── Retail fields ────────────────────────────────────────────────────────
    anchor_tenant      = Column(String, nullable=True)
    inline_space       = Column(Boolean, nullable=True)
    end_cap            = Column(Boolean, nullable=True)
    pylon_sign         = Column(Boolean, nullable=True)
    monument_sign      = Column(Boolean, nullable=True)
    traffic_count      = Column(Integer, nullable=True)
    frontage_ft        = Column(Float, nullable=True)
    drive_through      = Column(Boolean, nullable=True)
    number_of_buildings = Column(Integer, nullable=True)

    # ── Office fields ────────────────────────────────────────────────────────
    building_class    = Column(String, nullable=True)   # A, B, C
    fiber_optic       = Column(Boolean, nullable=True)
    generator         = Column(Boolean, nullable=True)
    raised_floor      = Column(Boolean, nullable=True)
    data_center_ready = Column(Boolean, nullable=True)
    leed_certified    = Column(String, nullable=True)
    energy_star       = Column(Boolean, nullable=True)

    # ── Multifamily fields ───────────────────────────────────────────────────
    unit_mix           = Column(String, nullable=True)
    avg_unit_sf        = Column(Float, nullable=True)
    avg_rent_per_unit  = Column(Float, nullable=True)
    avg_rent_per_sf    = Column(Float, nullable=True)
    laundry            = Column(String, nullable=True)
    pet_friendly       = Column(Boolean, nullable=True)
    affordable_units   = Column(Integer, nullable=True)
    market_rate_units  = Column(Integer, nullable=True)

    # ── Hospitality fields ───────────────────────────────────────────────────
    number_of_rooms  = Column(Integer, nullable=True)
    flag             = Column(String, nullable=True)
    franchise_expiry = Column(Date, nullable=True)
    adr              = Column(Float, nullable=True)   # average daily rate
    revpar           = Column(Float, nullable=True)   # revenue per available room
    restaurant_seats = Column(Integer, nullable=True)
    meeting_space_sf = Column(Float, nullable=True)
    pool_hotel       = Column(Boolean, nullable=True)
    fitness_center   = Column(Boolean, nullable=True)

    # ── Medical fields ───────────────────────────────────────────────────────
    exam_rooms       = Column(Integer, nullable=True)
    procedure_rooms  = Column(Integer, nullable=True)
    imaging_rooms    = Column(Integer, nullable=True)
    surgical_suites  = Column(Integer, nullable=True)
    icu_beds         = Column(Integer, nullable=True)
    licensed_beds    = Column(Integer, nullable=True)
    medical_gas      = Column(Boolean, nullable=True)
    emergency_power  = Column(Boolean, nullable=True)

    # ── Land fields ──────────────────────────────────────────────────────────
    zoning_jurisdiction = Column(String, nullable=True)
    floodplain          = Column(Boolean, nullable=True)
    floodplain_zone     = Column(String, nullable=True)
    wetlands            = Column(Boolean, nullable=True)
    wetlands_acres      = Column(Float, nullable=True)
    utilities_to_site   = Column(Boolean, nullable=True)
    road_frontage_ft    = Column(Float, nullable=True)
    corner_lot          = Column(Boolean, nullable=True)
    subdivided          = Column(Boolean, nullable=True)
    number_of_lots      = Column(Integer, nullable=True)
    plat_recorded       = Column(Boolean, nullable=True)
    environmental       = Column(String, nullable=True)

    # ── Extended financial ───────────────────────────────────────────────────
    gross_income      = Column(Float, nullable=True)
    operating_expense = Column(Float, nullable=True)
    vacancy_allowance = Column(Float, nullable=True)
    expense_ratio     = Column(Float, nullable=True)
    debt_service      = Column(Float, nullable=True)
    cash_flow         = Column(Float, nullable=True)
    price_per_unit    = Column(Float, nullable=True)
    price_per_room    = Column(Float, nullable=True)
    lease_type        = Column(String, nullable=True)
    tenant_pays       = Column(String, nullable=True)
    owner_pays        = Column(String, nullable=True)
    lease_expiration  = Column(Date, nullable=True)
    lease_term_months = Column(Integer, nullable=True)
    renewal_options   = Column(String, nullable=True)
    rent_bumps        = Column(String, nullable=True)

    # ── General commercial ───────────────────────────────────────────────────
    business_name     = Column(String, nullable=True)
    business_type     = Column(String, nullable=True)
    employee_count    = Column(Integer, nullable=True)
    franchise         = Column(Boolean, nullable=True)
    franchise_name    = Column(String, nullable=True)
    opportunity_zone  = Column(Boolean, nullable=True)
    enterprise_zone   = Column(Boolean, nullable=True)
    historic_district = Column(Boolean, nullable=True)
    tif_district      = Column(Boolean, nullable=True)

    # ── Residential (future use, all nullable) ───────────────────────────────
    bedrooms        = Column(Integer, nullable=True)
    bathrooms       = Column(Float, nullable=True)
    garage_spaces   = Column(Integer, nullable=True)
    hoa_fee         = Column(Float, nullable=True)
    hoa_frequency   = Column(String, nullable=True)
    school_district = Column(String, nullable=True)
    has_basement    = Column(Boolean, nullable=True)
    has_fireplace   = Column(Boolean, nullable=True)
    has_pool        = Column(Boolean, nullable=True)
    mls_number      = Column(String, nullable=True)
    list_date       = Column(Date, nullable=True)
    days_on_market  = Column(Integer, nullable=True)

    # Notes
    notes           = Column(Text)

    # Timestamps
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner       = relationship("User",     back_populates="properties")
    account     = relationship("Account",  back_populates="properties",
                                foreign_keys=[account_id])
    deals       = relationship("Deal",     back_populates="property")
    activities  = relationship("Activity", back_populates="property")
    documents   = relationship("Document", back_populates="property")
    comps       = relationship("Comp",     back_populates="property")
