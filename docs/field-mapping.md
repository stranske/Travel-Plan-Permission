# Field Mapping Plan

We maintain a canonical JSON for trips and expenses. A small mapping file translates canonical fields to each spreadsheet cell.

## Canonical Trip fields (initial)
- traveler_name
- business_purpose
- cost_center
- destination_zip
- city_state
- depart_date
- return_date
- event_registration_cost
- flight_pref_outbound {carrier_flight, depart_time, arrive_time, roundtrip_cost}
- flight_pref_return {carrier_flight, depart_time, arrive_time}
- lowest_cost_roundtrip
- parking_estimate
- hotel {name, address, city_state, nightly_rate, nights, conference_hotel, price_compare_notes}
- comparable_hotels [{name, nightly_rate}] (optional)
- ground_transport_pref
- notes

## Canonical Expense fields (initial)
- lines: [{date, from_to, miles, breakfast, lunch, dinner, hotel, airfare, rideshare_taxi, bus_train, parking_tolls, other, paid_by_third_party}]
- mileage_rate
- travel_advance
- totals (computed)

