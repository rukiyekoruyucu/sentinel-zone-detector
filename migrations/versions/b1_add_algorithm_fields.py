"""add algorithm_type, session_label, xg_config_json to sessions

Revision ID: b1_add_algorithm_fields
Revises: a377fb1ce018
Create Date: 2025-01-15 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision     = 'b1_add_algorithm_fields'
down_revision = 'a377fb1ce018'
branch_labels = None
depends_on    = None


def upgrade():
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'algorithm_type', sa.String(length=32),
            nullable=True, server_default='zone_detector'
        ))
        batch_op.add_column(sa.Column(
            'session_label', sa.String(length=128), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'xg_config_json', sa.Text(), nullable=True
        ))


def downgrade():
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_column('xg_config_json')
        batch_op.drop_column('session_label')
        batch_op.drop_column('algorithm_type')
