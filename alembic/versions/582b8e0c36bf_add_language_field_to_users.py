"""Add language field to users

Revision ID: 582b8e0c36bf
Revises: 1b845bce28ed
Create Date: 2024-09-01 13:50:21.248116

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '582b8e0c36bf'
down_revision: Union[str, None] = '1b845bce28ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('language', sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'language')
    # ### end Alembic commands ###
