"""
Seed NGN price configuration for Nigerian Naira payments.
Idempotent — safe to re-run. Updates existing entries if prices change.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app, db
from models import NGNPriceConfig

NGN_PRICES = [
    # Subscriptions (USD matches STRIPE_PRICE_* config and billing page display)
    {'product_type': 'subscription', 'product_key': 'starter',      'price_ngn': 15000,  'price_usd': 29.00},
    {'product_type': 'subscription', 'product_key': 'professional',  'price_ngn': 45000,  'price_usd': 99.00},
    {'product_type': 'subscription', 'product_key': 'business',      'price_ngn': 120000, 'price_usd': 299.00},
    # Credit packs
    {'product_type': 'credit_pack',  'product_key': 'pack_100',      'price_ngn': 5000,   'price_usd': 10.00},
    {'product_type': 'credit_pack',  'product_key': 'pack_250',      'price_ngn': 9000,   'price_usd': 20.00},
    {'product_type': 'credit_pack',  'product_key': 'pack_500',      'price_ngn': 15000,  'price_usd': 35.00},
    {'product_type': 'credit_pack',  'product_key': 'pack_1000',     'price_ngn': 25000,  'price_usd': 60.00},
]


def seed():
    with app.app_context():
        db.create_all()

        # Ensure price_usd column exists (may not be present in DBs created before this column was added)
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        existing_cols = [c['name'] for c in inspector.get_columns('ngn_price_configs')]
        if 'price_usd' not in existing_cols:
            db.session.execute(text('ALTER TABLE ngn_price_configs ADD COLUMN price_usd NUMERIC(10,2)'))
            db.session.commit()
            print("  Migrated: added price_usd column")

        created = 0
        updated = 0

        for item in NGN_PRICES:
            existing = NGNPriceConfig.query.filter_by(product_key=item['product_key']).first()
            if existing:
                changed = False
                if existing.price_ngn != item['price_ngn']:
                    existing.price_ngn = item['price_ngn']
                    changed = True
                if float(existing.price_usd or 0) != item['price_usd']:
                    existing.price_usd = item['price_usd']
                    changed = True
                if changed:
                    updated += 1
                    print(f"  Updated {item['product_key']}: ${item['price_usd']} / NGN {item['price_ngn']:,}")
            else:
                config = NGNPriceConfig(
                    product_type=item['product_type'],
                    product_key=item['product_key'],
                    price_ngn=item['price_ngn'],
                    price_usd=item['price_usd'],
                )
                db.session.add(config)
                created += 1
                print(f"  Created {item['product_key']}: ${item['price_usd']} / NGN {item['price_ngn']:,}")

        db.session.commit()
        print(f"\nDone: {created} created, {updated} updated, {len(NGN_PRICES) - created - updated} unchanged.")


if __name__ == '__main__':
    seed()
