@echo off
setlocal enabledelayedexpansion

echo ==================================
echo Automated Git Version Tagging Tool
echo ==================================
echo.

REM Set the date for the report file
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c-%%a-%%b)
for /f "tokens=1-2 delims=: " %%a in ('time /t') do (set mytime=%%a%%b)
set timestamp=%mydate%_%mytime%

REM Parse arguments
set VERSIONS_TO_PROCESS=10
set START_FROM=
set FORCE=
set LIGHTWEIGHT=
set DRY_RUN=

:parse_args
if "%~1"=="" goto start_tagging
if /i "%~1"=="--all" (
    set VERSIONS_TO_PROCESS=all
    shift
    goto parse_args
)
if /i "%~1"=="--limit" (
    set VERSIONS_TO_PROCESS=%~2
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--start-from" (
    set START_FROM=--start-from %~2
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--force" (
    set FORCE=--force
    shift
    goto parse_args
)
if /i "%~1"=="--lightweight" (
    set LIGHTWEIGHT=--lightweight
    shift
    goto parse_args
)
if /i "%~1"=="--dry-run" (
    set DRY_RUN=--dry-run
    shift
    goto parse_args
)
shift
goto parse_args

:start_tagging
echo Configuration:
if "%VERSIONS_TO_PROCESS%"=="all" (
    echo - Processing all versions
) else (
    echo - Processing %VERSIONS_TO_PROCESS% versions
)
if not "%START_FROM%"=="" echo - Starting from specified version
if not "%FORCE%"=="" echo - Force overwrite existing tags
if not "%LIGHTWEIGHT%"=="" echo - Creating lightweight tags
if not "%DRY_RUN%"=="" echo - Dry run (no actual changes)
echo.

echo Ensuring dependencies are installed...
pip install -r tagging_requirements.txt
if %ERRORLEVEL% neq 0 (
    echo Failed to install dependencies
    exit /b 1
)

echo.
echo Starting tagging process...

REM Create a report file
set REPORT_FILE=tag_report_%timestamp%.md
echo --report-file %REPORT_FILE%

if "%VERSIONS_TO_PROCESS%"=="all" (
    python tag_versions.py --all --push --batch --tag-even-if-unverified %START_FROM% %FORCE% %LIGHTWEIGHT% %DRY_RUN% --report-file %REPORT_FILE%
) else (
    python tag_versions.py --limit %VERSIONS_TO_PROCESS% --push --batch --tag-even-if-unverified %START_FROM% %FORCE% %LIGHTWEIGHT% %DRY_RUN% --report-file %REPORT_FILE%
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo Process completed with some errors. See %REPORT_FILE% for details.
    exit /b 1
) else (
    echo.
    echo Process completed successfully. See %REPORT_FILE% for details.
)

echo.
echo Tags have been created and pushed to the remote repository.
echo.

endlocal 