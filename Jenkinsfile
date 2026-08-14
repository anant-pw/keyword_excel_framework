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

// Same three triggers as .github/workflows/tests.yml:
//   push (via webhook)  -> Smoke
//   cron (nightly)      -> Regression
//   manual "Build with Parameters" -> your choice, defaults to Smoke

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
			description: 'Used only for a manual build - push/nightly decide this themselves below.'
		)

		string(
			name: 'EXTRA_EMAIL_TO',
			defaultValue: '',
			description: 'Optional extra recipient(s) for this build\'s run-notification email, comma-separated.'
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

					def sheets = [
						'TestSteps',
						'ParallelDemo',
						'ApiDemo',
						'RestfulBookerDemo',
						'DummyJsonDemo',
						'SchemaContractDemo'
					]

					def extraToFlag = params.EXTRA_EMAIL_TO?.trim()
						? "--email-extra-to \"${params.EXTRA_EMAIL_TO.trim()}\""
						: ""

					for (sheet in sheets) {

						bat """
							call .venv\\Scripts\\activate.bat
							python tests\\runner.py --sheet-name ${sheet} --suite ${env.SUITE} --workers 2 ${extraToFlag}
						"""
					}
				}
			}
		}

		stage('Run session demo (ordered)') {
			steps {
				script {

					def extraToFlag = params.EXTRA_EMAIL_TO?.trim()
						? "--email-extra-to \"${params.EXTRA_EMAIL_TO.trim()}\""
						: ""

					bat """
						call .venv\\Scripts\\activate.bat

						python tests\\runner.py --sheet-name SessionSave --suite ${env.SUITE} ${extraToFlag}

						python tests\\runner.py --sheet-name SessionReuse --suite ${env.SUITE} ${extraToFlag}
					"""
				}
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