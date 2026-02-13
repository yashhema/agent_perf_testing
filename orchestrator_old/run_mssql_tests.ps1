Set-Location "C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing\orchestrator"
$env:TEST_DB_TYPE = "mssql"
Write-Host "Running tests with TEST_DB_TYPE: $env:TEST_DB_TYPE"
Write-Host "Working directory: $(Get-Location)"
python -m pytest tests/integration/test_docker_scenario.py tests/integration/test_executor_docker.py -v --tb=short
