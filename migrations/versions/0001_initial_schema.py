"""Initial PostgreSQL schema for TradeZen

Revision ID: 0001_initial
Revises: 
Create Date: 2026-10-28 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # 2. rules table
    op.create_table(
        'rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('stop_loss_pct', sa.Float(), nullable=False, server_default='2.0'),
        sa.Column('max_trades_per_day', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('no_averaging_down', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('max_position_pct', sa.Float(), nullable=False, server_default='20.0'),
        sa.Column('practice_capital', sa.Float(), nullable=False, server_default='100000.0'),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rules_id'), 'rules', ['id'], unique=False)
    op.create_index(op.f('ix_rules_user_id'), 'rules', ['user_id'], unique=False)
    op.create_index(op.f('ix_rules_is_current'), 'rules', ['is_current'], unique=False)

    # 3. scenarios table
    op.create_table(
        'scenarios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('event_type', sa.String(length=20), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('current_price', sa.Float(), nullable=False),
        sa.Column('drop_pct', sa.Float(), nullable=False),
        sa.Column('candles', sa.JSON(), nullable=False),
        sa.Column('outcome_2m', sa.Float(), nullable=True),
        sa.Column('outcome_5m', sa.Float(), nullable=True),
        sa.Column('outcome_10m', sa.Float(), nullable=True),
        sa.Column('outcome_30m', sa.Float(), nullable=True),
        sa.Column('trades_today', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_trade_was_loss', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_on', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scenarios_id'), 'scenarios', ['id'], unique=False)
    op.create_index(op.f('ix_scenarios_event_type'), 'scenarios', ['event_type'], unique=False)
    op.create_index(op.f('ix_scenarios_active'), 'scenarios', ['active'], unique=False)

    # 4. attempts table
    op.create_table(
        'attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('scenario_id', sa.Integer(), nullable=False),
        sa.Column('attempt_no', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('actor_type', sa.String(length=20), nullable=False, server_default='human'),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('size', sa.Float(), nullable=False),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('decision_seconds', sa.Float(), nullable=False),
        sa.Column('chart_viewed', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('after_reveal', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('season_no', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['scenario_id'], ['scenarios.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_attempts_id'), 'attempts', ['id'], unique=False)
    op.create_index(op.f('ix_attempts_user_id'), 'attempts', ['user_id'], unique=False)
    op.create_index(op.f('ix_attempts_scenario_id'), 'attempts', ['scenario_id'], unique=False)
    op.create_index(op.f('ix_attempts_actor_type'), 'attempts', ['actor_type'], unique=False)
    op.create_index(op.f('ix_attempts_season_no'), 'attempts', ['season_no'], unique=False)

    # 5. bot_decisions table
    op.create_table(
        'bot_decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scenario_id', sa.Integer(), nullable=False),
        sa.Column('actor_type', sa.String(length=20), nullable=False, server_default='bot'),
        sa.Column('bot_name', sa.String(length=50), nullable=False),
        sa.Column('true_label', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('size', sa.Float(), nullable=False),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('decision_seconds', sa.Float(), nullable=False),
        sa.Column('features', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['scenario_id'], ['scenarios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bot_decisions_id'), 'bot_decisions', ['id'], unique=False)
    op.create_index(op.f('ix_bot_decisions_scenario_id'), 'bot_decisions', ['scenario_id'], unique=False)
    op.create_index(op.f('ix_bot_decisions_actor_type'), 'bot_decisions', ['actor_type'], unique=False)

    # 6. predictions table
    op.create_table(
        'predictions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('attempt_id', sa.Integer(), nullable=True),
        sa.Column('features', sa.JSON(), nullable=False),
        sa.Column('label', sa.String(length=50), nullable=False),
        sa.Column('probability', sa.Float(), nullable=False),
        sa.Column('model_version', sa.String(length=50), nullable=False),
        sa.Column('feedback_correct', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['attempt_id'], ['attempts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_predictions_id'), 'predictions', ['id'], unique=False)
    op.create_index(op.f('ix_predictions_user_id'), 'predictions', ['user_id'], unique=False)
    op.create_index(op.f('ix_predictions_attempt_id'), 'predictions', ['attempt_id'], unique=False)


def downgrade() -> None:
    op.drop_table('predictions')
    op.drop_table('bot_decisions')
    op.drop_table('attempts')
    op.drop_table('scenarios')
    op.drop_table('rules')
    op.drop_table('users')
