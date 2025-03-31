#
# Automated Git Version Tagging Tool - PowerShell Version
#

param(
    [switch]$All,
    [int]$Limit = 10,
    [string]$StartFrom,
    [switch]$Force,
    [switch]$Lightweight,
    [switch]$DryRun,
    [string]$Username,
    [string]$Token,
    [switch]$PromptCredentials,
    [switch]$TestConnection
)

Write-Host "==================================" -ForegroundColor Cyan
Write-Host "Automated Git Version Tagging Tool" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""

# Set the date for the report file
$timestamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$reportFile = "tag_report_$timestamp.md"

# Display configuration
Write-Host "Configuration:" -ForegroundColor Yellow
if ($All) {
    Write-Host "- Processing all versions"
} else {
    Write-Host "- Processing $Limit versions"
}
if ($StartFrom) { Write-Host "- Starting from version $StartFrom" }
if ($Force) { Write-Host "- Force overwrite existing tags" }
if ($Lightweight) { Write-Host "- Creating lightweight tags" }
if ($DryRun) { Write-Host "- Dry run (no actual changes)" -ForegroundColor Magenta }
if ($Username) { Write-Host "- Using provided username: $Username" }
if ($Token) { Write-Host "- Using provided GitHub token" }
if ($PromptCredentials) { Write-Host "- Will prompt for Git credentials" }
Write-Host ""

# Ensure dependencies are installed
Write-Host "Ensuring dependencies are installed..." -ForegroundColor Yellow
pip install -r tagging_requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to install dependencies" -ForegroundColor Red
    exit 1
}

# Test connection if requested
if ($TestConnection) {
    Write-Host "Testing connection to remote repository..." -ForegroundColor Yellow
    python tag_versions.py --test-connection
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Connection test successful!" -ForegroundColor Green
    } else {
        Write-Host "Connection test failed!" -ForegroundColor Red
    }
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Starting tagging process..." -ForegroundColor Green

# Build the command arguments
$scriptArgs = @()
if ($All) {
    $scriptArgs += "--all"
} else {
    $scriptArgs += "--limit"
    $scriptArgs += $Limit
}
$scriptArgs += "--push"
$scriptArgs += "--batch"
$scriptArgs += "--tag-even-if-unverified"
$scriptArgs += "--report-file"
$scriptArgs += $reportFile

if ($StartFrom) {
    $scriptArgs += "--start-from"
    $scriptArgs += $StartFrom
}
if ($Force) { $scriptArgs += "--force" }
if ($Lightweight) { $scriptArgs += "--lightweight" }
if ($DryRun) { $scriptArgs += "--dry-run" }
if ($Username) { 
    $scriptArgs += "--username" 
    $scriptArgs += $Username
}
if ($Token) { 
    $scriptArgs += "--token" 
    $scriptArgs += $Token
}
if ($PromptCredentials) { $scriptArgs += "--prompt-credentials" }

# Execute the tagging script
Write-Host "Executing: python tag_versions.py $scriptArgs" -ForegroundColor Gray
if ($Token) {
    # Don't display token in logs
    Write-Host "(Token value hidden for security)" -ForegroundColor Gray
}

# Run the script with credentials
python tag_versions.py $scriptArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Process completed with some errors. See $reportFile for details." -ForegroundColor Red
    
    # Suggest troubleshooting steps
    Write-Host "`nTroubleshooting steps for push failures:" -ForegroundColor Yellow
    Write-Host "1. Verify you have push access to the repository" -ForegroundColor Yellow
    Write-Host "2. Try using the --username and --token options or --prompt-credentials" -ForegroundColor Yellow
    Write-Host "3. Check if you need to configure SSH keys for this repository" -ForegroundColor Yellow
    Write-Host "4. Run with --test-connection to verify connectivity" -ForegroundColor Yellow
    
    exit 1
} else {
    Write-Host ""
    Write-Host "Process completed successfully. See $reportFile for details." -ForegroundColor Green
}

Write-Host ""
if (-not $DryRun) {
    Write-Host "Tags have been created and pushed to the remote repository." -ForegroundColor Cyan
} else {
    Write-Host "Dry run completed. No actual tags were created or pushed." -ForegroundColor Cyan
}
Write-Host ""

# Tip for verifying pushed tags
Write-Host "To verify pushed tags on GitHub, visit:" -ForegroundColor Green
$remoteUrl = git remote get-url origin
if ($remoteUrl -match "github.com[:/]([^/]+)/([^/.]+)") {
    $owner = $matches[1]
    $repo = $matches[2]
    if ($repo -match "\.git$") {
        $repo = $repo -replace "\.git$", ""
    }
    Write-Host "https://github.com/$owner/$repo/tags" -ForegroundColor Cyan
} else {
    Write-Host "Check the tags section of your repository."
} 