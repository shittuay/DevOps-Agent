"""Guard against tool-count and pricing drift between code and user-facing pages.

Source of truth:
- Tool counts: one per `'handler':` entry in src/tools/*_tools.py
  (same counting method as CLAUDE.md's Tool Inventory).
- Tier credits: the SubscriptionTier seed in app.py.

If this test fails after adding tools or changing tiers, update the
user-facing numbers to match the code — never the other way around.
Pure file-based: needs no app dependencies or database.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Keep in sync with the loaders list in routes/mcp.py::_get_all_tools
MCP_MODULES = [
    'aws_tools', 'kubernetes_tools', 'azure_tools', 'gcp_tools',
    'cicd_tools', 'terraform_tools', 'sonarqube_tools', 'nexus_tools',
    'docker_tools', 'git_tools', 'monitoring_tools', 'ansible_tools',
    'alerting_tools',
]


def _module_counts():
    return {
        f.stem: f.read_text(encoding='utf-8').count("'handler':")
        for f in (ROOT / 'src' / 'tools').glob('*_tools.py')
    }


def _tier_credits():
    """monthly_credits per tier from the shared tier definitions."""
    from services.subscription_tiers import TIER_DEFINITIONS
    return {t['name']: str(t['monthly_credits']) for t in TIER_DEFINITIONS}


def test_platform_total_in_user_facing_pages():
    total = sum(_module_counts().values())
    pages = ['landing.html', 'docs.html', 'login.html', 'about.html',
             'developers.html', 'onboarding.html', 'security.html']
    for name in pages:
        text = (ROOT / 'templates' / name).read_text(encoding='utf-8')
        assert str(total) in text, (
            f"templates/{name} no longer mentions the current tool total ({total}) — "
            f"update its hardcoded counts"
        )


def test_landing_category_counts():
    counts = _module_counts()
    landing = (ROOT / 'templates' / 'landing.html').read_text(encoding='utf-8')
    checks = {
        'aws_tools': f"{counts['aws_tools']} TOOLS",
        'kubernetes_tools': f"{counts['kubernetes_tools']} TOOLS",
        'terraform_tools': f"{counts['terraform_tools']} TOOLS",
        'github_tools': f"{counts['github_tools']} TOOLS",
        'git_tools': f"{counts['git_tools']} TOOLS",
    }
    for module, expected in checks.items():
        assert expected in landing, (
            f"landing.html tool card for {module} is stale — expected '{expected}'"
        )


def test_docs_aws_count():
    counts = _module_counts()
    docs = (ROOT / 'templates' / 'docs.html').read_text(encoding='utf-8')
    assert f"{counts['aws_tools']} AWS tools" in docs, (
        f"docs.html AWS section is stale — expected '{counts['aws_tools']} AWS tools'"
    )


def test_no_stale_totals_left_behind():
    """Any 7xx number followed by 'tools' (one word may sit between, e.g. "745 DevOps
    tools") or used as a stat counter must be the current total."""
    total = sum(_module_counts().values())
    pattern = re.compile(
        r'\b(7\d{2})(?=[ -](?:[\w.-]+ )?tools?\b|-tool\b)'
        r'|data-target="(7\d{2})"',
        re.IGNORECASE,
    )
    for f in (ROOT / 'templates').rglob('*.html'):
        for groups in pattern.findall(f.read_text(encoding='utf-8')):
            match = next(g for g in groups if g)
            assert int(match) == total, (
                f"{f.relative_to(ROOT)} mentions '{match} tools' but the registry has {total}"
            )


def test_markdown_docs_carry_current_totals():
    """User-facing Markdown docs state the platform and MCP totals."""
    counts = _module_counts()
    total = sum(counts.values())
    mcp_total = sum(counts[m] for m in MCP_MODULES)
    for rel in ['README.md', 'docs/FEATURE_REFERENCE.md']:
        text = (ROOT / rel).read_text(encoding='utf-8')
        assert f"**{total}**" in text, f"{rel} tool total is stale — expected {total}"
    registry = (ROOT / 'MCP_REGISTRY_SUBMISSION.md').read_text(encoding='utf-8')
    assert f"{mcp_total} tools across {len(MCP_MODULES)} modules" in registry
    stale = re.findall(r'\b(7\d{2}) tools\b', registry)
    assert all(int(n) == mcp_total for n in stale), f"MCP_REGISTRY_SUBMISSION.md: {stale}"


def test_mcp_docs_match_exposed_subset():
    counts = _module_counts()
    mcp_total = sum(counts[m] for m in MCP_MODULES)
    expected = f"{mcp_total} tools across {len(MCP_MODULES)} modules"
    for rel in ['mcp/README.md', 'mcp/package.json']:
        text = (ROOT / rel).read_text(encoding='utf-8')
        assert expected in text, f"{rel} is stale — expected '{expected}'"
    assert f"{mcp_total} tools." in (ROOT / 'mcp' / 'server.json').read_text(encoding='utf-8'), (
        f"mcp/server.json description is stale — expected '{mcp_total} tools.'"
    )


def test_landing_pricing_matches_tier_seed():
    credits = _tier_credits()
    landing = (ROOT / 'templates' / 'landing.html').read_text(encoding='utf-8')
    assert f"{int(credits['free'])} credits / month" in landing
    assert f"{int(credits['starter'])} credits / month" in landing
    assert f"{int(credits['professional']):,} credits / month" in landing
    assert f"{int(credits['business']):,} credits / month" in landing


def test_docs_billing_table_matches_tier_seed():
    credits = _tier_credits()
    docs = (ROOT / 'templates' / 'docs.html').read_text(encoding='utf-8')
    for tier in ['free', 'starter', 'professional', 'business']:
        cell = f"<td>{int(credits[tier]):,}</td>" if int(credits[tier]) >= 1000 \
            else f"<td>{int(credits[tier])}</td>"
        assert cell in docs, (
            f"docs.html billing table is stale for {tier} — expected {cell}"
        )
