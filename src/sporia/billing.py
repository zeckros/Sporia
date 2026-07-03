"""Intégration Stripe : Checkout + Billing Portal + webhooks (chantier 4.2).

Tout l'accès au SDK `stripe` est encapsulé ici. Config lue via l'environnement
(comme email.py) : STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID,
PUBLIC_BASE_URL. Clés absentes (DEV) → stripe_enabled() False, l'app démarre
mais les routes billing renvoient 503."""

from __future__ import annotations

import os

import stripe

from sporia.users import accounts

# Stripe subscription.status → notre subscription_status
_STATUS_MAP = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
}


class WebhookError(Exception):
    """Signature invalide ou payload webhook illisible."""


def stripe_enabled() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("STRIPE_PRICE_ID"))


def _base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def _configure() -> None:
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")


def _ensure_customer(account: dict) -> str:
    """Renvoie le stripe_customer_id du compte, en le créant si besoin."""
    cid = account.get("stripe_customer_id")
    if cid:
        return cid
    _configure()
    customer = stripe.Customer.create(
        email=account["email"],
        name=account.get("name") or account["email"],
        metadata={"user_id": str(account["id"])},
    )
    accounts.set_stripe_customer(account["id"], customer["id"])
    return customer["id"]


def create_checkout_session(account: dict) -> str:
    """Crée une Checkout Session (abonnement) et renvoie son URL hébergée."""
    _configure()
    cid = _ensure_customer(account)
    base = _base_url()
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=cid,
        line_items=[{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
        success_url=f"{base}/?checkout=success",
        cancel_url=f"{base}/?checkout=cancel",
        client_reference_id=str(account["id"]),
    )
    return session["url"]


def create_portal_session(account: dict) -> str:
    """Crée une session Billing Portal et renvoie son URL. Lève ValueError sans customer."""
    cid = account.get("stripe_customer_id")
    if not cid:
        raise ValueError("compte sans stripe_customer_id")
    _configure()
    session = stripe.billing_portal.Session.create(customer=cid, return_url=f"{_base_url()}/")
    return session["url"]
