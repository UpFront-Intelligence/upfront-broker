"""add commercial property type fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-04

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa_inspect(op.get_bind())
    existing = {c['name'] for c in inspector.get_columns('properties')}

    new_cols = [
        # Industrial
        ('clear_height_min',  sa.Float(),   True),
        ('clear_height_max',  sa.Float(),   True),
        ('dock_doors',        sa.Integer(), True),
        ('drive_in_doors',    sa.Integer(), True),
        ('rail_service',      sa.Boolean(), True),
        ('rail_service_type', sa.String(),  True),
        ('power_amps',        sa.String(),  True),
        ('power_volts',       sa.String(),  True),
        ('power_phase',       sa.String(),  True),
        ('column_spacing',    sa.String(),  True),
        ('floor_thickness',   sa.Float(),   True),
        ('floor_load',        sa.Float(),   True),
        ('sprinklers',        sa.Boolean(), True),
        ('sprinkler_type',    sa.String(),  True),
        ('crane_capacity',    sa.Float(),   True),
        ('crane_height',      sa.Float(),   True),
        ('office_pct',        sa.Float(),   True),
        ('office_sf',         sa.Float(),   True),
        ('yard_area',         sa.Float(),   True),
        ('secured_yard',      sa.Boolean(), True),
        ('cross_dock',        sa.Boolean(), True),
        # Retail
        ('anchor_tenant',       sa.String(),  True),
        ('inline_space',        sa.Boolean(), True),
        ('end_cap',             sa.Boolean(), True),
        ('pylon_sign',          sa.Boolean(), True),
        ('monument_sign',       sa.Boolean(), True),
        ('traffic_count',       sa.Integer(), True),
        ('frontage_ft',         sa.Float(),   True),
        ('drive_through',       sa.Boolean(), True),
        ('number_of_buildings', sa.Integer(), True),
        # Office
        ('building_class',    sa.String(),  True),
        ('fiber_optic',       sa.Boolean(), True),
        ('generator',         sa.Boolean(), True),
        ('raised_floor',      sa.Boolean(), True),
        ('data_center_ready', sa.Boolean(), True),
        ('leed_certified',    sa.String(),  True),
        ('energy_star',       sa.Boolean(), True),
        # Multifamily
        ('unit_mix',          sa.String(),  True),
        ('avg_unit_sf',       sa.Float(),   True),
        ('avg_rent_per_unit', sa.Float(),   True),
        ('avg_rent_per_sf',   sa.Float(),   True),
        ('laundry',           sa.String(),  True),
        ('pet_friendly',      sa.Boolean(), True),
        ('affordable_units',  sa.Integer(), True),
        ('market_rate_units', sa.Integer(), True),
        # Hospitality
        ('number_of_rooms',  sa.Integer(), True),
        ('flag',             sa.String(),  True),
        ('franchise_expiry', sa.Date(),    True),
        ('adr',              sa.Float(),   True),
        ('revpar',           sa.Float(),   True),
        ('restaurant_seats', sa.Integer(), True),
        ('meeting_space_sf', sa.Float(),   True),
        ('pool_hotel',       sa.Boolean(), True),
        ('fitness_center',   sa.Boolean(), True),
        # Medical
        ('exam_rooms',      sa.Integer(), True),
        ('procedure_rooms', sa.Integer(), True),
        ('imaging_rooms',   sa.Integer(), True),
        ('surgical_suites', sa.Integer(), True),
        ('icu_beds',        sa.Integer(), True),
        ('licensed_beds',   sa.Integer(), True),
        ('medical_gas',     sa.Boolean(), True),
        ('emergency_power', sa.Boolean(), True),
        # Land
        ('zoning_jurisdiction', sa.String(),  True),
        ('floodplain',          sa.Boolean(), True),
        ('floodplain_zone',     sa.String(),  True),
        ('wetlands',            sa.Boolean(), True),
        ('wetlands_acres',      sa.Float(),   True),
        ('utilities_to_site',   sa.Boolean(), True),
        ('road_frontage_ft',    sa.Float(),   True),
        ('corner_lot',          sa.Boolean(), True),
        ('subdivided',          sa.Boolean(), True),
        ('number_of_lots',      sa.Integer(), True),
        ('plat_recorded',       sa.Boolean(), True),
        ('environmental',       sa.String(),  True),
        # Extended financial
        ('gross_income',      sa.Float(),   True),
        ('operating_expense', sa.Float(),   True),
        ('vacancy_allowance', sa.Float(),   True),
        ('expense_ratio',     sa.Float(),   True),
        ('debt_service',      sa.Float(),   True),
        ('cash_flow',         sa.Float(),   True),
        ('price_per_unit',    sa.Float(),   True),
        ('price_per_room',    sa.Float(),   True),
        ('lease_type',        sa.String(),  True),
        ('tenant_pays',       sa.String(),  True),
        ('owner_pays',        sa.String(),  True),
        ('lease_expiration',  sa.Date(),    True),
        ('lease_term_months', sa.Integer(), True),
        ('renewal_options',   sa.String(),  True),
        ('rent_bumps',        sa.String(),  True),
        # General commercial
        ('business_name',     sa.String(),  True),
        ('business_type',     sa.String(),  True),
        ('employee_count',    sa.Integer(), True),
        ('franchise',         sa.Boolean(), True),
        ('franchise_name',    sa.String(),  True),
        ('opportunity_zone',  sa.Boolean(), True),
        ('enterprise_zone',   sa.Boolean(), True),
        ('historic_district', sa.Boolean(), True),
        ('tif_district',      sa.Boolean(), True),
        # Residential (future)
        ('bedrooms',        sa.Integer(), True),
        ('bathrooms',       sa.Float(),   True),
        ('garage_spaces',   sa.Integer(), True),
        ('hoa_fee',         sa.Float(),   True),
        ('hoa_frequency',   sa.String(),  True),
        ('school_district', sa.String(),  True),
        ('has_basement',    sa.Boolean(), True),
        ('has_fireplace',   sa.Boolean(), True),
        ('has_pool',        sa.Boolean(), True),
        ('mls_number',      sa.String(),  True),
        ('list_date',       sa.Date(),    True),
        ('days_on_market',  sa.Integer(), True),
    ]

    for col_name, col_type, nullable in new_cols:
        if col_name not in existing:
            op.add_column('properties', sa.Column(col_name, col_type, nullable=nullable))


def downgrade() -> None:
    cols = [
        'clear_height_min','clear_height_max','dock_doors','drive_in_doors',
        'rail_service','rail_service_type','power_amps','power_volts','power_phase',
        'column_spacing','floor_thickness','floor_load','sprinklers','sprinkler_type',
        'crane_capacity','crane_height','office_pct','office_sf','yard_area',
        'secured_yard','cross_dock','anchor_tenant','inline_space','end_cap',
        'pylon_sign','monument_sign','traffic_count','frontage_ft','drive_through',
        'number_of_buildings','building_class','fiber_optic','generator','raised_floor',
        'data_center_ready','leed_certified','energy_star','unit_mix','avg_unit_sf',
        'avg_rent_per_unit','avg_rent_per_sf','laundry','pet_friendly',
        'affordable_units','market_rate_units','number_of_rooms','flag',
        'franchise_expiry','adr','revpar','restaurant_seats','meeting_space_sf',
        'pool_hotel','fitness_center','exam_rooms','procedure_rooms','imaging_rooms',
        'surgical_suites','icu_beds','licensed_beds','medical_gas','emergency_power',
        'zoning_jurisdiction','floodplain','floodplain_zone','wetlands','wetlands_acres',
        'utilities_to_site','road_frontage_ft','corner_lot','subdivided','number_of_lots',
        'plat_recorded','environmental','gross_income','operating_expense',
        'vacancy_allowance','expense_ratio','debt_service','cash_flow','price_per_unit',
        'price_per_room','lease_type','tenant_pays','owner_pays','lease_expiration',
        'lease_term_months','renewal_options','rent_bumps','business_name',
        'business_type','employee_count','franchise','franchise_name','opportunity_zone',
        'enterprise_zone','historic_district','tif_district','bedrooms','bathrooms',
        'garage_spaces','hoa_fee','hoa_frequency','school_district','has_basement',
        'has_fireplace','has_pool','mls_number','list_date','days_on_market',
    ]
    for col in cols:
        op.drop_column('properties', col)
