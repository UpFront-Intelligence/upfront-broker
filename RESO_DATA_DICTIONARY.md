# RESO Data Dictionary 2.1 — Import Field Reference

Authoritative synonym registry used by `routers/imports.py` to fuzzy-match
CSV/XLSX column headers to Property model fields.

**Type tags:**
- `commercial` — CRE-specific fields only
- `residential` — residential-only fields (future support)
- `both` — universal fields used in both contexts

When `record_type = "property"` all synonyms are used regardless of type.
The type tag enables future residential-only / commercial-only import filtering.

> **Source:** RESO Data Dictionary 2.1 (reso.org) plus common MLS,
> CoStar, and manual-export header variants.

---

## Location

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `address` | both | `UnparsedAddress`, `StreetAddress`, `FullStreetAddress`, `PropertyAddress`, `SiteAddress`, `BuildingAddress`, `address`, `property address`, `street address`, `street`, `addr`, `location` |
| `city` | both | `City`, `PostalCity`, `city`, `municipality`, `town` |
| `state` | both | `StateOrProvince`, `State`, `state`, `st`, `province` |
| `zip` | both | `PostalCode`, `Zip`, `ZipCode`, `zip`, `zip code`, `postal`, `postal code` |
| `county` | both | `CountyOrParish`, `County`, `county`, `county name`, `jurisdiction` |

---

## Classification

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `property_type` | both | `PropertyType`, `PropertySubType`, `PropertyUse`, `LandUse`, `type`, `property type`, `asset type`, `use type`, `space use`, `building type` |
| `subtype` | both | `PropertySubType`, `PropertySubTypeAdditional`, `ArchitecturalStyle`, `subtype`, `sub type`, `secondary type`, `building class`, `property subtype`, `class` |
| `status` | both | `StandardStatus`, `MlsStatus`, `ListingStatus`, `status`, `listing status`, `property status` |
| `zoning` | both | `Zoning`, `ZoningDescription`, `ZoningCode`, `zoning`, `zone`, `zoning code`, `land use code` |

---

## Physical — Commercial

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `sf_rentable` | commercial | `BuildingAreaTotal`, `LeasableArea`, `GrossLeasableArea`, `GLA`, `RentableArea`, `sf`, `sqft`, `square feet`, `building size`, `rentable sf`, `rba`, `building sf`, `size`, `gla`, `rentable area` |
| `sf_land` | commercial | `LotSizeSquareFeet`, `LotSizeArea`, `LandArea`, `sf land`, `land sf`, `land area sf`, `land size`, `lot size sf`, `land square feet`, `lot sf`, `acreage sf`, `land area` |
| `units` | both | `NumberOfUnitsTotal`, `NumberOfUnitsInCommunity`, `UnitCount`, `NumberOfBuildings`, `units`, `unit count`, `number of units`, `# units`, `apt units` |
| `stories` | both | `StoriesTotal`, `Levels`, `NumberOfFloors`, `stories`, `floors`, `number of floors`, `num floors`, `building stories`, `# floors`, `# stories` |
| `year_built` | both | `YearBuilt`, `YearBuiltEffective`, `year built`, `year`, `built`, `year constructed` |
| `parking_ratio` | commercial | `ParkingRatio`, `ParkingTotal`, `GarageSpaces`, `ParkingFeatures`, `parking ratio`, `parking`, `parking spaces per 1000`, `parking/1000`, `p/1000`, `parking rate` |
| `occupancy_pct` | commercial | `OccupancyRate`, `OccupancyPercent`, `PercentLeased`, `occupancy pct`, `occupancy %`, `occupancy percent`, `occupancy`, `occupied pct`, `leased pct`, `leased %`, `percent leased`, `percent occupied`, `current occupancy`, `occ %`, `occ pct` |
| `clear_height` | commercial | `ClearHeight`, `clear_height`, `CeilingHeight`, `ceiling_height`, `WarehouseCeilingHeight`, `MinClearCeilingHeight`, `clear span height`, `warehouse height` |
| `dock_doors` | commercial | `DockHighDoors`, `dock_doors`, `NumberOfDockDoors`, `LoadingDocks`, `DockHighDoorsCount`, `# dock doors`, `loading dock doors`, `truck docks` |
| `drive_in_doors` | commercial | `DriveInDoors`, `drive_in_doors`, `GradeLevel`, `GradeLevelDoors`, `DriveInDoorsCount`, `grade level doors`, `drive-in doors`, `grade level access` |
| `rail_service` | commercial | `RailServiceType`, `rail_service`, `RailAccess`, `RailServiceYN`, `rail access`, `railroad siding`, `rail spur` |
| `power_amps` | commercial | `ElectricOnPropertyYN`, `power_amps`, `Voltage`, `Amps`, `ElectricService`, `ThreePhaseElectric`, `electrical service`, `3 phase`, `three phase`, `amps`, `voltage` |
| `sprinklers` | commercial | `SprinklersYN`, `sprinklers`, `FireSprinklerYN`, `SprinklerSystem`, `FireProtection`, `fire sprinkler`, `sprinkler system`, `wet sprinkler`, `dry sprinkler` |

---

## Physical — Residential

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `bedrooms` | residential | `BedroomsTotal`, `Bedrooms`, `BedsBaths`, `bedroom_count`, `beds`, `# bedrooms`, `bed count` |
| `bathrooms` | residential | `BathroomsTotalInteger`, `Bathrooms`, `BathroomsFull`, `BathroomsHalf`, `BathroomsThreeQuarter`, `bathroom_count`, `baths`, `beds_baths`, `# bathrooms`, `bath count` |
| `garage_spaces` | residential | `GarageSpaces`, `CarportSpaces`, `ParkingTotal`, `garage_spaces`, `parking_spaces`, `GarageYN`, `attached garage`, `detached garage` |
| `lot_size_acres` | residential | `LotSizeAcres`, `LotSizeArea`, `lot_size_acres`, `LotSizeSquareFeet`, `lot_acres`, `acreage`, `lot size`, `lot acres` |
| `hoa_fee` | residential | `AssociationFee`, `HOAFee`, `AssociationFeeFrequency`, `hoa_fee`, `association_fee`, `HOADues`, `MonthlyHOA`, `hoa`, `monthly hoa`, `association fee` |
| `school_district` | residential | `ElementarySchool`, `MiddleSchool`, `HighSchool`, `SchoolDistrict`, `school_district`, `ElementarySchoolDistrict`, `school district`, `schools`, `school` |
| `basement` | residential | `BasementYN`, `Basement`, `BelowGradeFinishedArea`, `basement`, `has_basement`, `finished basement`, `unfinished basement` |
| `fireplace` | residential | `FireplaceYN`, `FireplacesTotal`, `Fireplace`, `fireplace`, `fireplace_count`, `# fireplaces`, `has fireplace` |
| `pool` | residential | `PoolYN`, `PoolFeatures`, `pool`, `has_pool`, `PoolPrivateYN`, `private pool`, `community pool` |

---

## Physical — Both

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `heating` | both | `Heating`, `HeatingYN`, `CoolingYN`, `Cooling`, `HeatingFeatures`, `CoolingFeatures`, `HVAC`, `hvac_type`, `heating type`, `cooling type`, `heat`, `air conditioning`, `hvac` |
| `roof` | both | `Roof`, `RoofFeatures`, `roof_type`, `roofing`, `roof material`, `roof type` |
| `construction` | both | `ConstructionMaterials`, `construction_materials`, `FoundationDetails`, `foundation`, `ArchitecturalStyle`, `construction_type`, `building construction`, `construction material` |

---

## Commercial — Lease & Operations

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `lease_type` | commercial | `LeaseType`, `lease_type`, `LeaseTerm`, `LeaseExpiration`, `LeaseRenewalOption`, `CurrentLeaseType`, `NNNLeaseYN`, `nnn`, `gross lease`, `modified gross`, `absolute net` |
| `tenant_pays` | commercial | `TenantPays`, `tenant_pays`, `TenantExpenses`, `LesseeResponsibility`, `tenant expenses`, `lessee pays` |
| `owner_pays` | commercial | `OwnerPays`, `owner_pays`, `LandlordResponsibility`, `OwnerExpenses`, `landlord pays`, `lessor pays` |
| `gross_income` | commercial | `GrossIncome`, `gross_income`, `GrossScheduledIncome`, `GrossRentalIncome`, `PotentialGrossIncome`, `egi`, `effective gross income`, `scheduled gross income` |
| `operating_expense` | commercial | `OperatingExpense`, `operating_expense`, `AnnualExpense`, `TotalExpenses`, `OperatingExpenses`, `opex`, `total operating expenses`, `annual operating expenses` |
| `vacancy_allowance` | commercial | `VacancyAllowance`, `vacancy_allowance`, `VacancyRate`, `VacancyPercent`, `EstimatedVacancy`, `vacancy rate`, `vacancy %`, `vacancy factor` |
| `business_name` | commercial | `BusinessName`, `business_name`, `TenantName`, `CurrentTenant`, `OccupantName`, `Occupant`, `business name`, `current occupant` |
| `business_type` | commercial | `BusinessType`, `business_type`, `PropertyUse`, `CurrentUse`, `LandUse`, `UseCode`, `business type`, `property use`, `current use`, `land use` |

---

## Financial

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `asking_price` | both | `ListPrice`, `OriginalListPrice`, `CurrentPrice`, `ClosePrice`, `asking price`, `list price`, `total price`, `offer price`, `asking total` |
| `asking_price_per_sf` | commercial | `PricePerSquareFoot`, `ListPricePerUnit`, `asking price per sf`, `asking psf`, `price per sf`, `$/sf`, `price/sf`, `asking $/sf`, `list price psf`, `per sf`, `psf` |
| `assessed_value` | both | `TaxAssessedValue`, `AssessedValue`, `TaxAppraisedValue`, `assessed value`, `assessment`, `tax value`, `assessed` |
| `tax_amount` | both | `TaxAnnualAmount`, `TaxAmount`, `RealEstateTaxes`, `tax amount`, `taxes`, `tax`, `annual tax`, `property tax`, `tax bill`, `real estate tax`, `tax assessment amount` |
| `tax_year` | both | `TaxYear`, `TaxAssessmentYear`, `tax year`, `assessment year`, `tax yr`, `year assessed` |
| `cap_rate` | commercial | `CapRate`, `CapitalizationRate`, `cap rate`, `cap`, `capitalization rate` |
| `noi` | commercial | `NetOperatingIncome`, `NOI`, `noi`, `net operating income`, `net income`, `annual noi`, `operating income` |
| `last_sale_price` | both | `ClosePrice`, `SalePrice`, `PreviousSalePrice`, `last sale price`, `sold price`, `last sold price`, `close price` |
| `last_sale_date` | both | `CloseDate`, `PurchaseContractDate`, `PreviousSaleDate`, `last sale date`, `sold date`, `sale date`, `last sold date`, `close date` |

---

## Public Records

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `parcel_id` | both | `ParcelNumber`, `AssessorsParcelNumber`, `APN`, `PIN`, `TaxId`, `TaxParcelNumber`, `TaxLot`, `KeyPin`, `parcel`, `parcel id`, `pin`, `apn`, `parcel number`, `tax id` |
| `tenant` | commercial | `TenantName`, `CurrentTenant`, `OccupantName`, `tenant`, `tenants`, `current tenant`, `occupant` |

---

## Listing / MLS

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `mls_number` | both | `ListingId`, `MLSNumber`, `MLS#`, `mls_number`, `listing_id`, `MLSID`, `MatrixUniqueID`, `ListingKey`, `mls number`, `mls id`, `listing number` |
| `days_on_market` | both | `DaysOnMarket`, `days_on_market`, `DOM`, `CumulativeDaysOnMarket`, `CDOM`, `days on market`, `dom`, `cumulative dom` |
| `list_date` | both | `ListingContractDate`, `ListDate`, `list_date`, `OnMarketDate`, `OriginalEntryTimestamp`, `listing date`, `on market date`, `listed date` |
| `expiration_date` | both | `ExpirationDate`, `expiration_date`, `ContractStatusChangeDate`, `ListingExpirationDate`, `expiration`, `listing expiration` |
| `listing_agent` | both | `ListAgentFullName`, `ListAgentFirstName`, `ListAgentLastName`, `ListAgentEmail`, `ListAgentDirectPhone`, `listing_agent`, `AgentName`, `ListingAgent`, `listing agent`, `agent name`, `agent` |
| `listing_office` | both | `ListOfficeName`, `ListOfficePhone`, `ListOfficeEmail`, `listing_office`, `OfficeName`, `BrokerageName`, `listing office`, `brokerage`, `office name` |
| `showing_instructions` | both | `ShowingInstructions`, `showing_instructions`, `ShowingContactName`, `ShowingContactPhone`, `showing instructions`, `access instructions` |
| `virtual_tour` | both | `VirtualTourURLUnbranded`, `VirtualTourURLBranded`, `virtual_tour`, `TourURL`, `Video3DTourURL`, `virtual tour`, `tour url`, `3d tour` |

---

## General

| Model field | Type | RESO & synonym variants |
|---|---|---|
| `name` | both | `PropertyName`, `BuildingName`, `name`, `property name`, `building name` |
| `notes` | both | `PublicRemarks`, `PrivateRemarks`, `SyndicationRemarks`, `notes`, `comments`, `description`, `remarks`, `memo`, `public remarks` |

---

## Owner / Linked-Silo Fields

These fields map to **Account** and **Contact** records, not Property columns.
See `routers/imports.py` execute endpoint for the linked-silo creation logic.

| Virtual field | Type | RESO & synonym variants |
|---|---|---|
| `owner_name` | both | `ListOwnerName`, `OwnerName`, `TaxOwner`, `owner name`, `owner`, `landlord`, `property owner`, `ownername1`, `ownername` |
| `owner_contact` | both | `owner contact`, `contact name`, `contact person`, `owner contact name` |
| `owner_phone` | both | `OwnerPhone`, `owner phone`, `phone`, `owner phone number`, `contact phone` |
| `owner_email` | both | `OwnerEmail`, `owner email`, `email`, `owner email address`, `contact email` |
| `owner_address` | both | `OwnerAddress`, `TaxOwnerAddress`, `owner address`, `mailing address`, `owner mailing address` |
| `owner_city_state_zip` | both | `owner city state zip`, `city state zip`, `owner csz` |

---

## Fields Not Yet in Property Model

The following fields are in `RESO_SYNONYMS` for matching/suggestion purposes
but do not have corresponding DB columns. They will appear as "unmapped" in
the import UI until columns are added via Alembic migration.

**Residential (out of scope for CRE v1):**
`bedrooms`, `bathrooms`, `garage_spaces`, `lot_size_acres`, `hoa_fee`,
`school_district`, `basement`, `fireplace`, `pool`

**Commercial (future additions):**
`clear_height`, `dock_doors`, `drive_in_doors`, `rail_service`, `power_amps`,
`sprinklers`, `lease_type`, `tenant_pays`, `owner_pays`, `gross_income`,
`operating_expense`, `vacancy_allowance`, `business_name`, `business_type`

**Listing/MLS (future additions):**
`mls_number`, `days_on_market`, `list_date`, `expiration_date`,
`listing_agent`, `listing_office`, `showing_instructions`, `virtual_tour`

**Physical — both (future additions):**
`heating`, `roof`, `construction`
