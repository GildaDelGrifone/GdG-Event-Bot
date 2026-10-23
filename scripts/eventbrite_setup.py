#!/usr/bin/env python3
"""
Setup helper for the Eventbrite integration: validate the token, find the organization ID, create or edit venues and create collections.

Usage Examples:
    # Validate EVENTBRITE_TOKEN and list the organizations it can access:
    python3 scripts/eventbrite_setup.py --check --orgs

    # List the venues of the organization (EVENTBRITE_ORGANIZATION_ID, or --org):
    python3 scripts/eventbrite_setup.py --venues

    # Create a collection (e.g. "Giochi di ruolo") and print the id to put in .env:
    python3 scripts/eventbrite_setup.py --create-collection "Giochi di ruolo"

    # Create the venue once and print the EVENTBRITE_VENUE_ID to put in .env:
    python3 scripts/eventbrite_setup.py --create-venue --name "Gilda del Grifone" \\
        --address "Via Ada Negri 8/A" --city Torino --postal-code 10135 --country IT

    # Edit an existing venue (fields you leave out keep their current value):
    python3 scripts/eventbrite_setup.py --update-venue 215882649 --name "TO PLAY TORINO" \\
        --address "Via Borgaro, 2" --postal-code 10149 --region TO
"""

import argparse
import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import config
from core.eventbrite.client import EventbriteError, eb_get, eb_post, paginate
from core.eventbrite.collections import create_collection


def check_token():
    me = eb_get("/users/me/")
    print(f"✅ Token valido: {me.get('name') or '(senza nome)'} (user id {me.get('id')})")


def list_organizations():
    organizations = list(paginate("/users/me/organizations/", {}, "organizations"))
    if not organizations:
        print("Nessuna organizzazione trovata per questo token.")
    for org in organizations:
        print(f"{org.get('id')}\t{org.get('name')}")
    print("\nImposta EVENTBRITE_ORGANIZATION_ID con l'ID dell'organizzazione desiderata.")


def list_venues(organization_id):
    venues = list(paginate(f"/organizations/{organization_id}/venues/", {}, "venues"))
    if not venues:
        print("Nessun venue trovato.")
    for venue in venues:
        address = venue.get("address") or {}
        print(f"{venue.get('id')}\t{venue.get('name')}\t{address.get('localized_address_display') or ''}")


def create_venue(organization_id, args):
    venue = eb_post(f"/organizations/{organization_id}/venues/", json={"venue": {
        "name": args.name,
        "address": {key: value for key, value in {
            "address_1": args.address,
            "city": args.city or "Torino",
            "region": args.region,
            "postal_code": args.postal_code,
            "country": args.country or "IT",
        }.items() if value},
    }})
    print(f"✅ Venue creato: {venue.get('name')}")
    print(f"EVENTBRITE_VENUE_ID={venue.get('id')}")


ADDRESS_FIELDS = (("address", "address_1"), ("city", "city"), ("region", "region"),
                  ("postal_code", "postal_code"), ("country", "country"))


def update_venue(args):
    """Edits a venue. Eventbrite wants the whole address on every update, so the given fields are merged over the current one."""
    current = eb_get(f"/venues/{args.update_venue}/")
    address = {key: (current.get("address") or {}).get(key) for key in
               ("address_1", "address_2", "city", "region", "postal_code", "country")}
    for arg, key in ADDRESS_FIELDS:
        if getattr(args, arg) is not None:
            address[key] = getattr(args, arg)
    venue = eb_post(f"/venues/{args.update_venue}/", json={"venue": {
        "name": args.name or current.get("name"),
        "address": {key: value for key, value in address.items() if value},
    }})
    shown = venue.get("address") or {}
    print(f"✅ Venue aggiornato: {venue.get('name')} | {shown.get('localized_address_display') or ''} "
          f"({shown.get('latitude')}, {shown.get('longitude')})")


def create_collection_for_org(organization_id, name):
    organizers = list(paginate(f"/organizations/{organization_id}/organizers/", {}, "organizers"))
    if not organizers:
        raise EventbriteError(404, "NO_ORGANIZER", "L'organizzazione non ha organizzatori")
    organizer_id = config.EVENTBRITE_ORGANIZER_ID or organizers[0]["id"]
    collection = create_collection(name, organizer_id)
    print(f"✅ Collezione creata: {collection.get('name')} ({collection.get('absolute_url')})")
    print("Per renderla visibile pubblicala dalla dashboard Eventbrite (l'API la crea in bozza).")
    print(f"ID collezione: {collection.get('id')}  → EVENTBRITE_COLLECTION_ROLEPLAY o EVENTBRITE_COLLECTION_BOARDGAMES")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Configurazione dell'integrazione Eventbrite della Gilda del Grifone.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--check", action="store_true", help="Valida EVENTBRITE_TOKEN (GET /users/me/).")
    parser.add_argument("--orgs", action="store_true", help="Elenca gli ID delle organizzazioni accessibili.")
    parser.add_argument("--venues", action="store_true", help="Elenca i venue dell'organizzazione.")
    parser.add_argument("--create-venue", action="store_true", help="Crea un venue e stampa il suo ID.")
    parser.add_argument("--update-venue", metavar="ID", help="Modifica un venue esistente (con --name e/o i campi indirizzo).")
    parser.add_argument("--create-collection", metavar="NOME", help="Crea una collezione e stampa il suo ID.")
    parser.add_argument("--org", help="ID organizzazione (default: EVENTBRITE_ORGANIZATION_ID).")
    parser.add_argument("--name", help="Nome del venue (con --create-venue).")
    parser.add_argument("--address", help="Indirizzo del venue (con --create-venue).")
    parser.add_argument("--city", help="Città del venue (default alla creazione: Torino).")
    parser.add_argument("--region", help="Provincia/regione del venue (es. TO).")
    parser.add_argument("--postal-code", help="CAP del venue.")
    parser.add_argument("--country", help="Codice paese ISO a 2 lettere (default alla creazione: IT).")
    args = parser.parse_args(argv)
    if not (args.check or args.orgs or args.venues or args.create_venue or args.create_collection
            or args.update_venue):
        parser.error("specifica almeno una azione: --check, --orgs, --venues, --create-venue, --update-venue o --create-collection")
    if args.create_venue and not (args.name and args.address):
        parser.error("--create-venue richiede --name e --address")
    if args.update_venue and not any(getattr(args, arg) is not None for arg in
                                     ("name", "address", "city", "region", "postal_code", "country")):
        parser.error("--update-venue richiede almeno un campo da cambiare (--name, --address, --city, --region, --postal-code, --country)")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not config.EVENTBRITE_TOKEN:
        print("❌ EVENTBRITE_TOKEN non impostato nel file .env.")
        return 1

    organization_id = args.org or config.EVENTBRITE_ORGANIZATION_ID
    if (args.venues or args.create_venue or args.create_collection) and not organization_id:
        print("❌ Serve l'ID organizzazione: usa --orgs per trovarlo, poi --org o EVENTBRITE_ORGANIZATION_ID.")
        return 1

    try:
        if args.check:
            check_token()
        if args.orgs:
            list_organizations()
        if args.venues:
            list_venues(organization_id)
        if args.create_venue:
            create_venue(organization_id, args)
        if args.update_venue:
            update_venue(args)
        if args.create_collection:
            create_collection_for_org(organization_id, args.create_collection)
    except EventbriteError as e:
        print(f"❌ Errore Eventbrite: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
