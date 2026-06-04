"""
CSV / XLSX import with intelligent fuzzy field mapping.

POST /api/import/preview  — parse headers, suggest mapping with confidence scores
POST /api/import/execute  — import rows using confirmed mapping, detect duplicates
"""
import csv
import io
import json
import re
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from rapidfuzz import fuzz
import openpyxl

from database import get_db
from models.user import User
from models.property import Property
from models.contact import Contact
from models.account import Account
from models.contact_account import ContactAccount
from auth_utils import get_current_user

router = APIRouter()

# ── RESO Data Dictionary 2.1 — complete field + synonym registry ─────────────
# type: "commercial" | "residential" | "both"
# synonyms: RESO CamelCase field names + human-readable variants
# When record_type="property" all synonyms are used regardless of type.
# The type tag enables future residential-only / commercial-only filtering.

RESO_SYNONYMS = {
    # ── Location ────────────────────────────────────────────────────────────
    "address": {
        "type": "both",
        "synonyms": ["UnparsedAddress","StreetAddress","FullStreetAddress","PropertyAddress",
                     "SiteAddress","BuildingAddress","address","property address",
                     "street address","street","addr","property addr","site address","location"],
    },
    "city": {
        "type": "both",
        "synonyms": ["City","PostalCity","city","municipality","town"],
    },
    "state": {
        "type": "both",
        "synonyms": ["StateOrProvince","State","state","st","province"],
    },
    "zip": {
        "type": "both",
        "synonyms": ["PostalCode","Zip","ZipCode","zip","zip code","postal","postal code"],
    },
    "county": {
        "type": "both",
        "synonyms": ["CountyOrParish","County","county","county name","jurisdiction"],
    },
    # ── Classification ───────────────────────────────────────────────────────
    "property_type": {
        "type": "both",
        "synonyms": ["PropertyType","PropertySubType","PropertyUse","LandUse",
                     "type","property type","asset type","use type","space use","building type"],
    },
    "subtype": {
        "type": "both",
        "synonyms": ["PropertySubType","PropertySubTypeAdditional","ArchitecturalStyle",
                     "subtype","sub type","sub-type","secondary type","building class",
                     "property subtype","class"],
    },
    "status": {
        "type": "both",
        "synonyms": ["StandardStatus","MlsStatus","ListingStatus",
                     "status","listing status","property status"],
    },
    # ── Physical — commercial ────────────────────────────────────────────────
    "sf_rentable": {
        "type": "commercial",
        "synonyms": ["BuildingAreaTotal","LeasableArea","LeasableAreaUnits",
                     "GrossLeasableArea","GLA","RentableArea","BuildingAreaUnits",
                     "sf","sqft","square feet","building size","rentable sf","rba",
                     "building sf","size","gla","rentable area"],
    },
    "sf_land": {
        "type": "commercial",
        "synonyms": ["LotSizeSquareFeet","LotSizeArea","LotSizeUnits","LandArea",
                     "sf land","land sf","land area sf","land size","lot size sf",
                     "land square feet","lot sf","acreage sf","land area"],
    },
    "units": {
        "type": "both",
        "synonyms": ["NumberOfUnitsTotal","NumberOfUnitsInCommunity","UnitCount",
                     "NumberOfBuildings","units","unit count","number of units",
                     "# units","apt units"],
    },
    "stories": {
        "type": "both",
        "synonyms": ["StoriesTotal","Levels","NumberOfFloors",
                     "stories","floors","number of floors","num floors",
                     "building stories","number of stories","# floors","# stories"],
    },
    "year_built": {
        "type": "both",
        "synonyms": ["YearBuilt","YearBuiltEffective","YearEstablished",
                     "year built","year","built","year constructed"],
    },
    "zoning": {
        "type": "both",
        "synonyms": ["Zoning","ZoningDescription","zoning","zone","land use code"],
    },
    "parking_ratio": {
        "type": "commercial",
        "synonyms": ["ParkingRatio","ParkingTotal","GarageSpaces","ParkingFeatures",
                     "parking ratio","parking","parking spaces per 1000",
                     "parking/1000","p/1000","parking rate"],
    },
    "occupancy_pct": {
        "type": "commercial",
        "synonyms": ["OccupancyRate","OccupancyPercent","PercentLeased",
                     "occupancy pct","occupancy %","occupancy percent","occupancy",
                     "occupied pct","leased pct","leased %","percent leased",
                     "percent occupied","current occupancy","occ %","occ pct"],
    },
    # ── Physical — residential ───────────────────────────────────────────────
    "bedrooms": {
        "type": "residential",
        "synonyms": ["BedroomsTotal","Bedrooms","BedsBaths","bedroom_count",
                     "beds","# bedrooms","bed count"],
    },
    "bathrooms": {
        "type": "residential",
        "synonyms": ["BathroomsTotalInteger","Bathrooms","BathroomsFull","BathroomsHalf",
                     "BathroomsThreeQuarter","bathroom_count","baths","beds_baths",
                     "# bathrooms","bath count"],
    },
    "garage_spaces": {
        "type": "residential",
        "synonyms": ["GarageSpaces","CarportSpaces","ParkingTotal","garage_spaces",
                     "parking_spaces","GarageYN","attached garage","detached garage"],
    },
    "lot_size_acres": {
        "type": "residential",
        "synonyms": ["LotSizeAcres","LotSizeArea","lot_size_acres","LotSizeSquareFeet",
                     "lot_acres","acreage","lot size","lot acres"],
    },
    "hoa_fee": {
        "type": "residential",
        "synonyms": ["AssociationFee","HOAFee","AssociationFeeFrequency","hoa_fee",
                     "association_fee","HOADues","MonthlyHOA","hoa","monthly hoa",
                     "association fee"],
    },
    "school_district": {
        "type": "residential",
        "synonyms": ["ElementarySchool","MiddleSchool","HighSchool","SchoolDistrict",
                     "school_district","ElementarySchoolDistrict","school district",
                     "schools","school"],
    },
    "basement": {
        "type": "residential",
        "synonyms": ["BasementYN","Basement","BelowGradeFinishedArea","basement",
                     "has_basement","finished basement","unfinished basement"],
    },
    "fireplace": {
        "type": "residential",
        "synonyms": ["FireplaceYN","FireplacesTotal","Fireplace","fireplace",
                     "fireplace_count","# fireplaces","has fireplace"],
    },
    "pool": {
        "type": "residential",
        "synonyms": ["PoolYN","PoolFeatures","pool","has_pool","PoolPrivateYN",
                     "private pool","community pool"],
    },
    # ── Physical — both ──────────────────────────────────────────────────────
    "heating": {
        "type": "both",
        "synonyms": ["Heating","HeatingYN","CoolingYN","Cooling","HeatingFeatures",
                     "CoolingFeatures","HVAC","hvac_type","heating type","cooling type",
                     "heat","air conditioning","hvac"],
    },
    "roof": {
        "type": "both",
        "synonyms": ["Roof","RoofFeatures","roof_type","roofing",
                     "roof material","roof type"],
    },
    "construction": {
        "type": "both",
        "synonyms": ["ConstructionMaterials","construction_materials","FoundationDetails",
                     "foundation","ArchitecturalStyle","construction_type",
                     "building construction","construction material"],
    },
    # ── Commercial specialty ─────────────────────────────────────────────────
    "clear_height": {
        "type": "commercial",
        "synonyms": ["ClearHeight","clear_height","CeilingHeight","ceiling_height",
                     "WarehouseCeilingHeight","MinClearCeilingHeight",
                     "clear span height","warehouse height"],
    },
    "dock_doors": {
        "type": "commercial",
        "synonyms": ["DockHighDoors","dock_doors","NumberOfDockDoors","LoadingDocks",
                     "DockHighDoorsCount","# dock doors","loading dock doors",
                     "truck docks"],
    },
    "drive_in_doors": {
        "type": "commercial",
        "synonyms": ["DriveInDoors","drive_in_doors","GradeLevel","GradeLevelDoors",
                     "DriveInDoorsCount","grade level doors","drive-in doors",
                     "grade level access"],
    },
    "rail_service": {
        "type": "commercial",
        "synonyms": ["RailServiceType","rail_service","RailAccess","RailServiceYN",
                     "rail access","railroad siding","rail spur"],
    },
    "power_amps": {
        "type": "commercial",
        "synonyms": ["ElectricOnPropertyYN","power_amps","Voltage","Amps",
                     "ElectricService","ThreePhaseElectric","electrical service",
                     "3 phase","three phase","amps","voltage"],
    },
    "sprinklers": {
        "type": "commercial",
        "synonyms": ["SprinklersYN","sprinklers","FireSprinklerYN","SprinklerSystem",
                     "FireProtection","fire sprinkler","sprinkler system",
                     "wet sprinkler","dry sprinkler"],
    },
    "lease_type": {
        "type": "commercial",
        "synonyms": ["LeaseType","lease_type","LeaseTerm","LeaseExpiration",
                     "LeaseRenewalOption","LeaseAssignableTo","CurrentLeaseType",
                     "NNNLeaseYN","nnn","gross lease","modified gross",
                     "absolute net"],
    },
    "tenant_pays": {
        "type": "commercial",
        "synonyms": ["TenantPays","tenant_pays","TenantExpenses","LesseeResponsibility",
                     "tenant expenses","lessee pays"],
    },
    "owner_pays": {
        "type": "commercial",
        "synonyms": ["OwnerPays","owner_pays","LandlordResponsibility","OwnerExpenses",
                     "landlord pays","lessor pays"],
    },
    "gross_income": {
        "type": "commercial",
        "synonyms": ["GrossIncome","gross_income","GrossScheduledIncome","GrossRentalIncome",
                     "PotentialGrossIncome","egi","effective gross income",
                     "scheduled gross income"],
    },
    "operating_expense": {
        "type": "commercial",
        "synonyms": ["OperatingExpense","operating_expense","AnnualExpense","TotalExpenses",
                     "OperatingExpenses","opex","total operating expenses",
                     "annual operating expenses"],
    },
    "vacancy_allowance": {
        "type": "commercial",
        "synonyms": ["VacancyAllowance","vacancy_allowance","VacancyRate","VacancyPercent",
                     "EstimatedVacancy","vacancy rate","vacancy %","vacancy factor"],
    },
    "business_name": {
        "type": "commercial",
        "synonyms": ["BusinessName","business_name","TenantName","CurrentTenant",
                     "OccupantName","Occupant","business name","current occupant",
                     "tenant","tenants","current tenant","occupant"],
    },
    "business_type": {
        "type": "commercial",
        "synonyms": ["BusinessType","business_type","PropertyUse","CurrentUse",
                     "LandUse","UseCode","business type","property use",
                     "current use","land use"],
    },
    # ── Financial ────────────────────────────────────────────────────────────
    "asking_price": {
        "type": "both",
        "synonyms": ["ListPrice","OriginalListPrice","CurrentPrice","ClosePrice",
                     "asking price","list price","total price","offer price","asking total"],
    },
    "asking_price_per_sf": {
        "type": "commercial",
        "synonyms": ["PricePerSquareFoot","ListPricePerUnit",
                     "asking price per sf","asking psf","price per sf","$/sf",
                     "price/sf","asking $/sf","list price psf","per sf","psf"],
    },
    "assessed_value": {
        "type": "both",
        "synonyms": ["TaxAssessedValue","AssessedValue","TaxAppraisedValue",
                     "assessed value","assessment","tax value","assessed"],
    },
    "tax_amount": {
        "type": "both",
        "synonyms": ["TaxAnnualAmount","TaxAmount","RealEstateTaxes",
                     "tax amount","taxes","tax","annual tax","property tax",
                     "tax bill","real estate tax","tax assessment amount"],
    },
    "tax_year": {
        "type": "both",
        "synonyms": ["TaxYear","TaxAssessmentYear",
                     "tax year","assessment year","tax yr","year assessed"],
    },
    "cap_rate": {
        "type": "commercial",
        "synonyms": ["CapRate","CapitalizationRate","cap rate","cap","capitalization rate"],
    },
    "noi": {
        "type": "commercial",
        "synonyms": ["NetOperatingIncome","NOI","noi","net operating income","net income",
                     "annual noi","operating income"],
    },
    "last_sale_price": {
        "type": "both",
        "synonyms": ["ClosePrice","SalePrice","PreviousSalePrice",
                     "last sale price","sold price","last sold price","close price"],
    },
    "last_sale_date": {
        "type": "both",
        "synonyms": ["CloseDate","PurchaseContractDate","PreviousSaleDate",
                     "last sale date","sold date","sale date","last sold date","close date"],
    },
    # ── Public records ───────────────────────────────────────────────────────
    "parcel_id": {
        "type": "both",
        "synonyms": ["ParcelNumber","AssessorsParcelNumber","APN","PIN","TaxId",
                     "TaxParcelNumber","TaxLot","KeyPin",
                     "parcel","parcel id","pin","apn","parcel number","tax id"],
    },
    "zoning": {
        "type": "both",
        "synonyms": ["Zoning","ZoningDescription","ZoningCode",
                     "zoning","zone","zoning code","land use code"],
    },
    "tenant": {
        "type": "commercial",
        "synonyms": ["TenantName","CurrentTenant","OccupantName",
                     "tenant","tenants","current tenant","occupant"],
    },
    # ── Listing / MLS ────────────────────────────────────────────────────────
    "mls_number": {
        "type": "both",
        "synonyms": ["ListingId","MLSNumber","MLS#","mls_number","listing_id","MLSID",
                     "MatrixUniqueID","ListingKey","mls number","mls id","listing number"],
    },
    "days_on_market": {
        "type": "both",
        "synonyms": ["DaysOnMarket","days_on_market","DOM","CumulativeDaysOnMarket","CDOM",
                     "days on market","dom","cumulative dom"],
    },
    "list_date": {
        "type": "both",
        "synonyms": ["ListingContractDate","ListDate","list_date","OnMarketDate",
                     "OriginalEntryTimestamp","listing date","on market date","listed date"],
    },
    "expiration_date": {
        "type": "both",
        "synonyms": ["ExpirationDate","expiration_date","ContractStatusChangeDate",
                     "ListingExpirationDate","expiration","listing expiration"],
    },
    "listing_agent": {
        "type": "both",
        "synonyms": ["ListAgentFullName","ListAgentFirstName","ListAgentLastName",
                     "ListAgentEmail","ListAgentDirectPhone","listing_agent",
                     "AgentName","ListingAgent","listing agent","agent name","agent"],
    },
    "listing_office": {
        "type": "both",
        "synonyms": ["ListOfficeName","ListOfficePhone","ListOfficeEmail","listing_office",
                     "OfficeName","BrokerageName","listing office","brokerage","office name"],
    },
    "showing_instructions": {
        "type": "both",
        "synonyms": ["ShowingInstructions","showing_instructions","ShowingContactName",
                     "ShowingContactPhone","showing instructions","access instructions"],
    },
    "virtual_tour": {
        "type": "both",
        "synonyms": ["VirtualTourURLUnbranded","VirtualTourURLBranded","virtual_tour",
                     "TourURL","Video3DTourURL","virtual tour","tour url","3d tour"],
    },
    # ── General ──────────────────────────────────────────────────────────────
    "name": {
        "type": "both",
        "synonyms": ["PropertyName","BuildingName","name","property name","building name"],
    },
    "notes": {
        "type": "both",
        "synonyms": ["PublicRemarks","PrivateRemarks","SyndicationRemarks",
                     "notes","comments","description","remarks","memo","public remarks"],
    },
    # ── Owner / linked-silo fields ───────────────────────────────────────────
    "owner_name": {
        "type": "both",
        "synonyms": ["ListOwnerName","OwnerName","TaxOwner",
                     "owner name","owner","landlord","property owner",
                     "ownername1","ownername"],
    },
    "owner_contact": {
        "type": "both",
        "synonyms": ["owner contact","contact name","contact person","owner contact name"],
    },
    "owner_phone": {
        "type": "both",
        "synonyms": ["OwnerPhone","owner phone","phone","owner phone number","contact phone"],
    },
    "owner_email": {
        "type": "both",
        "synonyms": ["OwnerEmail","owner email","email","owner email address","contact email"],
    },
    "owner_address": {
        "type": "both",
        "synonyms": ["OwnerAddress","TaxOwnerAddress",
                     "owner address","mailing address","owner mailing address"],
    },
    "owner_city_state_zip": {
        "type": "both",
        "synonyms": ["owner city state zip","city state zip","owner csz"],
    },
    # ── New commercial fields ────────────────────────────────────────────────
    "clear_height_min": {
        "type": "commercial",
        "synonyms": ["ClearHeight","clear_height","MinClearCeilingHeight","ceiling_height",
                     "WarehouseClearHeight","clear height","min clear height","eave height"],
    },
    "clear_height_max": {
        "type": "commercial",
        "synonyms": ["MaxClearHeight","max_clear_height","MaxCeilingHeight",
                     "max clear height","ridge height","peak height"],
    },
    "power_phase": {
        "type": "commercial",
        "synonyms": ["ThreePhaseElectric","power_phase","ElectricPhase","Phase",
                     "3 phase","three phase","single phase","electric phase"],
    },
    "power_volts": {
        "type": "commercial",
        "synonyms": ["Voltage","power_volts","ElectricVoltage","volts","voltage"],
    },
    "column_spacing": {
        "type": "commercial",
        "synonyms": ["ColumnSpacing","column_spacing","BaySize","BayDepth","bay spacing",
                     "bay size","structural bays"],
    },
    "floor_thickness": {
        "type": "commercial",
        "synonyms": ["FloorThickness","floor_thickness","ConcreteThickness","slab thickness",
                     "floor slab","concrete floor"],
    },
    "floor_load": {
        "type": "commercial",
        "synonyms": ["FloorLoad","floor_load","FloorLoadCapacity","load capacity",
                     "floor capacity","pounds per sf"],
    },
    "sprinkler_type": {
        "type": "commercial",
        "synonyms": ["SprinklerType","sprinkler_type","FireSprinklerType",
                     "wet sprinkler","dry sprinkler","ESFR"],
    },
    "crane_capacity": {
        "type": "commercial",
        "synonyms": ["CraneCapacity","crane_capacity","CraneTons","overhead crane",
                     "crane tons","bridge crane"],
    },
    "crane_height": {
        "type": "commercial",
        "synonyms": ["CraneHeight","crane_height","CraneHookHeight",
                     "crane hook height","hook height"],
    },
    "office_pct": {
        "type": "commercial",
        "synonyms": ["OfficePct","office_pct","OfficePercent","office percent",
                     "% office","office ratio"],
    },
    "office_sf": {
        "type": "commercial",
        "synonyms": ["OfficeSF","office_sf","OfficeArea","office area","office square feet",
                     "office space"],
    },
    "yard_area": {
        "type": "commercial",
        "synonyms": ["YardArea","yard_area","OutdoorStorageArea","yard","storage yard",
                     "outdoor storage","truck yard"],
    },
    "secured_yard": {
        "type": "commercial",
        "synonyms": ["SecuredYard","secured_yard","FencedYard","fenced yard",
                     "secured storage","gated yard"],
    },
    "cross_dock": {
        "type": "commercial",
        "synonyms": ["CrossDock","cross_dock","CrossDocking","cross dock",
                     "cross-dock","cross docking"],
    },
    "anchor_tenant": {
        "type": "commercial",
        "synonyms": ["AnchorTenant","anchor_tenant","MajorTenant","PrimaryTenant",
                     "anchor store","anchor","major tenant"],
    },
    "inline_space": {
        "type": "commercial",
        "synonyms": ["InlineSpace","inline_space","InlineUnit","inline unit","in-line",
                     "inline store"],
    },
    "end_cap": {
        "type": "commercial",
        "synonyms": ["EndCap","end_cap","EndUnit","end unit","end cap unit"],
    },
    "pylon_sign": {
        "type": "commercial",
        "synonyms": ["PylonSign","pylon_sign","PylonSignYN","pylon","pole sign",
                     "freestanding sign"],
    },
    "monument_sign": {
        "type": "commercial",
        "synonyms": ["MonumentSign","monument_sign","MonumentSignYN","monument",
                     "ground sign","low profile sign"],
    },
    "traffic_count": {
        "type": "commercial",
        "synonyms": ["TrafficCount","traffic_count","VehicleCount","DailyTrafficCount",
                     "AADT","cars per day","average daily traffic","vehicles per day"],
    },
    "frontage_ft": {
        "type": "commercial",
        "synonyms": ["Frontage","frontage_ft","StreetFrontage","LotFrontage",
                     "road frontage","frontage","linear feet"],
    },
    "drive_through": {
        "type": "commercial",
        "synonyms": ["DriveThrough","drive_through","DriveThroughYN","drive-through",
                     "drive thru","drive-thru"],
    },
    "number_of_buildings": {
        "type": "commercial",
        "synonyms": ["NumberOfBuildings","number_of_buildings","BuildingCount",
                     "# buildings","number buildings","buildings on site"],
    },
    "building_class": {
        "type": "commercial",
        "synonyms": ["BuildingClass","building_class","Class","PropertyClass",
                     "building grade","office class","class a","class b","class c"],
    },
    "fiber_optic": {
        "type": "commercial",
        "synonyms": ["FiberOptic","fiber_optic","FiberOpticYN","fiber","fiber internet",
                     "fiber connectivity","dark fiber"],
    },
    "generator": {
        "type": "commercial",
        "synonyms": ["Generator","generator","GeneratorYN","backup generator",
                     "emergency generator","standby generator"],
    },
    "raised_floor": {
        "type": "commercial",
        "synonyms": ["RaisedFloor","raised_floor","RaisedFloorYN","raised access floor",
                     "access floor","computer floor"],
    },
    "data_center_ready": {
        "type": "commercial",
        "synonyms": ["DataCenterReady","data_center_ready","DataCenterYN",
                     "data center","tech ready","mission critical"],
    },
    "leed_certified": {
        "type": "commercial",
        "synonyms": ["LEED","leed_certified","GreenCertification","EnergyStarYN",
                     "leed gold","leed silver","leed platinum","green building",
                     "energy certification"],
    },
    "energy_star": {
        "type": "commercial",
        "synonyms": ["EnergyStar","energy_star","EnergyStarYN","energy star certified",
                     "EPA energy star"],
    },
    "unit_mix": {
        "type": "commercial",
        "synonyms": ["UnitMix","unit_mix","UnitTypes","ApartmentMix","unit breakdown",
                     "unit type mix","bedroom mix"],
    },
    "avg_unit_sf": {
        "type": "commercial",
        "synonyms": ["AverageUnitSize","avg_unit_sf","AvgUnitSF","average unit size",
                     "avg unit size","average unit sf"],
    },
    "avg_rent_per_unit": {
        "type": "commercial",
        "synonyms": ["AverageRent","avg_rent_per_unit","AvgMonthlyRent",
                     "AverageMonthlyRent","average rent","avg monthly rent",
                     "average monthly rent per unit"],
    },
    "avg_rent_per_sf": {
        "type": "commercial",
        "synonyms": ["AverageRentPerSF","avg_rent_per_sf","AvgRentPSF",
                     "average rent per sf","avg rent psf","rent psf"],
    },
    "laundry": {
        "type": "commercial",
        "synonyms": ["LaundryFeatures","laundry","LaundryFacilities","WasherDryer",
                     "laundry facilities","on-site laundry","laundry room"],
    },
    "pet_friendly": {
        "type": "commercial",
        "synonyms": ["PetPolicy","pet_friendly","PetsAllowed","PetFriendlyYN",
                     "pets allowed","dogs allowed","pet policy"],
    },
    "affordable_units": {
        "type": "commercial",
        "synonyms": ["AffordableUnits","affordable_units","LowIncomeUnits",
                     "subsidized units","income restricted","affordable housing units"],
    },
    "market_rate_units": {
        "type": "commercial",
        "synonyms": ["MarketRateUnits","market_rate_units","MarketUnits",
                     "market rate","unrestricted units"],
    },
    "number_of_rooms": {
        "type": "commercial",
        "synonyms": ["NumberOfRooms","number_of_rooms","RoomCount","HotelRooms",
                     "Rooms","total rooms","room count","keys","number of keys"],
    },
    "flag": {
        "type": "commercial",
        "synonyms": ["Flag","flag","HotelFlag","HotelBrand","brand","hotel brand",
                     "franchise flag","hotel chain"],
    },
    "franchise_expiry": {
        "type": "commercial",
        "synonyms": ["FranchiseExpiry","franchise_expiry","FranchiseExpiration",
                     "LicenseExpiry","PLA expiry","franchise expiration date"],
    },
    "adr": {
        "type": "commercial",
        "synonyms": ["AverageDailyRate","ADR","adr","AvgDailyRate",
                     "average daily rate","room rate","average room rate"],
    },
    "revpar": {
        "type": "commercial",
        "synonyms": ["RevPAR","revpar","RevenuePerAvailableRoom","RevPar",
                     "revenue per available room"],
    },
    "restaurant_seats": {
        "type": "commercial",
        "synonyms": ["RestaurantSeats","restaurant_seats","DiningCapacity",
                     "seating capacity","restaurant capacity","f&b seats"],
    },
    "meeting_space_sf": {
        "type": "commercial",
        "synonyms": ["MeetingSpaceSF","meeting_space_sf","MeetingRoomSF",
                     "conference space","event space sf","ballroom sf","meeting room area"],
    },
    "pool_hotel": {
        "type": "commercial",
        "synonyms": ["PoolYN","pool_hotel","PoolFeatures","has pool","swimming pool",
                     "indoor pool","outdoor pool"],
    },
    "fitness_center": {
        "type": "commercial",
        "synonyms": ["FitnessCenter","fitness_center","FitnessCenterYN","gym",
                     "exercise room","health club","fitness room"],
    },
    "exam_rooms": {
        "type": "commercial",
        "synonyms": ["ExamRooms","exam_rooms","MedicalRooms","ClinicalRooms",
                     "examination rooms","clinical spaces","consult rooms"],
    },
    "procedure_rooms": {
        "type": "commercial",
        "synonyms": ["ProcedureRooms","procedure_rooms","TreatmentRooms",
                     "procedure suites","treatment rooms","minor procedure rooms"],
    },
    "imaging_rooms": {
        "type": "commercial",
        "synonyms": ["ImagingRooms","imaging_rooms","RadiologyRooms",
                     "imaging suites","radiology","x-ray rooms","MRI rooms"],
    },
    "surgical_suites": {
        "type": "commercial",
        "synonyms": ["SurgicalSuites","surgical_suites","ORs","OperatingRooms",
                     "operating suites","OR count","operating rooms"],
    },
    "icu_beds": {
        "type": "commercial",
        "synonyms": ["ICUBeds","icu_beds","IntensiveCareUnit","critical care beds",
                     "ICU capacity","intensive care beds"],
    },
    "licensed_beds": {
        "type": "commercial",
        "synonyms": ["LicensedBeds","licensed_beds","HospitalBeds","TotalBeds",
                     "bed count","total licensed beds","hospital capacity"],
    },
    "medical_gas": {
        "type": "commercial",
        "synonyms": ["MedicalGas","medical_gas","MedicalGasYN","oxygen","med gas",
                     "piped oxygen","medical gases"],
    },
    "emergency_power": {
        "type": "commercial",
        "synonyms": ["EmergencyPower","emergency_power","BackupPower","UPS",
                     "emergency generator","backup power system","emergency electrical"],
    },
    "zoning_jurisdiction": {
        "type": "both",
        "synonyms": ["ZoningJurisdiction","zoning_jurisdiction","Municipality",
                     "governing body","zoning authority","jurisdiction"],
    },
    "floodplain": {
        "type": "both",
        "synonyms": ["FloodZone","floodplain","FloodPlainYN","FEMA_Zone",
                     "flood zone","in floodplain","FEMA flood"],
    },
    "floodplain_zone": {
        "type": "both",
        "synonyms": ["FloodZoneCode","FEMAFloodZone","floodplain_zone",
                     "FloodZoneDescription","FEMA zone","flood designation","AE zone"],
    },
    "wetlands": {
        "type": "both",
        "synonyms": ["WetlandsYN","wetlands","WetlandArea","HasWetlands",
                     "has wetlands","wetland","delineated wetlands"],
    },
    "wetlands_acres": {
        "type": "both",
        "synonyms": ["WetlandsAcres","wetlands_acres","WetlandAreaAcres",
                     "wetland acres","wetland area"],
    },
    "utilities_to_site": {
        "type": "both",
        "synonyms": ["UtilitiesToSite","utilities_to_site","UtilitiesAvailable",
                     "utilities at site","utilities stubbed","site utilities"],
    },
    "road_frontage_ft": {
        "type": "both",
        "synonyms": ["RoadFrontage","road_frontage_ft","StreetFrontage",
                     "road frontage feet","highway frontage","arterial frontage"],
    },
    "corner_lot": {
        "type": "both",
        "synonyms": ["CornerLot","corner_lot","CornerLotYN","corner","corner location",
                     "corner parcel"],
    },
    "subdivided": {
        "type": "both",
        "synonyms": ["Subdivided","subdivided","SubdividedYN","can be subdivided",
                     "divisible","subdividable"],
    },
    "number_of_lots": {
        "type": "both",
        "synonyms": ["NumberOfLots","number_of_lots","LotCount","total lots",
                     "# lots","parcels","parcel count"],
    },
    "plat_recorded": {
        "type": "both",
        "synonyms": ["PlatRecorded","plat_recorded","PlatRecordedYN","platted",
                     "plat filed","recorded plat"],
    },
    "environmental": {
        "type": "both",
        "synonyms": ["Environmental","environmental","EnvironmentalSurvey","Phase1",
                     "Phase2","environmental study","ESA","environmental report"],
    },
    "expense_ratio": {
        "type": "commercial",
        "synonyms": ["ExpenseRatio","expense_ratio","OperatingExpenseRatio",
                     "expense ratio","opex ratio","expense to income"],
    },
    "debt_service": {
        "type": "commercial",
        "synonyms": ["DebtService","debt_service","AnnualDebtService","DSCR",
                     "mortgage payment","loan payment","annual debt service"],
    },
    "cash_flow": {
        "type": "commercial",
        "synonyms": ["CashFlow","cash_flow","NetCashFlow","AfterTaxCashFlow",
                     "cash flow","net cash flow","free cash flow"],
    },
    "price_per_unit": {
        "type": "commercial",
        "synonyms": ["PricePerUnit","price_per_unit","CostPerUnit","ValuePerUnit",
                     "price per unit","per unit price","unit value"],
    },
    "price_per_room": {
        "type": "commercial",
        "synonyms": ["PricePerRoom","price_per_room","CostPerRoom","ValuePerKey",
                     "price per room","per key","per room"],
    },
    "lease_expiration": {
        "type": "commercial",
        "synonyms": ["LeaseExpiration","lease_expiration","LeaseEndDate","LeaseTerm",
                     "LeaseExpiryDate","lease expiry","lease end","expiry date"],
    },
    "lease_term_months": {
        "type": "commercial",
        "synonyms": ["LeaseTerm","lease_term_months","LeaseTermMonths","term months",
                     "lease term","lease length months"],
    },
    "renewal_options": {
        "type": "commercial",
        "synonyms": ["RenewalOptions","renewal_options","LeaseRenewalOption",
                     "renewal terms","options to renew","lease options"],
    },
    "rent_bumps": {
        "type": "commercial",
        "synonyms": ["RentBumps","rent_bumps","RentEscalations","CPI adjustments",
                     "annual increases","rent steps","rent escalations"],
    },
    "employee_count": {
        "type": "commercial",
        "synonyms": ["EmployeeCount","employee_count","NumberOfEmployees","Employees",
                     "staff count","headcount","employees"],
    },
    "franchise": {
        "type": "commercial",
        "synonyms": ["Franchise","franchise","FranchiseYN","franchised","is franchise",
                     "franchise business"],
    },
    "franchise_name": {
        "type": "commercial",
        "synonyms": ["FranchiseName","franchise_name","FranchiseBrand","franchise brand",
                     "franchisor","franchise company"],
    },
    "opportunity_zone": {
        "type": "both",
        "synonyms": ["OpportunityZone","opportunity_zone","OZone","QOZ","qualified OZ",
                     "opportunity fund zone","OZ designation"],
    },
    "enterprise_zone": {
        "type": "both",
        "synonyms": ["EnterpriseZone","enterprise_zone","EZ","economic development zone",
                     "development zone","EDZ"],
    },
    "historic_district": {
        "type": "both",
        "synonyms": ["HistoricDistrict","historic_district","HistoricYN","HistoricSite",
                     "historic","national register","listed building"],
    },
    "tif_district": {
        "type": "both",
        "synonyms": ["TIFDistrict","tif_district","TaxIncrementFinancing","TIF",
                     "tax increment","TIF zone","brownfield TIF"],
    },
    "hoa_frequency": {
        "type": "residential",
        "synonyms": ["AssociationFeeFrequency","hoa_frequency","HOAFrequency",
                     "hoa billing","monthly quarterly annual","hoa period"],
    },
    "has_basement": {
        "type": "residential",
        "synonyms": ["BasementYN","has_basement","Basement","finished basement",
                     "unfinished basement","basement"],
    },
    "has_fireplace": {
        "type": "residential",
        "synonyms": ["FireplaceYN","has_fireplace","FireplacesTotal","fireplace",
                     "wood burning","gas fireplace"],
    },
    "has_pool": {
        "type": "residential",
        "synonyms": ["PoolPrivateYN","has_pool","PoolYN","private pool",
                     "swimming pool","in-ground pool"],
    },
    "list_date": {
        "type": "both",
        "synonyms": ["ListingContractDate","ListDate","list_date","OnMarketDate",
                     "OriginalEntryTimestamp","listing date","on market date","listed"],
    },
    "days_on_market": {
        "type": "both",
        "synonyms": ["DaysOnMarket","days_on_market","DOM","CumulativeDaysOnMarket",
                     "CDOM","days on market","cumulative dom"],
    },
    "mls_number": {
        "type": "both",
        "synonyms": ["ListingId","MLSNumber","MLS#","mls_number","listing_id","MLSID",
                     "MatrixUniqueID","ListingKey","mls number","mls id"],
    },
}

# ── Flatten RESO_SYNONYMS into SYNONYMS["property"] ──────────────────────────
# All fields used regardless of type — type tag is for future filtering only.
_RESO_PROP = {field: data["synonyms"] for field, data in RESO_SYNONYMS.items()}

# ── Synonym dictionaries ──────────────────────────────────────────────────────

SYNONYMS = {
    "property": _RESO_PROP,
    "contact": {
        "first_name":    ["first name","first","fname","given name","forename"],
        "last_name":     ["last name","last","lname","surname","family name"],
        "email":         ["email","email address","e-mail","e mail","mail"],
        "phone":         ["phone","phone number","office phone","work phone",
                          "telephone","office"],
        "mobile":        ["mobile","cell","cell phone","mobile phone","cellular"],
        "title":         ["title","job title","position","role","designation"],
        "company":       ["company","firm","organization","employer","brokerage"],
        "contact_type":  ["type","contact type","category","classification"],
        "notes":         ["notes","comments","bio","remarks"],
    },
    "account": {
        "name":        ["name","company name","entity name","account name","llc name",
                        "firm name","organization"],
        "entity_type": ["type","entity type","company type","structure","org type"],
        "ein":         ["ein","tax id","federal id","employer id","tin"],
        "phone":       ["phone","main phone","office phone","telephone"],
        "email":       ["email","contact email","main email"],
        "address":     ["address","mailing address","street address","business address"],
        "city":        ["city","town","municipality"],
        "state":       ["state","province"],
        "zip":         ["zip","postal code","zip code"],
        "notes":       ["notes","comments","description"],
    },
    "deal": {
        "name":             ["name","deal name","transaction name","opportunity","deal title"],
        "deal_type":        ["type","deal type","transaction type","listing type","rep type"],
        "stage":            ["stage","status","pipeline stage","deal status","phase"],
        "list_price":       ["list price","listing price","asking price","price"],
        "sale_price":       ["sale price","sold price","closed price","purchase price"],
        "commission_pct":   ["commission","commission pct","commission rate","commission %",
                             "fee"],
        "projected_close":  ["projected close","expected close","close date","target close",
                             "estimated close"],
        "notes":            ["notes","comments","remarks"],
    },
}

# Valid model fields — prevents unknown-kwarg crashes on model instantiation
VALID_FIELDS = {
    "property": {
        # Core
        "name","address","city","state","zip","county","property_type","subtype",
        "status","year_built","sf_rentable","sf_land","units","stories","zoning",
        "parking_ratio","occupancy_pct","asking_price","asking_price_per_sf",
        "assessed_value","tax_amount","tax_year","cap_rate","noi",
        "parcel_id","legal_desc","tenant","last_sale_price","last_sale_date","notes",
        # Industrial
        "clear_height_min","clear_height_max","dock_doors","drive_in_doors",
        "rail_service","rail_service_type","power_amps","power_volts","power_phase",
        "column_spacing","floor_thickness","floor_load","sprinklers","sprinkler_type",
        "crane_capacity","crane_height","office_pct","office_sf","yard_area",
        "secured_yard","cross_dock",
        # Retail
        "anchor_tenant","inline_space","end_cap","pylon_sign","monument_sign",
        "traffic_count","frontage_ft","drive_through","number_of_buildings",
        # Office
        "building_class","fiber_optic","generator","raised_floor",
        "data_center_ready","leed_certified","energy_star",
        # Multifamily
        "unit_mix","avg_unit_sf","avg_rent_per_unit","avg_rent_per_sf",
        "laundry","pet_friendly","affordable_units","market_rate_units",
        # Hospitality
        "number_of_rooms","flag","franchise_expiry","adr","revpar",
        "restaurant_seats","meeting_space_sf","pool_hotel","fitness_center",
        # Medical
        "exam_rooms","procedure_rooms","imaging_rooms","surgical_suites",
        "icu_beds","licensed_beds","medical_gas","emergency_power",
        # Land
        "zoning_jurisdiction","floodplain","floodplain_zone","wetlands",
        "wetlands_acres","utilities_to_site","road_frontage_ft","corner_lot",
        "subdivided","number_of_lots","plat_recorded","environmental",
        # Extended financial
        "gross_income","operating_expense","vacancy_allowance","expense_ratio",
        "debt_service","cash_flow","price_per_unit","price_per_room",
        "lease_type","tenant_pays","owner_pays","lease_expiration",
        "lease_term_months","renewal_options","rent_bumps",
        # General commercial
        "business_name","business_type","employee_count","franchise","franchise_name",
        "opportunity_zone","enterprise_zone","historic_district","tif_district",
        # Residential
        "bedrooms","bathrooms","garage_spaces","hoa_fee","hoa_frequency",
        "school_district","has_basement","has_fireplace","has_pool",
        "mls_number","list_date","days_on_market",
    },
    # owner_* fields are virtual — handled in execute, never passed to Property()
    "_owner_fields": {"owner_name","owner_contact","owner_phone",
                      "owner_email","owner_address","owner_city_state_zip"},
    "contact":  {"first_name","last_name","email","phone","mobile","title",
                 "contact_type","source","notes"},
    "account":  {"name","entity_type","ein","website","phone","email",
                 "address","city","state","zip","notes"},
    "deal":     {"name","deal_type","stage","list_price","sale_price",
                 "commission_pct","projected_close","notes"},
}

# Fields that need numeric coercion
NUMERIC_FIELDS = {
    "property": {
        # Core
        "sf_rentable":float,"sf_land":float,"asking_price":float,
        "asking_price_per_sf":float,"assessed_value":float,"tax_amount":float,
        "year_built":int,"units":int,"stories":int,"tax_year":int,
        "parking_ratio":float,"occupancy_pct":float,"cap_rate":float,"noi":float,
        "last_sale_price":float,
        # Industrial
        "clear_height_min":float,"clear_height_max":float,
        "dock_doors":int,"drive_in_doors":int,
        "floor_thickness":float,"floor_load":float,
        "crane_capacity":float,"crane_height":float,
        "office_pct":float,"office_sf":float,"yard_area":float,
        # Retail
        "traffic_count":int,"frontage_ft":float,"number_of_buildings":int,
        # Multifamily
        "avg_unit_sf":float,"avg_rent_per_unit":float,"avg_rent_per_sf":float,
        "affordable_units":int,"market_rate_units":int,
        # Hospitality
        "number_of_rooms":int,"adr":float,"revpar":float,
        "restaurant_seats":int,"meeting_space_sf":float,
        # Medical
        "exam_rooms":int,"procedure_rooms":int,"imaging_rooms":int,
        "surgical_suites":int,"icu_beds":int,"licensed_beds":int,
        # Land
        "wetlands_acres":float,"road_frontage_ft":float,"number_of_lots":int,
        # Extended financial
        "gross_income":float,"operating_expense":float,"vacancy_allowance":float,
        "expense_ratio":float,"debt_service":float,"cash_flow":float,
        "price_per_unit":float,"price_per_room":float,
        "lease_term_months":int,
        # General commercial
        "employee_count":int,
        # Residential
        "bedrooms":int,"bathrooms":float,"garage_spaces":int,
        "hoa_fee":float,"days_on_market":int,
    },
    "contact":  {},
    "account":  {},
    "deal":     {"list_price":float,"sale_price":float,"commission_pct":float},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return (s or "").lower().strip()


def _read_file(content: bytes, filename: str):
    """Returns (headers: list, rows: list[dict])."""
    if (filename or "").lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not all_rows:
            return [], []
        headers = [str(h).strip() if h is not None else f"col_{i}"
                   for i, h in enumerate(all_rows[0])]
        rows = []
        for row in all_rows[1:]:
            rows.append({headers[i]: (str(v).strip() if v is not None else "")
                         for i, v in enumerate(row)})
        return headers, rows
    else:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        headers = list(reader.fieldnames or [])
        return headers, list(reader)


def _best_match(header: str, synonyms: dict):
    """Returns (field_name | None, score 0-100)."""
    h = _norm(header)
    best_field, best_score = None, 0
    for field, syns in synonyms.items():
        for syn in syns:
            score = fuzz.token_sort_ratio(h, _norm(syn))
            if score > best_score:
                best_score = score
                best_field = field
    return (best_field if best_score >= 60 else None), best_score


_DATE_FIELDS = {
    "property": {"last_sale_date","franchise_expiry","lease_expiration","list_date"},
    "deal":     {"projected_close"},
}

_DATE_FMTS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y", "%Y/%m/%d")

def _parse_date(val: str):
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _parse_csz(val: str):
    """Parse 'City, ST 12345' → (city, state, zip). Returns (None, None, None) on failure."""
    m = re.match(r'^(.+),\s*([A-Za-z]{2})\s+(\d{5})', val.strip())
    if m:
        return m.group(1).strip(), m.group(2).upper(), m.group(3)
    return None, None, None


def _coerce(mapped: dict, record_type: str) -> dict:
    """Numeric + date type coercion; silently skips unparseable values."""
    out = dict(mapped)
    for field, typ in NUMERIC_FIELDS.get(record_type, {}).items():
        if field in out and out[field]:
            try:
                out[field] = typ(str(out[field]).replace(",", "").replace("$", "")
                                 .replace("%", "").strip())
            except (ValueError, TypeError):
                del out[field]
    for field in _DATE_FIELDS.get(record_type, set()):
        if field in out and out[field]:
            parsed = _parse_date(str(out[field]))
            if parsed:
                out[field] = parsed
            else:
                del out[field]
    return out


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/preview")
async def preview_import(
    file:        UploadFile = File(...),
    record_type: str        = Form(...),
    current_user: User      = Depends(get_current_user),
):
    if record_type not in SYNONYMS:
        raise HTTPException(400, f"Unknown record_type: {record_type}")

    content = await file.read()
    headers, rows = _read_file(content, file.filename or "")
    if not headers:
        raise HTTPException(400, "Could not parse file — no headers found")

    syns = SYNONYMS[record_type]
    mapping = {}
    for h in headers:
        field, score = _best_match(h, syns)
        mapping[h] = {
            "field":      field,
            "score":      score,
            "confidence": "high" if score >= 85 else "medium" if score >= 60 else "none",
        }

    owner_fields_present = (
        record_type == "property" and
        any(v.get("field") in VALID_FIELDS.get("_owner_fields", set())
            for v in mapping.values())
    )

    return {
        "headers":            headers,
        "preview_rows":       rows[:3],
        "total_rows":         len(rows),
        "suggested_mapping":  mapping,
        "available_fields":   list(syns.keys()),
        "owner_columns_detected": owner_fields_present,
        "owner_notice": (
            "This import will also create Accounts and Contacts from owner data"
            if owner_fields_present else None
        ),
    }


@router.post("/execute")
async def execute_import(
    file:             UploadFile = File(...),
    record_type:      str        = Form(...),
    mapping:          str        = Form(...),   # JSON: {"CSV col": "model_field"|"_skip"|null}
    current_user:     User       = Depends(get_current_user),
    db:               Session    = Depends(get_db),
):
    if record_type not in SYNONYMS:
        raise HTTPException(400, f"Unknown record_type: {record_type}")

    confirmed = json.loads(mapping)           # {csv_header: field_name | "_skip" | null}
    content   = await file.read()
    _, rows   = _read_file(content, file.filename or "")

    valid        = VALID_FIELDS.get(record_type, set())
    owner_fields = VALID_FIELDS.get("_owner_fields", set())
    all_allowed  = valid | owner_fields   # both sets pass through to mapped
    imported, skipped = 0, 0
    duplicates, flagged, errors = [], [], []

    for row_num, row in enumerate(rows, start=2):
        try:
            # Build mapped dict from confirmed field assignments
            mapped = {}
            for csv_col, field in confirmed.items():
                if not field or field == "_skip":
                    continue
                if field not in all_allowed:
                    continue
                val = str(row.get(csv_col, "") or "").strip()
                if val:
                    mapped[field] = val

            mapped = _coerce(mapped, record_type)

            # ── Property ──────────────────────────────────────────
            if record_type == "property":
                if not mapped.get("address"):
                    flagged.append({"row": row_num, "reason": "Missing address",
                                    "data": dict(row)})
                    continue
                existing = db.query(Property).filter(
                    Property.owner_id == current_user.id,
                    Property.address.ilike(mapped.get("address", "")),
                    Property.city.ilike(mapped.get("city", "")),
                ).first()
                if existing:
                    duplicates.append({"row": row_num,
                                       "reason": f"{mapped.get('address')}, {mapped.get('city')} already exists"})
                    skipped += 1
                    continue

                # Separate owner fields (go to Account/Contact) from property fields
                owner_fields = VALID_FIELDS.get("_owner_fields", set())
                owner_data   = {k: v for k, v in mapped.items() if k in owner_fields}
                prop_data    = {k: v for k, v in mapped.items() if k not in owner_fields}

                if not prop_data.get("name"):
                    prop_data["name"] = prop_data.get("address", "")

                prop = Property(**{k: v for k, v in prop_data.items() if k in valid},
                                owner_id=current_user.id)
                db.add(prop)
                db.flush()   # need prop.id for Account link

                # ── Create / link Account from owner_name ──────────
                acct = None
                if owner_data.get("owner_name"):
                    acct_name = owner_data["owner_name"].strip()
                    acct = db.query(Account).filter(
                        Account.owner_id == current_user.id,
                        Account.name.ilike(acct_name),
                    ).first()
                    if not acct:
                        city_o, state_o, zip_o = _parse_csz(
                            owner_data.get("owner_city_state_zip") or "")
                        acct = Account(
                            owner_id = current_user.id,
                            name     = acct_name,
                            address  = owner_data.get("owner_address") or None,
                            city     = city_o,
                            state    = state_o,
                            zip      = zip_o,
                        )
                        db.add(acct)
                        db.flush()
                    prop.account_id = acct.id

                # ── Create / link Contact from owner_contact ───────
                if owner_data.get("owner_contact"):
                    parts   = owner_data["owner_contact"].strip().split(" ", 1)
                    first   = parts[0]
                    last    = parts[1] if len(parts) > 1 else ""
                    email   = (owner_data.get("owner_email") or "").lower() or None
                    phone   = owner_data.get("owner_phone") or None

                    contact = None
                    if email:
                        contact = db.query(Contact).filter(
                            Contact.owner_id == current_user.id,
                            Contact.email == email,
                        ).first()
                    if not contact:
                        contact = db.query(Contact).filter(
                            Contact.owner_id == current_user.id,
                            Contact.first_name.ilike(first),
                            Contact.last_name.ilike(last),
                        ).first()
                    if not contact:
                        contact = Contact(
                            owner_id     = current_user.id,
                            first_name   = first,
                            last_name    = last,
                            email        = email,
                            phone        = phone,
                            contact_type = "Owner",
                        )
                        db.add(contact)
                        db.flush()

                    # Link contact ↔ account (if account exists and not already linked)
                    if acct:
                        already = db.query(ContactAccount).filter(
                            ContactAccount.contact_id == contact.id,
                            ContactAccount.account_id == acct.id,
                        ).first()
                        if not already:
                            db.add(ContactAccount(
                                contact_id = contact.id,
                                account_id = acct.id,
                                role       = "Owner",
                                is_primary = True,
                            ))

            # ── Contact ───────────────────────────────────────────
            elif record_type == "contact":
                if not mapped.get("first_name") and not mapped.get("last_name"):
                    flagged.append({"row": row_num, "reason": "Missing name",
                                    "data": dict(row)})
                    continue
                email = (mapped.get("email") or "").lower()
                if email:
                    existing = db.query(Contact).filter(
                        Contact.owner_id == current_user.id,
                        Contact.email == email,
                    ).first()
                    if existing:
                        duplicates.append({"row": row_num,
                                           "reason": f"Contact {email} already exists"})
                        skipped += 1
                        continue
                    mapped["email"] = email
                db.add(Contact(**{k: v for k, v in mapped.items() if k in valid},
                               owner_id=current_user.id))

            # ── Account ───────────────────────────────────────────
            elif record_type == "account":
                if not mapped.get("name"):
                    flagged.append({"row": row_num, "reason": "Missing account name",
                                    "data": dict(row)})
                    continue
                existing = db.query(Account).filter(
                    Account.owner_id == current_user.id,
                    Account.name.ilike(mapped.get("name", "")),
                ).first()
                if existing:
                    duplicates.append({"row": row_num,
                                       "reason": f"Account '{mapped.get('name')}' already exists"})
                    skipped += 1
                    continue
                db.add(Account(**{k: v for k, v in mapped.items() if k in valid},
                               owner_id=current_user.id))

            # ── Deal (preview-only — requires property linking) ───
            elif record_type == "deal":
                flagged.append({"row": row_num,
                                 "reason": "Deals require a linked Property — add via the Deals page",
                                 "data": mapped})
                continue

            imported += 1

        except Exception as exc:
            errors.append({"row": row_num, "reason": str(exc)})

    if imported > 0:
        db.commit()

    return {
        "imported":     imported,
        "skipped":      skipped,
        "flagged":      len(flagged),
        "flagged_rows": flagged,
        "duplicates":   duplicates,
        "errors":       errors,
    }
