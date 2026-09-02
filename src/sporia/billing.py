"""Intégration Stripe : Checkout + Billing Portal + webhooks (chantier 4.2).

Tout l'accès au SDK `stripe` est encapsulé ici. Config lue via l'environnement
(comme email.py) : STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID,
PUBLIC_BASE_URL. Clés absentes (DEV) → stripe_enabled() False, l'app démarre
mais les routes billing renvoient 503."""

from __future__ import annotations

import os
import time

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


def has_access(account: dict | None) -> bool:
    """True si le compte a droit à l'app : admin, abonnement actif, ou période payée en cours."""
    if account is None:
        return False
    if account.get("role") == "admin":
        return True
    # 'beta' = accès offert accordé par un admin (bêta-testeur), sans passage par Stripe.
    if account.get("subscription_status") in ("active", "beta"):
        return True
    cpe = account.get("current_period_end")
    return bool(cpe) and cpe > int(time.time())


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


def cancel_subscription(account: dict) -> None:
    """Résilie les abonnements Stripe du compte (best-effort, ne lève jamais)."""
    cid = account.get("stripe_customer_id")
    if not cid or not stripe_enabled():
        return
    try:
        _configure()
        subs = stripe.Subscription.list(customer=cid)
        for sub in subs["data"]:
            stripe.Subscription.delete(sub["id"])
    except Exception as e:  # jamais bloquer la suppression de compte
        print(f"[billing] annulation Stripe échouée pour {cid} : {e}")


def process_event(payload: bytes, sig_header: str) -> None:
    """Vérifie la signature Stripe puis applique l'événement (idempotent).

    Lève WebhookError si la signature ou le payload est invalide."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except (stripe.error.SignatureVerificationError, ValueError) as e:
        raise WebhookError(str(e)) from e

    etype = event["type"]
    obj = event["data"]["object"]
    customer_id = obj.get("customer")

    if etype == "checkout.session.completed":
        _update(customer_id, "active", None)
    elif etype == "customer.subscription.updated":
        status = _STATUS_MAP.get(obj.get("status"), "active")
        _update(customer_id, status, obj.get("current_period_end"))
    elif etype == "customer.subscription.deleted":
        _update(customer_id, "canceled", obj.get("current_period_end"))
    elif etype == "invoice.payment_failed":
        _update(customer_id, "past_due", None)
    # autres types → ignorés (no-op)


def _update(customer_id: str | None, status: str, period_end: int | None) -> None:
    if not customer_id:
        return
    acc = accounts.get_by_stripe_customer(customer_id)
    if acc is None:
        print(f"[billing] webhook pour customer inconnu {customer_id} — ignoré")
        return
    accounts.set_subscription(acc["id"], status, period_end)
