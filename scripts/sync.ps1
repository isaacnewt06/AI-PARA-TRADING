param(
    [string]$Channel = "",
    [string]$Mode = "incremental"
)

if ($Channel) {
    python -m src.cli.main sync --channel $Channel --mode $Mode
} else {
    python -m src.cli.main sync --mode $Mode
}
