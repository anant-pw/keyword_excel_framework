	// Same three triggers as .github/workflows/tests.yml, same reasoning:
	//   push (via webhook)  -> Smoke
	//   cron (nightly)      -> Regression
	//   manual "Build with Parameters" -> your choice, defaults to Smoke
	//
	// Push-triggering needs the GitHub plugin + a webhook configured on the
	// Jenkins job itself (githubPush() below only arms it - it doesn't set up
	// the webhook). Nightly and manual work from this file alone.
	//
	// cleanWs() at the start matters here in a way it doesn't for GitHub
	// Actions: GH Actions runners are thrown away after every run, so there's
	// never a leftover sessions/*.json from a previous build. A Jenkins agent
	// commonly REUSES its workspace across builds, so without an explicit
	// clean, SessionReuse could accidentally pass using a session file a
	// PREVIOUS build's SessionSave step wrote - masking the exact ordering bug
	// core/session_manager.py's preflight check exists to catch. Wiping the
	// workspace every build makes Jenkins behave the same as GH Actions here.

pipeline {
    agent any

    triggers {
        githubPush()
        cron(env.BRANCH_NAME == 'main' ? '0 2 * * *' : '')
    }

    parameters {
        choice(
            name: 'SUITE',
            choices: ['Smoke', 'Regression'],
            description: 'Used only for a manual build - push/nightly decide this automatically.'
        )

        string(
            name: 'SHEET_NAME',
            defaultValue: 'ALL',
            description: 'ALL runs every sheet found in the selected Excel workbook. Enter an exact sheet/tab name to run only that sheet, or SessionDemo to run SessionSave -> SessionReuse sequentially.'
        )

        string(
            name: 'SHEET_FILE',
            defaultValue: '',
            description: 'Optional Excel workbook path. Leave blank to use test_sheet_file from config.yaml.'
        )

        string(
            name: 'WORKERS',
            defaultValue: '2',
            description: 'Parallel worker processes per sheet run.'
        )

        choice(
            name: 'BROWSER',
            choices: ['chromium', 'firefox', 'webkit'],
            description: 'Browser engine for this run.'
        )

        booleanParam(
            name: 'HEADED',
            defaultValue: false,
            description: 'Run with a visible browser.'
        )

        string(
            name: 'BASE_URL',
            defaultValue: '',
            description: 'Optional environment URL override.'
        )

        booleanParam(
            name: 'NO_SCREENSHOTS',
            defaultValue: false,
            description: 'Skip failure screenshots for this run.'
        )

        string(
            name: 'SLOW_MO_MS',
            defaultValue: '0',
            description: 'Playwright action delay in milliseconds.'
        )

        choice(
            name: 'EMAIL_SEND_ON_OVERRIDE',
            choices: ['AUTO', 'always', 'failure_only'],
            description: 'AUTO keeps the existing suite-based email behavior.'
        )

        string(
            name: 'EXTRA_EMAIL_TO',
            defaultValue: '',
            description: 'Optional extra recipient(s) for this build notification, comma-separated.'
        )
    }

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    environment {
        SMTP_PASSWORD = credentials('smtp-password')
    }

    stages {

        stage('Determine suite') {
            steps {
                script {
                    if (currentBuild.getBuildCauses('hudson.triggers.TimerTrigger$TimerTriggerCause')) {
                        env.SUITE = 'Regression'
                    } else if (currentBuild.getBuildCauses('hudson.model.Cause$UserIdCause')) {
                        env.SUITE = params.SUITE
                    } else {
                        env.SUITE = 'Smoke'
                    }

                    echo "Running Suite=${env.SUITE}"
                }
            }
        }

        stage('Compute run flags') {
            steps {
                script {
                    def flags = []

                    flags << "--workers ${params.WORKERS?.trim() ?: '2'}"
                    flags << "--browser ${params.BROWSER}"

                    if (params.SHEET_FILE?.trim()) {
                        flags << "--sheet-file \"${params.SHEET_FILE.trim()}\""
                    }

                    if (params.HEADED) {
                        flags << "--headed"
                    }

                    if (params.BASE_URL?.trim()) {
                        flags << "--base-url \"${params.BASE_URL.trim()}\""
                    }

                    if (params.NO_SCREENSHOTS) {
                        flags << "--no-screenshot"
                    }

                    if (params.SLOW_MO_MS?.trim() && params.SLOW_MO_MS.trim() != '0') {
                        flags << "--slow-mo ${params.SLOW_MO_MS.trim()}"
                    }

                    def emailSendOn =
                        (params.EMAIL_SEND_ON_OVERRIDE &&
                         params.EMAIL_SEND_ON_OVERRIDE != 'AUTO')
                            ? params.EMAIL_SEND_ON_OVERRIDE
                            : ((env.SUITE == 'Regression') ? 'always' : 'failure_only')

                    flags << "--email-send-on ${emailSendOn}"

                    if (params.EXTRA_EMAIL_TO?.trim()) {
                        flags << "--email-extra-to \"${params.EXTRA_EMAIL_TO.trim()}\""
                    }

                    env.RUN_FLAGS = flags.join(' ')

                    echo "Computed run flags: ${env.RUN_FLAGS}"
                }
            }
        }

        stage('Clean workspace') {
            steps {
                cleanWs()
            }
        }

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Install dependencies') {
            steps {
                bat """
                    py -m venv .venv
                    call .venv\\Scripts\\activate.bat
                    python -m pip install --upgrade pip
                    pip install -r requirements.txt
                    python -m playwright install ${params.BROWSER}
                """
            }
        }

        stage('Resolve Excel workbook') {
            steps {
                script {
                    /*
                     * Determine the workbook that will actually be used.
                     *
                     * If SHEET_FILE is supplied, use it.
                     * Otherwise read test_sheet_file from config.yaml.
                     */
                    def workbookPath = params.SHEET_FILE?.trim()

                    if (!workbookPath) {
                        workbookPath = bat(
                            returnStdout: true,
                            script: '''
                                call .venv\\Scripts\\activate.bat
                                python -c "import yaml; print((yaml.safe_load(open('config/config.yaml', encoding='utf-8')) or {}).get('test_sheet_file', 'testsheets/TestSuite.xlsx'))"
                            '''
                        ).trim()
                    }

                    env.ACTIVE_SHEET_FILE = workbookPath

                    echo "Excel workbook selected: ${env.ACTIVE_SHEET_FILE}"

                    if (!fileExists(env.ACTIVE_SHEET_FILE)) {
                        error("Excel workbook not found: ${env.ACTIVE_SHEET_FILE}")
                    }
                }
            }
        }

        stage('Resolve Excel sheets') {
            steps {
                script {

                    if (params.SHEET_NAME?.trim() == 'SessionDemo') {
                        echo "SessionDemo selected - SessionSave -> SessionReuse will run sequentially."
                        env.RUN_SHEETS = ''
                        return
                    }

                    /*
                     * If a specific sheet was supplied, don't inspect or assume
                     * anything about the workbook.
                     */
                    if (params.SHEET_NAME?.trim() &&
                        params.SHEET_NAME.trim() != 'ALL') {

                        env.RUN_SHEETS = params.SHEET_NAME.trim()

                        echo "Selected Excel sheet: ${env.RUN_SHEETS}"
                        return
                    }

                    /*
                     * SHEET_NAME=ALL:
                     * Dynamically discover the tabs from the ACTUAL workbook.
                     *
                     * There is deliberately no hardcoded TestSuite.xlsx
                     * sheet list here.
                     */
                    def discoveredSheets = bat(
                        returnStdout: true,
                        script: """
                            call .venv\\\\Scripts\\\\activate.bat
                            python -c "import openpyxl; wb=openpyxl.load_workbook(r'${env.ACTIVE_SHEET_FILE}', read_only=True); print('|'.join(wb.sheetnames)); wb.close()"
                        """
                    ).trim()

                    if (!discoveredSheets) {
                        error("No worksheets found in Excel workbook: ${env.ACTIVE_SHEET_FILE}")
                    }

                    def allSheets = discoveredSheets
                        .split('\\|')
                        .collect { it.trim() }
                        .findAll { it }

                    /*
                     * SessionSave and SessionReuse must remain ordered.
                     * Remove them from the normal sheet loop and execute them
                     * in the dedicated sequential stage below.
                     */
                    def sessionSheets = ['SessionSave', 'SessionReuse']

                    def normalSheets = allSheets.findAll {
                        !sessionSheets.contains(it)
                    }

                    env.RUN_SHEETS = normalSheets.join('|')
                    env.HAS_SESSION_SHEETS =
                        allSheets.any { sessionSheets.contains(it) }
                            ? 'true'
                            : 'false'

                    echo "Discovered Excel sheets: ${allSheets.join(', ')}"
                    echo "Normal sheets: ${normalSheets.join(', ')}"

                    if (env.HAS_SESSION_SHEETS == 'true') {
                        echo "SessionSave/SessionReuse detected. They will run sequentially."
                    }
                }
            }
        }

        stage('Run test sheets') {
            when {
                expression {
                    params.SHEET_NAME?.trim() != 'SessionDemo'
                }
            }

            steps {
                script {

                    def sheets = env.RUN_SHEETS
                        ? env.RUN_SHEETS.split('\\|').collect { it.trim() }.findAll { it }
                        : []

                    if (sheets.isEmpty()) {
                        echo "No normal Excel sheets selected."
                        return
                    }

                    for (sheet in sheets) {

                        echo "Running Excel sheet: ${sheet}"

                        bat """
                            call .venv\\Scripts\\activate.bat
                            python tests\\runner.py --sheet-name "${sheet}" --suite ${env.SUITE} ${env.RUN_FLAGS}
                        """
                    }
                }
            }
        }

        stage('Run session demo (ordered)') {
            when {
                expression {
                    params.SHEET_NAME?.trim() == 'SessionDemo' ||
                    env.HAS_SESSION_SHEETS == 'true'
                }
            }

            steps {
                bat """
                    call .venv\\Scripts\\activate.bat
                    python tests\\runner.py --sheet-name SessionSave --suite ${env.SUITE} ${env.RUN_FLAGS}
                    python tests\\runner.py --sheet-name SessionReuse --suite ${env.SUITE} ${env.RUN_FLAGS}
                """
            }
        }
    }

    post {
        always {

            archiveArtifacts(
                artifacts: 'reports/**, logs/**',
                allowEmptyArchive: true,
                fingerprint: false
            )

            publishHTML([
                allowMissing: true,
                alwaysLinkToLastBuild: true,
                keepAll: true,
                reportDir: 'reports',
                reportFiles: 'report_*.html',
                reportName: 'Execution Report',
                reportTitles: 'Keyword Framework - Execution Report'
            ])

            allure([
                includeProperties: false,
                jdk: '',
                results: [
                    [path: 'reports/allure-results']
                ]
            ])
        }
    }
}