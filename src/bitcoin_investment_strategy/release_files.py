"""The files each daily publication contains. Standard library only, so the publish job
can read it without installing the package."""

DATA_MANIFEST = "data/manifests/data_manifest.json"

DATA_FILES = frozenset({
    "data/processed/bitcoin_daily.csv",
    "data/processed/median_household_income_annual.csv",
    "data/manifests/source_registry.csv",
    "data/manifests/column_dictionary.csv",
})

REPORT_DIR = "outputs/savings/latest"
REPORT_MANIFEST = "export_manifest.json"
REPORT_FILES = frozenset({
    "plan_definition.json", "savings_report.json", "README.md",
    "cohort_summary.csv", "ytd_summary.csv",
    "cohort_paths.csv", "contribution_schedule.csv",
    "cohort_comparison.png", "cohort_comparison.svg",
    "current_year_savings.png", "current_year_savings.svg",
})

# The supply and demand release, built from the same Report Library release.
RESEARCH_MANIFEST = "data/research/manifests/data_manifest.json"
RESEARCH_FILES = frozenset({
    "data/research/bitcoin_daily.csv",
    "data/research/technology_adoption_annual.csv",
    "data/research/bitcoin_owner_estimates.csv",
    "data/research/etf_daily.csv",
    "data/research/etf_totals_daily.csv",
    "data/research/etf_quarterly.csv",
    "data/research/manifests/source_registry.csv",
    "data/research/manifests/column_dictionary.csv",
})

NOTEBOOK = "notebooks/bitcoin_savings_plan.ipynb"
RESEARCH_NOTEBOOKS = frozenset({
    "notebooks/bitcoin_supply_dynamics.ipynb",
    "notebooks/bitcoin_demand_dynamics.ipynb",
})
NOTEBOOKS = frozenset({NOTEBOOK}) | RESEARCH_NOTEBOOKS

PUBLICATION_FILES = DATA_FILES | RESEARCH_FILES | {DATA_MANIFEST, RESEARCH_MANIFEST} | NOTEBOOKS | {
    f"{REPORT_DIR}/{name}" for name in REPORT_FILES | {REPORT_MANIFEST}
}
