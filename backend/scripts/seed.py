"""Seed 500,000 realistic products across 30 categories.

Run:  python -m scripts.seed            (skips if already seeded)
      python -m scripts.seed --force    (wipe and reload)

Why it is fast:
- Faker is slow per call, so we use it once to build small pools of brands,
  colours and sentences, then combine pool entries with `random` (cheap).
- Rows go in through asyncpg's COPY (`copy_records_to_table`), which is far
  faster than INSERT statements, in batches of 50k so memory stays flat.

Why it is idempotent:
- Categories use INSERT ... ON CONFLICT DO NOTHING.
- If the products table already holds exactly the target number of rows we do
  nothing. If it holds a partial load (an interrupted earlier run) we
  TRUNCATE and reload, so we never end up with duplicates or gaps.
- Generation uses a fixed random seed, so every run produces the same data.
"""
import argparse
import asyncio
import os
import random
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import asyncpg
from faker import Faker

from app.config import get_settings

BATCH_SIZE = 50_000
RANDOM_SEED = 42

# (name, slug, nouns, (min_price, max_price))
CATEGORIES: list[tuple[str, str, list[str], tuple[int, int]]] = [
    ("Electronics", "electronics", ["Charger", "Power Bank", "Cable", "Adapter", "Smart Plug", "LED Strip"], (5, 150)),
    ("Computers", "computers", ["Laptop", "Monitor", "Keyboard", "Mouse", "SSD", "Webcam"], (15, 2500)),
    ("Smartphones", "smartphones", ["Phone", "Phone Case", "Screen Protector", "Car Mount", "Stylus"], (5, 1400)),
    ("Audio", "audio", ["Headphones", "Earbuds", "Speaker", "Soundbar", "Microphone", "Amplifier"], (10, 900)),
    ("Cameras", "cameras", ["Camera", "Lens", "Tripod", "Camera Bag", "Memory Card", "Flash"], (10, 3000)),
    ("Gaming", "gaming", ["Controller", "Gaming Headset", "Gaming Chair", "Console Stand", "Mouse Pad"], (10, 600)),
    ("Home & Kitchen", "home-kitchen", ["Blender", "Kettle", "Toaster", "Knife Set", "Frying Pan", "Coffee Maker"], (8, 400)),
    ("Furniture", "furniture", ["Desk", "Chair", "Bookshelf", "Sofa", "Lamp", "Side Table"], (25, 1800)),
    ("Garden", "garden", ["Planter", "Hose", "Garden Shears", "Bird Feeder", "Lawn Sprinkler"], (5, 300)),
    ("Tools", "tools", ["Drill", "Screwdriver Set", "Hammer", "Wrench", "Tool Box", "Tape Measure"], (5, 450)),
    ("Automotive", "automotive", ["Car Vacuum", "Seat Cover", "Dash Cam", "Tire Inflator", "Floor Mat"], (8, 350)),
    ("Sports", "sports", ["Football", "Tennis Racket", "Basketball", "Cricket Bat", "Badminton Set"], (8, 300)),
    ("Outdoors", "outdoors", ["Tent", "Sleeping Bag", "Backpack", "Lantern", "Water Bottle", "Hiking Pole"], (8, 600)),
    ("Fitness", "fitness", ["Yoga Mat", "Dumbbell", "Resistance Band", "Kettlebell", "Jump Rope"], (5, 500)),
    ("Toys", "toys", ["Puzzle", "Building Blocks", "Doll", "Toy Car", "Board Game", "Plush Toy"], (5, 150)),
    ("Baby", "baby", ["Stroller", "Baby Monitor", "Diaper Bag", "High Chair", "Baby Blanket"], (10, 700)),
    ("Books", "books", ["Novel", "Cookbook", "Notebook", "Planner", "Atlas", "Biography"], (5, 80)),
    ("Music", "music", ["Guitar", "Ukulele", "Keyboard Piano", "Drum Pad", "Guitar Strings"], (5, 1500)),
    ("Movies", "movies", ["Blu-ray", "DVD Box Set", "Projector Screen", "Film Poster"], (5, 120)),
    ("Clothing", "clothing", ["T-Shirt", "Hoodie", "Jacket", "Jeans", "Sweater", "Dress"], (8, 300)),
    ("Shoes", "shoes", ["Sneakers", "Running Shoes", "Boots", "Sandals", "Loafers"], (15, 350)),
    ("Jewelry", "jewelry", ["Necklace", "Ring", "Bracelet", "Earrings", "Pendant"], (10, 2000)),
    ("Watches", "watches", ["Watch", "Smartwatch", "Watch Strap", "Fitness Tracker"], (15, 1500)),
    ("Beauty", "beauty", ["Face Serum", "Lipstick", "Moisturizer", "Hair Dryer", "Perfume"], (5, 250)),
    ("Health", "health", ["Thermometer", "First Aid Kit", "Massage Gun", "Vitamin Pack", "Scale"], (5, 300)),
    ("Pet Supplies", "pet-supplies", ["Dog Bed", "Cat Tree", "Pet Bowl", "Leash", "Pet Carrier"], (5, 250)),
    ("Office", "office", ["Desk Organizer", "Stapler", "Whiteboard", "Pen Set", "Paper Shredder"], (3, 400)),
    ("Arts & Crafts", "arts-crafts", ["Paint Set", "Sketchbook", "Brush Set", "Easel", "Craft Kit"], (4, 250)),
    ("Grocery", "grocery", ["Coffee Beans", "Green Tea", "Olive Oil", "Granola", "Dark Chocolate"], (3, 60)),
    ("Travel", "travel", ["Suitcase", "Travel Pillow", "Packing Cubes", "Passport Holder", "Duffel Bag"], (8, 500)),
]

ADJECTIVES = [
    "Wireless", "Portable", "Compact", "Premium", "Classic", "Ergonomic", "Smart", "Ultra",
    "Lightweight", "Heavy-Duty", "Vintage", "Modern", "Eco", "Pro", "Deluxe", "Mini",
    "Foldable", "Waterproof", "Rechargeable", "Organic", "Handmade", "Adjustable", "Slim", "Rugged",
]


def build_pools(fake: Faker) -> dict[str, list[str]]:
    """Call Faker a few thousand times instead of millions of times."""
    return {
        "brands": list({fake.company().split(" ")[0].strip(",") for _ in range(600)}),
        "colors": list({fake.color_name() for _ in range(300)}),
        "sentences": [fake.paragraph(nb_sentences=3) for _ in range(3000)],
    }


def make_product(rng: random.Random, pools: dict, index: int, category_id: int,
                 nouns: list[str], price_range: tuple[int, int], now: datetime) -> tuple:
    brand = rng.choice(pools["brands"])
    noun = rng.choice(nouns)
    name = f"{brand} {rng.choice(ADJECTIVES)} {rng.choice(pools['colors'])} {noun}"
    low, high = price_range
    # Skew prices towards the cheap end, like a real catalog.
    price = Decimal(str(round(low + (high - low) * (rng.random() ** 2), 2))).quantize(Decimal("0.01"))
    created_at = now - timedelta(minutes=rng.randint(0, 2 * 365 * 24 * 60))
    return (
        f"WC-{index:07d}",
        name,
        brand,
        f"{name}. {rng.choice(pools['sentences'])}",
        category_id,
        price,
        rng.randint(0, 500),
        Decimal(str(round(rng.uniform(1.0, 5.0), 1))),
        created_at,
        created_at,
    )


async def ensure_categories(conn: asyncpg.Connection) -> list[tuple[int, list[str], tuple[int, int]]]:
    await conn.executemany(
        "INSERT INTO categories (name, slug) VALUES ($1, $2) ON CONFLICT (slug) DO NOTHING",
        [(name, slug) for name, slug, _, _ in CATEGORIES],
    )
    rows = await conn.fetch("SELECT id, slug FROM categories")
    id_by_slug = {row["slug"]: row["id"] for row in rows}
    return [(id_by_slug[slug], nouns, prices) for _, slug, nouns, prices in CATEGORIES]


async def load_products(conn: asyncpg.Connection, categories: list, total: int) -> None:
    rng = random.Random(RANDOM_SEED)
    fake = Faker()
    Faker.seed(RANDOM_SEED)
    pools = build_pools(fake)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    columns = ["sku", "name", "brand", "description", "category_id", "price", "stock",
               "rating", "created_at", "updated_at"]

    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        batch = []
        for index in range(start + 1, end + 1):
            category_id, nouns, prices = rng.choice(categories)
            batch.append(make_product(rng, pools, index, category_id, nouns, prices, now))
        await conn.copy_records_to_table("products", records=batch, columns=columns)
        print(f"[seed] inserted {end:,}/{total:,}", flush=True)


async def seed(total: int, force: bool) -> None:
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        categories = await ensure_categories(conn)
        existing = await conn.fetchval("SELECT count(*) FROM products")
        if existing == total and not force:
            print(f"[seed] {existing:,} products already present, nothing to do")
            return
        if existing:
            print(f"[seed] found {existing:,} products (target {total:,}), reloading from scratch")
            await conn.execute("TRUNCATE products RESTART IDENTITY")

        started = time.perf_counter()
        async with conn.transaction():
            await load_products(conn, categories, total)
        # Fresh statistics so the planner picks the right indexes immediately.
        await conn.execute("ANALYZE products")
        print(f"[seed] done: {total:,} products in {time.perf_counter() - started:.1f}s")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Warpcart catalog")
    parser.add_argument("--count", type=int, default=int(os.getenv("SEED_PRODUCTS", "500000")))
    parser.add_argument("--force", action="store_true", help="wipe and reload even if already seeded")
    args = parser.parse_args()
    asyncio.run(seed(args.count, args.force))


if __name__ == "__main__":
    main()
