"""Allow running sub-modules via python -m broker.<module>."""
import sys

if len(sys.argv) < 2:
    print("Usage: python -m broker.<module> [args]")
    print("Available modules: inspect, generate, schema")
    sys.exit(1)
