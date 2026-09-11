# Recall development
Use the separate `recall` Conda environment. Run `conda run -n recall pytest`.
Read docs/STATUS.md before resuming. Default tests must be offline and free.
All writes belong to the service; CLI/TUI use its API. Keep initial attempts and
review events immutable except the audited latest-review correction operation.
Never enable live spending, deployment, or SMS without user authorization.
