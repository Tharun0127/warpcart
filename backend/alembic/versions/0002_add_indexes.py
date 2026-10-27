"""Indexes for the read paths.

- pg_trgm GIN index on name: makes `name ILIKE '%keyword%'` use an index.
  A plain B-tree cannot help a leading-wildcard LIKE.
- (category_id, price): category filter + price range in one index range scan.
  It also covers the foreign key lookup on category_id.
- (price): price-range filters without a category.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_name_trgm ON products USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_category_price ON products (category_id, price)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_price ON products (price)")
    op.execute("ANALYZE products")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_price")
    op.execute("DROP INDEX IF EXISTS ix_products_category_price")
    op.execute("DROP INDEX IF EXISTS ix_products_name_trgm")
