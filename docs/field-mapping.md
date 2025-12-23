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
