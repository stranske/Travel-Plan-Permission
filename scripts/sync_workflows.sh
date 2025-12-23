#!/bin/bash
# Sync workflow files from stranske/Workflows repo
# Usage: ./scripts/sync_workflows.sh [--dry-run]

set -e

WORKFLOWS_REPO="stranske/Workflows"
BRANCH="main"
DRY_RUN=false

if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "DRY RUN MODE - no files will be modified"
fi

# Files to sync (full copy from Workflows repo)
FULL_SYNC_FILES=(
    ".github/workflows/agents-63-issue-intake.yml"
)

# Scripts required by agents-63-issue-intake.yml (ChatGPT sync)
SCRIPTS_TO_SYNC=(
    "decode_raw_input.py"
    "parse_chatgpt_topics.py"
    "fallback_split.py"
)

# Files to sync from templates (thin callers)
TEMPLATE_FILES=(
    "agents-orchestrator.yml:.github/workflows/agents-70-orchestrator.yml"
    "agents-pr-meta.yml:.github/workflows/agents-pr-meta.yml"
    "ci.yml:.github/workflows/ci.yml"
    "autofix.yml:.github/workflows/autofix.yml"
)

echo "Syncing workflows from $WORKFLOWS_REPO@$BRANCH..."

# Sync full workflow files
for file in "${FULL_SYNC_FILES[@]}"; do
    echo "  Fetching $file..."
    url="https://raw.githubusercontent.com/$WORKFLOWS_REPO/$BRANCH/$file"
    if $DRY_RUN; then
        echo "    Would download: $url"
    else
        curl -sL "$url" -o "$file"        # Fix local reusable workflow references to point to remote Workflows repo
        # The Workflows repo uses local refs (./.github/workflows/...) but consumer
        # repos need remote refs (stranske/Workflows/.github/workflows/...@main)
        sed -i 's|uses: \.\/\.github\/workflows\/\(.*\.yml\)|uses: stranske/Workflows/.github/workflows/\1@main|g' "$file"        echo "    ✓ Updated $file"
    fi
done

# Sync template files
for mapping in "${TEMPLATE_FILES[@]}"; do
    src="${mapping%%:*}"
    dst="${mapping##*:}"
    echo "  Fetching template $src → $dst..."
    url="https://raw.githubusercontent.com/$WORKFLOWS_REPO/$BRANCH/templates/consumer-repo/.github/workflows/$src"
    if $DRY_RUN; then
        echo "    Would download: $url"
    else
        curl -sL "$url" -o "$dst"
        echo "    ✓ Updated $dst"
    fi
done

# Sync scripts required by agents-63-issue-intake.yml
echo "Syncing scripts from $WORKFLOWS_REPO@$BRANCH..."
mkdir -p .github/scripts
for script in "${SCRIPTS_TO_SYNC[@]}"; do
    echo "  Fetching .github/scripts/$script..."
    url="https://raw.githubusercontent.com/$WORKFLOWS_REPO/$BRANCH/.github/scripts/$script"
    if $DRY_RUN; then
        echo "    Would download: $url"
    else
        curl -sL "$url" -o ".github/scripts/$script"
        echo "    ✓ Updated .github/scripts/$script"
    fi
done

echo ""
echo "Sync complete. Review changes with: git diff .github/"
