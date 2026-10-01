"""The files each daily publication contains. Standard library only, so the publish job
can read it without installing the package."""

DATA_MANIFEST = "data/manifests/data_manifest.json"

DATA_FILES = frozenset({
    "data/raw/fred/median_household_income.csv",
    "data/processed/bitcoin_daily.csv",
    "data/processed/median_household_income_annual.csv",
    "data/manifests/source_registry.csv",
    "data/manifests/column_dictionary.csv",
})

REPORT_DIR = "outputs/savings/latest"
REPORT_MANIFEST = "export_manifest.json"
REPORT_FILES = frozenset({
    "plan_definition.json", "section3_packet.json", "README.md",
    "cohort_summary.csv", "ytd_summary.csv", "benchmark_results.csv",
    "cohort_paths.csv", "contribution_schedule.csv",
    "cohort_comparison.png", "cohort_comparison.svg",
    "current_year_savings.png", "current_year_savings.svg",
})

NOTEBOOK = "notebooks/bitcoin_savings_plan.ipynb"

PUBLICATION_FILES = DATA_FILES | {DATA_MANIFEST, NOTEBOOK} | {
    f"{REPORT_DIR}/{name}" for name in REPORT_FILES | {REPORT_MANIFEST}
}
