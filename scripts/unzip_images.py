#!/usr/bin/env python3
"""
Utility script to unzip image archives.

Usage Examples:
    # Unzip all archives in a specific directory or subdirectories:
    python3 scripts/unzip_images.py data/2026
    python3 scripts/unzip_images.py data/2026/09
    python3 scripts/unzip_images.py data/2026/09/04
    python3 scripts/unzip_images.py 2026/09

    # Unzip archives within a date range:
    python3 scripts/unzip_images.py --start 01-09-2026 --end 10-09-2026

    # Unzip archives for a single date:
    python3 scripts/unzip_images.py --date 04-09-2026

    # Delete the zip files after successful extraction:
    python3 scripts/unzip_images.py data/2026 --delete-zip
"""

import os
import sys
import glob
import zipfile
import argparse
from datetime import datetime, timedelta

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from core.config import DATA_DIR
except ImportError:
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def parse_date(date_str):
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    raise ValueError(f"Invalid date format: '{date_str}'. Expected DD-MM-YYYY or YYYY-MM-DD.")


def get_date_range(start_date, end_date):
    start = parse_date(start_date)
    end = parse_date(end_date)
    if start > end:
        raise ValueError(f"Start date ({start_date}) cannot be after end date ({end_date}).")
    
    dates = []
    curr = start
    while curr <= end:
        dates.append(curr)
        curr += timedelta(days=1)
    return dates


def extract_zip(zip_path, delete_zip=False):
    dest_dir = os.path.dirname(zip_path)
    try:
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            file_list = zipf.namelist()
            if not file_list:
                print(f"⚠️  {zip_path} is empty.")
                return 0
            zipf.extractall(dest_dir)
            print(f"✅ Extracted {len(file_list)} file(s) from {zip_path} into {dest_dir}/")
            for f in file_list:
                print(f"   - {f}")
        
        if delete_zip:
            os.remove(zip_path)
            print(f"🗑️  Deleted archive {zip_path}")
            
        return len(file_list)
    except Exception as e:
        print(f"❌ Failed to extract {zip_path}: {e}")
        return 0


def unzip_in_directory(target_path, delete_zip=False):
    if not os.path.exists(target_path):
        # Try checking relative to DATA_DIR
        alt_path = os.path.join(DATA_DIR, target_path)
        if os.path.exists(alt_path):
            target_path = alt_path
        else:
            print(f"❌ Path not found: {target_path}")
            return 0

    target_path = os.path.abspath(target_path)
    print(f"🔍 Searching for zip archives in: {target_path}")
    
    # If the target is directly a zip file
    if os.path.isfile(target_path) and target_path.endswith(".zip"):
        return extract_zip(target_path, delete_zip=delete_zip)

    # Search recursively for .zip files
    zip_files = sorted(glob.glob(os.path.join(target_path, "**", "*.zip"), recursive=True))
    if not zip_files:
        print(f"ℹ️  No zip archives found in {target_path}")
        return 0

    total_extracted = 0
    for zp in zip_files:
        total_extracted += extract_zip(zp, delete_zip=delete_zip)

    return total_extracted


def unzip_date_range(start_str, end_str, data_dir, delete_zip=False):
    dates = get_date_range(start_str, end_str)
    print(f"🗓️ Checking {len(dates)} day(s) between {start_str} and {end_str} in {data_dir}...")
    
    total_extracted = 0
    days_with_archives = 0
    for d in dates:
        day_dir = os.path.join(data_dir, d.strftime("%Y"), d.strftime("%m"), d.strftime("%d"))
        if os.path.exists(day_dir):
            zip_files = glob.glob(os.path.join(day_dir, "*.zip"))
            for zp in zip_files:
                extracted = extract_zip(zp, delete_zip=delete_zip)
                if extracted > 0:
                    days_with_archives += 1
                    total_extracted += extracted

    if total_extracted == 0:
        print("ℹ️  No archives found in the specified date range.")
    else:
        print(f"\n🎉 Finished: Extracted {total_extracted} files across {days_with_archives} archive(s).")
    return total_extracted


def main():
    parser = argparse.ArgumentParser(
        description="Extract archived event images from directories or date ranges.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("path", nargs="?", help="Directory path or zip file to extract (e.g. data/2026/09 or 2026)")
    parser.add_argument("--start", help="Start date (DD-MM-YYYY or YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (DD-MM-YYYY or YYYY-MM-DD)")
    parser.add_argument("--date", help="Single date (DD-MM-YYYY or YYYY-MM-DD)")
    parser.add_argument("--data-dir", default=DATA_DIR, help=f"Base data directory (default: {DATA_DIR})")
    parser.add_argument("--delete-zip", action="store_true", help="Delete the zip file after successful extraction")

    args = parser.parse_args()

    if args.date:
        args.start = args.date
        args.end = args.date

    if args.start and not args.end:
        parser.error("--start requires --end (or use --date for a single date).")
    if args.end and not args.start:
        parser.error("--end requires --start.")

    if args.start and args.end:
        try:
            unzip_date_range(args.start, args.end, args.data_dir, delete_zip=args.delete_zip)
        except ValueError as e:
            print(f"❌ Error: {e}")
            sys.exit(1)
    elif args.path:
        unzip_in_directory(args.path, delete_zip=args.delete_zip)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
