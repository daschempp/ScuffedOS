"""Fitness provider integrations (M4).

The vendor-neutral seam lives in ``base`` (normalized dataclasses, the
``FitnessProvider`` protocol, and ``AuthError``). Concrete providers (WHOOP
today) register here. The ``configure``/``all_providers`` registry lands with
the provider phase.
"""
from __future__ import annotations
