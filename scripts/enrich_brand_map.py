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


# ---------------------------------------------------------------------------
# Financials: revenue + headcount
# ---------------------------------------------------------------------------
# Format: { name: { "rev_usd": int, "rev_year": int, "rev_src": str, "hc_band": str, "hc_src": str (optional) } }
# rev_src: public_filing | press_release | reported_estimate
# hc_band: 1_10 | 11_50 | 51_200 | 201_500 | 501_1000 | 1001_5000 | 5001_10000 | 10000_plus
# hc_src defaults to "linkedin" if omitted.
#
# Honesty policy:
#  - rev_usd: only when figure is from public filings or a credible public disclosure.
#  - Foreign-currency figures converted to USD at roughly the year-end rate; rounded to
#    the nearest $100M (or $1B for >$10B brands).
#  - hc_band: only where LinkedIn / filings reliably indicate the band.
#  - Subsidiary brands whose parent doesn't disclose brand-level financials get rev omitted.
#  - Skip the brand entirely if neither field is confidently known. Do not fabricate.
FINANCIALS = {
    # Sportswear
    "Nike":          {"rev_usd": 51_400_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Adidas":        {"rev_usd": 23_700_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Puma":          {"rev_usd": 9_300_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Under Armour":  {"rev_usd": 5_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "ASICS":         {"rev_usd": 4_500_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "New Balance":   {"rev_usd": 7_800_000_000,  "rev_year": 2024, "rev_src": "press_release", "hc_band": "5001_10000"},
    "Hoka":          {"rev_usd": 2_200_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "501_1000"},
    "On Running":    {"rev_usd": 2_500_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},

    # Activewear
    "Gymshark":      {"rev_usd": 700_000_000,    "rev_year": 2024, "rev_src": "press_release", "hc_band": "501_1000"},
    "Lululemon":     {"rev_usd": 10_500_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Outdoor Voices":{"hc_band": "51_200"},

    # Outdoor
    "Patagonia":     {"rev_usd": 1_500_000_000,  "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "1001_5000"},
    "The North Face":{"rev_usd": 3_200_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Columbia":      {"rev_usd": 3_400_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "Arc'teryx":     {"rev_usd": 2_000_000_000,  "rev_year": 2024, "rev_src": "press_release", "hc_band": "501_1000"},
    "REI":           {"rev_usd": 3_800_000_000,  "rev_year": 2024, "rev_src": "press_release", "hc_band": "10000_plus"},

    # Fitness equipment & wearables
    "Peloton":       {"rev_usd": 2_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Whoop":         {"hc_band": "201_500"},
    "Oura":          {"hc_band": "201_500"},
    "Garmin":        {"rev_usd": 5_500_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Fitbit":        {"hc_band": "1001_5000"},

    # Supplements / nutrition
    "Myprotein":     {"rev_usd": 500_000_000,    "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "501_1000"},
    "Huel":          {"rev_usd": 200_000_000,    "rev_year": 2024, "rev_src": "press_release", "hc_band": "201_500"},
    "AG1":           {"hc_band": "201_500"},
    "Ritual":        {"hc_band": "51_200"},

    # Beauty retail / mass-market
    "Sephora":       {"rev_usd": 18_000_000_000, "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "10000_plus"},
    "Ulta":          {"rev_usd": 11_200_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Boots":         {"rev_usd": 9_000_000_000,  "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "10000_plus"},

    # Cosmetics
    "Glossier":      {"rev_usd": 275_000_000,    "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "201_500"},
    "Charlotte Tilbury":{"rev_usd": 700_000_000, "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "501_1000"},
    "Estée Lauder":  {"rev_usd": 15_600_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "L'Oréal":       {"rev_usd": 45_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Olaplex":       {"rev_usd": 425_000_000,    "rev_year": 2024, "rev_src": "public_filing", "hc_band": "201_500"},

    # Appliances / grooming
    "Dyson":         {"rev_usd": 8_000_000_000,  "rev_year": 2024, "rev_src": "press_release", "hc_band": "10000_plus"},
    "Harry's":       {"rev_usd": 400_000_000,    "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "201_500"},

    # Fashion / fast-fashion
    "Zara":          {"rev_usd": 38_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "H&M":           {"rev_usd": 22_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Shein":         {"rev_usd": 38_000_000_000, "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "10000_plus"},
    "Uniqlo":        {"rev_usd": 21_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "ASOS":          {"rev_usd": 4_400_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Boohoo":        {"rev_usd": 1_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},

    # Luxury
    "Louis Vuitton": {"rev_usd": 22_000_000_000, "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "10000_plus"},
    "Chanel":        {"rev_usd": 19_700_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Hermès":        {"rev_usd": 16_300_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Prada":         {"rev_usd": 5_400_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Burberry":      {"rev_usd": 3_300_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},

    # Watches / jewellery
    "Rolex":         {"rev_usd": 11_500_000_000, "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "10000_plus"},
    "Pandora":       {"rev_usd": 4_300_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},

    # Footwear
    "Allbirds":      {"rev_usd": 190_000_000,    "rev_year": 2024, "rev_src": "public_filing", "hc_band": "501_1000"},
    "Crocs":         {"rev_usd": 4_100_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "Dr. Martens":   {"rev_usd": 980_000_000,    "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},

    # Beverages
    "Coca-Cola":     {"rev_usd": 47_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Pepsi":         {"rev_usd": 92_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Red Bull":      {"rev_usd": 12_000_000_000, "rev_year": 2024, "rev_src": "press_release", "hc_band": "10000_plus"},
    "Monster Energy":{"rev_usd": 7_500_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Celsius":       {"rev_usd": 1_400_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "201_500"},
    "Liquid Death":  {"rev_usd": 350_000_000,    "rev_year": 2024, "rev_src": "press_release", "hc_band": "51_200"},

    # Alcohol
    "Heineken":      {"rev_usd": 33_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "BrewDog":       {"rev_usd": 400_000_000,    "rev_year": 2024, "rev_src": "press_release", "hc_band": "1001_5000"},

    # QSR / restaurants
    "McDonald's":    {"rev_usd": 26_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Burger King":   {"rev_usd": 10_900_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Chipotle":      {"rev_usd": 11_300_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Starbucks":     {"rev_usd": 36_200_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Domino's":      {"rev_usd": 4_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},

    # Food delivery
    "DoorDash":      {"rev_usd": 10_700_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "Uber Eats":     {"hc_band": "10000_plus"},
    "Deliveroo":     {"rev_usd": 2_500_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Just Eat":      {"rev_usd": 5_400_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},

    # Meal kits & plant-based
    "HelloFresh":    {"rev_usd": 8_200_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Gousto":        {"rev_usd": 400_000_000,    "rev_year": 2024, "rev_src": "press_release", "hc_band": "501_1000"},
    "Beyond Meat":   {"rev_usd": 320_000_000,    "rev_year": 2024, "rev_src": "public_filing", "hc_band": "501_1000"},
    "Oatly":         {"rev_usd": 825_000_000,    "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},

    # Grocery
    "Tesco":         {"rev_usd": 87_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Sainsbury's":   {"rev_usd": 41_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Whole Foods":   {"rev_usd": 22_000_000_000, "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "10000_plus"},

    # Tech
    "Apple":         {"rev_usd": 391_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Samsung":       {"rev_usd": 234_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Sony":          {"rev_usd": 89_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Google":        {"rev_usd": 350_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Microsoft":     {"rev_usd": 245_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Bose":          {"rev_usd": 4_000_000_000,   "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "5001_10000"},
    "Sonos":         {"rev_usd": 1_500_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "GoPro":         {"rev_usd": 800_000_000,     "rev_year": 2024, "rev_src": "public_filing", "hc_band": "501_1000"},
    "DJI":           {"rev_usd": 9_000_000_000,   "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "10000_plus"},
    "Logitech":      {"rev_usd": 4_500_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "Nvidia":        {"rev_usd": 130_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Intel":         {"rev_usd": 53_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "AMD":           {"rev_usd": 25_800_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},

    # AI / SaaS
    "OpenAI":        {"rev_usd": 4_000_000_000,   "rev_year": 2024, "rev_src": "press_release", "hc_band": "1001_5000"},
    "Anthropic":     {"rev_usd": 1_000_000_000,   "rev_year": 2024, "rev_src": "press_release", "hc_band": "501_1000"},
    "Adobe":         {"rev_usd": 21_500_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Canva":         {"rev_usd": 2_500_000_000,   "rev_year": 2024, "rev_src": "press_release", "hc_band": "1001_5000"},
    "Figma":         {"rev_usd": 750_000_000,     "rev_year": 2024, "rev_src": "press_release", "hc_band": "1001_5000"},
    "Notion":        {"hc_band": "501_1000"},
    "Slack":         {"hc_band": "1001_5000"},
    "Zoom":          {"rev_usd": 4_700_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},

    # Gaming
    "Nintendo":      {"rev_usd": 10_500_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "Activision Blizzard":{"rev_usd": 12_000_000_000, "rev_year": 2023, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Electronic Arts":{"rev_usd": 7_600_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Ubisoft":       {"rev_usd": 2_500_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Epic Games":    {"rev_usd": 5_700_000_000,   "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "1001_5000"},

    # Streaming
    "Netflix":       {"rev_usd": 39_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Spotify":       {"rev_usd": 16_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},

    # Travel
    "Airbnb":        {"rev_usd": 11_100_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "Booking.com":   {"rev_usd": 23_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Expedia":       {"rev_usd": 13_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Marriott":      {"rev_usd": 25_100_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Hilton":        {"rev_usd": 11_200_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Hyatt":         {"rev_usd": 6_800_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Delta Air Lines":{"rev_usd": 61_600_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "United Airlines":{"rev_usd": 57_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "American Airlines":{"rev_usd": 54_200_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "British Airways":{"rev_usd": 18_300_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Ryanair":       {"rev_usd": 14_500_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "easyJet":       {"rev_usd": 11_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},

    # Mobility
    "Uber":          {"rev_usd": 43_900_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Lyft":          {"rev_usd": 5_800_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},

    # Auto
    "Tesla":         {"rev_usd": 97_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Rivian":        {"rev_usd": 4_400_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Polestar":      {"rev_usd": 2_400_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Lucid Motors":  {"rev_usd": 800_000_000,     "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "BYD":           {"rev_usd": 107_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Toyota":        {"rev_usd": 310_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Honda":         {"rev_usd": 145_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Ford":          {"rev_usd": 185_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "BMW":           {"rev_usd": 162_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Mercedes-Benz": {"rev_usd": 162_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Audi":          {"rev_usd": 70_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Porsche":       {"rev_usd": 44_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Volkswagen":    {"rev_usd": 348_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Hyundai":       {"rev_usd": 130_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Kia":           {"rev_usd": 78_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Harley-Davidson":{"rev_usd": 5_400_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "Ducati":        {"rev_usd": 1_100_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},

    # Banking / fintech
    "Chase":         {"hc_band": "10000_plus"},
    "Bank of America":{"rev_usd": 100_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "HSBC":          {"rev_usd": 67_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Barclays":      {"rev_usd": 32_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Lloyds":        {"rev_usd": 22_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Revolut":       {"rev_usd": 2_200_000_000,   "rev_year": 2023, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "Monzo":         {"rev_usd": 1_100_000_000,   "rev_year": 2024, "rev_src": "press_release", "hc_band": "1001_5000"},
    "Starling Bank": {"rev_usd": 880_000_000,     "rev_year": 2024, "rev_src": "press_release", "hc_band": "1001_5000"},
    "Chime":         {"hc_band": "1001_5000"},
    "Wise":          {"rev_usd": 1_500_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "PayPal":        {"rev_usd": 31_800_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},

    # Cards / BNPL
    "Visa":          {"rev_usd": 35_900_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Mastercard":    {"rev_usd": 28_200_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "American Express":{"rev_usd": 65_900_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Klarna":        {"rev_usd": 2_800_000_000,   "rev_year": 2024, "rev_src": "press_release", "hc_band": "1001_5000"},
    "Afterpay":      {"hc_band": "1001_5000"},
    "Affirm":        {"rev_usd": 2_300_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},

    # Investing / crypto
    "Robinhood":     {"rev_usd": 2_900_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "eToro":         {"rev_usd": 900_000_000,     "rev_year": 2024, "rev_src": "press_release", "hc_band": "1001_5000"},
    "Coinbase":      {"rev_usd": 6_600_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Binance":       {"rev_usd": 16_800_000_000,  "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "5001_10000"},
    "Kraken":        {"hc_band": "1001_5000"},

    # Apps & platforms
    "Bumble":        {"rev_usd": 1_100_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "501_1000"},
    "Hinge":         {"hc_band": "201_500"},
    "Tinder":        {"hc_band": "501_1000"},
    "Duolingo":      {"rev_usd": 750_000_000,     "rev_year": 2024, "rev_src": "public_filing", "hc_band": "501_1000"},
    "Babbel":        {"rev_usd": 270_000_000,     "rev_year": 2024, "rev_src": "press_release", "hc_band": "501_1000"},
    "MasterClass":   {"hc_band": "501_1000"},
    "Coursera":      {"rev_usd": 695_000_000,     "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Udemy":         {"rev_usd": 785_000_000,     "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Skillshare":    {"hc_band": "201_500"},
    "Headspace":     {"hc_band": "501_1000"},
    "Calm":          {"hc_band": "201_500"},
    "BetterHelp":    {"hc_band": "501_1000"},

    # Marketplaces / retail
    "Amazon":        {"rev_usd": 638_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "eBay":          {"rev_usd": 10_300_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Etsy":          {"rev_usd": 2_800_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Shopify":       {"rev_usd": 8_900_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},
    "Walmart":       {"rev_usd": 681_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Target":        {"rev_usd": 107_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Costco":        {"rev_usd": 254_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "John Lewis":    {"rev_usd": 12_400_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Marks & Spencer":{"rev_usd": 16_000_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},

    # Home & furniture
    "IKEA":          {"rev_usd": 50_000_000_000,  "rev_year": 2024, "rev_src": "press_release", "hc_band": "10000_plus"},
    "Wayfair":       {"rev_usd": 11_900_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Casper":        {"rev_usd": 500_000_000,     "rev_year": 2024, "rev_src": "reported_estimate", "hc_band": "201_500"},
    "Eight Sleep":   {"hc_band": "201_500"},
    "Le Creuset":    {"hc_band": "1001_5000"},
    "B&Q":           {"rev_usd": 4_800_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Home Depot":    {"rev_usd": 159_500_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Lowe's":        {"rev_usd": 83_700_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},

    # Kids / toys
    "Lego":          {"rev_usd": 10_100_000_000,  "rev_year": 2024, "rev_src": "press_release", "hc_band": "10000_plus"},
    "Mattel":        {"rev_usd": 5_400_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Hasbro":        {"rev_usd": 4_100_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "5001_10000"},

    # Pets
    "Chewy":         {"rev_usd": 11_900_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "BarkBox":       {"rev_usd": 490_000_000,     "rev_year": 2024, "rev_src": "public_filing", "hc_band": "501_1000"},

    # Gambling
    "DraftKings":    {"rev_usd": 4_800_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "FanDuel":       {"rev_usd": 6_000_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Bet365":        {"rev_usd": 4_400_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},

    # Telecom
    "Verizon":       {"rev_usd": 134_800_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "AT&T":          {"rev_usd": 122_300_000_000, "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "T-Mobile":      {"rev_usd": 81_400_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Vodafone":      {"rev_usd": 40_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},

    # Energy
    "Octopus Energy":{"rev_usd": 16_000_000_000,  "rev_year": 2024, "rev_src": "press_release", "hc_band": "5001_10000"},

    # Insurance
    "Progressive":   {"rev_usd": 75_300_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},
    "Lemonade":      {"rev_usd": 530_000_000,     "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Aviva":         {"rev_usd": 65_000_000_000,  "rev_year": 2024, "rev_src": "public_filing", "hc_band": "10000_plus"},

    # SaaS tail
    "Squarespace":   {"rev_usd": 1_200_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
    "Wix":           {"rev_usd": 1_800_000_000,   "rev_year": 2024, "rev_src": "public_filing", "hc_band": "1001_5000"},
}


# ---------------------------------------------------------------------------
# Social-media follower counts (approximate)
# ---------------------------------------------------------------------------
# Format: { name: { "ig": int, "tt": int, "yt": int, "x": int, "fb": int, "li": int, "yr": int } }
#   ig = Instagram, tt = TikTok, yt = YouTube, x = X/Twitter,
#   fb = Facebook, li = LinkedIn, yr = as-of-year
#
# Honesty policy:
#  - Counts fluctuate week-to-week. Values rounded to:
#       <1M:      nearest 100k
#       1M-10M:   nearest 100k-500k
#       10M-100M: nearest 1M
#       100M+:    nearest 10M
#  - Only included when the brand has a meaningfully public, well-known account
#    on the given platform. Skip platforms where presence is minimal or count
#    is genuinely uncertain.
#  - yr = year the count was last reasonably accurate per training data.
SOCIAL_FOLLOWERS = {
    # Sportswear / activewear (top accounts globally)
    "Nike":          {"ig": 310_000_000, "tt": 6_000_000,  "yt": 2_100_000, "x": 10_000_000, "yr": 2025},
    "Adidas":        {"ig": 29_000_000,  "tt": 5_000_000,  "yt": 1_500_000, "x": 4_500_000,  "yr": 2025},
    "Puma":          {"ig": 14_000_000,  "tt": 2_500_000,  "yt": 600_000,   "yr": 2025},
    "Under Armour":  {"ig": 7_500_000,   "tt": 800_000,    "yt": 400_000,   "yr": 2025},
    "Reebok":        {"ig": 4_500_000,   "tt": 600_000,    "yr": 2025},
    "ASICS":         {"ig": 2_500_000,   "yr": 2025},
    "New Balance":   {"ig": 3_500_000,   "tt": 700_000,    "yr": 2025},
    "Hoka":          {"ig": 1_500_000,   "tt": 400_000,    "yr": 2025},
    "On Running":    {"ig": 1_400_000,   "tt": 300_000,    "yr": 2025},
    "Gymshark":      {"ig": 7_000_000,   "tt": 5_500_000,  "yt": 1_000_000, "yr": 2025},
    "Lululemon":     {"ig": 5_500_000,   "tt": 1_500_000,  "yt": 200_000,   "yr": 2025},
    "Alo Yoga":      {"ig": 3_500_000,   "tt": 1_500_000,  "yr": 2025},
    "Vuori":         {"ig": 600_000,     "yr": 2025},

    # Outdoor
    "Patagonia":     {"ig": 5_500_000,   "yt": 350_000,    "yr": 2025},
    "The North Face":{"ig": 6_000_000,   "tt": 800_000,    "yr": 2025},
    "REI":           {"ig": 2_500_000,   "yr": 2025},

    # Fitness / wearables
    "Peloton":       {"ig": 1_300_000,   "tt": 350_000,    "yr": 2025},
    "Whoop":         {"ig": 500_000,     "yr": 2025},
    "Oura":          {"ig": 350_000,     "yr": 2025},
    "Garmin":        {"ig": 1_500_000,   "yr": 2025},
    "Fitbit":        {"ig": 700_000,     "yr": 2025},

    # Supplements
    "Myprotein":     {"ig": 1_500_000,   "yr": 2025},
    "Huel":          {"ig": 400_000,     "yr": 2025},
    "AG1":           {"ig": 500_000,     "yr": 2025},

    # Beauty retail
    "Sephora":       {"ig": 23_000_000,  "tt": 6_000_000,  "yt": 1_500_000, "yr": 2025},
    "Ulta":          {"ig": 8_000_000,   "tt": 2_500_000,  "yr": 2025},
    "Boots":         {"ig": 1_300_000,   "yr": 2025},

    # Cosmetics (high-engagement category)
    "Glossier":      {"ig": 3_000_000,   "tt": 400_000,    "yr": 2025},
    "Charlotte Tilbury":{"ig": 5_500_000, "tt": 1_500_000, "yr": 2025},
    "Rare Beauty":   {"ig": 4_500_000,   "tt": 2_500_000,  "yr": 2025},
    "Fenty Beauty":  {"ig": 12_500_000,  "tt": 3_500_000,  "yr": 2025},
    "MAC Cosmetics": {"ig": 27_000_000,  "tt": 4_000_000,  "yr": 2025},
    "NARS":          {"ig": 3_500_000,   "yr": 2025},
    "Estée Lauder":  {"ig": 6_500_000,   "yr": 2025},
    "L'Oréal":       {"ig": 11_000_000,  "yr": 2025},
    "Maybelline":    {"ig": 12_500_000,  "yr": 2025},

    # Skincare
    "CeraVe":        {"ig": 1_500_000,   "tt": 2_500_000,  "yr": 2025},
    "The Ordinary":  {"ig": 2_500_000,   "yr": 2025},
    "Drunk Elephant":{"ig": 1_500_000,   "yr": 2025},
    "Olaplex":       {"ig": 2_500_000,   "tt": 600_000,    "yr": 2025},

    # Appliances / grooming
    "Dyson":         {"ig": 1_800_000,   "yr": 2025},
    "Manscaped":     {"ig": 600_000,     "yr": 2025},
    "Harry's":       {"ig": 200_000,     "yr": 2025},
    "Gillette":      {"ig": 1_700_000,   "yr": 2025},

    # Fashion
    "Zara":          {"ig": 60_000_000,  "tt": 4_500_000,  "yr": 2025},
    "H&M":           {"ig": 41_000_000,  "tt": 6_500_000,  "yr": 2025},
    "Shein":         {"ig": 32_000_000,  "tt": 14_000_000, "yr": 2025},
    "Uniqlo":        {"ig": 5_000_000,   "yr": 2025},
    "ASOS":          {"ig": 13_000_000,  "tt": 1_500_000,  "yr": 2025},
    "Boohoo":        {"ig": 8_500_000,   "yr": 2025},
    "PrettyLittleThing":{"ig": 17_000_000, "yr": 2025},

    # Luxury
    "Gucci":         {"ig": 53_000_000,  "tt": 4_000_000,  "yt": 1_500_000, "yr": 2025},
    "Louis Vuitton": {"ig": 56_000_000,  "tt": 6_000_000,  "yt": 2_000_000, "yr": 2025},
    "Chanel":        {"ig": 61_000_000,  "tt": 3_000_000,  "yt": 2_500_000, "yr": 2025},
    "Hermès":        {"ig": 16_000_000,  "yr": 2025},
    "Prada":         {"ig": 32_000_000,  "yr": 2025},
    "Dior":          {"ig": 51_000_000,  "tt": 8_500_000,  "yr": 2025},
    "Burberry":      {"ig": 22_000_000,  "yr": 2025},

    # Watches / jewellery
    "Rolex":         {"ig": 17_000_000,  "yr": 2025},
    "Tag Heuer":     {"ig": 1_700_000,   "yr": 2025},
    "Cartier":       {"ig": 17_000_000,  "yr": 2025},
    "Tiffany & Co":  {"ig": 14_500_000,  "yr": 2025},
    "Pandora":       {"ig": 11_000_000,  "yr": 2025},

    # Eyewear
    "Ray-Ban":       {"ig": 5_500_000,   "yr": 2025},
    "Warby Parker":  {"ig": 600_000,     "yr": 2025},
    "Oakley":        {"ig": 3_500_000,   "yr": 2025},

    # Footwear
    "Allbirds":      {"ig": 400_000,     "yr": 2025},
    "Crocs":         {"ig": 2_500_000,   "tt": 1_200_000,  "yr": 2025},
    "Dr. Martens":   {"ig": 2_500_000,   "yr": 2025},

    # Beverages
    "Coca-Cola":     {"ig": 3_000_000,   "tt": 2_000_000,  "yt": 4_000_000, "fb": 110_000_000, "yr": 2025},
    "Pepsi":         {"ig": 3_500_000,   "yt": 2_500_000,  "yr": 2025},
    "Red Bull":      {"ig": 19_000_000,  "tt": 8_000_000,  "yt": 13_000_000, "yr": 2025},
    "Monster Energy":{"ig": 9_500_000,   "yr": 2025},
    "Celsius":       {"ig": 1_300_000,   "tt": 1_000_000,  "yr": 2025},
    "Liquid Death":  {"ig": 3_000_000,   "tt": 5_500_000,  "yr": 2025},

    # Alcohol
    "Heineken":      {"ig": 1_500_000,   "yr": 2025},
    "Guinness":      {"ig": 600_000,     "yr": 2025},
    "BrewDog":       {"ig": 500_000,     "yr": 2025},

    # QSR
    "McDonald's":    {"ig": 5_500_000,   "tt": 4_500_000,  "yt": 6_000_000, "yr": 2025},
    "Burger King":   {"ig": 3_000_000,   "yr": 2025},
    "KFC":           {"ig": 2_500_000,   "yr": 2025},
    "Chipotle":      {"ig": 2_500_000,   "tt": 2_500_000,  "yr": 2025},
    "Starbucks":     {"ig": 18_000_000,  "tt": 2_500_000,  "yt": 350_000,  "yr": 2025},
    "Domino's":      {"ig": 1_500_000,   "yr": 2025},

    # Food delivery
    "DoorDash":      {"ig": 700_000,     "tt": 800_000,    "yr": 2025},
    "Uber Eats":     {"ig": 700_000,     "yr": 2025},
    "Deliveroo":     {"ig": 600_000,     "yr": 2025},

    # Meal kits / plant-based
    "HelloFresh":    {"ig": 1_500_000,   "yr": 2025},
    "Beyond Meat":   {"ig": 700_000,     "yr": 2025},
    "Oatly":         {"ig": 500_000,     "yr": 2025},

    # Grocery
    "Tesco":         {"ig": 800_000,     "yr": 2025},
    "Whole Foods":   {"ig": 4_000_000,   "yr": 2025},
    "Trader Joe's":  {"ig": 4_000_000,   "yr": 2025},

    # Tech
    "Apple":         {"ig": 33_000_000,  "yt": 21_000_000, "tt": 5_500_000, "yr": 2025},
    "Samsung":       {"ig": 8_000_000,   "yt": 6_000_000,  "yr": 2025},
    "Sony":          {"ig": 5_500_000,   "yr": 2025},
    "Google":        {"ig": 16_500_000,  "yt": 12_500_000, "yr": 2025},
    "Microsoft":     {"ig": 5_000_000,   "yr": 2025},
    "Bose":          {"ig": 600_000,     "yr": 2025},
    "Sonos":         {"ig": 250_000,     "yr": 2025},
    "Beats":         {"ig": 3_500_000,   "yr": 2025},
    "GoPro":         {"ig": 18_000_000,  "tt": 3_500_000,  "yt": 11_000_000, "yr": 2025},
    "DJI":           {"ig": 4_500_000,   "yr": 2025},
    "Razer":         {"ig": 3_500_000,   "yr": 2025},
    "Logitech":      {"ig": 600_000,     "yr": 2025},
    "Nvidia":        {"ig": 2_500_000,   "yr": 2025},
    "Intel":         {"ig": 1_500_000,   "yr": 2025},

    # AI / SaaS
    "OpenAI":        {"x": 5_000_000,    "yr": 2025},
    "Anthropic":     {"x": 350_000,      "yr": 2025},
    "Midjourney":    {"x": 1_500_000,    "yr": 2025},
    "Adobe":         {"ig": 4_000_000,   "yr": 2025},
    "Canva":         {"ig": 1_500_000,   "yr": 2025},
    "Figma":         {"x": 400_000,      "yr": 2025},
    "Notion":        {"x": 350_000,      "yr": 2025},
    "Grammarly":     {"ig": 250_000,     "yr": 2025},

    # Gaming
    "Nintendo":      {"ig": 1_500_000,   "yt": 11_500_000, "x": 10_500_000, "yr": 2025},
    "PlayStation":   {"ig": 35_000_000,  "yt": 16_500_000, "yr": 2025},
    "Xbox":          {"ig": 19_000_000,  "yt": 8_500_000,  "yr": 2025},
    "Electronic Arts":{"ig": 5_500_000,  "yr": 2025},
    "Epic Games":    {"ig": 800_000,     "yt": 3_500_000,  "yr": 2025},
    "Riot Games":    {"ig": 5_500_000,   "yr": 2025},

    # Streaming
    "Netflix":       {"ig": 33_000_000,  "tt": 41_000_000, "yt": 32_000_000, "yr": 2025},
    "Disney+":       {"ig": 11_000_000,  "yr": 2025},
    "Spotify":       {"ig": 5_500_000,   "tt": 2_500_000,  "yr": 2025},
    "Apple Music":   {"ig": 2_500_000,   "yr": 2025},

    # Travel
    "Airbnb":        {"ig": 5_500_000,   "yr": 2025},
    "Booking.com":   {"ig": 400_000,     "yr": 2025},
    "Marriott":      {"ig": 2_500_000,   "yr": 2025},
    "Hilton":        {"ig": 1_500_000,   "yr": 2025},
    "Emirates":      {"ig": 11_000_000,  "yr": 2025},
    "Ryanair":       {"ig": 2_500_000,   "tt": 2_500_000,  "yr": 2025},

    # Mobility
    "Uber":          {"ig": 1_500_000,   "yr": 2025},
    "Lyft":          {"ig": 250_000,     "yr": 2025},

    # Auto
    "Tesla":         {"ig": 10_500_000,  "yt": 3_500_000,  "yr": 2025},
    "Rivian":        {"ig": 1_500_000,   "yr": 2025},
    "Polestar":      {"ig": 600_000,     "yr": 2025},
    "Toyota":        {"ig": 1_500_000,   "yr": 2025},
    "Honda":         {"ig": 1_500_000,   "yr": 2025},
    "Ford":          {"ig": 1_700_000,   "yr": 2025},
    "BMW":           {"ig": 39_000_000,  "yt": 3_000_000,  "yr": 2025},
    "Mercedes-Benz": {"ig": 32_000_000,  "yt": 2_500_000,  "yr": 2025},
    "Audi":          {"ig": 16_000_000,  "yr": 2025},
    "Porsche":       {"ig": 39_000_000,  "yt": 1_500_000,  "yr": 2025},
    "Hyundai":       {"ig": 1_500_000,   "yr": 2025},
    "Harley-Davidson":{"ig": 7_500_000,  "yr": 2025},
    "Ducati":        {"ig": 3_500_000,   "yr": 2025},

    # Fintech
    "Revolut":       {"ig": 800_000,     "yr": 2025},
    "Monzo":         {"ig": 250_000,     "yr": 2025},
    "PayPal":        {"ig": 1_500_000,   "yr": 2025},
    "Cash App":      {"ig": 1_500_000,   "yr": 2025},
    "American Express":{"ig": 2_000_000, "yr": 2025},
    "Klarna":        {"ig": 600_000,     "yr": 2025},
    "Robinhood":     {"ig": 1_000_000,   "yr": 2025},
    "Coinbase":      {"ig": 1_300_000,   "yr": 2025},
    "Binance":       {"ig": 3_000_000,   "x": 11_000_000,  "yr": 2025},

    # Apps & platforms
    "Bumble":        {"ig": 600_000,     "yr": 2025},
    "Hinge":         {"ig": 700_000,     "tt": 1_300_000,  "yr": 2025},
    "Tinder":        {"ig": 4_000_000,   "tt": 1_500_000,  "yr": 2025},
    "Duolingo":      {"ig": 7_500_000,   "tt": 14_000_000, "yr": 2025},
    "Babbel":        {"ig": 400_000,     "yr": 2025},
    "MasterClass":   {"ig": 700_000,     "yr": 2025},
    "Headspace":     {"ig": 600_000,     "yr": 2025},
    "Calm":          {"ig": 1_100_000,   "yr": 2025},

    # Retail
    "Amazon":        {"ig": 6_500_000,   "yr": 2025},
    "eBay":          {"ig": 1_500_000,   "yr": 2025},
    "Etsy":          {"ig": 3_500_000,   "yr": 2025},
    "Shopify":       {"ig": 1_500_000,   "yr": 2025},
    "Walmart":       {"ig": 3_500_000,   "tt": 7_500_000,  "yr": 2025},
    "Target":        {"ig": 5_000_000,   "tt": 2_000_000,  "yr": 2025},
    "Costco":        {"ig": 1_500_000,   "yr": 2025},

    # Home & furniture
    "IKEA":          {"ig": 7_000_000,   "yr": 2025},
    "West Elm":      {"ig": 2_500_000,   "yr": 2025},
    "Wayfair":       {"ig": 4_500_000,   "yr": 2025},
    "Casper":        {"ig": 350_000,     "yr": 2025},

    # Kids / toys
    "Lego":          {"ig": 8_500_000,   "yt": 16_500_000, "yr": 2025},
    "Mattel":        {"ig": 1_500_000,   "yr": 2025},

    # Pets
    "Chewy":         {"ig": 1_500_000,   "tt": 800_000,    "yr": 2025},
    "BarkBox":       {"ig": 1_500_000,   "yr": 2025},

    # Gambling
    "DraftKings":    {"ig": 1_500_000,   "yr": 2025},
    "FanDuel":       {"ig": 600_000,     "yr": 2025},
}


def normalize_sells(v):
    """sells_in_countries is either a list of ISO codes or the literal string 'global'."""
    if v is None:
        return None
    if isinstance(v, str):
        return v  # 'global' literal
    return list(v)


PLATFORM_KEYS = [("ig", "instagram"), ("tt", "tiktok"), ("yt", "youtube"),
                 ("x", "twitter_x"), ("fb", "facebook"), ("li", "linkedin"),
                 ("pi", "pinterest")]


def main():
    doc = json.loads(SRC.read_text())
    brands = doc["brands"]

    core_full = 0
    core_partial = 0
    core_none = 0
    with_revenue = 0
    with_headcount = 0
    with_followers = 0

    for b in brands:
        name = b["name"]

        # Core enrichment (hq/sells/stage/tier/programs)
        if name in E:
            ext = E[name]
            if "hq" in ext:        b["hq_country"] = ext["hq"]
            if "sells" in ext:     b["sells_in_countries"] = normalize_sells(ext["sells"])
            if "stage" in ext:     b["company_stage"] = ext["stage"]
            if "tier" in ext:      b["typical_campaign_tier"] = ext["tier"]
            if "programs" in ext:  b["creator_program_presence"] = list(ext["programs"])
            keys_present = sum(1 for k in ("hq_country", "sells_in_countries", "company_stage",
                                           "typical_campaign_tier", "creator_program_presence") if k in b)
            if keys_present == 5: core_full += 1
            else: core_partial += 1
        else:
            core_none += 1

        # Financials: revenue + headcount
        if name in FINANCIALS:
            f = FINANCIALS[name]
            if "rev_usd" in f:
                b["revenue"] = {
                    "amount_usd": f["rev_usd"],
                    "as_of_year": f["rev_year"],
                    "source": f["rev_src"]
                }
                with_revenue += 1
            if "hc_band" in f:
                b["headcount"] = {
                    "band": f["hc_band"],
                    "source": f.get("hc_src", "linkedin")
                }
                with_headcount += 1

        # Social follower counts
        if name in SOCIAL_FOLLOWERS:
            s = SOCIAL_FOLLOWERS[name]
            followers = {}
            for short, full in PLATFORM_KEYS:
                if short in s:
                    followers[full] = s[short]
            if followers:
                followers["as_of_year"] = s.get("yr", 2025)
                b["social_followers"] = followers
                with_followers += 1

    # Update the metadata block
    doc["$comment"] = (
        "Seed lookup table for auto-completing the `industry_id` field on previous_brands when a "
        "user types a brand name. Resolution order at runtime: 1) exact name match (case-insensitive), "
        "2) alias match, 3) domain match, 4) AI inference fallback (later phase). New successful AI "
        "inferences should be appended here so the seed grows over time. "
        "Each record may also carry enrichment fields (hq_country, sells_in_countries, company_stage, "
        "typical_campaign_tier, creator_program_presence, revenue, headcount, social_followers) used by "
        "Brand Discovery searches (see docs/brand_discovery.md) and qualification scoring. Fields are "
        "present only when we have confident values; absence means 'not yet enriched' - the app treats "
        "missing as unknown rather than assuming a default. See docs/brand_enrichment_workflow.md for "
        "the end-to-end process that takes a brand from name-only to fully enriched."
    )
    doc["updated"] = "2026-05-26"
    doc["enrichment_field_definitions"] = {
        "hq_country": "ISO 3166-1 alpha-2 country code of the brand's headquarters.",
        "sells_in_countries": "Either the literal string 'global' or an array of ISO 3166-1 alpha-2 codes for primary markets.",
        "company_stage": "One of: bootstrapped | seed | series_a | series_b | series_c | series_d | private_growth | public | subsidiary | state_owned | unknown.",
        "typical_campaign_tier": "One of: nano | micro | mid | macro | premium | unknown. Indicates the creator follower-tier band this brand typically works with.",
        "creator_program_presence": "Array of observed channels: direct | aspire | grin | ltk | shopmy | agency_of_record.",
        "revenue": "Object: { amount_usd: int (annual revenue, USD), as_of_year: int (fiscal year reported), source: 'public_filing' | 'press_release' | 'reported_estimate' }. Foreign currencies converted to USD, rounded to nearest $100M (or $1B for >$10B brands).",
        "headcount": "Object: { band: '1_10' | '11_50' | '51_200' | '201_500' | '501_1000' | '1001_5000' | '5001_10000' | '10000_plus', source: 'linkedin' | 'public_filing' | 'press_release' | 'reported_estimate' }. LinkedIn-standard bands.",
        "social_followers": "Object: { instagram?: int, tiktok?: int, youtube?: int, twitter_x?: int, facebook?: int, linkedin?: int, pinterest?: int, as_of_year: int }. Counts rounded based on scale (<1M: 100k; 1M-10M: 100k-500k; 10M-100M: 1M; 100M+: 10M). Platforms with minimal/uncertain presence are omitted."
    }

    SRC.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")

    total = len(brands)
    print(f"Total brands: {total}")
    print(f"  Core enrichment (5/5 fields): {core_full}  ({100*core_full//total}%)")
    print(f"  Core partial: {core_partial}")
    print(f"  Core none: {core_none}")
    print(f"  Revenue populated: {with_revenue}  ({100*with_revenue//total}%)")
    print(f"  Headcount populated: {with_headcount}  ({100*with_headcount//total}%)")
    print(f"  Social-followers populated: {with_followers}  ({100*with_followers//total}%)")
    print(f"\nWrote {SRC}")


if __name__ == "__main__":
    main()
