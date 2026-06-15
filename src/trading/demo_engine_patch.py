"""PATCHED Demo Engine - Uses unleashed protocol for full operation."""

# Quick monkey-patch to disable restrictive protocol
import sys
import src.trading.controlled_demo_survival_protocol as cdsp

# Replace the restrictive protocol class
from src.trading.unleashed_demo_protocol import UnleashedDemoProtocolV1

# Override the class in the module
cdsp.ControlledDemoSurvivalProtocolV1 = UnleashedDemoProtocolV1

print("✓ Unleashed protocol patched into ControlledDemoSurvivalProtocolV1")