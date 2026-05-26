#!/usr/bin/env python3
"""
Build the three affinity files from authored data:
- data/niche_industry_affinity.json     (direct, 3-tier, symmetric)
- data/niche_audience_affinity.json     (niche -> IAB Interest + Demographic)
- data/industry_audience_affinity.json  (industry -> IAB Purchase Intent + Demographic)

All cross-references are validated against:
- data/niches.json
- data/industries.json
- data/iab_audience_taxonomy_v1.1.json

Quality floor: every edge has either a citable source ('iab' | 'imh' | 'hypeauditor'
| 'case-study') or a non-generic logical reason. Generic 'broad audience' reasons
are not accepted - if the niche is too broad for a specific industry to be
distinguishable, the edge is omitted.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'

niches = {n['id']: n for n in json.loads((DATA/'niches.json').read_text())['niches']}
industries = {i['id']: i for i in json.loads((DATA/'industries.json').read_text())['industries']}
iab = {s['id']: s for s in json.loads((DATA/'iab_audience_taxonomy_v1.1.json').read_text())['segments']}

# ---------------------------------------------------------------------------
# IAB segment shortcuts. Names match the official taxonomy v1.1.
# ---------------------------------------------------------------------------
# Demographic
AGE = {'18-20': 3, '21-24': 4, '25-29': 5, '30-34': 6, '35-39': 7, '40-44': 8,
       '45-49': 9, '50-54': 10, '55-59': 11, '60-64': 12, '65-69': 13, '70-74': 14, '75+': 15}
GENDER_F = 49
GENDER_M = 50
GENDER_OTHER = 51
HOME_LOC = 54
HH_INCOME = 60
LIFE_STAGE = 93
NUM_CHILDREN = 125
OWNERSHIP = 137
URBANIZATION = 146
MARRIED = 161
SINGLE = 162
INCOME = 164
AFFLUENCE = 191

# Interest (root 206)
INT_ACADEMIC = 207
INT_AUTO = 243
INT_AUTO_BUYING = 244
INT_AUTO_TECH = 246
INT_AUTO_CULTURE = 248
INT_AUTO_CLASSIC = 249
INT_AUTO_GREEN = 253
INT_AUTO_LUXURY = 254
INT_AUTO_MOTORCYCLES = 255
INT_AUTO_PERFORMANCE = 256
INT_BOOKS = 258
INT_BUSINESS_FINANCE = 268
INT_CAREERS = 338
INT_CAREER_ADVICE = 340
INT_REMOTE_WORK = 342
INT_EDUCATION = 344
INT_LANGUAGE_LEARNING = 346
INT_ONLINE_EDU = 347
INT_FAMILY = 348
INT_PARENTING = 350
INT_FINE_ART = 359
INT_DANCE = 361
INT_DESIGN = 362
INT_DIGITAL_ARTS = 363
INT_FINE_ART_PHOTO = 364
INT_FOOD_DRINK = 368
INT_ALCOHOL = 369
INT_BBQ = 370
INT_COOKING = 371
INT_BAKING = 372
INT_DINING_OUT = 373
INT_FOOD_MOVEMENTS = 375
INT_HEALTHY_COOKING = 376
INT_NON_ALCOHOLIC = 377
INT_VEGAN = 378
INT_VEGETARIAN = 379
INT_WORLD_CUISINES = 380
INT_HEALTH_SERVICES = 381
INT_HEALTHY_LIVING = 406
INT_CHILDRENS_HEALTH = 407
INT_FITNESS = 408
INT_MENS_HEALTH = 411
INT_NUTRITION = 412
INT_SENIOR_HEALTH = 413
INT_WEIGHT_LOSS = 414
INT_WELLNESS = 415
INT_WOMENS_HEALTH = 421
INT_HOBBIES = 422
INT_ARTS_CRAFTS = 424
INT_CONTENT_PRODUCTION = 440
INT_GAMES_PUZZLES = 445
INT_MUSICAL_INSTRUMENTS = 452
INT_HOME_GARDEN = 457
INT_GARDENING = 458
INT_HOME_ENTERTAINING = 459
INT_HOME_IMPROVEMENT = 460
INT_INTERIOR_DECOR = 461
INT_LANDSCAPING = 462
INT_OUTDOOR_DECOR = 463
INT_REMODELING = 464
INT_SMART_HOME = 465
INT_MOVIES = 467
INT_COMEDY_MOVIES = 470
INT_DOCUMENTARY = 472
INT_FAMILY_MOVIES = 474
INT_MUSIC = 481
INT_NEWS_POLITICS = 522
INT_PERSONAL_FINANCE = 534
INT_FRUGAL = 535
INT_INSURANCE = 536
INT_DEBT = 537
INT_INVESTING = 538
INT_TAXES = 539
INT_RETIREMENT = 540
INT_PETS = 541
INT_BIRDS = 542
INT_CATS = 543
INT_DOGS = 544
INT_FISH = 545
INT_HORSES = 546
INT_REPTILES = 549
INT_PHARMA_CONDITIONS = 550
INT_POP_CULTURE = 581
INT_HUMOR = 582
INT_REAL_ESTATE = 583
INT_REAL_ESTATE_BUYING = 591
INT_SHOPPING = 606
INT_SPORTS = 607
INT_AMERICAN_FOOTBALL = 608
INT_BASEBALL = 613
INT_BASKETBALL = 614
INT_BODYBUILDING = 616
INT_BOXING = 618
INT_CYCLING = 625
INT_EXTREME_SPORTS = 631
INT_FANTASY_SPORTS = 640
INT_FISHING_SPORTS = 643
INT_GOLF = 644
INT_HUNTING = 646
INT_MARTIAL_ARTS = 650
INT_OLYMPIC = 651
INT_POKER = 654
INT_SKIING = 661
INT_SOCCER = 663
INT_SPORTS_EQUIPMENT = 665
INT_TENNIS = 669
INT_TRACK = 670
INT_WALKING = 672
INT_WEIGHTLIFTING = 674
INT_WRESTLING = 675
INT_STYLE_FASHION = 676
INT_BEAUTY = 677
INT_BODY_ART = 678
INT_CHILDRENS_CLOTHING = 679
INT_DESIGNER_CLOTHING = 680
INT_FASHION_TRENDS = 681
INT_HIGH_FASHION = 682
INT_MENS_FASHION = 683
INT_PERSONAL_CARE = 684
INT_STREET_STYLE = 685
INT_WOMENS_FASHION = 686
INT_TECH = 687
INT_AI = 688
INT_AR = 689
INT_COMPUTING = 690
INT_CONSUMER_ELECTRONICS = 703
INT_VR = 705
INT_TV = 706
INT_COMEDY_TV = 709
INT_REALITY_TV = 714
INT_SPORTS_TV = 718
INT_TRAVEL = 719
INT_ADVENTURE_TRAVEL = 720
INT_BEACH_TRAVEL = 724
INT_CAMPING = 725
INT_FAMILY_TRAVEL = 728
INT_ROAD_TRIPS = 731
INT_GAMING = 733
INT_CONSOLE_GAMES = 734
INT_ESPORTS = 735
INT_MOBILE_GAMES = 736
INT_PC_GAMES = 737
INT_GAME_GENRES = 738

# Purchase Intent (root 752)
PI_APPS = 753
PI_BOOK_APPS = 755
PI_BUSINESS_APPS = 756
PI_EDU_APPS = 757
PI_ENTERTAINMENT_APPS = 758
PI_FINANCE_APPS = 759
PI_FOOD_APPS = 760
PI_GAME_APPS = 761
PI_HEALTH_FITNESS_APPS = 762
PI_LIFESTYLE_APPS = 763
PI_MAGAZINE_APPS = 764
PI_MEDICAL_APPS = 765
PI_MUSIC_APPS = 766
PI_NAV_APPS = 767
PI_NEWS_APPS = 768
PI_PHOTO_VIDEO_APPS = 769
PI_PRODUCTIVITY_APPS = 770
PI_REFERENCE_APPS = 771
PI_SHOPPING_APPS = 773
PI_SOCIAL_APPS = 774
PI_SPORTS_APPS = 775
PI_TRAVEL_APPS = 776
PI_ARTS_ENT = 779
PI_BLOGS_SOCIAL = 780
PI_CULTURE_ARTS = 781
PI_EXPERIENCES = 782
PI_FANTASY_SPORTS = 799
PI_MUSIC_VIDEO_STREAMING = 800
PI_ONLINE_ENT = 801
PI_RADIO_PODCASTS = 802
PI_TICKETS = 803
PI_TV_PI = 804
PI_AUTO_OWNERSHIP = 805
PI_NEW_VEHICLES = 806
PI_PREOWNED = 829
PI_AUTO_PRODUCTS = 852
PI_AUTO_CARE = 853
PI_AUTO_PARTS = 854
PI_AUTO_SERVICES = 861
PI_AUTO_RENTAL = 862
PI_AUTO_REPAIR = 863
PI_BEAUTY_SERVICES = 865
PI_BEAUTY_SALONS = 866
PI_HAIR_SALONS = 867
PI_NAIL_SALONS = 868
PI_PIERCING = 869
PI_SPAS = 870
PI_BUSINESS_INDUSTRIAL = 871
PI_ADVERTISING = 872
PI_CONFERENCES = 874
PI_HR = 882
PI_TELECOM = 911
PI_CLOTHING_ACCESSORIES = 919
PI_CLOTHING = 920
PI_CLOTHING_ACC = 928
PI_COSTUMES = 929
PI_FOOTWEAR = 930
PI_BAGS_WALLETS = 932
PI_JEWELRY_WATCHES = 933
PI_SUNGLASSES = 934
PI_COLLECTABLES = 935
PI_SPORTS_CARDS = 940
PI_CONSUMER_ELECTRONICS = 942
PI_AUDIO = 944
PI_CAMERAS = 947
PI_COMPUTERS = 953
PI_E_READERS = 956
PI_MOBILE_PLANS = 960
PI_MOBILE_PHONES = 961
PI_TABLETS = 965
PI_TVS = 966
PI_GAME_CONSOLE_ACC = 970
PI_GAMES_CONSOLES = 971
PI_CPG = 972
PI_EDIBLE = 973
PI_NON_EDIBLE = 1179
PI_EDU_CAREERS = 1368
PI_ADULT_ED = 1369
PI_CAREER_IMPROVEMENT = 1370
PI_COLLEGES = 1371
PI_EMPLOYMENT_AGENCIES = 1372
PI_LANGUAGE_LEARNING = 1373
PI_ONLINE_EDUCATION = 1374
PI_FAMILY_PARENTING = 1377
PI_CHILDCARE = 1378
PI_GENEALOGY = 1381
PI_KIDS_ACTIVITIES = 1382
PI_FINANCE_INSURANCE = 1383
PI_ACCOUNTANTS = 1384
PI_BANKING = 1385
PI_BOOKKEEPERS = 1386
PI_CREDIT_REPAIR = 1387
PI_CREDIT_CARDS = 1388
PI_INSURANCE_PI = 1389
PI_MORTGAGE = 1394
PI_PAYDAY_LOANS = 1395
PI_RETIREMENT_PI = 1396
PI_STOCKS_INVESTMENTS = 1397
PI_TAX_PREP = 1399
PI_FOOD_BEV_SERVICES = 1400
PI_BAKERIES = 1401
PI_BARS = 1402
PI_CATERING = 1403
PI_FAST_FOOD = 1404
PI_FOOD_DELIVERY = 1405
PI_RESTAURANTS = 1406
PI_FURNITURE = 1407
PI_BABY_FURNITURE = 1408
PI_BBQ_GRILLS = 1409
PI_BEDS = 1410
PI_OUTDOOR_FURNITURE = 1416
PI_GIFTS = 1420
PI_FLOWERS = 1421
PI_GIFT_CARDS = 1423
PI_GREETING_CARDS = 1425
PI_PARTY_GOODS = 1427
PI_HARDWARE = 1428
PI_BUILDING_MATERIALS = 1430
PI_TOOLS = 1446
PI_HEALTH_MEDICAL = 1448
PI_ALT_MEDICINE = 1449
PI_CHIROPRACTORS = 1451
PI_COSMETIC_MEDICAL = 1453
PI_DENTAL = 1454
PI_DRUGSTORES = 1455
PI_ELDER_CARE = 1456
PI_HAIR_LOSS = 1458
PI_HEALTHCARE = 1459
PI_HEALTH_SERVICES_PI = 1460
PI_HOSPITALS = 1461
PI_MASSAGE = 1462
PI_PHYSICAL_THERAPY = 1465
PI_SKIN_CARE = 1466
PI_SMOKING_CESSATION = 1467
PI_VACCINES = 1469
PI_VISION_CARE = 1470
PI_HOBBIES_PI = 1471
PI_ARTS_CRAFTS_PI = 1472
PI_MUSICAL_INSTRUMENTS_PI = 1473
PI_PSYCHICS_ASTROLOGY = 1474
PI_WORKSHOPS = 1475
PI_HOME_GARDEN_SERVICES = 1476
PI_APPLIANCE_REPAIR = 1477
PI_HOME_SECURITY = 1478
PI_HOME_IMPROVEMENT_PI = 1483
PI_HOUSEKEEPING = 1484
PI_LANDSCAPING_PI = 1485
PI_LAWN_GARDEN = 1486
PI_PEST = 1487
PI_PLUMBERS = 1488
PI_LEGAL = 1493
PI_ATTORNEYS = 1494
PI_LIFE_EVENTS = 1496
PI_ANNIVERSARY = 1497
PI_BABY_SHOWERS = 1498
PI_BACHELOR_BACHELORETTE = 1499
PI_BIRTHDAYS = 1500
PI_BIRTHS = 1501
PI_FUNERAL = 1502
PI_GRADUATIONS = 1503
PI_WEDDING = 1505
PI_LOGISTICS = 1506
PI_SHIPPING = 1507
PI_STORAGE = 1508
PI_NON_PROFITS = 1538
PI_CHARITIES = 1539
PI_CIVIC = 1540
PI_MILITARY_ORGS = 1542
PI_NGOS = 1543
PI_OFFICE_EQUIP = 1546
PI_PET_SERVICES = 1549
PI_PET_BREEDERS = 1550
PI_PET_GROOMING = 1551
PI_PET_SITTING = 1552
PI_PET_STORES = 1553
PI_VET_SERVICES = 1554
PI_PHARMA_PI = 1555
PI_REAL_ESTATE_PI = 1585
PI_COMMERCIAL_RE = 1586
PI_RE_RENTALS = 1587
PI_RE_SALES = 1588
PI_RESIDENTIAL_RE = 1590
PI_REC_FITNESS = 1591
PI_DANCE_STUDIOS = 1592
PI_GYMS = 1593
PI_PERSONAL_TRAINERS = 1595
PI_SELF_DEFENSE = 1596
PI_YOGA_STUDIOS = 1598
PI_SOFTWARE = 1599
PI_COMPUTER_SOFTWARE = 1600
PI_DIGITAL_GOODS = 1617
PI_SPORTING_GOODS = 1618
PI_ATHLETICS_EQUIP = 1619
PI_EXERCISE_EQUIP = 1633
PI_INDOOR_GAMES_EQUIP = 1634
PI_OUTDOOR_REC_EQUIP = 1635
PI_TRAVEL_TOURISM = 1649
PI_ADVENTURE_TRAVEL_PI = 1650
PI_AIR_TRAVEL = 1651
PI_AUTO_RENTAL_PI = 1652
PI_BEACH_TRAVEL_PI = 1653
PI_BNB = 1654
PI_BUDGET_TRAVEL = 1655
PI_BUSINESS_TRAVEL = 1656
PI_CAMPING_PI = 1659
PI_CRUISE = 1661
PI_DAY_TRIPS = 1662
PI_FAMILY_TRAVEL_PI = 1663
PI_HOTELS = 1666
PI_PASSENGER_TRANSPORT = 1668
PI_RAIL = 1669
PI_ROAD_TRIPS_PI = 1670
PI_SIGHTSEEING = 1671
PI_TRAVEL_AGENTS = 1674
PI_TRAVEL_INSURANCE = 1675
PI_WEB_SERVICES = 1676
PI_ISPS = 1678
PI_WEB_HOSTING = 1679


def adult_ages(start='18-20', end='65-69'):
    keys = list(AGE.keys())
    return [AGE[k] for k in keys[keys.index(start):keys.index(end)+1]]


# ---------------------------------------------------------------------------
# niche_id -> { evidence, primary[], secondary[], tertiary[] }
# Quality-floored. Edge present only if there is a citable source OR a
# non-generic logical reason that distinguishes this industry from "any".
# Empty tiers omitted from output. Evidence at group level; per-edge overrides
# allowed in `overrides[]` if a specific edge needs its own source.
# ---------------------------------------------------------------------------
N2I = {}

def n2i(nid, evidence, primary=None, secondary=None, tertiary=None, overrides=None):
    assert nid in niches, f"unknown niche {nid}"
    for tier_list in (primary, secondary, tertiary):
        for x in (tier_list or []):
            assert x in industries, f"{nid}: unknown industry {x}"
    for o in (overrides or []):
        assert o['industry_id'] in industries
    N2I[nid] = {
        'niche_id': nid,
        'evidence': evidence,
        **({'primary': primary} if primary else {}),
        **({'secondary': secondary} if secondary else {}),
        **({'tertiary': tertiary} if tertiary else {}),
        **({'overrides': overrides} if overrides else {}),
    }

# --- Beauty ---
n2i('beauty', 'IAB Purchase Intent: Beauty Services + Cosmetic Medical; Style & Fashion > Beauty Interest. Largest single influencer-spend category per IMH 2024.',
    primary=['cosmetics','skincare-brands','haircare-brands','fragrance-brands','specialty-retail'],
    secondary=['beauty-personal-care','oral-care','personal-hygiene','femtech','jewellery'],
    tertiary=['d2c-subscription','supplements-brands','dental-services','vision-care','telehealth'])
n2i('makeup', 'Direct match to IAB Style & Fashion > Beauty. Cosmetics brands dominate influencer spend per HypeAuditor 2024 beauty report.',
    primary=['cosmetics','specialty-retail'], secondary=['skincare-brands','beauty-personal-care'])
n2i('skincare', 'Skincare brands are the fastest-growing beauty sub-segment per IMH 2024.',
    primary=['skincare-brands','cosmetics'], secondary=['specialty-retail','supplements-brands','femtech','dental-services','telehealth'])
n2i('haircare', 'IAB Purchase Intent: Hair Salons + Hair Loss Treatments map cleanly.',
    primary=['haircare-brands','specialty-retail'], secondary=['cosmetics','mens-grooming','beauty-personal-care'])
n2i('nails', 'Nail brands and salon services per IAB Beauty Services > Nail Salons.',
    primary=['cosmetics','specialty-retail'], secondary=['beauty-personal-care','jewellery'])
n2i('fragrance', 'Fragrance is a luxury-adjacent vertical with heavy influencer launch use (Dior, Tom Ford case studies).',
    primary=['fragrance-brands','luxury-goods'], secondary=['cosmetics','specialty-retail','beauty-personal-care'])

# --- Fashion ---
n2i('fashion', 'IAB Style & Fashion + Clothing and Accessories. Fashion is the #2 influencer-spend category after beauty per IMH 2024.',
    primary=['womenswear','menswear-brands','footwear','fast-fashion','jewellery','watches','eyewear','bags-luggage','specialty-retail','marketplaces-ecom'],
    secondary=['luxury-goods','activewear','intimates','swimwear','department-stores','d2c-subscription','eyewear'][:6],
    tertiary=['fragrance-brands','cosmetics','watches','home-decor-brands','luggage-travel-gear'])
n2i('streetwear', 'Streetwear collabs are a documented case-study category (Nike SB, Supreme, Off-White creator partnerships).',
    primary=['footwear','sportswear','fashion-apparel','specialty-retail'], secondary=['luxury-goods','marketplaces-ecom','gaming-hardware','audio-equipment'])
n2i('luxury-fashion', 'High-net-worth audience; luxury maisons run creator programs (Vogue Business 2024).',
    primary=['luxury-goods','jewellery','watches','fragrance-brands'], secondary=['hotels','cruises','airlines','financial-services','cosmetics'])
n2i('sustainable-fashion', 'Sustainability-aligned brands explicitly target eco-conscious creators (Allbirds, Patagonia case studies).',
    primary=['fashion-apparel','footwear','outdoor-gear'], secondary=['plant-based-food','beauty-personal-care','d2c-subscription'])
n2i('modest-fashion', 'Modest-fashion creators command premium CPMs in MENA/SEA markets per HypeAuditor 2024 regional report.',
    primary=['womenswear','fashion-apparel','specialty-retail'], secondary=['cosmetics','jewellery','luxury-goods'])
n2i('plus-size-fashion', 'Body-inclusive brand sub-segment with dedicated influencer programs (Aerie #AerieREAL).',
    primary=['womenswear','intimates','fashion-apparel'], secondary=['swimwear','cosmetics','specialty-retail'])
n2i('sneakers', 'Sneaker culture has the densest creator-brand ecosystem outside beauty (Nike, Jordan, New Balance, Hoka campaigns).',
    primary=['footwear','sportswear','specialty-retail','marketplaces-ecom'], secondary=['activewear','watches','luxury-goods'])
n2i('accessories', 'Jewellery/watches/bags are a high-conversion influencer category per Tribe Dynamics EMV reports.',
    primary=['jewellery','watches','bags-luggage','eyewear'], secondary=['luxury-goods','fashion-apparel','specialty-retail'])
n2i('menswear', 'Menswear creators frequently work with grooming + watches alongside apparel (Hodinkee, MR PORTER programs).',
    primary=['menswear-brands','footwear','watches','mens-grooming','fragrance-brands'], secondary=['fashion-apparel','luxury-goods','eyewear','specialty-retail'])

# --- Fitness ---
n2i('fitness', 'IAB Interest: Healthy Living > Fitness; Purchase Intent: Recreation and Fitness + Sporting Goods. Athleisure and supplements are top categories per IMH 2024 wellness report.',
    primary=['activewear','sportswear','sports-nutrition','supplements-brands','fitness-equipment','gyms-studios','wearables'],
    secondary=['footwear','sports-outdoor','meal-kits','plant-based-food','soft-drinks','telehealth'],
    tertiary=['fashion-apparel','consumer-electronics-brands','health-pharma','mental-health-services'])
n2i('bodybuilding', 'IAB Sports > Bodybuilding. Supplement deals dominate per Athletic Greens / Bulk / MyProtein creator programs.',
    primary=['sports-nutrition','supplements-brands','activewear','fitness-equipment'], secondary=['gyms-studios','sportswear','wearables','mens-grooming'])
n2i('weightlifting', 'Powerlifting + strength niche is a long-tail commercial vertical (Rogue, Eleiko case studies).',
    primary=['sports-nutrition','fitness-equipment','activewear'], secondary=['supplements-brands','gyms-studios','sportswear','wearables'])
n2i('running', 'IAB Sports > Track and Field. Running shoe market drives heavy creator spend (Hoka, On, Brooks).',
    primary=['footwear','sportswear','activewear','wearables','sports-nutrition'], secondary=['fitness-equipment','soft-drinks','no-low-alcohol','travel-hospitality'])
n2i('yoga', 'IAB Purchase Intent: Yoga Studios. Athleisure and wellness adjacent.',
    primary=['activewear','gyms-studios','supplements-brands','sportswear'], secondary=['mental-health-services','plant-based-food','meal-kits','femtech','wearables'])
n2i('pilates', 'Premium boutique fitness audience; activewear and wellness brands dominate.',
    primary=['activewear','sportswear','gyms-studios'], secondary=['fitness-equipment','supplements-brands','wearables','femtech'])
n2i('crossfit', 'IAB Sports + CrossFit-specific brand ecosystem (Reebok, Nobull, Rogue).',
    primary=['sports-nutrition','fitness-equipment','activewear','sportswear'], secondary=['supplements-brands','gyms-studios','wearables','footwear'])
n2i('hiit', 'Functional fitness audience tracks closely with CrossFit/bodybuilding commercial pattern.',
    primary=['activewear','sports-nutrition','fitness-equipment'], secondary=['supplements-brands','gyms-studios','sportswear','wearables'])
n2i('calisthenics', 'Equipment-light niche; apps + apparel + supplements lead.',
    primary=['activewear','sports-nutrition','consumer-software'], secondary=['supplements-brands','sportswear','fitness-equipment','wearables'])
n2i('cycling', 'IAB Sports > Cycling. Bike, kit, and endurance-nutrition brands lead (Rapha, Castelli, Maurten).',
    primary=['bicycles','sports-outdoor','sports-nutrition','activewear'], secondary=['wearables','sportswear','no-low-alcohol','travel-hospitality'])

# --- Health & Wellness ---
n2i('health-wellness', 'IAB Healthy Living + Health and Medical Services. Wellness is a $1.8T market with rapid creator-led D2C growth (McKinsey 2024).',
    primary=['supplements-brands','mental-health-services','femtech','telehealth','plant-based-food'],
    secondary=['fitness-equipment','activewear','beauty-personal-care','meal-kits','wearables','dental-services'],
    tertiary=['skincare-brands','sports-nutrition','health-pharma','dental-services','vision-care'])
n2i('nutrition', 'IAB Healthy Living > Nutrition. Meal kits, supplements, RD-creators commercial pattern (HelloFresh, AG1).',
    primary=['supplements-brands','meal-kits','plant-based-food','sports-nutrition'], secondary=['femtech','telehealth','wearables','grocery','mental-health-services'])
n2i('supplements', 'Direct match.',
    primary=['supplements-brands','sports-nutrition'], secondary=['telehealth','femtech','plant-based-food','wearables'])
n2i('biohacking', 'Tech-forward wellness audience; wearables + sleep tech + supplements lead (Whoop, Eight Sleep case studies).',
    primary=['wearables','supplements-brands','bedding-bath','consumer-electronics-brands'],
    secondary=['femtech','sports-nutrition','telehealth','mental-health-services','smart-home'])
n2i('sleep', 'Mattress + sleep tech is a saturated influencer category (Casper, Eight Sleep, Hatch).',
    primary=['bedding-bath','wearables','supplements-brands'], secondary=['mental-health-services','consumer-electronics-brands','home-living','femtech'])
n2i('mental-health', 'IAB Pharmaceuticals + Healthy Living. Sensitive: requires creator opt-in; BetterHelp partnership backlash widely documented.',
    primary=['mental-health-services','telehealth','supplements-brands'],
    secondary=['femtech','mental-health-services','consumer-software','online-courses'],
    overrides=[{'industry_id':'mental-health-services','strength':'primary','evidence':{'source':'case-study','note':'BetterHelp creator program is one of the largest influencer spends in the category; also one of the most contested (FTC settlement 2023)'}}])
n2i('meditation', 'Mindfulness app category (Calm, Headspace) is a documented top-spend app vertical per Mediakix.',
    primary=['mental-health-services','consumer-software'], secondary=['supplements-brands','femtech','online-courses','wearables'])

# --- Food & Drink ---
n2i('food-drink', 'IAB Food & Drink Interest + Food and Beverage Services PI. CPG and QSR are top categories for creator spend.',
    primary=['food-beverage','restaurants-qsr','grocery','food-delivery','snacks','meal-kits','soft-drinks','coffee-tea','kitchenware'],
    secondary=['plant-based-food','dairy','condiments-sauces','alcohol-beer','alcohol-wine','alcohol-spirits','frozen-food','specialty-retail'],
    tertiary=['supplements-brands','home-appliances','no-low-alcohol'])
n2i('cooking', 'Home-cook creator vertical drives kitchenware + grocery + meal kits (Half Baked Harvest, Bon Appétit).',
    primary=['kitchenware','meal-kits','grocery','food-beverage','home-appliances'], secondary=['condiments-sauces','restaurants-qsr','specialty-retail','snacks','plant-based-food'])
n2i('baking', 'King Arthur, Le Creuset, KitchenAid case studies.',
    primary=['kitchenware','home-appliances','food-beverage'], secondary=['grocery','specialty-retail','condiments-sauces'])
n2i('restaurants', 'Restaurant + food-tour creators land OpenTable, Resy, hospitality group deals.',
    primary=['restaurants-qsr','food-delivery','hotels','tourism-boards','grocery'], secondary=['alcohol-wine','alcohol-spirits','specialty-retail','airlines','otas'])
n2i('vegan', 'Plant-based brand category aligns 1:1 (Oatly, Beyond Meat, Impossible).',
    primary=['plant-based-food','food-beverage','grocery'], secondary=['supplements-brands','meal-kits','restaurants-qsr','specialty-retail'])
n2i('keto', 'Keto product market is a documented D2C category (Perfect Keto, HighKey, Quest).',
    primary=['food-beverage','supplements-brands','sports-nutrition','grocery'], secondary=['meal-kits','plant-based-food','specialty-retail','weight-management'])
n2i('coffee', 'Coffee creators land equipment + bean + cafe deals (Breville, Trade, Blue Bottle).',
    primary=['coffee-tea','kitchenware','home-appliances','restaurants-qsr'], secondary=['food-beverage','grocery','specialty-retail'])
n2i('cocktails', 'Mixology vertical drives spirits + glassware deals (Diageo Reserve, Liquor.com).',
    primary=['alcohol-spirits','alcohol-wine','no-low-alcohol','kitchenware'], secondary=['restaurants-qsr','food-beverage','specialty-retail','grocery'])
n2i('wine', 'Wine creators land winery + retailer deals (Vivino, Bright Cellars, direct winery).',
    primary=['alcohol-wine','restaurants-qsr','specialty-retail'], secondary=['kitchenware','grocery','tourism-boards','hotels'])

# --- Travel ---
n2i('travel', 'IAB Travel + Travel and Tourism. Tourism boards + airlines + hotels are dominant spenders per Skift 2024.',
    primary=['airlines','hotels','short-term-rentals','otas','tourism-boards','luggage-travel-gear'],
    secondary=['car-rental','cruises','consumer-electronics-brands','outdoor-gear','fashion-apparel','specialty-retail','telecom-utilities'],
    tertiary=['restaurants-qsr','cosmetics','wearables','financial-services','insurance'])
n2i('luxury-travel', 'High-end audience; luxury hotels + cruise + private aviation programs.',
    primary=['hotels','cruises','airlines','luxury-goods'], secondary=['luggage-travel-gear','financial-services','watches','jewellery','fragrance-brands'])
n2i('budget-travel', 'Hostelworld, Skyscanner, budget-airline programs are documented.',
    primary=['otas','airlines','short-term-rentals'], secondary=['luggage-travel-gear','hotels','consumer-software','telecom-utilities'])
n2i('solo-travel', 'Solo-travel-tour operators and safety-tech are growth categories per Skift.',
    primary=['hotels','short-term-rentals','otas','tourism-boards'], secondary=['airlines','luggage-travel-gear','consumer-electronics-brands','telecom-utilities','financial-services'])
n2i('family-travel', 'Family-travel creators command premium CPMs in 30-44 parent audience per HypeAuditor 2024.',
    primary=['hotels','cruises','tourism-boards','short-term-rentals','airlines'], secondary=['toys','luggage-travel-gear','car-rental','restaurants-qsr','specialty-retail'])
n2i('adventure-travel', 'Outdoor gear + adventure operators (REI, Patagonia, GoPro).',
    primary=['outdoor-gear','tourism-boards','airlines','consumer-electronics-brands'], secondary=['hotels','luggage-travel-gear','wearables','automotive-industry','insurance'])
n2i('digital-nomad', 'Remote-work tech + coworking + neobank programs (Wise, Revolut, SafetyWing).',
    primary=['fintech-neobanks','telecom-utilities','consumer-software','saas','short-term-rentals'], secondary=['airlines','insurance','luggage-travel-gear','cybersecurity','wearables'])

# --- Lifestyle (broad-audience: quality floor enforced) ---
n2i('lifestyle', 'Broad-audience niche. Edges restricted to documented top-spend categories with case-study evidence.',
    primary=['fashion-apparel','beauty-personal-care','home-living','food-delivery'],
    secondary=['hotels','restaurants-qsr','specialty-retail','d2c-subscription','consumer-electronics-brands','home-decor-brands'],
    tertiary=['fintech-neobanks','telecom-utilities','meal-kits','soft-drinks'])
n2i('productivity', 'SaaS + neobank + EdTech creator programs (Notion, Brilliant, Skillshare case studies).',
    primary=['saas','consumer-software','online-courses'], secondary=['fintech-neobanks','productivity-apps','wearables','coffee-tea'])
n2i('minimalism', 'Minimalist creators land smart-home + fewer-but-better D2C brands.',
    primary=['home-decor-brands','furniture','fashion-apparel'], secondary=['smart-home','kitchenware','d2c-subscription','specialty-retail'])
n2i('day-in-the-life', 'Broad-audience format. Edges limited to lifestyle CPG categories with documented spend.',
    primary=['food-delivery','beauty-personal-care','fashion-apparel'], secondary=['coffee-tea','home-living','d2c-subscription','soft-drinks'])

# --- Family & Parenting ---
n2i('family-parenting', 'IAB Family and Parenting PI + Life Events. Top-3 CPG niche per HypeAuditor 2024.',
    primary=['baby-food','diapers-nappies','baby-gear','toys','kids-edutainment','grocery'],
    secondary=['insurance','financial-services','auto-oems','home-improvement','home-appliances','snacks','vision-care'],
    tertiary=['restaurants-qsr','tourism-boards','hotels','meal-kits','dental-services'])
n2i('pregnancy', 'Pre-baby + maternity-wear + femtech (Bumpsuit, Hatch, Flo Health).',
    primary=['diapers-nappies','baby-gear','femtech','baby-food'], secondary=['skincare-brands','supplements-brands','insurance','telehealth','grocery'])
n2i('newborn-baby', 'Direct match.',
    primary=['diapers-nappies','baby-food','baby-gear','toys'], secondary=['skincare-brands','femtech','furniture','insurance','grocery'])
n2i('toddler', 'Toy + edutainment + family-meal sweet spot.',
    primary=['toys','kids-edutainment','baby-food','baby-gear'], secondary=['kidswear','grocery','snacks','insurance','tourism-boards'])
n2i('mom-life', 'Mom-creator vertical is the single largest parenting sub-niche by spend per HypeAuditor.',
    primary=['baby-food','diapers-nappies','baby-gear','toys','kids-edutainment','grocery','femtech'],
    secondary=['cosmetics','skincare-brands','fashion-apparel','meal-kits','snacks','insurance','home-appliances'])
n2i('dad-life', 'Dad-creator audience is 25-44 male homeowner-skewed; case studies cover BBQ, lawn, family auto, life insurance (Allstate, Toyota, Lowes case studies).',
    primary=['baby-gear','toys','baby-food','diapers-nappies','home-improvement','auto-oems','grocery'],
    secondary=['insurance','financial-services','sports-teams-leagues','restaurants-qsr','consumer-electronics-brands','snacks','soft-drinks','alcohol-beer'],
    tertiary=['gardening-brands','home-improvement','outdoor-gear','tyres'])

# --- Home & Interiors ---
n2i('home-interiors', 'IAB Home & Garden + Home and Garden Services PI. Big-ticket purchase audience; Wayfair, IKEA, RH case studies.',
    primary=['furniture','home-decor-brands','home-appliances','home-improvement','kitchenware','bedding-bath'],
    secondary=['cleaning-household','smart-home','gardening-brands','specialty-retail','d2c-subscription'],
    tertiary=['mortgages','residential-real-estate','insurance'])
n2i('interior-design', 'Direct match. RH, West Elm, Article case studies.',
    primary=['furniture','home-decor-brands','bedding-bath','kitchenware'], secondary=['home-appliances','smart-home','specialty-retail','d2c-subscription'])
n2i('home-renovation', 'Home Depot, Lowes, B&Q maker-creator programs.',
    primary=['home-improvement','furniture','home-appliances'], secondary=['kitchenware','bedding-bath','mortgages','home-decor-brands','home-improvement'])
n2i('gardening', 'Garden + tool + outdoor-furniture vertical (Burpee, Greenhouse Megastore, Stihl case studies).',
    primary=['gardening-brands','home-improvement','outdoor-gear'], secondary=['home-decor-brands','furniture','plant-based-food','pets-industry'])
n2i('organisation', 'Container Store + IKEA + Marie Kondo brand category.',
    primary=['home-decor-brands','furniture','specialty-retail'], secondary=['cleaning-household','home-appliances','kitchenware','d2c-subscription'])

# --- Tech ---
n2i('tech', 'IAB Tech & Computing + Consumer Electronics PI. Top influencer-spend category in male 25-44 demo per HypeAuditor 2024 tech report.',
    primary=['consumer-electronics-brands','mobile-devices','computing-hardware','audio-equipment','wearables','saas','ai-products'],
    secondary=['gaming-hardware','smart-home','cybersecurity','mobile-carriers','internet-providers','consumer-software'],
    tertiary=['ev-brands','streaming-services','financial-services','online-courses'])
n2i('consumer-electronics', 'Direct match.',
    primary=['consumer-electronics-brands','audio-equipment','mobile-devices','computing-hardware','wearables'], secondary=['smart-home','gaming-hardware','specialty-retail','marketplaces-ecom'])
n2i('ai', 'AI tools category (OpenAI, Anthropic, Midjourney, Perplexity creator programs).',
    primary=['ai-products','saas','consumer-software'], secondary=['online-courses','productivity-apps','cybersecurity','computing-hardware'])
n2i('software-reviews', 'SaaS + consumer-app reviews (Tom\'s Guide, Wirecutter style).',
    primary=['saas','consumer-software','productivity-apps'], secondary=['cybersecurity','ai-products','marketplaces-ecom','online-courses'])
n2i('pc-building', 'Hardware deep-dive niche (Linus Tech Tips ecosystem).',
    primary=['computing-hardware','gaming-hardware','consumer-electronics-brands'], secondary=['saas','cybersecurity','audio-equipment','specialty-retail'])
n2i('mobile-phones', 'Phone + accessory + carrier programs (Samsung, Apple, OnePlus).',
    primary=['mobile-devices','consumer-electronics-brands','mobile-carriers'], secondary=['audio-equipment','wearables','cybersecurity','telecom-utilities'])

# --- Gaming ---
n2i('gaming', 'IAB Video Gaming. Console, hardware, energy drinks, gaming chairs - documented vertical.',
    primary=['game-publishers','gaming-hardware','indie-games','mobile-games-publishers','creator-tools','consumer-electronics-brands'],
    secondary=['esports-orgs','audio-equipment','soft-drinks','snacks','streaming-services','cybersecurity','furniture'],
    tertiary=['mens-grooming','telecom-utilities','crypto-exchanges'])
n2i('pc-gaming', 'Hardware-heavy vertical (Nvidia, Razer, Logitech, Corsair).',
    primary=['gaming-hardware','computing-hardware','game-publishers'], secondary=['audio-equipment','creator-tools','soft-drinks','furniture','consumer-electronics-brands'])
n2i('console-gaming', 'Sony/MS/Nintendo + first-party publisher programs.',
    primary=['game-publishers','gaming-hardware','consumer-electronics-brands'], secondary=['streaming-services','audio-equipment','soft-drinks','snacks'])
n2i('mobile-gaming', 'Mobile publisher CPI campaigns are a huge category (Genshin, Royal Match).',
    primary=['mobile-games-publishers','game-publishers','consumer-electronics-brands'], secondary=['mobile-devices','soft-drinks','snacks','streaming-services'])
n2i('esports', 'Esports orgs + peripheral brands + energy drinks (Red Bull, G FUEL).',
    primary=['esports-orgs','gaming-hardware','game-publishers','soft-drinks'], secondary=['audio-equipment','sportswear','creator-tools','telecom-utilities','snacks'])
n2i('streaming', 'Twitch/YouTube/Kick streamer ecosystem.',
    primary=['creator-tools','gaming-hardware','audio-equipment','game-publishers'], secondary=['soft-drinks','snacks','streaming-services','consumer-software','mens-grooming'])

# --- Entertainment (broad-audience: quality floor enforced) ---
n2i('entertainment', 'Broad-audience niche. Limited to documented top-spend lifestyle CPG categories.',
    primary=['streaming-services','snacks','soft-drinks','food-delivery'],
    secondary=['dating-apps','restaurants-qsr','fashion-apparel','gambling','telecom-utilities'])
n2i('comedy', 'Comedy creators land soft drinks + dating apps + streaming + snacks (Pepsi, Tinder, Netflix case studies).',
    primary=['soft-drinks','snacks','dating-apps','streaming-services','food-delivery'],
    secondary=['restaurants-qsr','fashion-apparel','alcohol-beer','mobile-games-publishers','telecom-utilities'])
n2i('sketch-comedy', 'Same commercial pattern as comedy.',
    primary=['soft-drinks','snacks','streaming-services','dating-apps'], secondary=['restaurants-qsr','food-delivery','fashion-apparel','mobile-games-publishers'])
n2i('memes', 'Meme accounts skew younger; mobile games + dating + fashion are dominant (per Klear meme creator report).',
    primary=['mobile-games-publishers','dating-apps','fast-fashion'], secondary=['food-delivery','soft-drinks','snacks','streaming-services'])
n2i('reactions', 'Reaction creators land streaming + game-publisher previews + snack brands.',
    primary=['streaming-services','game-publishers','snacks'], secondary=['soft-drinks','mobile-games-publishers','food-delivery','dating-apps'])
n2i('storytime', 'Storytime creators (true crime adjacent) land subscription + snack + lifestyle (BetterHelp, Audible historically).',
    primary=['streaming-services','publishing','snacks'], secondary=['mental-health-services','dating-apps','d2c-subscription','food-delivery'])
n2i('asmr', 'ASMR-specific brand pattern: skincare, sleep, audio tech.',
    primary=['skincare-brands','bedding-bath','audio-equipment'], secondary=['mental-health-services','cosmetics','d2c-subscription','consumer-electronics-brands'])

# --- Music ---
n2i('music', 'IAB Music and Audio + Music DSP PI.',
    primary=['music-dsps','music-labels','live-events','ticketing','audio-equipment'],
    secondary=['fashion-apparel','soft-drinks','alcohol-spirits','ticketing','mobile-carriers'])
n2i('artist-musician', 'Artists land their own brand deals (sneakers, spirits, watches case studies).',
    primary=['music-labels','music-dsps','live-events','fashion-apparel','footwear'], secondary=['alcohol-spirits','luxury-goods','watches','soft-drinks','audio-equipment'])
n2i('dj-producer', 'DJ creator ecosystem (Pioneer DJ, Native Instruments, Splice).',
    primary=['audio-equipment','consumer-software','live-events'], secondary=['music-dsps','alcohol-spirits','soft-drinks','fashion-apparel'])
n2i('music-reviews', 'Audio gear + DSP + record label PR (Anthony Fantano model).',
    primary=['music-dsps','music-labels','audio-equipment'], secondary=['streaming-services','consumer-electronics-brands','live-events'])

# --- Art & Design ---
n2i('art-design', 'IAB Fine Art + Hobbies > Arts & Crafts.',
    primary=['specialty-retail','online-courses','consumer-software'], secondary=['ai-products','publishing','d2c-subscription','specialty-retail'])
n2i('illustration', 'Procreate, Wacom, Adobe creator programs.',
    primary=['consumer-software','ai-products','online-courses'], secondary=['publishing','specialty-retail','computing-hardware'])
n2i('graphic-design', 'Adobe, Figma, Canva creator programs.',
    primary=['saas','consumer-software','ai-products'], secondary=['online-courses','computing-hardware','publishing'])
n2i('digital-art', 'Same pattern as illustration.',
    primary=['consumer-software','ai-products','computing-hardware'], secondary=['online-courses','publishing','specialty-retail'])
n2i('painting', 'Traditional art supply brands + classes (Blick, Winsor & Newton).',
    primary=['specialty-retail','online-courses'], secondary=['publishing','consumer-software'])
n2i('photography', 'Camera + lens + editing software (Sony, Canon, Adobe).',
    primary=['consumer-electronics-brands','consumer-software','saas'], secondary=['online-courses','specialty-retail','ai-products','travel-hospitality'])

# --- Education ---
n2i('education', 'IAB Education and Careers PI. Online courses + EdTech + university programs.',
    primary=['online-courses','tutoring','language-learning-brands','k12','higher-ed'],
    secondary=['publishing','saas','consumer-software','ai-products'])
n2i('science', 'Science creators (Veritasium, Kurzgesagt) land brand programs from Brilliant, Henson, hardware brands.',
    primary=['online-courses','language-learning-brands','publishing'], secondary=['ai-products','consumer-electronics-brands','saas','computing-hardware'])
n2i('history', 'History creators land subscription edutainment (Curiosity Stream, Nebula) + book publishers.',
    primary=['streaming-services','publishing','online-courses'], secondary=['language-learning-brands','tourism-boards','specialty-retail'])
n2i('languages', 'Duolingo, Babbel, Pimsleur creator programs.',
    primary=['language-learning-brands','online-courses','tutoring'], secondary=['publishing','tourism-boards','saas','consumer-software'])
n2i('study-tips', 'EdTech + productivity SaaS (Notion, Quizlet, Anki).',
    primary=['online-courses','saas','consumer-software','tutoring'], secondary=['publishing','language-learning-brands','productivity-apps','higher-ed'])

# --- Business & Finance ---
n2i('business-finance', 'IAB Business and Finance + Personal Finance + Finance and Insurance PI.',
    primary=['retail-banking','fintech-neobanks','investing-platforms','credit-cards','insurance','online-courses','saas'],
    secondary=['accounting','crypto-exchanges','buy-now-pay-later','tax-services','consulting'],
    tertiary=['marketing-agencies','recruitment-hr-tech','professional-services'])
n2i('entrepreneurship', 'Founder-creator + SaaS + finance + course audience.',
    primary=['saas','online-courses','fintech-neobanks','consulting'], secondary=['marketing-agencies','recruitment-hr-tech','credit-cards','accounting','cybersecurity'])
n2i('personal-finance', 'FinTok + neobanks + budgeting apps.',
    primary=['fintech-neobanks','credit-cards','investing-platforms','buy-now-pay-later'], secondary=['retail-banking','insurance','tax-services','online-courses','consumer-software'])
n2i('investing', 'Brokerage + crypto exchange creator programs (sensitive: SEC/FCA scrutiny).',
    primary=['investing-platforms','fintech-neobanks','crypto-exchanges'],
    secondary=['retail-banking','credit-cards','insurance','online-courses','accounting'],
    overrides=[{'industry_id':'investing-platforms','strength':'primary','evidence':{'source':'case-study','note':'Robinhood/eToro creator programs are top spenders; SEC FY2023 enforcement actions documented'}}])
n2i('crypto-web3', 'Crypto exchanges + Web3 brands. Sensitive vertical with platform restrictions.',
    primary=['crypto-exchanges','fintech-neobanks'], secondary=['investing-platforms','cybersecurity','consumer-software','online-courses'])
n2i('career', 'Career creators land LinkedIn, Indeed, recruitment-platform deals.',
    primary=['recruitment-hr-tech','online-courses','professional-services'], secondary=['saas','language-learning-brands','consulting','consumer-software'])

# --- Sports ---
n2i('sports', 'IAB Sports + Sports Teams. Wide commercial coverage.',
    primary=['sportswear','sports-teams-leagues','sports-nutrition','sporting-equipment','soft-drinks','footwear'],
    secondary=['gambling','streaming-services','fitness-equipment','wearables','automotive-industry','alcohol-beer'],
    tertiary=['credit-cards','insurance','telecom-utilities','restaurants-qsr'])
n2i('football-soccer', 'World\'s largest sport audience. Boots, jerseys, sportsbook (sensitive).',
    primary=['sportswear','sports-teams-leagues','footwear','soft-drinks'], secondary=['gambling','streaming-services','alcohol-beer','sports-nutrition','fitness-equipment'])
n2i('american-football', 'NFL audience - QSR, beer, gambling, auto, insurance dominate ad spend.',
    primary=['sports-teams-leagues','sportswear','soft-drinks','alcohol-beer','restaurants-qsr','gambling'], secondary=['insurance','auto-oems','snacks','streaming-services','financial-services'])
n2i('basketball', 'Sneaker + apparel + sportsbook.',
    primary=['footwear','sportswear','sports-teams-leagues','gambling'], secondary=['soft-drinks','snacks','streaming-services','watches'])
n2i('tennis', 'Premium apparel + racquet + watches (Rolex, Wilson, Babolat).',
    primary=['sportswear','sporting-equipment','watches','footwear'], secondary=['luxury-goods','tourism-boards','wearables','alcohol-wine'])
n2i('golf', 'High-affluence audience; clubs, apparel, luxury, financial services.',
    primary=['sporting-equipment','sportswear','luxury-goods'], secondary=['watches','tourism-boards','automotive-industry','financial-services','alcohol-spirits','insurance'])
n2i('motorsport', 'F1 + NASCAR audience - watches, energy drinks, tech, auto, sportsbook.',
    primary=['watches','soft-drinks','automotive-industry','sports-teams-leagues','gambling'], secondary=['ev-brands','consumer-electronics-brands','luxury-goods','telecom-utilities','alcohol-spirits'])
n2i('combat-sports', 'UFC + boxing - energy drinks, supplements, betting, apparel.',
    primary=['sports-nutrition','supplements-brands','soft-drinks','gambling'], secondary=['sportswear','sports-teams-leagues','footwear','streaming-services','mens-grooming'])

# --- Outdoors ---
n2i('outdoors', 'IAB Travel > Adventure + Outdoor Recreation Equipment PI.',
    primary=['outdoor-gear','sports-outdoor','footwear','sportswear','automotive-industry'],
    secondary=['ev-brands','consumer-electronics-brands','tourism-boards','airlines','insurance','wearables'])
n2i('hiking', 'Direct match. Patagonia, REI, Hoka, Salomon.',
    primary=['outdoor-gear','footwear','sportswear','sports-nutrition'], secondary=['tourism-boards','wearables','consumer-electronics-brands','insurance'])
n2i('camping', 'IAB Camping. RV + tent + cooler brands (Yeti, Coleman, Thule).',
    primary=['outdoor-gear','automotive-industry','sports-outdoor'], secondary=['ev-brands','tourism-boards','food-beverage','consumer-electronics-brands','insurance'])
n2i('climbing', 'Specialty gear brands (Black Diamond, Petzl, La Sportiva).',
    primary=['outdoor-gear','footwear','sports-outdoor'], secondary=['sportswear','tourism-boards','wearables','sports-nutrition'])
n2i('surfing', 'Board + wetsuit + surf-travel brands.',
    primary=['outdoor-gear','swimwear','sportswear'], secondary=['tourism-boards','hotels','skincare-brands','soft-drinks'])
n2i('snowsports', 'Ski/snowboard + resort + apparel.',
    primary=['outdoor-gear','sportswear','tourism-boards'], secondary=['hotels','airlines','wearables','consumer-electronics-brands','automotive-industry'])
n2i('fishing', 'Fishing-tackle + boat + truck-brand category (Yeti, Shimano, Ford F-150).',
    primary=['outdoor-gear','sports-outdoor','automotive-industry'], secondary=['food-beverage','insurance','tourism-boards','alcohol-beer'])

# --- Automotive ---
n2i('automotive', 'IAB Automotive Interest + Automotive Ownership PI.',
    primary=['auto-oems','ev-brands','auto-aftermarket','tyres','motorcycle-brands','auto-dealers'],
    secondary=['insurance','financial-services','consumer-electronics-brands','car-rental','energy-utilities'],
    tertiary=['watches','outdoor-gear','luxury-goods'])
n2i('car-reviews', 'OEM + aftermarket creator programs (Doug DeMuro model).',
    primary=['auto-oems','ev-brands','auto-aftermarket','tyres'], secondary=['insurance','auto-dealers','consumer-electronics-brands','watches','wearables'])
n2i('ev', 'EV-specific creator ecosystem (Tesla, Rivian, Lucid, charging brands).',
    primary=['ev-brands','energy-utilities','consumer-electronics-brands'], secondary=['auto-oems','smart-home','insurance','tyres','wearables'])
n2i('motorcycles', 'Motorcycle + gear + insurance.',
    primary=['motorcycle-brands','auto-aftermarket','outdoor-gear'], secondary=['insurance','watches','consumer-electronics-brands','tourism-boards'])
n2i('classic-cars', 'Niche audience; insurance, restoration, watches, auction houses.',
    primary=['auto-oems','auto-aftermarket','watches'], secondary=['insurance','luxury-goods','home-improvement','specialty-retail'])
n2i('car-modding', 'Aftermarket parts + tools + automotive electronics.',
    primary=['auto-aftermarket','tyres','home-improvement'], secondary=['auto-oems','consumer-electronics-brands','insurance','energy-utilities'])

# --- Pets ---
n2i('pets', 'IAB Pets Interest + Pet Services PI.',
    primary=['pet-food','pet-supplies','vet-services','pet-tech','pet-insurance'], secondary=['specialty-retail','d2c-subscription','marketplaces-ecom','toys'])
n2i('dogs', 'Direct match. Largest pet creator sub-niche.',
    primary=['pet-food','pet-supplies','vet-services','pet-insurance','pet-tech'], secondary=['d2c-subscription','specialty-retail','marketplaces-ecom','outdoor-gear'])
n2i('cats', 'Direct match. Premium food + litter + tech (Litter-Robot).',
    primary=['pet-food','pet-supplies','pet-tech','vet-services'], secondary=['pet-insurance','specialty-retail','d2c-subscription','marketplaces-ecom'])
n2i('exotic-pets', 'Specialised supplies + vet + insurance.',
    primary=['pet-supplies','pet-food','vet-services'], secondary=['pet-insurance','specialty-retail','marketplaces-ecom'])

# --- Sustainability ---
n2i('sustainability', 'Eco-aligned brand category (Patagonia, Allbirds, Oatly, Tesla).',
    primary=['plant-based-food','outdoor-gear','ev-brands','fashion-apparel'],
    secondary=['energy-utilities','d2c-subscription','beauty-personal-care','meal-kits','home-living'])
n2i('zero-waste', 'D2C refill + reusable goods category.',
    primary=['d2c-subscription','beauty-personal-care','cleaning-household','plant-based-food'], secondary=['kitchenware','specialty-retail','fashion-apparel','home-living'])
n2i('ethical-living', 'Same commercial pattern as zero-waste + sustainable fashion.',
    primary=['plant-based-food','fashion-apparel','beauty-personal-care','d2c-subscription'], secondary=['outdoor-gear','home-living','meal-kits','specialty-retail'])

# --- Spirituality ---
n2i('spirituality', 'Wellness + app + jewellery (Insight Timer, Sanctuary).',
    primary=['mental-health-services','jewellery','specialty-retail'], secondary=['consumer-software','online-courses','femtech','publishing'])
n2i('astrology', 'App category (Co-Star, The Pattern) + jewellery + lifestyle.',
    primary=['consumer-software','jewellery','mental-health-services'], secondary=['publishing','specialty-retail','femtech'])
n2i('tarot', 'Same pattern as astrology.',
    primary=['consumer-software','jewellery'], secondary=['publishing','specialty-retail','mental-health-services'])

# --- News, Politics, Dance, etc. ---
n2i('news-politics', 'News creators land subscription media + financial + civic categories. Sensitive vertical.',
    primary=['publishing','streaming-services'], secondary=['financial-services','online-courses','consumer-software','political-advocacy'])
n2i('social-commentary', 'Long-form essay/comment creators land publisher + course + lifestyle deals.',
    primary=['publishing','online-courses','streaming-services'], secondary=['mental-health-services','d2c-subscription','consumer-software'])
n2i('dance', 'Dance creators land activewear + footwear + music DSPs.',
    primary=['activewear','footwear','music-dsps'], secondary=['sportswear','consumer-electronics-brands','live-events','cosmetics'])
n2i('film-tv', 'Film/TV criticism + appointment-viewing creators land streamer + ticketing + publisher deals.',
    primary=['streaming-services','ticketing','film-tv-studios','publishing'], secondary=['audio-equipment','specialty-retail','consumer-electronics-brands'])
n2i('books', 'BookTok/Bookstagram drives publisher sales + Audible + Kindle (NPD BookScan documented).',
    primary=['publishing','specialty-retail','streaming-services'], secondary=['online-courses','consumer-electronics-brands','d2c-subscription','coffee-tea'])
n2i('diy-crafts', 'Michaels, Joann, Cricut creator programs.',
    primary=['specialty-retail','home-improvement','d2c-subscription'], secondary=['consumer-software','home-decor-brands','kitchenware'])
n2i('wedding', 'IAB Life Events > Wedding. Big-ticket purchase audience.',
    primary=['jewellery','luxury-goods','hotels','tourism-boards'], secondary=['fashion-apparel','cosmetics','specialty-retail','financial-services','airlines','insurance'])
n2i('lgbtq', 'LGBTQ+ creators have dedicated brand programs (Pride campaigns, Heaps Normal, Bumble).',
    primary=['fashion-apparel','beauty-personal-care','dating-apps','alcohol-beer'], secondary=['cosmetics','streaming-services','mental-health-services','specialty-retail'])
n2i('body-positivity', 'Inclusive brand category (Aerie, Savage X Fenty, Dove).',
    primary=['intimates','beauty-personal-care','cosmetics','fashion-apparel'], secondary=['swimwear','femtech','mental-health-services','specialty-retail'])
n2i('disability-advocacy', 'Accessibility-aligned brand programs (Microsoft, Nike GO FlyEase, Tommy Adaptive).',
    primary=['fashion-apparel','footwear','consumer-electronics-brands'], secondary=['mental-health-services','telehealth','consumer-software','vision-care'])
n2i('veterans-military', 'Military-creator audience; insurance + auto + apparel (USAA, GovX case studies).',
    primary=['insurance','automotive-industry','fashion-apparel','sportswear'], secondary=['fitness-equipment','home-improvement','financial-services','outdoor-gear'])

# ---------------------------------------------------------------------------
# niche -> IAB segment IDs
# ---------------------------------------------------------------------------
N2A = {}

def n2a(nid, interest=None, demographic=None, evidence='', purchase_intent=None):
    assert nid in niches
    for i in (interest or []) + (purchase_intent or []) + (demographic or []):
        assert i in iab, f"{nid}: unknown IAB segment {i}"
    N2A[nid] = {
        'niche_id': nid,
        **({'interest_segments': interest} if interest else {}),
        **({'demographic_segments': demographic} if demographic else {}),
        **({'purchase_intent_segments': purchase_intent} if purchase_intent else {}),
        'evidence': evidence,
    }

# Beauty
n2a('beauty', interest=[INT_BEAUTY, INT_STYLE_FASHION, INT_PERSONAL_CARE],
    demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']],
    evidence='IAB Style & Fashion > Beauty; female-skewed 18-44 audience per HypeAuditor 2024 beauty.')
n2a('makeup', interest=[INT_BEAUTY, INT_FASHION_TRENDS, INT_PERSONAL_CARE], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Direct IAB match; younger skew.')
n2a('skincare', interest=[INT_BEAUTY, INT_PERSONAL_CARE, INT_HEALTHY_LIVING, INT_WELLNESS], demographic=[GENDER_F, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Wider age skew than makeup per HypeAuditor.')
n2a('haircare', interest=[INT_BEAUTY, INT_PERSONAL_CARE], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Beauty subset.')
n2a('nails', interest=[INT_BEAUTY, INT_PERSONAL_CARE, INT_BODY_ART], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Beauty + body-art proximity.')
n2a('fragrance', interest=[INT_BEAUTY, INT_HIGH_FASHION, INT_DESIGNER_CLOTHING], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Luxury-adjacent demo.')

# Fashion
n2a('fashion', interest=[INT_STYLE_FASHION, INT_FASHION_TRENDS, INT_WOMENS_FASHION, INT_MENS_FASHION, INT_SHOPPING], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB; broad gender.')
n2a('streetwear', interest=[INT_STYLE_FASHION, INT_STREET_STYLE, INT_FASHION_TRENDS], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Younger male skew per HypeAuditor street/sneaker reports.')
n2a('luxury-fashion', interest=[INT_HIGH_FASHION, INT_DESIGNER_CLOTHING, INT_FASHION_TRENDS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AFFLUENCE], evidence='High-net-worth audience.')
n2a('sustainable-fashion', interest=[INT_STYLE_FASHION, INT_FASHION_TRENDS, INT_HEALTHY_LIVING], demographic=[GENDER_F, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Eco-conscious female-skewed.')
n2a('modest-fashion', interest=[INT_STYLE_FASHION, INT_WOMENS_FASHION], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Modest creator audiences in MENA/SEA per HypeAuditor regional.')
n2a('plus-size-fashion', interest=[INT_STYLE_FASHION, INT_WOMENS_FASHION], demographic=[GENDER_F, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Inclusive sub-segment.')
n2a('sneakers', interest=[INT_STYLE_FASHION, INT_STREET_STYLE, INT_SPORTS], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Male-skewed; streetwear adjacent.')
n2a('accessories', interest=[INT_STYLE_FASHION, INT_HIGH_FASHION, INT_DESIGNER_CLOTHING], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Cross-gender; premium tilt.')
n2a('menswear', interest=[INT_MENS_FASHION, INT_STYLE_FASHION, INT_DESIGNER_CLOTHING], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB match.')

# Fitness
n2a('fitness', interest=[INT_HEALTHY_LIVING, INT_FITNESS, INT_WELLNESS, INT_NUTRITION, INT_SPORTS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB Healthy Living > Fitness; balanced gender.')
n2a('bodybuilding', interest=[INT_BODYBUILDING, INT_FITNESS, INT_WEIGHTLIFTING, INT_NUTRITION, INT_MENS_HEALTH], demographic=[GENDER_M, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB match; male skew.')
n2a('weightlifting', interest=[INT_WEIGHTLIFTING, INT_FITNESS, INT_BODYBUILDING, INT_NUTRITION], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
n2a('running', interest=[INT_TRACK, INT_FITNESS, INT_HEALTHY_LIVING, INT_WELLNESS], demographic=adult_ages('21-24','55-59'), evidence='Direct IAB Sports > Track & Field; wide age range.')
n2a('yoga', interest=[INT_FITNESS, INT_WELLNESS, INT_HEALTHY_LIVING, INT_WOMENS_HEALTH], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Female skew per HypeAuditor wellness.')
n2a('pilates', interest=[INT_FITNESS, INT_WELLNESS, INT_WOMENS_HEALTH], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Premium female audience.')
n2a('crossfit', interest=[INT_FITNESS, INT_BODYBUILDING, INT_NUTRITION, INT_WEIGHTLIFTING], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Functional fitness demo.')
n2a('hiit', interest=[INT_FITNESS, INT_HEALTHY_LIVING, INT_NUTRITION], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Time-poor working-adult demo.')
n2a('calisthenics', interest=[INT_FITNESS, INT_BODYBUILDING], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Young male skew.')
n2a('cycling', interest=[INT_CYCLING, INT_FITNESS, INT_HEALTHY_LIVING, INT_SPORTS], demographic=adult_ages('25-29','60-64'), evidence='Direct IAB Sports > Cycling; wide age, male-skewed.')

# Health & wellness
n2a('health-wellness', interest=[INT_HEALTHY_LIVING, INT_WELLNESS, INT_NUTRITION, INT_HEALTH_SERVICES], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
n2a('nutrition', interest=[INT_NUTRITION, INT_HEALTHY_LIVING, INT_HEALTHY_COOKING, INT_FOOD_MOVEMENTS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB Healthy Living > Nutrition.')
n2a('supplements', interest=[INT_NUTRITION, INT_HEALTHY_LIVING, INT_WELLNESS, INT_HEALTH_SERVICES], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Wellness + fitness overlap.')
n2a('biohacking', interest=[INT_HEALTHY_LIVING, INT_WELLNESS, INT_TECH, INT_NUTRITION], demographic=[GENDER_M, AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49'], AFFLUENCE], evidence='Affluent male skew per Whoop/Oura/Eight Sleep buyer profiles.')
n2a('sleep', interest=[INT_HEALTHY_LIVING, INT_WELLNESS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Wide adult age range.')
n2a('mental-health', interest=[INT_PHARMA_CONDITIONS, INT_HEALTHY_LIVING, INT_WELLNESS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger skew per Calm/Headspace 2024 user data.')
n2a('meditation', interest=[INT_WELLNESS, INT_HEALTHY_LIVING], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Wellness-adjacent.')

# Food & drink
n2a('food-drink', interest=[INT_FOOD_DRINK, INT_COOKING, INT_DINING_OUT, INT_WORLD_CUISINES], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
n2a('cooking', interest=[INT_COOKING, INT_FOOD_DRINK, INT_HEALTHY_COOKING, INT_WORLD_CUISINES], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
n2a('baking', interest=[INT_BAKING, INT_COOKING, INT_FOOD_DRINK], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Female skew per HypeAuditor food vertical.')
n2a('restaurants', interest=[INT_DINING_OUT, INT_FOOD_DRINK, INT_WORLD_CUISINES], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Dining-out segment.')
n2a('vegan', interest=[INT_VEGAN, INT_FOOD_MOVEMENTS, INT_HEALTHY_COOKING, INT_HEALTHY_LIVING], demographic=[GENDER_F, AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB; female-skewed.')
n2a('keto', interest=[INT_FOOD_MOVEMENTS, INT_HEALTHY_COOKING, INT_NUTRITION, INT_WEIGHT_LOSS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Adult diet demo.')
n2a('coffee', interest=[INT_NON_ALCOHOLIC, INT_FOOD_DRINK], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Daily-driver coffee buyer demo.')
n2a('cocktails', interest=[INT_ALCOHOL, INT_FOOD_DRINK], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Adult-only.')
n2a('wine', interest=[INT_ALCOHOL, INT_DINING_OUT], demographic=adult_ages('25-29','65-69'), evidence='Wide adult age range.')

# Travel
n2a('travel', interest=[INT_TRAVEL, INT_ADVENTURE_TRAVEL, INT_BEACH_TRAVEL, INT_FAMILY_TRAVEL], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB.')
n2a('luxury-travel', interest=[INT_TRAVEL, INT_HIGH_FASHION, INT_DESIGNER_CLOTHING], demographic=[AGE['35-39'], AGE['40-44'], AGE['45-49'], AGE['50-54'], AFFLUENCE], evidence='HNW audience.')
n2a('budget-travel', interest=[INT_TRAVEL, INT_ADVENTURE_TRAVEL, INT_FRUGAL], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger/backpacker demo.')
n2a('solo-travel', interest=[INT_TRAVEL, INT_ADVENTURE_TRAVEL], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], SINGLE], evidence='Solo audience.')
n2a('family-travel', interest=[INT_FAMILY_TRAVEL, INT_TRAVEL, INT_FAMILY], demographic=[AGE['30-34'], AGE['35-39'], AGE['40-44'], MARRIED, NUM_CHILDREN], evidence='Direct IAB Family Travel.')
n2a('adventure-travel', interest=[INT_ADVENTURE_TRAVEL, INT_TRAVEL, INT_EXTREME_SPORTS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB Adventure Travel.')
n2a('digital-nomad', interest=[INT_TRAVEL, INT_REMOTE_WORK, INT_CAREERS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB Remote Working + Travel overlap.')

# Lifestyle
n2a('lifestyle', interest=[INT_STYLE_FASHION, INT_FOOD_DRINK, INT_TRAVEL, INT_HOME_GARDEN], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Broad; limited to top adjacent interests.')
n2a('productivity', interest=[INT_CAREERS, INT_CAREER_ADVICE, INT_BUSINESS_FINANCE, INT_REMOTE_WORK], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Working-adult demo.')
n2a('minimalism', interest=[INT_HOME_GARDEN, INT_INTERIOR_DECOR, INT_FRUGAL], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Adult homebuilder demo.')
n2a('day-in-the-life', interest=[INT_STYLE_FASHION, INT_FOOD_DRINK, INT_HOME_GARDEN], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Younger vlog audience.')

# Family & parenting
n2a('family-parenting', interest=[INT_PARENTING, INT_FAMILY, INT_CHILDRENS_HEALTH, INT_FAMILY_TRAVEL], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], NUM_CHILDREN, MARRIED], evidence='Direct IAB Parenting.')
n2a('pregnancy', interest=[INT_PARENTING, INT_WOMENS_HEALTH, INT_HEALTHY_LIVING], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
n2a('newborn-baby', interest=[INT_PARENTING, INT_CHILDRENS_HEALTH, INT_FAMILY], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], NUM_CHILDREN], evidence='Direct IAB.')
n2a('toddler', interest=[INT_PARENTING, INT_CHILDRENS_HEALTH, INT_FAMILY], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], NUM_CHILDREN], evidence='Same as newborn.')
n2a('mom-life', interest=[INT_PARENTING, INT_FAMILY, INT_WOMENS_HEALTH, INT_HEALTHY_COOKING], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], NUM_CHILDREN, MARRIED], evidence='Direct IAB; female-skewed.')
n2a('dad-life', interest=[INT_PARENTING, INT_FAMILY, INT_MENS_HEALTH, INT_BBQ, INT_HOME_IMPROVEMENT], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], NUM_CHILDREN, MARRIED, OWNERSHIP], evidence='Direct IAB Parenting + BBQ + Home Improvement; homeowner skew.')

# Home & interiors
n2a('home-interiors', interest=[INT_HOME_GARDEN, INT_INTERIOR_DECOR, INT_HOME_IMPROVEMENT, INT_REMODELING], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], OWNERSHIP], evidence='Direct IAB.')
n2a('interior-design', interest=[INT_INTERIOR_DECOR, INT_HOME_GARDEN, INT_HOME_ENTERTAINING], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
n2a('home-renovation', interest=[INT_HOME_IMPROVEMENT, INT_REMODELING, INT_HOME_GARDEN], demographic=[AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49'], OWNERSHIP], evidence='Homeowner demo.')
n2a('gardening', interest=[INT_GARDENING, INT_HOME_GARDEN, INT_LANDSCAPING, INT_OUTDOOR_DECOR], demographic=[AGE['35-39'], AGE['40-44'], AGE['45-49'], AGE['50-54'], AGE['55-59'], OWNERSHIP], evidence='Older homeowner skew.')
n2a('organisation', interest=[INT_HOME_GARDEN, INT_INTERIOR_DECOR], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Female-skewed lifestyle.')

# Tech
n2a('tech', interest=[INT_TECH, INT_CONSUMER_ELECTRONICS, INT_COMPUTING, INT_AI], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB; male skew.')
n2a('consumer-electronics', interest=[INT_CONSUMER_ELECTRONICS, INT_TECH], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
n2a('ai', interest=[INT_AI, INT_TECH, INT_COMPUTING], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
n2a('software-reviews', interest=[INT_TECH, INT_COMPUTING], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Tech audience.')
n2a('pc-building', interest=[INT_COMPUTING, INT_CONSUMER_ELECTRONICS, INT_GAMING], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Male enthusiast skew.')
n2a('mobile-phones', interest=[INT_CONSUMER_ELECTRONICS, INT_TECH], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger upgrade-cycle demo.')

# Gaming
n2a('gaming', interest=[INT_GAMING, INT_CONSOLE_GAMES, INT_PC_GAMES, INT_MOBILE_GAMES, INT_ESPORTS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
n2a('pc-gaming', interest=[INT_PC_GAMES, INT_GAMING, INT_COMPUTING], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Direct IAB.')
n2a('console-gaming', interest=[INT_CONSOLE_GAMES, INT_GAMING], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
n2a('mobile-gaming', interest=[INT_MOBILE_GAMES, INT_GAMING], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Wider demo than console.')
n2a('esports', interest=[INT_ESPORTS, INT_GAMING, INT_PC_GAMES], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Direct IAB.')
n2a('streaming', interest=[INT_GAMING, INT_CONTENT_PRODUCTION], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Twitch/Kick demo.')

# Entertainment
n2a('entertainment', interest=[INT_POP_CULTURE, INT_TV, INT_MOVIES, INT_HUMOR], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
n2a('comedy', interest=[INT_HUMOR, INT_COMEDY_MOVIES, INT_COMEDY_TV], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Direct IAB.')
n2a('sketch-comedy', interest=[INT_HUMOR, INT_POP_CULTURE], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Same as comedy.')
n2a('memes', interest=[INT_HUMOR, INT_POP_CULTURE], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Youngest skew.')
n2a('reactions', interest=[INT_POP_CULTURE, INT_TV, INT_MOVIES, INT_GAMING], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Pop-culture overlap.')
n2a('storytime', interest=[INT_POP_CULTURE, INT_BOOKS], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Female-skewed per BookTok overlap.')
n2a('asmr', interest=[INT_HEALTHY_LIVING, INT_WELLNESS, INT_POP_CULTURE], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Sleep + wellness adjacency.')

# Music
n2a('music', interest=[INT_MUSIC, INT_POP_CULTURE], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
n2a('artist-musician', interest=[INT_MUSIC, INT_POP_CULTURE, INT_FASHION_TRENDS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Pop-culture overlap.')
n2a('dj-producer', interest=[INT_MUSIC, INT_TECH], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Producer demo.')
n2a('music-reviews', interest=[INT_MUSIC, INT_POP_CULTURE], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Music-fan demo.')

# Art & design
n2a('art-design', interest=[INT_FINE_ART, INT_DESIGN, INT_DIGITAL_ARTS, INT_ARTS_CRAFTS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB Fine Art.')
n2a('illustration', interest=[INT_DESIGN, INT_DIGITAL_ARTS, INT_FINE_ART], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Direct IAB.')
n2a('graphic-design', interest=[INT_DESIGN, INT_TECH, INT_DIGITAL_ARTS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Pro-creative demo.')
n2a('digital-art', interest=[INT_DIGITAL_ARTS, INT_DESIGN, INT_AI], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Direct IAB.')
n2a('painting', interest=[INT_FINE_ART, INT_ARTS_CRAFTS], demographic=adult_ages('25-29','65-69'), evidence='Wide adult demo.')
n2a('photography', interest=[INT_FINE_ART_PHOTO, INT_FINE_ART, INT_TRAVEL], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')

# Education
n2a('education', interest=[INT_EDUCATION, INT_ONLINE_EDU, INT_ACADEMIC], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
n2a('science', interest=[INT_ACADEMIC, INT_EDUCATION], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='STEM demo.')
n2a('history', interest=[INT_BOOKS, INT_EDUCATION, INT_DOCUMENTARY], demographic=adult_ages('25-29','65-69'), evidence='Older adult skew.')
n2a('languages', interest=[INT_LANGUAGE_LEARNING, INT_EDUCATION, INT_TRAVEL], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
n2a('study-tips', interest=[INT_EDUCATION, INT_ONLINE_EDU, INT_CAREERS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Student demo.')

# Business & finance
n2a('business-finance', interest=[INT_BUSINESS_FINANCE, INT_PERSONAL_FINANCE, INT_INVESTING], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AFFLUENCE], evidence='Direct IAB.')
n2a('entrepreneurship', interest=[INT_BUSINESS_FINANCE, INT_CAREERS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Founder demo.')
n2a('personal-finance', interest=[INT_PERSONAL_FINANCE, INT_FRUGAL, INT_INVESTING], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
n2a('investing', interest=[INT_INVESTING, INT_PERSONAL_FINANCE], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Male-skewed per Robinhood demos.')
n2a('crypto-web3', interest=[INT_INVESTING, INT_TECH], demographic=[GENDER_M, AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger male per Coinbase demos.')
n2a('career', interest=[INT_CAREERS, INT_CAREER_ADVICE, INT_REMOTE_WORK], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')

# Sports
n2a('sports', interest=[INT_SPORTS, INT_SPORTS_TV, INT_FANTASY_SPORTS], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB; male skew.')
n2a('football-soccer', interest=[INT_SOCCER, INT_SPORTS, INT_SPORTS_TV], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
n2a('american-football', interest=[INT_AMERICAN_FOOTBALL, INT_SPORTS, INT_SPORTS_TV, INT_FANTASY_SPORTS], demographic=adult_ages('21-24','55-59'), evidence='Direct IAB.')
n2a('basketball', interest=[INT_BASKETBALL, INT_SPORTS, INT_SPORTS_TV], demographic=adult_ages('18-20','45-49'), evidence='Direct IAB.')
n2a('tennis', interest=[INT_TENNIS, INT_SPORTS, INT_SPORTS_TV], demographic=adult_ages('25-29','65-69'), evidence='Affluent demo.')
n2a('golf', interest=[INT_GOLF, INT_SPORTS, INT_SPORTS_TV], demographic=[GENDER_M, AGE['35-39'], AGE['40-44'], AGE['45-49'], AGE['50-54'], AGE['55-59'], AGE['60-64'], AFFLUENCE], evidence='High-income male skew.')
n2a('motorsport', interest=[INT_AUTO_PERFORMANCE, INT_SPORTS, INT_SPORTS_TV], demographic=[GENDER_M, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Male auto-enthusiast demo.')
n2a('combat-sports', interest=[INT_BOXING, INT_MARTIAL_ARTS, INT_WRESTLING, INT_SPORTS_TV], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')

# Outdoors
n2a('outdoors', interest=[INT_ADVENTURE_TRAVEL, INT_CAMPING, INT_EXTREME_SPORTS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
n2a('hiking', interest=[INT_ADVENTURE_TRAVEL, INT_CAMPING, INT_WALKING], demographic=adult_ages('21-24','55-59'), evidence='Wide adult demo.')
n2a('camping', interest=[INT_CAMPING, INT_ADVENTURE_TRAVEL, INT_FAMILY_TRAVEL], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB.')
n2a('climbing', interest=[INT_EXTREME_SPORTS, INT_ADVENTURE_TRAVEL], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Young adventure demo.')
n2a('surfing', interest=[INT_EXTREME_SPORTS, INT_BEACH_TRAVEL], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Beach demo.')
n2a('snowsports', interest=[INT_SKIING, INT_EXTREME_SPORTS, INT_ADVENTURE_TRAVEL], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AFFLUENCE], evidence='Affluent winter demo.')
n2a('fishing', interest=[INT_FISHING_SPORTS, INT_SPORTS, INT_ADVENTURE_TRAVEL], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49'], AGE['50-54']], evidence='Direct IAB; male skew.')

# Automotive
n2a('automotive', interest=[INT_AUTO, INT_AUTO_BUYING, INT_AUTO_TECH, INT_AUTO_CULTURE], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB.')
n2a('car-reviews', interest=[INT_AUTO_BUYING, INT_AUTO, INT_AUTO_TECH], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Buying-intent demo.')
n2a('ev', interest=[INT_AUTO_GREEN, INT_AUTO_TECH, INT_AUTO, INT_TECH], demographic=[AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49'], AFFLUENCE], evidence='Direct IAB.')
n2a('motorcycles', interest=[INT_AUTO_MOTORCYCLES, INT_AUTO], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB.')
n2a('classic-cars', interest=[INT_AUTO_CLASSIC, INT_AUTO, INT_AUTO_CULTURE], demographic=[GENDER_M, AGE['40-44'], AGE['45-49'], AGE['50-54'], AGE['55-59'], AGE['60-64']], evidence='Older male demo.')
n2a('car-modding', interest=[INT_AUTO_PERFORMANCE, INT_AUTO_CULTURE, INT_AUTO_TECH], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Young male enthusiast.')

# Pets
n2a('pets', interest=[INT_PETS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
n2a('dogs', interest=[INT_DOGS, INT_PETS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
n2a('cats', interest=[INT_CATS, INT_PETS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
n2a('exotic-pets', interest=[INT_REPTILES, INT_PETS, INT_BIRDS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')

# Sustainability
n2a('sustainability', interest=[INT_FOOD_MOVEMENTS, INT_HEALTHY_LIVING, INT_AUTO_GREEN], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Eco-conscious demo.')
n2a('zero-waste', interest=[INT_HEALTHY_LIVING, INT_FOOD_MOVEMENTS], demographic=[GENDER_F, AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Female eco demo.')
n2a('ethical-living', interest=[INT_HEALTHY_LIVING, INT_FOOD_MOVEMENTS], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Conscious-consumer demo.')

# Spirituality
n2a('spirituality', interest=[INT_WELLNESS, INT_POP_CULTURE], demographic=[GENDER_F, AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Female-skewed wellness adjacency.')
n2a('astrology', interest=[INT_WELLNESS, INT_POP_CULTURE], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Younger female demo.')
n2a('tarot', interest=[INT_WELLNESS, INT_POP_CULTURE], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Same as astrology.')

# News, politics, etc.
n2a('news-politics', interest=[INT_NEWS_POLITICS], demographic=adult_ages('21-24','65-69'), evidence='Direct IAB; wide adult demo.')
n2a('social-commentary', interest=[INT_NEWS_POLITICS, INT_POP_CULTURE], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Adult commentary demo.')
n2a('dance', interest=[INT_DANCE, INT_FITNESS, INT_MUSIC], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Direct IAB.')
n2a('film-tv', interest=[INT_MOVIES, INT_TV, INT_POP_CULTURE], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
n2a('books', interest=[INT_BOOKS, INT_POP_CULTURE], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='BookTok female skew.')
n2a('diy-crafts', interest=[INT_ARTS_CRAFTS, INT_HOBBIES, INT_HOME_GARDEN], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB Arts & Crafts.')
n2a('wedding', interest=[INT_HIGH_FASHION, INT_DESIGNER_CLOTHING, INT_TRAVEL], demographic=[AGE['25-29'], AGE['30-34'], SINGLE], evidence='Pre-marital demo.')
n2a('lgbtq', interest=[INT_POP_CULTURE, INT_STYLE_FASHION], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], GENDER_OTHER], evidence='LGBTQ+ audience.')
n2a('body-positivity', interest=[INT_WELLNESS, INT_HEALTHY_LIVING, INT_STYLE_FASHION], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Female-skewed wellness.')
n2a('disability-advocacy', interest=[INT_HEALTHY_LIVING, INT_NEWS_POLITICS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Advocacy demo.')
n2a('veterans-military', interest=[INT_NEWS_POLITICS, INT_SPORTS], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Male-skewed adult.')


# ---------------------------------------------------------------------------
# industry -> IAB Purchase Intent + Demographic
# ---------------------------------------------------------------------------
I2A = {}

def i2a(iid, purchase_intent=None, demographic=None, evidence='', interest=None):
    assert iid in industries
    for x in (purchase_intent or []) + (demographic or []) + (interest or []):
        assert x in iab, f"{iid}: unknown IAB segment {x}"
    I2A[iid] = {
        'industry_id': iid,
        **({'purchase_intent_segments': purchase_intent} if purchase_intent else {}),
        **({'interest_segments': interest} if interest else {}),
        **({'demographic_segments': demographic} if demographic else {}),
        'evidence': evidence,
    }

# Beauty & personal care
i2a('beauty-personal-care', purchase_intent=[PI_BEAUTY_SERVICES, PI_COSMETIC_MEDICAL, PI_SKIN_CARE], demographic=[GENDER_F], evidence='Direct IAB Beauty Services.')
i2a('cosmetics', purchase_intent=[PI_BEAUTY_SERVICES, PI_BEAUTY_SALONS], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('skincare-brands', purchase_intent=[PI_SKIN_CARE, PI_COSMETIC_MEDICAL, PI_BEAUTY_SERVICES], demographic=[GENDER_F, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
i2a('haircare-brands', purchase_intent=[PI_HAIR_SALONS, PI_HAIR_LOSS, PI_BEAUTY_SERVICES], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('fragrance-brands', purchase_intent=[PI_BEAUTY_SERVICES, PI_BEAUTY_SALONS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Beauty Services umbrella.')
i2a('oral-care', purchase_intent=[PI_DENTAL, PI_DRUGSTORES], demographic=adult_ages('18-20','60-64'), evidence='Direct IAB Dental Care.')
i2a('mens-grooming', purchase_intent=[PI_BEAUTY_SERVICES, PI_HAIR_SALONS, PI_DRUGSTORES], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Beauty Services + male skew.')
i2a('personal-hygiene', purchase_intent=[PI_DRUGSTORES, PI_BEAUTY_SERVICES], demographic=adult_ages('18-20','55-59'), evidence='Daily-driver CPG.')

# Fashion & apparel
i2a('fashion-apparel', purchase_intent=[PI_CLOTHING, PI_CLOTHING_ACCESSORIES, PI_FOOTWEAR], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('womenswear', purchase_intent=[PI_CLOTHING, PI_CLOTHING_ACCESSORIES], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('menswear-brands', purchase_intent=[PI_CLOTHING, PI_CLOTHING_ACCESSORIES], demographic=[GENDER_M, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
i2a('kidswear', purchase_intent=[PI_CLOTHING, PI_KIDS_ACTIVITIES], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], NUM_CHILDREN], evidence='Parent buyer.')
i2a('footwear', purchase_intent=[PI_FOOTWEAR, PI_CLOTHING_ACCESSORIES], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('luxury-goods', purchase_intent=[PI_CLOTHING, PI_JEWELRY_WATCHES, PI_BAGS_WALLETS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AFFLUENCE], evidence='HNW demo.')
i2a('fast-fashion', purchase_intent=[PI_CLOTHING], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Young value-conscious female.')
i2a('jewellery', purchase_intent=[PI_JEWELRY_WATCHES, PI_BAGS_WALLETS], demographic=[GENDER_F, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
i2a('watches', purchase_intent=[PI_JEWELRY_WATCHES], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Male affluent demo.')
i2a('eyewear', purchase_intent=[PI_SUNGLASSES, PI_VISION_CARE], demographic=adult_ages('21-24','55-59'), evidence='Direct IAB.')
i2a('bags-luggage', purchase_intent=[PI_BAGS_WALLETS, PI_CLOTHING_ACCESSORIES], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
i2a('activewear', purchase_intent=[PI_CLOTHING, PI_FOOTWEAR, PI_EXERCISE_EQUIP], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Fitness + clothing overlap.')
i2a('intimates', purchase_intent=[PI_CLOTHING], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Female apparel.')
i2a('swimwear', purchase_intent=[PI_CLOTHING], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Seasonal apparel.')

# Sports & outdoor
i2a('sports-outdoor', purchase_intent=[PI_SPORTING_GOODS, PI_OUTDOOR_REC_EQUIP, PI_ATHLETICS_EQUIP], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('sportswear', purchase_intent=[PI_CLOTHING, PI_FOOTWEAR, PI_ATHLETICS_EQUIP], demographic=adult_ages('18-20','45-49'), evidence='Wide adult demo.')
i2a('sporting-equipment', purchase_intent=[PI_ATHLETICS_EQUIP, PI_SPORTING_GOODS], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('outdoor-gear', purchase_intent=[PI_OUTDOOR_REC_EQUIP, PI_SPORTING_GOODS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB.')
i2a('bicycles', purchase_intent=[PI_SPORTING_GOODS, PI_ATHLETICS_EQUIP, PI_OUTDOOR_REC_EQUIP], demographic=adult_ages('21-24','55-59'), evidence='Cycling buyer.')
i2a('fitness-equipment', purchase_intent=[PI_EXERCISE_EQUIP, PI_SPORTING_GOODS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
i2a('gyms-studios', purchase_intent=[PI_GYMS, PI_PERSONAL_TRAINERS, PI_YOGA_STUDIOS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
i2a('sports-teams-leagues', purchase_intent=[PI_TICKETS, PI_FANTASY_SPORTS, PI_SPORTS_CARDS], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Sports fan demo.')

# Food & beverage
i2a('food-beverage', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=adult_ages('18-20','65-69'), evidence='Direct IAB CPG.')
i2a('snacks', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=adult_ages('18-20','45-49'), evidence='CPG.')
i2a('frozen-food', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='CPG.')
i2a('dairy', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=adult_ages('21-24','55-59'), evidence='CPG.')
i2a('plant-based-food', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=[GENDER_F, AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger female skew.')
i2a('meal-kits', purchase_intent=[PI_CPG, PI_EDIBLE, PI_FOOD_DELIVERY], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Working-adult demo.')
i2a('ready-meals', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='CPG.')
i2a('condiments-sauces', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=adult_ages('21-24','55-59'), evidence='CPG.')
i2a('coffee-tea', purchase_intent=[PI_CPG, PI_EDIBLE, PI_BAKERIES], demographic=adult_ages('18-20','55-59'), evidence='Daily-driver CPG.')
i2a('soft-drinks', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='CPG.')
i2a('bottled-water', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=adult_ages('18-20','45-49'), evidence='CPG.')
i2a('alcohol-beer', purchase_intent=[PI_BARS, PI_CPG, PI_EDIBLE], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Adult-only.')
i2a('alcohol-wine', purchase_intent=[PI_BARS, PI_CPG, PI_EDIBLE], demographic=adult_ages('25-29','65-69'), evidence='Wide adult.')
i2a('alcohol-spirits', purchase_intent=[PI_BARS, PI_CPG], demographic=adult_ages('21-24','55-59'), evidence='Adult-only.')
i2a('no-low-alcohol', purchase_intent=[PI_CPG, PI_EDIBLE, PI_BARS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Mindful-drinking demo.')
i2a('restaurants-qsr', purchase_intent=[PI_FAST_FOOD, PI_RESTAURANTS, PI_FOOD_BEV_SERVICES], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('grocery', purchase_intent=[PI_CPG, PI_EDIBLE], demographic=adult_ages('21-24','65-69'), evidence='Grocery shopper.')
i2a('food-delivery', purchase_intent=[PI_FOOD_DELIVERY, PI_FOOD_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], URBANIZATION], evidence='Urban younger demo.')

# Health & pharma
i2a('health-pharma', purchase_intent=[PI_HEALTH_MEDICAL, PI_DRUGSTORES, PI_PHARMA_PI], demographic=adult_ages('21-24','65-69'), evidence='Direct IAB.')
i2a('supplements-brands', purchase_intent=[PI_HEALTH_MEDICAL, PI_DRUGSTORES, PI_ALT_MEDICINE], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
i2a('sports-nutrition', purchase_intent=[PI_HEALTH_MEDICAL, PI_EXERCISE_EQUIP, PI_DRUGSTORES], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Fitness audience.')
i2a('otc-medicine', purchase_intent=[PI_DRUGSTORES, PI_PHARMA_PI, PI_HEALTH_MEDICAL], demographic=adult_ages('25-29','65-69'), evidence='Adult buyer.')
i2a('prescription-pharma', purchase_intent=[PI_PHARMA_PI, PI_HEALTH_MEDICAL, PI_HEALTHCARE], demographic=adult_ages('30-34','65-69'), evidence='Adult patient demo.')
i2a('telehealth', purchase_intent=[PI_HEALTH_MEDICAL, PI_HEALTHCARE, PI_MEDICAL_APPS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Digital-native patient.')
i2a('mental-health-services', purchase_intent=[PI_HEALTH_MEDICAL, PI_HEALTHCARE, PI_MEDICAL_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger user per Calm/BetterHelp demos.')
i2a('weight-management', purchase_intent=[PI_HEALTH_MEDICAL, PI_DRUGSTORES, PI_HEALTHCARE], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Adult diet demo.')
i2a('sexual-wellness', purchase_intent=[PI_HEALTH_MEDICAL, PI_DRUGSTORES], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger adult demo.')
i2a('femtech', purchase_intent=[PI_HEALTH_MEDICAL, PI_MEDICAL_APPS, PI_HEALTHCARE], demographic=[GENDER_F, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Female health-tech.')
i2a('dental-services', purchase_intent=[PI_DENTAL, PI_HEALTH_MEDICAL], demographic=adult_ages('18-20','65-69'), evidence='Direct IAB.')
i2a('vision-care', purchase_intent=[PI_VISION_CARE, PI_HEALTH_MEDICAL], demographic=adult_ages('21-24','65-69'), evidence='Direct IAB.')

# Technology
i2a('technology', purchase_intent=[PI_CONSUMER_ELECTRONICS, PI_COMPUTERS, PI_SOFTWARE], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
i2a('consumer-electronics-brands', purchase_intent=[PI_CONSUMER_ELECTRONICS, PI_AUDIO, PI_TVS, PI_CAMERAS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('mobile-devices', purchase_intent=[PI_MOBILE_PHONES, PI_MOBILE_PLANS, PI_CONSUMER_ELECTRONICS], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('wearables', purchase_intent=[PI_CONSUMER_ELECTRONICS, PI_HEALTH_FITNESS_APPS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Tech + fitness overlap.')
i2a('audio-equipment', purchase_intent=[PI_AUDIO, PI_CONSUMER_ELECTRONICS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('computing-hardware', purchase_intent=[PI_COMPUTERS, PI_CONSUMER_ELECTRONICS], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Male enthusiast skew.')
i2a('saas', purchase_intent=[PI_COMPUTER_SOFTWARE, PI_BUSINESS_APPS, PI_PRODUCTIVITY_APPS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Working-adult demo.')
i2a('consumer-software', purchase_intent=[PI_COMPUTER_SOFTWARE, PI_LIFESTYLE_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('ai-products', purchase_intent=[PI_COMPUTER_SOFTWARE, PI_PRODUCTIVITY_APPS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Working-adult tech adopter.')
i2a('cybersecurity', purchase_intent=[PI_COMPUTER_SOFTWARE], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Working-adult security demo.')
i2a('smart-home', purchase_intent=[PI_CONSUMER_ELECTRONICS, PI_HOME_SECURITY], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], OWNERSHIP], evidence='Homeowner tech adopter.')

# Gaming industry
i2a('gaming-industry', purchase_intent=[PI_GAMES_CONSOLES, PI_GAME_CONSOLE_ACC, PI_GAME_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('game-publishers', purchase_intent=[PI_GAMES_CONSOLES, PI_GAME_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('indie-games', purchase_intent=[PI_GAMES_CONSOLES, PI_GAME_APPS, PI_DIGITAL_GOODS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Gamer demo.')
i2a('mobile-games-publishers', purchase_intent=[PI_GAME_APPS, PI_DIGITAL_GOODS], demographic=adult_ages('18-20','45-49'), evidence='Wider casual demo.')
i2a('gaming-hardware', purchase_intent=[PI_GAME_CONSOLE_ACC, PI_GAMES_CONSOLES, PI_CONSUMER_ELECTRONICS, PI_COMPUTERS], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Male enthusiast.')
i2a('esports-orgs', purchase_intent=[PI_GAMES_CONSOLES, PI_TICKETS], demographic=[GENDER_M, AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Young male.')
i2a('creator-tools', purchase_intent=[PI_COMPUTER_SOFTWARE, PI_AUDIO, PI_GAME_CONSOLE_ACC], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Streamer/creator demo.')

# Media & entertainment
i2a('media-entertainment', purchase_intent=[PI_TV_PI, PI_MUSIC_VIDEO_STREAMING, PI_TICKETS], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('streaming-services', purchase_intent=[PI_MUSIC_VIDEO_STREAMING, PI_ENTERTAINMENT_APPS, PI_TV_PI], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('film-tv-studios', purchase_intent=[PI_TV_PI, PI_TICKETS, PI_MUSIC_VIDEO_STREAMING], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('music-labels', purchase_intent=[PI_MUSIC_VIDEO_STREAMING, PI_TICKETS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Music fan.')
i2a('music-dsps', purchase_intent=[PI_MUSIC_VIDEO_STREAMING, PI_MUSIC_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('podcasts-networks', purchase_intent=[PI_RADIO_PODCASTS, PI_MUSIC_VIDEO_STREAMING], demographic=adult_ages('21-24','55-59'), evidence='Direct IAB.')
i2a('publishing', purchase_intent=[PI_BOOK_APPS, PI_ONLINE_ENT], demographic=adult_ages('18-20','65-69'), evidence='Reader demo.')
i2a('live-events', purchase_intent=[PI_TICKETS, PI_EXPERIENCES], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
i2a('ticketing', purchase_intent=[PI_TICKETS, PI_EXPERIENCES], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')

# Travel & hospitality
i2a('travel-hospitality', purchase_intent=[PI_TRAVEL_TOURISM, PI_HOTELS, PI_AIR_TRAVEL], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB.')
i2a('airlines', purchase_intent=[PI_AIR_TRAVEL, PI_TRAVEL_TOURISM, PI_TRAVEL_AGENTS], demographic=adult_ages('21-24','65-69'), evidence='Direct IAB.')
i2a('hotels', purchase_intent=[PI_HOTELS, PI_TRAVEL_TOURISM], demographic=adult_ages('25-29','65-69'), evidence='Direct IAB.')
i2a('short-term-rentals', purchase_intent=[PI_HOTELS, PI_BNB, PI_TRAVEL_AGENTS, PI_TRAVEL_APPS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Younger family demo.')
i2a('otas', purchase_intent=[PI_TRAVEL_AGENTS, PI_TRAVEL_APPS, PI_AIR_TRAVEL, PI_HOTELS], demographic=adult_ages('21-24','55-59'), evidence='Direct IAB.')
i2a('cruises', purchase_intent=[PI_CRUISE, PI_TRAVEL_TOURISM], demographic=[AGE['45-49'], AGE['50-54'], AGE['55-59'], AGE['60-64'], AGE['65-69']], evidence='Older affluent demo.')
i2a('tourism-boards', purchase_intent=[PI_TRAVEL_TOURISM, PI_SIGHTSEEING], demographic=adult_ages('25-29','65-69'), evidence='Direct IAB.')
i2a('luggage-travel-gear', purchase_intent=[PI_BAGS_WALLETS, PI_TRAVEL_TOURISM], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Travel buyer.')
i2a('car-rental', purchase_intent=[PI_AUTO_RENTAL_PI, PI_TRAVEL_TOURISM], demographic=adult_ages('21-24','55-59'), evidence='Direct IAB.')

# Automotive industry
i2a('automotive-industry', purchase_intent=[PI_AUTO_OWNERSHIP, PI_NEW_VEHICLES, PI_AUTO_SERVICES], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB.')
i2a('auto-oems', purchase_intent=[PI_NEW_VEHICLES, PI_AUTO_OWNERSHIP], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB.')
i2a('ev-brands', purchase_intent=[PI_NEW_VEHICLES, PI_AUTO_OWNERSHIP], demographic=[AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49'], AFFLUENCE], evidence='Affluent EV buyer.')
i2a('auto-aftermarket', purchase_intent=[PI_AUTO_PARTS, PI_AUTO_PRODUCTS], demographic=[GENDER_M, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
i2a('motorcycle-brands', purchase_intent=[PI_AUTO_OWNERSHIP, PI_NEW_VEHICLES], demographic=[GENDER_M, AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Male rider demo.')
i2a('tyres', purchase_intent=[PI_AUTO_PARTS, PI_AUTO_SERVICES], demographic=adult_ages('25-29','55-59'), evidence='Direct IAB.')
i2a('auto-dealers', purchase_intent=[PI_NEW_VEHICLES, PI_PREOWNED, PI_AUTO_OWNERSHIP], demographic=adult_ages('25-29','55-59'), evidence='Direct IAB.')

# Financial services
i2a('financial-services', purchase_intent=[PI_FINANCE_INSURANCE, PI_BANKING, PI_INSURANCE_PI], demographic=adult_ages('21-24','65-69'), evidence='Direct IAB.')
i2a('retail-banking', purchase_intent=[PI_BANKING], demographic=adult_ages('21-24','65-69'), evidence='Direct IAB.')
i2a('fintech-neobanks', purchase_intent=[PI_BANKING, PI_FINANCE_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger digital-native.')
i2a('investing-platforms', purchase_intent=[PI_STOCKS_INVESTMENTS, PI_FINANCE_APPS], demographic=[GENDER_M, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Younger male per brokerage demos.')
i2a('credit-cards', purchase_intent=[PI_CREDIT_CARDS, PI_BANKING], demographic=adult_ages('21-24','55-59'), evidence='Direct IAB.')
i2a('buy-now-pay-later', purchase_intent=[PI_CREDIT_CARDS, PI_FINANCE_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger Klarna/Afterpay demo.')
i2a('insurance', purchase_intent=[PI_INSURANCE_PI, PI_FINANCE_INSURANCE], demographic=adult_ages('25-29','65-69'), evidence='Direct IAB.')
i2a('crypto-exchanges', purchase_intent=[PI_DIGITAL_GOODS, PI_STOCKS_INVESTMENTS, PI_FINANCE_APPS], demographic=[GENDER_M, AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger male per Coinbase demos.')
i2a('tax-services', purchase_intent=[PI_TAX_PREP, PI_ACCOUNTANTS, PI_FINANCE_INSURANCE], demographic=adult_ages('25-29','65-69'), evidence='Adult filer.')

# Telecom & utilities
i2a('telecom-utilities', purchase_intent=[PI_TELECOM, PI_MOBILE_PLANS], demographic=adult_ages('18-20','65-69'), evidence='Direct IAB.')
i2a('mobile-carriers', purchase_intent=[PI_MOBILE_PLANS, PI_MOBILE_PHONES, PI_TELECOM], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('internet-providers', purchase_intent=[PI_ISPS, PI_WEB_SERVICES, PI_TELECOM], demographic=adult_ages('25-29','65-69'), evidence='Direct IAB.')
i2a('energy-utilities', purchase_intent=[PI_HOME_GARDEN_SERVICES, PI_HOME_SECURITY], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49'], OWNERSHIP], evidence='Homeowner.')

# Home & living
i2a('home-living', purchase_intent=[PI_FURNITURE, PI_HOME_GARDEN_SERVICES, PI_HOME_IMPROVEMENT_PI], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], OWNERSHIP], evidence='Direct IAB.')
i2a('furniture', purchase_intent=[PI_FURNITURE, PI_BEDS, PI_OUTDOOR_FURNITURE], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
i2a('home-decor-brands', purchase_intent=[PI_FURNITURE, PI_HOME_GARDEN_SERVICES], demographic=[GENDER_F, AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Female homemaker.')
i2a('home-appliances', purchase_intent=[PI_APPLIANCE_REPAIR, PI_FURNITURE], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], OWNERSHIP], evidence='Homeowner.')
i2a('kitchenware', purchase_intent=[PI_FURNITURE, PI_CPG], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Home cook.')
i2a('bedding-bath', purchase_intent=[PI_BEDS, PI_FURNITURE], demographic=adult_ages('21-24','55-59'), evidence='Direct IAB.')
i2a('cleaning-household', purchase_intent=[PI_HOUSEKEEPING, PI_NON_EDIBLE], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Household buyer.')
i2a('home-improvement', purchase_intent=[PI_HOME_IMPROVEMENT_PI, PI_HARDWARE, PI_TOOLS], demographic=[AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49'], OWNERSHIP], evidence='Direct IAB.')
i2a('gardening-brands', purchase_intent=[PI_LAWN_GARDEN, PI_LANDSCAPING_PI], demographic=[AGE['35-39'], AGE['40-44'], AGE['45-49'], AGE['50-54'], OWNERSHIP], evidence='Older homeowner.')

# Baby & kids
i2a('baby-kids', purchase_intent=[PI_FAMILY_PARENTING, PI_CHILDCARE, PI_KIDS_ACTIVITIES, PI_BABY_FURNITURE], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], NUM_CHILDREN], evidence='Direct IAB.')
i2a('baby-food', purchase_intent=[PI_FAMILY_PARENTING, PI_CPG, PI_EDIBLE], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], NUM_CHILDREN], evidence='Parent buyer.')
i2a('diapers-nappies', purchase_intent=[PI_FAMILY_PARENTING, PI_CPG], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], NUM_CHILDREN], evidence='Direct IAB.')
i2a('baby-gear', purchase_intent=[PI_FAMILY_PARENTING, PI_BABY_FURNITURE], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], NUM_CHILDREN], evidence='Direct IAB.')
i2a('toys', purchase_intent=[PI_KIDS_ACTIVITIES, PI_FAMILY_PARENTING], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], NUM_CHILDREN], evidence='Direct IAB.')
i2a('kids-edutainment', purchase_intent=[PI_KIDS_ACTIVITIES, PI_EDU_APPS, PI_FAMILY_PARENTING], demographic=[AGE['30-34'], AGE['35-39'], AGE['40-44'], NUM_CHILDREN], evidence='Parent of school-age.')

# Pets industry
i2a('pets-industry', purchase_intent=[PI_PET_SERVICES, PI_PET_STORES, PI_VET_SERVICES], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
i2a('pet-food', purchase_intent=[PI_PET_STORES, PI_PET_SERVICES, PI_CPG], demographic=adult_ages('21-24','65-69'), evidence='Pet owner.')
i2a('pet-supplies', purchase_intent=[PI_PET_STORES, PI_PET_SERVICES], demographic=adult_ages('21-24','55-59'), evidence='Direct IAB.')
i2a('pet-tech', purchase_intent=[PI_PET_STORES, PI_CONSUMER_ELECTRONICS], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Pet-owner tech adopter.')
i2a('vet-services', purchase_intent=[PI_VET_SERVICES, PI_PET_SERVICES], demographic=adult_ages('25-29','65-69'), evidence='Direct IAB.')
i2a('pet-insurance', purchase_intent=[PI_INSURANCE_PI, PI_PET_SERVICES], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Insurance + pet overlap.')

# Education industry
i2a('education-industry', purchase_intent=[PI_EDU_CAREERS, PI_ONLINE_EDUCATION, PI_COLLEGES], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('online-courses', purchase_intent=[PI_ONLINE_EDUCATION, PI_EDU_APPS, PI_EDU_CAREERS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Direct IAB.')
i2a('tutoring', purchase_intent=[PI_ONLINE_EDUCATION, PI_EDU_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], NUM_CHILDREN], evidence='Student + parent.')
i2a('language-learning-brands', purchase_intent=[PI_LANGUAGE_LEARNING, PI_EDU_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Direct IAB.')
i2a('k12', purchase_intent=[PI_EDU_CAREERS], demographic=[AGE['30-34'], AGE['35-39'], AGE['40-44'], NUM_CHILDREN], evidence='Parent of school-age.')
i2a('higher-ed', purchase_intent=[PI_COLLEGES, PI_EDU_CAREERS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Direct IAB.')
i2a('coding-bootcamps', purchase_intent=[PI_ONLINE_EDUCATION, PI_CAREER_IMPROVEMENT], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Tech-career switcher.')

# Apps & platforms
i2a('apps-platforms', purchase_intent=[PI_APPS, PI_LIFESTYLE_APPS, PI_SOCIAL_APPS], demographic=adult_ages('18-20','45-49'), evidence='Direct IAB.')
i2a('dating-apps', purchase_intent=[PI_LIFESTYLE_APPS, PI_SOCIAL_APPS], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], SINGLE], evidence='Single-adult demo.')
i2a('social-platforms', purchase_intent=[PI_SOCIAL_APPS], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('productivity-apps', purchase_intent=[PI_PRODUCTIVITY_APPS, PI_BUSINESS_APPS], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Working-adult.')
i2a('language-translation-apps', purchase_intent=[PI_LANGUAGE_LEARNING, PI_EDU_APPS], demographic=adult_ages('18-20','45-49'), evidence='Direct IAB.')
i2a('marketplaces', purchase_intent=[PI_SHOPPING_APPS], demographic=adult_ages('18-20','55-59'), evidence='Wide buyer demo.')
i2a('ride-share-mobility', purchase_intent=[PI_NAV_APPS, PI_AUTO_RENTAL_PI], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34'], URBANIZATION], evidence='Urban younger demo.')

# Retail & e-commerce
i2a('retail-ecommerce', purchase_intent=[PI_SHOPPING_APPS, PI_CPG, PI_CLOTHING], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('department-stores', purchase_intent=[PI_CLOTHING, PI_FURNITURE, PI_CPG], demographic=adult_ages('25-29','65-69'), evidence='Wide buyer.')
i2a('specialty-retail', purchase_intent=[PI_CLOTHING, PI_BEAUTY_SERVICES], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Younger speciality demo.')
i2a('marketplaces-ecom', purchase_intent=[PI_SHOPPING_APPS], demographic=adult_ages('18-20','55-59'), evidence='Direct IAB.')
i2a('d2c-subscription', purchase_intent=[PI_SHOPPING_APPS, PI_CPG], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Subscription buyer.')
i2a('discount-resale', purchase_intent=[PI_SHOPPING_APPS, PI_CLOTHING], demographic=[AGE['18-20'], AGE['21-24'], AGE['25-29']], evidence='Younger thrift demo.')

# Real estate
i2a('real-estate', purchase_intent=[PI_REAL_ESTATE_PI, PI_RESIDENTIAL_RE, PI_RE_SALES], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44'], AGE['45-49']], evidence='Direct IAB.')
i2a('residential-real-estate', purchase_intent=[PI_RESIDENTIAL_RE, PI_RE_SALES], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')
i2a('rental-platforms', purchase_intent=[PI_RE_RENTALS, PI_REAL_ESTATE_PI], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34']], evidence='Renter demo.')
i2a('mortgages', purchase_intent=[PI_MORTGAGE, PI_FINANCE_INSURANCE], demographic=[AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Direct IAB.')

# Professional services
i2a('professional-services', purchase_intent=[PI_BUSINESS_INDUSTRIAL, PI_LEGAL, PI_ACCOUNTANTS], demographic=adult_ages('25-29','65-69'), evidence='Adult professional.')
i2a('legal-services', purchase_intent=[PI_LEGAL, PI_ATTORNEYS], demographic=adult_ages('25-29','65-69'), evidence='Direct IAB.')
i2a('consulting', purchase_intent=[PI_BUSINESS_INDUSTRIAL, PI_ADVERTISING], demographic=adult_ages('25-29','60-64'), evidence='B2B.')
i2a('accounting', purchase_intent=[PI_ACCOUNTANTS, PI_BOOKKEEPERS, PI_TAX_PREP], demographic=adult_ages('25-29','65-69'), evidence='Direct IAB.')
i2a('recruitment-hr-tech', purchase_intent=[PI_EMPLOYMENT_AGENCIES, PI_BUSINESS_APPS, PI_HR], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39']], evidence='Working-adult.')
i2a('marketing-agencies', purchase_intent=[PI_ADVERTISING, PI_BUSINESS_INDUSTRIAL], demographic=adult_ages('25-29','55-59'), evidence='B2B.')

# Non-profit & government
i2a('non-profit-government', purchase_intent=[PI_NON_PROFITS, PI_CHARITIES, PI_CIVIC], demographic=adult_ages('25-29','65-69'), evidence='Direct IAB.')
i2a('charities', purchase_intent=[PI_CHARITIES, PI_NON_PROFITS, PI_NGOS], demographic=adult_ages('25-29','65-69'), evidence='Direct IAB.')
i2a('government-public-sector', purchase_intent=[PI_CIVIC, PI_NON_PROFITS], demographic=adult_ages('21-24','65-69'), evidence='Civic engagement.')
i2a('political-advocacy', purchase_intent=[PI_CIVIC, PI_NON_PROFITS], demographic=adult_ages('21-24','65-69'), evidence='Sensitive vertical.')

# Sensitive / restricted
i2a('sensitive-restricted', evidence='Parent category for restricted industries. Sub-industries have specific IAB mappings; this parent intentionally has none.')
i2a('tobacco-vape', purchase_intent=[PI_SMOKING_CESSATION], demographic=adult_ages('21-24','55-59'), evidence='Adult-only; SMOKING_CESSATION is the closest IAB segment - sensitive.')
i2a('cannabis-cbd', purchase_intent=[PI_ALT_MEDICINE, PI_DRUGSTORES], demographic=[AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Adult-only; alt-medicine adjacency.')
i2a('gambling', purchase_intent=[PI_FANTASY_SPORTS], demographic=[GENDER_M, AGE['21-24'], AGE['25-29'], AGE['30-34'], AGE['35-39'], AGE['40-44']], evidence='Adult male sports-fan demo. Sensitive.')
i2a('lottery', purchase_intent=[PI_FANTASY_SPORTS], demographic=adult_ages('21-24','65-69'), evidence='Adult-only.')
i2a('adult-industry', evidence='Adult-only; no clean IAB Purchase Intent mapping. Sensitive vertical - typically blocked on mainstream creator platforms.')
i2a('firearms', evidence='Adult-only; no clean IAB Purchase Intent mapping. Sensitive vertical - restricted on most mainstream creator platforms.')

# Industries without specific authored mapping inherit from parent at runtime.

# ---------------------------------------------------------------------------
# Emit files
# ---------------------------------------------------------------------------
ROOT_DATA = DATA

(ROOT_DATA/'niche_industry_affinity.json').write_text(json.dumps({
    '$comment': 'Direct niche -> industry affinity with 3-tier strength. Symmetric edges. Sub-niches inherit parent edges via app-side fallback unless overridden. Quality-floored: an edge appears only with a citable source or non-generic logical reason. Evidence at group level; per-edge overrides in optional `overrides[]`. Niche IDs reference data/niches.json; industry IDs reference data/industries.json.',
    'version': '1.0.0',
    'updated': '2026-05-26',
    'strength_scale': ['primary', 'secondary', 'tertiary'],
    'fallback_behavior': 'Sub-niches with no entry inherit their parent niche\'s edges (resolved at app load time using data/niches.json parent links).',
    'evidence_sources': {
        'iab': 'IAB Tech Lab Audience Taxonomy 1.1 alignment',
        'imh': 'Influencer Marketing Hub annual benchmark reports',
        'hypeauditor': 'HypeAuditor State of Influencer Marketing reports',
        'case-study': 'Documented brand-creator campaign or partnership history',
        'logic': 'Reasoned mapping with no specific public citation (non-generic only)'
    },
    'groups': list(N2I.values())
}, ensure_ascii=False, indent=2) + '\n')

(ROOT_DATA/'niche_audience_affinity.json').write_text(json.dumps({
    '$comment': 'Bridge leg 1: niche -> IAB Audience Taxonomy segments (Interest + Demographic). Used to compute niche<->industry affinity via shared IAB segments and to factor in a specific talent\'s real audience_demographics. IAB segment IDs reference data/iab_audience_taxonomy_v1.1.json.',
    'version': '1.0.0',
    'updated': '2026-05-26',
    'iab_source_file': 'iab_audience_taxonomy_v1.1.json',
    'fallback_behavior': 'Sub-niches with no entry inherit their parent niche\'s segments.',
    'groups': list(N2A.values())
}, ensure_ascii=False, indent=2) + '\n')

(ROOT_DATA/'industry_audience_affinity.json').write_text(json.dumps({
    '$comment': 'Bridge leg 2: industry -> IAB Audience Taxonomy segments (Purchase Intent + Demographic). Pairs with niche_audience_affinity.json to produce the bridged niche<->industry affinity.',
    'version': '1.0.0',
    'updated': '2026-05-26',
    'iab_source_file': 'iab_audience_taxonomy_v1.1.json',
    'fallback_behavior': 'Sub-industries with no entry inherit their parent industry\'s segments.',
    'groups': list(I2A.values())
}, ensure_ascii=False, indent=2) + '\n')

# ---------------------------------------------------------------------------
# Validation summary
# ---------------------------------------------------------------------------
all_edges = sum(len(g.get('primary',[])) + len(g.get('secondary',[])) + len(g.get('tertiary',[])) for g in N2I.values())
print(f"\nniche_industry_affinity: {len(N2I)} niche groups, {all_edges} edges authored")
print(f"  niches covered: {len(N2I)}/{len(niches)}  ({100*len(N2I)//len(niches)}%)")
print(f"  niches without direct edges (will inherit from parent): {sorted(set(niches) - set(N2I))[:10]}{'...' if len(set(niches)-set(N2I))>10 else ''}")
print(f"\nniche_audience_affinity: {len(N2A)} niche groups")
print(f"  niches covered: {len(N2A)}/{len(niches)}")
print(f"\nindustry_audience_affinity: {len(I2A)} industry groups")
print(f"  industries covered: {len(I2A)}/{len(industries)}  ({100*len(I2A)//len(industries)}%)")
print(f"\nAll cross-references validated against niches.json, industries.json, and iab_audience_taxonomy_v1.1.json.")
