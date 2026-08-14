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
			choice(name: 'SHEET_NAME', choices: ['ALL', 'TestSteps', 'ParallelDemo', 'ApiDemo', 'RestfulBookerDemo', 'DummyJsonDemo', 'SchemaContractDemo', 'SessionDemo'], description: 'ALL (default) runs the full matrix, same as before this parameter existed - what push/nightly get automatically since they never fill this form in. Pick one sheet to run just that for a faster manual/debug build. SessionDemo runs the SessionSave->SessionReuse ordered pair on its own.')
			string(name: 'SHEET_FILE', defaultValue: '', description: 'Optional - path to an alternate workbook (overrides test_sheet_file from config.yaml). Leave blank to use testsheets/TestSuite.xlsx.')
			string(name: 'WORKERS', defaultValue: '2', description: 'Parallel worker processes per sheet run.')
			choice(name: 'BROWSER', choices: ['chromium', 'firefox', 'webkit'], description: 'Browser engine for this run.')
			booleanParam(name: 'HEADED', defaultValue: false, description: 'Run with a visible browser instead of headless - only meaningful on an agent with a desktop session to actually watch it on.')
			string(name: 'BASE_URL', defaultValue: '', description: 'Optional - point this run at a different environment (e.g. staging) than base_url in config.yaml. Leave blank to use config.yaml as-is.')
			booleanParam(name: 'NO_SCREENSHOTS', defaultValue: false, description: 'Skip failure screenshots for this run - smaller/faster report, less detail to debug from.')
			string(name: 'SLOW_MO_MS', defaultValue: '0', description: 'Milliseconds of delay Playwright adds between actions - only useful paired with HEADED for a live demo/walkthrough. 0 = off.')
			choice(name: 'EMAIL_SEND_ON_OVERRIDE', choices: ['AUTO', 'always', 'failure_only'], description: 'AUTO (default) keeps the existing rule: always for Regression, failure_only for Smoke. Pick always/failure_only to force one regardless of SUITE for this build only.')
			string(name: 'EXTRA_EMAIL_TO', defaultValue: '', description: 'Optional extra recipient(s) for this build\'s run-notification email, comma-separated. Added on top of email.to_addresses in config.yaml for THIS build only - does not change config.yaml.')
		}

		options {
			timestamps()
			disableConcurrentBuilds()
		}

		environment {
			// Injects the Jenkins Credentials entry named 'smtp-password' as
			// SMTP_PASSWORD in every step's process environment - this is what
			// core/notifier.py actually reads (os.environ.get("SMTP_PASSWORD")),
			// so the secret never touches config.yaml or this file in plaintext.
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
							env.SUITE = 'Smoke'   // push / webhook-triggered
						}
						echo "Running Suite=${env.SUITE} (trigger-derived, not just the SUITE parameter)"
					}
				}
			}

			stage('Compute run flags') {
				steps {
					script {
						// Single place that turns build parameters into runner.py CLI flags,
						// so the sheet-matrix stage and the session-demo stage can't drift out
						// of sync with each other. Every optional param that's blank/unset
						// here simply means "use whatever config.yaml already says" - runner.py
						// only overrides a config.yaml value when the flag is actually passed.
						def flags = []
						flags << "--workers ${params.WORKERS?.trim() ?: '2'}"
						flags << "--browser ${params.BROWSER}"
						if (params.SHEET_FILE?.trim())   flags << "--sheet-file \"${params.SHEET_FILE.trim()}\""
						if (params.HEADED)                flags << "--headed"
						if (params.BASE_URL?.trim())      flags << "--base-url \"${params.BASE_URL.trim()}\""
						if (params.NO_SCREENSHOTS)        flags << "--no-screenshot"
						if (params.SLOW_MO_MS?.trim() && params.SLOW_MO_MS.trim() != '0') {
							flags << "--slow-mo ${params.SLOW_MO_MS.trim()}"
						}

						// Regression is the deliberate, less-frequent run (nightly cron or
						// manual choice) - worth a notification either way, so send_on=always
						// there. Smoke fires on every push and stays failure_only, or a green
						// build would email the team on every commit. EMAIL_SEND_ON_OVERRIDE
						// lets a manual build force one or the other regardless of that rule.
						def emailSendOn = (params.EMAIL_SEND_ON_OVERRIDE && params.EMAIL_SEND_ON_OVERRIDE != 'AUTO') \
							? params.EMAIL_SEND_ON_OVERRIDE \
							: ((env.SUITE == 'Regression') ? 'always' : 'failure_only')
						flags << "--email-send-on ${emailSendOn}"
						if (params.EXTRA_EMAIL_TO?.trim()) flags << "--email-extra-to \"${params.EXTRA_EMAIL_TO.trim()}\""

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

			stage('Run test sheets') {
				when { expression { params.SHEET_NAME == 'ALL' || params.SHEET_NAME != 'SessionDemo' } }
				steps {
					script {
						// Same set as the GitHub Actions matrix, run sequentially
						// here rather than in parallel { } - keeps Jenkins agent
						// resource usage predictable and the failure output in one
						// readable console log, at the cost of wall-clock time.
						// Switch to a `parallel` block if that trade-off stops
						// being the right one once real test volume grows.
						def allSheets = ['TestSteps', 'ParallelDemo', 'ApiDemo', 'RestfulBookerDemo', 'DummyJsonDemo', 'SchemaContractDemo']
						def sheets = (params.SHEET_NAME == 'ALL') ? allSheets : [params.SHEET_NAME]
						for (sheet in sheets) {
							bat """
								call .venv\\Scripts\\activate.bat
								python tests\\runner.py --sheet-name ${sheet} --suite ${env.SUITE} ${env.RUN_FLAGS}
							"""
						}
					}
				}
			}

			stage('Run session demo (ordered)') {
				when { expression { params.SHEET_NAME == 'ALL' || params.SHEET_NAME == 'SessionDemo' } }
				steps {
					// SessionSave then SessionReuse, same reasoning as the
					// GitHub Actions job of the same name - these can't be in
					// the sheets list above because order matters between them.
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