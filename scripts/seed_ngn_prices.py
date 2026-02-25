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
    # Subscriptions
    {'product_type': 'subscription', 'product_key': 'starter', 'price_ngn': 15000},
    {'product_type': 'subscription', 'product_key': 'professional', 'price_ngn': 45000},
    {'product_type': 'subscription', 'product_key': 'business', 'price_ngn': 120000},
    # Credit packs
    {'product_type': 'credit_pack', 'product_key': 'pack_100', 'price_ngn': 5000},
    {'product_type': 'credit_pack', 'product_key': 'pack_250', 'price_ngn': 9000},
    {'product_type': 'credit_pack', 'product_key': 'pack_500', 'price_ngn': 15000},
    {'product_type': 'credit_pack', 'product_key': 'pack_1000', 'price_ngn': 25000},
]


def seed():
    with app.app_context():
        db.create_all()

        created = 0
        updated = 0

        for item in NGN_PRICES:
            existing = NGNPriceConfig.query.filter_by(product_key=item['product_key']).first()
            if existing:
                if existing.price_ngn != item['price_ngn']:
                    existing.price_ngn = item['price_ngn']
                    updated += 1
                    print(f"  Updated {item['product_key']}: ₦{item['price_ngn']:,}")
            else:
                config = NGNPriceConfig(
                    product_type=item['product_type'],
                    product_key=item['product_key'],
                    price_ngn=item['price_ngn'],
                )
                db.session.add(config)
                created += 1
                print(f"  Created {item['product_key']}: ₦{item['price_ngn']:,}")

        db.session.commit()
        print(f"\nDone: {created} created, {updated} updated, {len(NGN_PRICES) - created - updated} unchanged.")


if __name__ == '__main__':
    seed()
