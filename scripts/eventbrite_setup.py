#!/usr/bin/env python3
"""
Setup helper for the Eventbrite integration: validate the token, find the organization ID and create the venue.

Usage Examples:
    # Validate EVENTBRITE_TOKEN and list the organizations it can access:
    python3 scripts/eventbrite_setup.py --check --orgs

    # List the venues of the organization (EVENTBRITE_ORGANIZATION_ID, or --org):
    python3 scripts/eventbrite_setup.py --venues

    # Create the venue once and print the EVENTBRITE_VENUE_ID to put in .env:
    python3 scripts/eventbrite_setup.py --create-venue --name "Gilda del Grifone" \\
        --address "Via Ada Negri 8/A" --city Torino --postal-code 10135 --country IT
"""

import argparse
import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import config
from core.eventbrite.client import EventbriteError, eb_get, eb_post, paginate


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
        "address": {
            "address_1": args.address,
            "city": args.city,
            "postal_code": args.postal_code,
            "country": args.country,
        },
    }})
    print(f"✅ Venue creato: {venue.get('name')}")
    print(f"EVENTBRITE_VENUE_ID={venue.get('id')}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Configurazione dell'integrazione Eventbrite della Gilda del Grifone.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--check", action="store_true", help="Valida EVENTBRITE_TOKEN (GET /users/me/).")
    parser.add_argument("--orgs", action="store_true", help="Elenca gli ID delle organizzazioni accessibili.")
    parser.add_argument("--venues", action="store_true", help="Elenca i venue dell'organizzazione.")
    parser.add_argument("--create-venue", action="store_true", help="Crea un venue e stampa il suo ID.")
    parser.add_argument("--org", help="ID organizzazione (default: EVENTBRITE_ORGANIZATION_ID).")
    parser.add_argument("--name", help="Nome del venue (con --create-venue).")
    parser.add_argument("--address", help="Indirizzo del venue (con --create-venue).")
    parser.add_argument("--city", default="Torino", help="Città del venue (default: Torino).")
    parser.add_argument("--postal-code", help="CAP del venue (con --create-venue).")
    parser.add_argument("--country", default="IT", help="Codice paese ISO a 2 lettere (default: IT).")
    args = parser.parse_args(argv)
    if not (args.check or args.orgs or args.venues or args.create_venue):
        parser.error("specifica almeno una azione: --check, --orgs, --venues o --create-venue")
    if args.create_venue and not (args.name and args.address):
        parser.error("--create-venue richiede --name e --address")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not config.EVENTBRITE_TOKEN:
        print("❌ EVENTBRITE_TOKEN non impostato nel file .env.")
        return 1

    organization_id = args.org or config.EVENTBRITE_ORGANIZATION_ID
    if (args.venues or args.create_venue) and not organization_id:
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
    except EventbriteError as e:
        print(f"❌ Errore Eventbrite: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
