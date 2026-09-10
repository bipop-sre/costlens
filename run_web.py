#!/usr/bin/env python3
"""Start the CostLens Web Dashboard."""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "costlens.web.app:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
    )
