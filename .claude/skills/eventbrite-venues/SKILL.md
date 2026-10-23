---
name: eventbrite-venues
description: Create a new Eventbrite venue or edit an existing one (name/address) for the GdG Event Bot, and wire it into .env so the bot can offer it with /bot_eventbrite_venue. Use when the user wants to add, rename, move or fix an Eventbrite venue, or add another place events can be held.
---

# Eventbrite venues

Everything goes through `scripts/eventbrite_setup.py`, run from the repository root (it reads `.env`: `EVENTBRITE_TOKEN`, `EVENTBRITE_ORGANIZATION_ID`). Never print the token.

## What the API can and cannot do
- **Create** (`--create-venue`) and **edit** (`--update-venue`): yes.
- **Delete: no.** `DELETE` answers `405 METHOD_NOT_ALLOWED` on every route (checked). An unused or duplicate venue can only be renamed (e.g. "(duplicato, non usare)") or removed by Eventbrite support.
- An update needs the **whole address** in every call. `--update-venue` fetches the current one and merges the fields you pass, so only pass what changes.
- Eventbrite geocodes the address itself: after a create/update the script prints the coordinates. Check them.

## List
```
python3 scripts/eventbrite_setup.py --venues
```
Shows `id`, name and address of every venue of the organization. Show it to the user before editing anything.

## Create
```
python3 scripts/eventbrite_setup.py --create-venue --name "NAME" --address "Via X, 1" \
    --postal-code 10100 [--city Torino] [--region TO] [--country IT]
```
It prints `EVENTBRITE_VENUE_ID=<id>`. Defaults: city Torino, country IT.

## Edit
```
python3 scripts/eventbrite_setup.py --update-venue <id> [--name "NAME"] [--address "Via X, 1"] \
    [--city C] [--region TO] [--postal-code 10100] [--country IT]
```
At least one field is required.

## Rules
1. **Street address from the user.** A Google Maps link (`maps.app.goo.gl/...`) only resolves (`curl -sL -o /dev/null -w '%{url_effective}'`) to a place name and coordinates, and reverse geocoding gives a nearby street, not the venue's address. Ask the user for the street address, then confirm the coordinates the script prints match the ones in the link.
2. **Editing a venue's name or address changes it for every event held there** (events point to the venue, not a copy), so do not edit one that events already use without asking; prefer creating a new venue or reusing an unused one the user names. Changing `EVENTBRITE_VENUE_ID` (the default) is safe: it only affects events published afterwards, existing events keep their venue.
3. State what you will change (id, old values, new values) and get a yes before any create or update; both are visible on the real account.
4. Use a throw-away approach for experiments: never create test venues you cannot remove, since the API cannot delete them.

## Make the bot use it
In `.env`:
- `EVENTBRITE_VENUE_ID=<id>`: the **default** venue (used until someone picks another).
- `EVENTBRITE_VENUE_ID_ALTERNATIVES=<id2>,<id3>`: extra venues, comma separated.

Restart the bot. With more than one venue configured, an admin runs `/bot_eventbrite_venue` and taps the venue for new events (kept in memory, back to the default after a restart). Each event keeps the venue it was published with.
