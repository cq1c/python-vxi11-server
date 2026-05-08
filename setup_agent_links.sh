#!/bin/bash
# Create compatibility links for tools that do not read AGENTS.md directly.

set -e

[ ! -e CLAUDE.md ] && ln -sf AGENTS.md CLAUDE.md

# Cursor old versions:
# [ ! -e .cursorrules ] && ln -sf AGENTS.md .cursorrules

# Gemini CLI, enable only if desired:
# [ ! -e GEMINI.md ] && ln -sf AGENTS.md GEMINI.md

echo "Agent context links set up"
echo "AGENTS.md is the single source of truth"
