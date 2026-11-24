#!/usr/bin/env python3
"""build_orders.py: writes orders/order-<leg>.json for every leg with the registered seed, and orders/SHA256SUMS. Deterministic: run it twice, the sums are equal.

Run:  uv run --no-project python -I build_orders.py
"""
import hashlib
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261124  # the registered seed of the orders (the date of the draft)
spec = importlib.util.spec_from_file_location("plan", os.path.join(HERE, "plan.py"))
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)
picks_path = os.path.join(HERE, "picks.json")
picks = json.load(open(picks_path))
os.makedirs(os.path.join(HERE, "orders"), exist_ok=True)
sums = []
for leg in ("L0", "L1", "L2", "L3", "L4", "H", "L5", "L6"):
    order = plan.build(leg, SEED, dict(plan.DEFAULT_PROVEN), picks, plan.sha256_file(picks_path))
    path = os.path.join(HERE, "orders", f"order-{leg}.json")
    sums.append(f"{plan.dump(order, path)}  order-{leg}.json")
    print(f"{leg}: salt {order['salt']}, {len(order['units'])} units, {len(order['claims'])} claims, claimable {order['claimable']}")
open(os.path.join(HERE, "orders", "SHA256SUMS"), "w").write("\n".join(sums) + "\n")
print("\n".join(sums))
assert hashlib.sha256(open(plan.__file__, "rb").read()).hexdigest() == json.load(open(os.path.join(HERE, "orders", "order-L1.json")))["plan_py_sha256"]
