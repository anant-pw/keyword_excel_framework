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
        cron(env.BRANCH_NAME == 'main' ? '0 2 * * *' : '')   // nightly, main branch only
    }

    parameters {
        choice(name: 'SUITE', choices: ['Smoke', 'Regression'], description: 'Used only for a manual build - push/nightly decide this themselves below.')
    }

    options {
        timestamps()
        disableConcurrentBuilds()
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
                        env.SUITE = 'Smoke'   // push / webhook-triggered
                    }
                    echo "Running Suite=${env.SUITE} (trigger-derived, not just the SUITE parameter)"
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
                bat '''
                    py -m venv .venv
                    call .venv\\Scripts\\activate.bat
                    python -m pip install --upgrade pip
                    pip install -r requirements.txt
                    python -m playwright install chromium
                '''
            }
        }

        stage('Run test sheets') {
            steps {
                script {
                    // Same set as the GitHub Actions matrix, run sequentially
                    // here rather than in parallel { } - keeps Jenkins agent
                    // resource usage predictable and the failure output in one
                    // readable console log, at the cost of wall-clock time.
                    // Switch to a `parallel` block if that trade-off stops
                    // being the right one once real test volume grows.
                    def sheets = ['TestSteps', 'ParallelDemo', 'ApiDemo', 'RestfulBookerDemo', 'DummyJsonDemo', 'SchemaContractDemo']
                    for (sheet in sheets) {
                        bat """
                            call .venv\\Scripts\\activate.bat
                            python tests\\runner.py --sheet-name ${sheet} --suite ${env.SUITE} --workers 2
                        """
                    }
                }
            }
        }

        stage('Run session demo (ordered)') {
            steps {
                // SessionSave then SessionReuse, same reasoning as the
                // GitHub Actions job of the same name - these can't be in
                // the sheets list above because order matters between them.
                bat """
                    call .venv\\Scripts\\activate.bat
                    python tests\\runner.py --sheet-name SessionSave --suite ${env.SUITE}
                    python tests\\runner.py --sheet-name SessionReuse --suite ${env.SUITE}
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
			}
	}
}