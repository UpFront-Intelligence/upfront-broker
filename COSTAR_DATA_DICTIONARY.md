# CoStar Export Column Reference

Column names as they appear in CoStar CSV exports (verified against CoStar Pro).
Used by `routers/comps.py` to drive the upload-costar endpoint.

> **Note:** CoStar occasionally renames columns between product versions.
> If an import produces zero results, open the CSV and compare header row
> against the names below, then update the aliases in `comps.py`.

---

## Auto-Detection Logic

The importer inspects the CSV header row and classifies the file as a
**sale comp** or **lease comp** before mapping any rows.

| Export type | Signature columns (any one present → detected) |
|---|---|
| Sale comp  | `Sale Price`, `Recorded Buyer`, `Sale Date` |
| Lease comp | `Tenant Name`, `Commencement Date`, `Transaction Size` |

If neither signature matches, the file is rejected with an error.

---

## Sale Comps Export

CoStar product: **Property Sales**

| CoStar Column | Aliases | Comp field | Notes |
|---|---|---|---|
| `Building Address` | `Property Address`, `Address` | `address` | Street only |
| `City` | | `city` | |
| `State` | | `state` | |
| `Property Type` | | `property_type` | |
| `RBA` | `Building Size (SF)` | `sf` | Rentable building area |
| `Sale Price` | `Price` | `sale_price` | Stripped of `$` and `,` |
| `Price/SF` | `Sale Price/SF` | `price_per_sf` | |
| `Cap Rate` | | `cap_rate` | Stripped of `%` |
| `Sale Date` | `Close Date` | `sale_date` | Formats: M/D/YYYY, YYYY-MM-DD |
| `Year Built` | | `year_built` | |
| `Property Name` | | `notes` | Prepended as `Property: …` |
| `Recorded Buyer` | `Buyer` | `notes` | Prepended as `Buyer: …` |
| `Recorded Seller` | `Seller` | `notes` | Prepended as `Seller: …` |
| `NOI at Sale` | `NOI` | `notes` | Prepended as `NOI: …` |
| `Transaction Type` | | `notes` | e.g. Arm's Length, Portfolio |
| `Parcel No.` | `Parcel Number`, `APN` | `notes` | |
| `Building Class` | | `notes` | |
| `Submarket` | | `notes` | |
| `Days On Market` | | `notes` | |
| `Verified` | `Confirmed` | `notes` | |

`source` is set to `"CoStar Sale Comp"`.

---

## Lease Comps Export

CoStar product: **Space Leases**

| CoStar Column | Aliases | Comp field | Notes |
|---|---|---|---|
| `Building Address` | `Property Address`, `Address` | `address` | |
| `City` | | `city` | |
| `State` | | `state` | |
| `Property Type` | `Space Type` | `property_type` | Space Type used as fallback |
| `Transaction Size` | `Transaction Size (SF)`, `Leased SF` | `sf` | Leased SF, not building SF |
| `Effective Rent` | `Effective Rent/SF/Yr` | `price_per_sf` | Best rent metric (post-concessions) |
| `Commencement Date` | `Lease Start Date` | `sale_date` | Reuses date field |
| `Year Built` | | `year_built` | |
| `Tenant Name` | | `notes` | Prepended as `Tenant: …` |
| `Lease Type` | | `notes` | NNN, MG, FSG, Modified Gross |
| `Lease Term` | `Lease Term (Months)` | `notes` | Prepended as `Term: … mo` |
| `Starting Rent` | `Starting Rent/SF/Yr` | `notes` | Prepended as `Starting Rent: …` |
| `Asking Rent` | `Asking Rent/SF/Yr` | `notes` | Prepended as `Asking Rent: …` |
| `Free Rent` | `Free Rent (Months)` | `notes` | Prepended as `Free Rent: … mo` |
| `TI Allowance` | `TI Allowance (TI/SF)`, `TI/SF` | `notes` | Prepended as `TI: $…/SF` |
| `Expiration Date` | `Lease End Date` | `notes` | |
| `Suite` | `Suite/Floor` | `notes` | |
| `Parent Company` | | `notes` | |
| `Building Class` | | `notes` | |
| `Submarket` | | `notes` | |
| `Verified` | `Confirmed` | `notes` | |

`source` is set to `"CoStar Lease Comp"`.
`sale_price` and `cap_rate` are left `null` (not applicable to leases).

---

---

## Michigan Public Records — Property Model Mapping

Fields returned by the county enrichment sources documented in
`MICHIGAN_PUBLIC_RECORDS.md`. Written to the **Property** model (not the Comp
model) via the `POST /api/properties/{id}/enrich` endpoint (next session).

### Source field names by system

| Property model field | ArcGIS field (Oakland) | ArcGIS field (Macomb) | BS&A scraped label |
|---|---|---|---|
| `parcel_id` | `PARCELID` | `PARCEL_ID` | `Parcel Number` |
| `assessed_value` | `SEV` | `SEV` | `SEV` |
| `tax_amount` | `SUMTAX` + `WINTERTAX` | `TAXES` | `Summer Tax` + `Winter Tax` |
| `zoning` | `ZONING` ¹ | `ZONING` ¹ | `Zoning` ¹ |
| `legal_desc` | `LEGALDESC` | `LEGAL_DESC` | `Legal Description` |
| *(account link)* | `OWNERNAME1` | `OWNER_NAME` | `Owner Name` | 

> ¹ Zoning is a municipal function in Michigan. ArcGIS parcel layers sometimes
> omit it; BS&A includes it when the municipality has uploaded zoning data.
> Treat as optional — skip silently if absent rather than erroring.

### Owner entity → Account link

Public records return the vested owner name, typically an LLC
(e.g. `"OAK STREET INVESTMENTS LLC"`). This does not map to a Property field
directly — it maps to the **Account** model via `property.account_id`.

Write policy:
1. Normalize the name (strip extra whitespace, title-case).
2. Search `accounts` where `owner_id = current_user.id AND name ILIKE {normalized}`.
3. **Match found** → set `property.account_id = account.id`. Do not create a duplicate.
4. **No match** → create a new Account (`entity_type = "LLC"` if name ends in
   LLC/PLLC/LC, else leave null), then set `property.account_id`.
5. **`property.account_id` already set** → skip; do not overwrite an existing
   intentional link without explicit user confirmation.

### Write policy for all other fields

| Condition | Behavior |
|---|---|
| Property field is `null` / empty | Always write the enriched value |
| Property field already has a value | Skip — never silently overwrite broker data |
| `assessed_value` or `tax_amount` | Always update (these change annually) |

The enrichment endpoint should return a diff object before committing:
```json
{
  "will_set":   { "parcel_id": "12-34-567-890", "assessed_value": 385000 },
  "will_skip":  { "zoning": "already set to C-2" },
  "account":    { "action": "create", "name": "Oak Street Investments LLC" }
}
```
The frontend shows this diff and requires confirmation before the PUT fires.

---

## Fields Not in the Comp Model

The following CoStar columns are intentionally skipped. Add them to the
`Comp` model and a migration if you need them later.

| Column | Reason skipped |
|---|---|
| `Zip Code` | Model has no zip field on Comp |
| `County` | Same |
| `Market` | Same |
| `RBA` (on lease rows) | We store leased SF (`Transaction Size`), not building SF |
| `# Stories` | Same |
| `Year Renovated` | Same |
| `Secondary Type` | Same |
| `Tenant Industry` / `Parent Company` | Stored in notes if present |
| `Days On Market` | Stored in notes on sale rows |
