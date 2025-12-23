# Field Mapping Plan

We maintain a canonical JSON for trips and expenses. A small mapping file
translates canonical fields to each spreadsheet cell.

## Itinerary template mappings (ITIN-2025.1)

The canonical trip fields for **Travel_Itinerary_Form_2025.xlsx** (Template ID:
ITIN-2025.1) are enumerated in `config/excel_mappings.yaml` with the following
cell targets on the **Itinerary** sheet:

- traveler_name → **B4**
- business_purpose → **B5**
- cost_center → **D5**
- destination_zip → **F7**
- city_state → **B7**
- depart_date → **B9**
- return_date → **D9**
- event_registration_cost → **F11**
- flight_pref_outbound.{carrier_flight, depart_time, arrive_time, roundtrip_cost}
  → **B12**, **C12**, **D12**, **F12**
- flight_pref_return.{carrier_flight, depart_time, arrive_time}
  → **B13**, **C13**, **D13**
- lowest_cost_roundtrip → **F13**
- parking_estimate → **F15**
- hotel.{name, address, city_state, nightly_rate, nights, price_compare_notes}
  → **B17**, **B18**, **E18**, **F17**, **G17**, **B20**
- comparable_hotels[0|1].{name, nightly_rate} → **B22/F22**, **B23/F23**
- ground_transport_pref (dropdown) → **B25**
- notes → **B27**

### Checkbox and dropdown formats

- **hotel.conference_hotel** checkbox at **E17** uses `Yes` / `No` values.
- **ground_transport_pref** dropdown at **B25** expects one of:
  `Rideshare/Taxi`, `Rental Car`, `Public Transit`, or `Personal Vehicle`.

### Formula-driven fields

- Meal per-diem total at **F28** is formula-driven in the template and should
  not be overwritten by the agent. Mapping is marked `formula_driven: true` for
  version **ITIN-2025.1**.

## Minimal Q&A coverage (draft)

To reach field completeness within ten questions for typical trips, start with:

1. Traveler name and role.
2. Trip purpose / event name.
3. Destination city/state and ZIP.
4. Travel dates (depart / return).
5. Cost center or chartfield.
6. Registration cost (if applicable).
7. Outbound flight preference (carrier + times) and lowest available fare.
8. Return flight preference (carrier + times).
9. Hotel choice (conference hotel Y/N), nightly rate, nights, comparable options.
10. Ground transport preference and parking estimate.

## Canonical Trip fields (initial)

- traveler_name
- business_purpose
- cost_center
- destination_zip
- city_state
- depart_date
- return_date
- event_registration_cost
- flight_pref_outbound {carrier_flight, depart_time, arrive_time,
  roundtrip_cost}
- flight_pref_return {carrier_flight, depart_time, arrive_time}
- lowest_cost_roundtrip
- parking_estimate
- hotel {name, address, city_state, nightly_rate, nights, conference_hotel,
  price_compare_notes}
- comparable_hotels [{name, nightly_rate}] (optional)
- ground_transport_pref
- notes

## Canonical Expense fields (initial)

- lines: [{
  date, from_to, miles, breakfast, lunch, dinner, hotel, airfare,
  rideshare_taxi, bus_train, parking_tolls, other, paid_by_third_party
  }]
- mileage_rate
- travel_advance
- totals (computed)

## Spreadsheet templates and version IDs

- Travel_Itinerary_Form_2025.xlsx — **Template ID**: ITIN-2025.1 (last
  reviewed: 2025‑09‑06)
- Expense_Report_Form_FY2025_revised_Jan_2025.xlsx — **Template ID**:
  EXP-2025.1 (last reviewed: 2025‑09‑06)

When a template changes cell positions or validation rules, bump the Template
ID and update mapping notes.
