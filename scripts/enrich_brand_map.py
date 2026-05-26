#!/usr/bin/env python3
"""
Enrich data/brand_industry_map.json with five additional fields per brand:

  hq_country               ISO 3166-1 alpha-2
  sells_in_countries       ISO 3166-1 alpha-2 list (primary markets)
  company_stage            bootstrapped | seed | series_a..d | private_growth | public | subsidiary | state_owned | unknown
  typical_campaign_tier    nano | micro | mid | macro | premium | unknown
                           (matches creator follower tiers; "premium" = global brand budgets
                           working with celebrity/A-list talent)
  creator_program_presence ["direct", "aspire", "grin", "ltk", "shopmy", "agency_of_record"]
                           (observed channels; "direct" is the universal default)

Honest-gaps policy: only fields with high-confidence values are populated.
Unknown fields are omitted from the output (not set to null) so missing
data is visually distinct from `unknown` (which means "we checked and
genuinely don't know").

Run: python3 scripts/enrich_brand_map.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "brand_industry_map.json"

# ---------------------------------------------------------------------------
# Curated enrichment by brand name.
# Format: { brand_name: { hq, sells, stage, tier, programs } }
# Any key omitted means "we don't have a confident value" -> field omitted from output.
# Tier rationale guide:
#   premium = global mass spenders working with A-list celebrities (Apple, Coca-Cola, LVMH brands)
#   macro   = brands with 6-figure influencer budgets per campaign, work with 1M+ creators
#   mid     = D2C brands working with 100k-1M creators routinely (Gymshark, AG1, Liquid Death)
#   micro   = niche brands working with 10k-100k creators (most newer D2C)
#   nano    = local/very small brands working with <10k creators (rarely in this list)
# ---------------------------------------------------------------------------

E = {
    # Sportswear
    "Nike": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Adidas": {"hq": "DE", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Puma": {"hq": "DE", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct", "agency_of_record"]},
    "Under Armour": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Reebok": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "ASICS": {"hq": "JP", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "New Balance": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Hoka": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "On Running": {"hq": "CH", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},

    # Activewear
    "Gymshark": {"hq": "GB", "sells": ["GB", "US", "AU", "DE", "FR", "CA"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Lululemon": {"hq": "CA", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Alo Yoga": {"hq": "US", "sells": ["US", "GB", "CA", "AU"], "stage": "private_growth", "tier": "mid", "programs": ["direct", "ltk"]},
    "Vuori": {"hq": "US", "sells": ["US", "GB", "CA"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Outdoor Voices": {"hq": "US", "sells": ["US"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},

    # Outdoor
    "Patagonia": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "The North Face": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Columbia": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Arc'teryx": {"hq": "CA", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "REI": {"hq": "US", "sells": ["US"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},

    # Fitness equipment & wearables
    "Peloton": {"hq": "US", "sells": ["US", "GB", "CA", "AU", "DE"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Tonal": {"hq": "US", "sells": ["US"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Hydrow": {"hq": "US", "sells": ["US", "GB"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Whoop": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Oura": {"hq": "FI", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Garmin": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Fitbit": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Sports nutrition / supplements
    "Myprotein": {"hq": "GB", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "Optimum Nutrition": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Huel": {"hq": "GB", "sells": ["GB", "US", "DE", "FR", "JP"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "AG1": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Ritual": {"hq": "US", "sells": ["US", "CA", "GB"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},

    # Beauty retail
    "Sephora": {"hq": "FR", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Ulta": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Boots": {"hq": "GB", "sells": ["GB", "IE"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Cosmetics
    "Glossier": {"hq": "US", "sells": ["US", "GB", "CA", "FR"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Charlotte Tilbury": {"hq": "GB", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Rare Beauty": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Fenty Beauty": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "premium", "programs": ["direct"]},
    "MAC Cosmetics": {"hq": "CA", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "NARS": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Estée Lauder": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "L'Oréal": {"hq": "FR", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Maybelline": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Skincare
    "CeraVe": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "The Ordinary": {"hq": "CA", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "Drunk Elephant": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "Olaplex": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},

    # Appliances / grooming
    "Dyson": {"hq": "GB", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Manscaped": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Dollar Shave Club": {"hq": "US", "sells": ["US", "CA", "GB", "AU"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Harry's": {"hq": "US", "sells": ["US", "GB", "DE", "CA"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Gillette": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},

    # Fast fashion / fashion
    "Zara": {"hq": "ES", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "H&M": {"hq": "SE", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Shein": {"hq": "SG", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Uniqlo": {"hq": "JP", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "ASOS": {"hq": "GB", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Boohoo": {"hq": "GB", "sells": "global", "stage": "public", "tier": "mid", "programs": ["direct"]},
    "PrettyLittleThing": {"hq": "GB", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},

    # Luxury
    "Gucci": {"hq": "IT", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Louis Vuitton": {"hq": "FR", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Chanel": {"hq": "FR", "sells": "global", "stage": "private_growth", "tier": "premium", "programs": ["direct"]},
    "Hermès": {"hq": "FR", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Prada": {"hq": "IT", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Dior": {"hq": "FR", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Burberry": {"hq": "GB", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},

    # Watches / jewellery
    "Rolex": {"hq": "CH", "sells": "global", "stage": "private_growth", "tier": "premium", "programs": ["direct"]},
    "Tag Heuer": {"hq": "CH", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Cartier": {"hq": "FR", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Tiffany & Co": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Pandora": {"hq": "DK", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},

    # Eyewear
    "Ray-Ban": {"hq": "IT", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Warby Parker": {"hq": "US", "sells": ["US", "CA"], "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Oakley": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Footwear
    "Allbirds": {"hq": "US", "sells": ["US", "GB", "CA", "AU", "DE", "JP"], "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Crocs": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Dr. Martens": {"hq": "GB", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},

    # Soft drinks / beverages
    "Coca-Cola": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Pepsi": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Red Bull": {"hq": "AT", "sells": "global", "stage": "private_growth", "tier": "premium", "programs": ["direct"]},
    "Monster Energy": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Celsius": {"hq": "US", "sells": ["US", "GB", "AU"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Liquid Death": {"hq": "US", "sells": ["US", "GB", "CA"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},

    # Alcohol
    "Heineken": {"hq": "NL", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Guinness": {"hq": "IE", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Stella Artois": {"hq": "BE", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "BrewDog": {"hq": "GB", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Don Julio": {"hq": "MX", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Patrón": {"hq": "MX", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Grey Goose": {"hq": "FR", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Hendrick's": {"hq": "GB", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Veuve Clicquot": {"hq": "FR", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Moët & Chandon": {"hq": "FR", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},

    # QSR / restaurants
    "McDonald's": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Burger King": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "KFC": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Subway": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Chipotle": {"hq": "US", "sells": ["US", "CA", "GB", "DE", "FR"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Domino's": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Starbucks": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Dunkin'": {"hq": "US", "sells": ["US"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Food delivery
    "DoorDash": {"hq": "US", "sells": ["US", "CA", "AU", "JP", "GB", "DE"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Uber Eats": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Deliveroo": {"hq": "GB", "sells": ["GB", "FR", "IT", "BE", "IE", "AE", "SG", "HK"], "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Just Eat": {"hq": "GB", "sells": ["GB", "IE", "DE", "FR", "ES", "IT", "NL", "AU", "CA"], "stage": "public", "tier": "mid", "programs": ["direct"]},

    # Meal kits / plant-based
    "HelloFresh": {"hq": "DE", "sells": ["US", "GB", "DE", "AU", "CA", "NZ", "FR", "NL", "SE"], "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Gousto": {"hq": "GB", "sells": ["GB"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Blue Apron": {"hq": "US", "sells": ["US"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Beyond Meat": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Impossible Foods": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Oatly": {"hq": "SE", "sells": "global", "stage": "public", "tier": "mid", "programs": ["direct"]},

    # Grocery
    "Tesco": {"hq": "GB", "sells": ["GB", "IE"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Sainsbury's": {"hq": "GB", "sells": ["GB"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Whole Foods": {"hq": "US", "sells": ["US", "GB", "CA"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Trader Joe's": {"hq": "US", "sells": ["US"], "stage": "private_growth", "tier": "micro", "programs": ["direct"]},
    "Aldi": {"hq": "DE", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},

    # Consumer electronics
    "Apple": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Samsung": {"hq": "KR", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Sony": {"hq": "JP", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Google": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Microsoft": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Bose": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Sonos": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Beats": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "JBL": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "GoPro": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "DJI": {"hq": "CN", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Razer": {"hq": "SG", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Logitech": {"hq": "CH", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "HyperX": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "Nvidia": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Intel": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "AMD": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},

    # AI / SaaS
    "OpenAI": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Anthropic": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Midjourney": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "micro", "programs": ["direct"]},
    "Adobe": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Canva": {"hq": "AU", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Figma": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Notion": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Grammarly": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Slack": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Zoom": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "NordVPN": {"hq": "LT", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "ExpressVPN": {"hq": "VG", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Surfshark": {"hq": "NL", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},

    # Game publishers
    "Nintendo": {"hq": "JP", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "PlayStation": {"hq": "JP", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Xbox": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Activision Blizzard": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Electronic Arts": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Ubisoft": {"hq": "FR", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Epic Games": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Riot Games": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Streaming
    "Netflix": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Disney+": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "HBO Max": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Amazon Prime Video": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Hulu": {"hq": "US", "sells": ["US", "JP"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Apple TV+": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Spotify": {"hq": "SE", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Apple Music": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "YouTube Music": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Audible": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Kindle": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Travel & hospitality
    "Airbnb": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Vrbo": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Booking.com": {"hq": "NL", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Expedia": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Kayak": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "Marriott": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Hilton": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Hyatt": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Delta Air Lines": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "United Airlines": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "American Airlines": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "British Airways": {"hq": "GB", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Emirates": {"hq": "AE", "sells": "global", "stage": "state_owned", "tier": "premium", "programs": ["direct"]},
    "Ryanair": {"hq": "IE", "sells": ["GB", "IE", "ES", "IT", "DE", "FR"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "easyJet": {"hq": "GB", "sells": ["GB", "EU"], "stage": "public", "tier": "macro", "programs": ["direct"]},

    # Mobility
    "Uber": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Lyft": {"hq": "US", "sells": ["US", "CA"], "stage": "public", "tier": "macro", "programs": ["direct"]},

    # Auto / EV
    "Tesla": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Rivian": {"hq": "US", "sells": ["US", "CA"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Polestar": {"hq": "SE", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Lucid Motors": {"hq": "US", "sells": ["US", "EU", "ME"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "BYD": {"hq": "CN", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Toyota": {"hq": "JP", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "Honda": {"hq": "JP", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Ford": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "BMW": {"hq": "DE", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Mercedes-Benz": {"hq": "DE", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Audi": {"hq": "DE", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Porsche": {"hq": "DE", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Volkswagen": {"hq": "DE", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Hyundai": {"hq": "KR", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Kia": {"hq": "KR", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Harley-Davidson": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Ducati": {"hq": "IT", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Triumph Motorcycles": {"hq": "GB", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},

    # Banking & fintech
    "Chase": {"hq": "US", "sells": ["US"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Bank of America": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "HSBC": {"hq": "GB", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Barclays": {"hq": "GB", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Lloyds": {"hq": "GB", "sells": ["GB"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Revolut": {"hq": "GB", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Monzo": {"hq": "GB", "sells": ["GB", "US"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Starling Bank": {"hq": "GB", "sells": ["GB"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Chime": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Wise": {"hq": "GB", "sells": "global", "stage": "public", "tier": "mid", "programs": ["direct"]},
    "PayPal": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Cash App": {"hq": "US", "sells": ["US", "GB"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Cards / BNPL
    "Visa": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Mastercard": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "American Express": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Klarna": {"hq": "SE", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Afterpay": {"hq": "AU", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "Affirm": {"hq": "US", "sells": ["US", "CA"], "stage": "public", "tier": "mid", "programs": ["direct"]},

    # Investing / crypto
    "Robinhood": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "mid", "programs": ["direct"]},
    "eToro": {"hq": "IL", "sells": "global", "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Trading 212": {"hq": "GB", "sells": ["GB", "EU"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Coinbase": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Binance": {"hq": "AE", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Kraken": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},

    # Apps & platforms
    "Bumble": {"hq": "US", "sells": "global", "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Hinge": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "Tinder": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Match.com": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "Duolingo": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Babbel": {"hq": "DE", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "MasterClass": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Coursera": {"hq": "US", "sells": "global", "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Udemy": {"hq": "US", "sells": "global", "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Skillshare": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Headspace": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Calm": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "BetterHelp": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Marketplaces
    "Amazon": {"hq": "US", "sells": "global", "stage": "public", "tier": "premium", "programs": ["direct", "agency_of_record"]},
    "eBay": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Etsy": {"hq": "US", "sells": "global", "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Shopify": {"hq": "CA", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Walmart": {"hq": "US", "sells": ["US", "CA", "MX"], "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Target": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Costco": {"hq": "US", "sells": ["US", "CA", "MX", "GB", "JP", "KR", "AU"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "John Lewis": {"hq": "GB", "sells": ["GB"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Marks & Spencer": {"hq": "GB", "sells": ["GB", "IE"], "stage": "public", "tier": "macro", "programs": ["direct"]},

    # Home & furniture
    "IKEA": {"hq": "SE", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "West Elm": {"hq": "US", "sells": ["US", "CA", "GB", "AU"], "stage": "subsidiary", "tier": "mid", "programs": ["direct"]},
    "Wayfair": {"hq": "US", "sells": ["US", "CA", "GB", "DE"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Casper": {"hq": "US", "sells": ["US", "CA"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Simba": {"hq": "GB", "sells": ["GB", "EU"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Eight Sleep": {"hq": "US", "sells": ["US", "GB", "CA", "DE"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "Le Creuset": {"hq": "FR", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Ninja": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Vitamix": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "B&Q": {"hq": "GB", "sells": ["GB", "IE"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Home Depot": {"hq": "US", "sells": ["US", "CA", "MX"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Lowe's": {"hq": "US", "sells": ["US", "CA"], "stage": "public", "tier": "macro", "programs": ["direct"]},

    # Kids
    "Lego": {"hq": "DK", "sells": "global", "stage": "private_growth", "tier": "premium", "programs": ["direct"]},
    "Mattel": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Hasbro": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Pampers": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "premium", "programs": ["direct"]},
    "Huggies": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Pets
    "Purina": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Pedigree": {"hq": "US", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Royal Canin": {"hq": "FR", "sells": "global", "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Chewy": {"hq": "US", "sells": ["US", "CA"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "BarkBox": {"hq": "US", "sells": ["US", "CA"], "stage": "public", "tier": "mid", "programs": ["direct"]},

    # Gambling (sensitive)
    "DraftKings": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "FanDuel": {"hq": "US", "sells": ["US"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Bet365": {"hq": "GB", "sells": "global", "stage": "private_growth", "tier": "macro", "programs": ["direct"]},
    "Paddy Power": {"hq": "IE", "sells": ["GB", "IE"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "William Hill": {"hq": "GB", "sells": ["GB"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Telecom
    "Verizon": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "premium", "programs": ["direct"]},
    "AT&T": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "premium", "programs": ["direct"]},
    "T-Mobile": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "premium", "programs": ["direct"]},
    "Vodafone": {"hq": "GB", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "EE": {"hq": "GB", "sells": ["GB"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "O2": {"hq": "GB", "sells": ["GB"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Three": {"hq": "GB", "sells": ["GB"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Energy
    "Octopus Energy": {"hq": "GB", "sells": ["GB", "DE", "FR", "JP", "US"], "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
    "British Gas": {"hq": "GB", "sells": ["GB"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "EDF Energy": {"hq": "GB", "sells": ["GB"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},

    # Insurance
    "Geico": {"hq": "US", "sells": ["US"], "stage": "subsidiary", "tier": "macro", "programs": ["direct"]},
    "Progressive": {"hq": "US", "sells": ["US"], "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Lemonade": {"hq": "US", "sells": ["US", "GB", "DE", "FR", "NL"], "stage": "public", "tier": "mid", "programs": ["direct"]},
    "Aviva": {"hq": "GB", "sells": ["GB", "IE", "CA"], "stage": "public", "tier": "macro", "programs": ["direct"]},

    # Web / SaaS tail
    "Squarespace": {"hq": "US", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Wix": {"hq": "IL", "sells": "global", "stage": "public", "tier": "macro", "programs": ["direct"]},
    "Webflow": {"hq": "US", "sells": "global", "stage": "private_growth", "tier": "mid", "programs": ["direct"]},
}


def normalize_sells(v):
    """sells_in_countries is either a list of ISO codes or the literal string 'global'."""
    if v is None:
        return None
    if isinstance(v, str):
        return v  # 'global' literal
    return list(v)


def main():
    doc = json.loads(SRC.read_text())
    brands = doc["brands"]

    enriched_count = 0
    partial_count = 0
    no_data_count = 0

    for b in brands:
        name = b["name"]
        if name not in E:
            no_data_count += 1
            continue
        ext = E[name]
        # Only set fields where we have data; omit otherwise so
        # missing data is visible (not silently null).
        if "hq" in ext:
            b["hq_country"] = ext["hq"]
        if "sells" in ext:
            b["sells_in_countries"] = normalize_sells(ext["sells"])
        if "stage" in ext:
            b["company_stage"] = ext["stage"]
        if "tier" in ext:
            b["typical_campaign_tier"] = ext["tier"]
        if "programs" in ext:
            b["creator_program_presence"] = list(ext["programs"])

        # Track completeness
        keys_present = sum(1 for k in ("hq_country", "sells_in_countries", "company_stage",
                                       "typical_campaign_tier", "creator_program_presence") if k in b)
        if keys_present == 5:
            enriched_count += 1
        else:
            partial_count += 1

    # Update the metadata block
    doc["$comment"] = (
        "Seed lookup table for auto-completing the `industry_id` field on previous_brands when a "
        "user types a brand name. Resolution order at runtime: 1) exact name match (case-insensitive), "
        "2) alias match, 3) domain match, 4) AI inference fallback (later phase). New successful AI "
        "inferences should be appended here so the seed grows over time. "
        "Each record may also carry enrichment fields (hq_country, sells_in_countries, company_stage, "
        "typical_campaign_tier, creator_program_presence) used by Brand Discovery searches (see "
        "docs/brand_discovery.md). Fields are present only when we have confident values; absence "
        "means 'not yet enriched' - the app should treat missing as unknown."
    )
    doc["updated"] = "2026-05-26"
    doc["enrichment_field_definitions"] = {
        "hq_country": "ISO 3166-1 alpha-2 country code of the brand's headquarters.",
        "sells_in_countries": "Either the literal string 'global' or an array of ISO 3166-1 alpha-2 codes for primary markets.",
        "company_stage": "One of: bootstrapped | seed | series_a | series_b | series_c | series_d | private_growth | public | subsidiary | state_owned | unknown.",
        "typical_campaign_tier": "One of: nano | micro | mid | macro | premium | unknown. Indicates the creator follower-tier band this brand typically works with.",
        "creator_program_presence": "Array of observed channels: direct | aspire | grin | ltk | shopmy | agency_of_record."
    }

    SRC.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")

    total = len(brands)
    print(f"Total brands: {total}")
    print(f"  Fully enriched (5/5 fields): {enriched_count}  ({100*enriched_count//total}%)")
    print(f"  Partially enriched: {partial_count}")
    print(f"  Not enriched (no entry in E): {no_data_count}  ({100*no_data_count//total}%)")
    print(f"\nWrote {SRC}")


if __name__ == "__main__":
    main()
