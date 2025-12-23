# Field Mapping Plan

We maintain a canonical JSON for trips and expenses. A small mapping file
translates canonical fields to each spreadsheet cell.

## Version tracking

| Template file | Template ID | Last reviewed | Notes |
| --- | --- | --- | --- |
| Travel_Itinerary_Form_2025.xlsx | ITIN-2025.1 | 2025-09-06 | Dropdown for ground transport, checkbox for conference hotel, per-diem cells remain formula-driven |
| Expense_Report_Form_FY2025_revised_Jan_2025.xlsx | EXP-2025.1 | 2025-09-06 | Not mapped in this iteration |

Any changes to template cells or validation rules must bump the Template ID and
be recorded in `config/excel_mappings.yaml` under the matching version key.
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

## Spreadsheet templates and cell targets

The mapping for `ITIN-2025.1` lives in `config/excel_mappings.yaml` and covers
all canonical trip fields. Highlights:

- Traveler and purpose: `traveler_name -> B3`, `business_purpose -> B4`
- Dates and destination: `city_state -> B5`, `destination_zip -> F5`,
  `depart_date -> B6`, `return_date -> D6`
- Flight preferences: outbound and return flight numbers plus time slots fill
  `B8:D9`, cost comparisons fill `E8:E9`
- Hotel block: hotel identity and rate details occupy `B11:F12`, with a
  conference-hotel checkbox in `G12` and comparison notes in `B13`
- Optional comparable hotel rows begin at `B14` (first entry mapped)
- Ground transport dropdown sits at `B15` with allowed values
  `rideshare/taxi`, `rental car`, `public transit`, `personal vehicle`
- Parking, registration, and notes use `F9`, `F6`, and `B16` respectively
- Per-diem totals remain formula-driven at `H20`

## Prompt and output bundle

- A ten-question intake flow covers traveler identity, destination, dates,
  business purpose, flight preferences, fare comparison, hotel details,
  conference-hotel confirmation, transport choice, and miscellaneous extras.
- The prompt engine skips already-answered fields and keeps the question list to
  10 or fewer for typical trips.
- Output bundle spec:
  - `itinerary.xlsx`: binary content tagged with template version
  - `summary.pdf`: single-page summary text rendered for quick review
  - `conversation_log_json`: serialized Q&A log including attachment notices
  - Attachments: optional `conference_brochure.pdf` is accepted and referenced
    in the conversation log for downstream rendering
