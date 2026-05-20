# stripe-billing-reconciler
CLI tool written in Python — chosen for scripting ergonomics and Stripe SDK maturity — that fetches Stripe charge and subscription events via cursor-based pagination, cross-references them against a local orders table (columns: order_id TEXT, amount_cents INTEGER, stripe_charge_id TEXT, created_at TIMESTAMP), and outputs a structured discrepancy re
