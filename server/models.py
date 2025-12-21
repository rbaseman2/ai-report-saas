# server/models.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    # matches: id uuid primary key default gen_random_uuid()
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True)


class Subscription(Base):
    __tablename__ = "subscriptions"

    # matches: id bigint
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    customer_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # stripe subscription id stored here
    subscription_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # stripe price id stored here
    price_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # matches: timestamp with time zone
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # you added this column already
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), nullable=True, index=True)


class Summary(Base):
    __tablename__ = "summaries"

    # matches your create table: id uuid primary key default gen_random_uuid()
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)

    # matches: user_id uuid not null references users(id)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # matches: subscription_id bigint references subscriptions(id)
    subscription_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id"), nullable=True
    )

    input_type: Mapped[str] = mapped_column(Text)
    input_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    summary_text: Mapped[str] = mapped_column(Text)

    tokens_used: Mapped[int] = mapped_column(BigInteger, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
