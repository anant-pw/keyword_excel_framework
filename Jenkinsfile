	pipeline {
		agent any

		triggers {
			githubPush()
			cron(env.BRANCH_NAME == 'main' ? '0 2 * * *' : '')
		}

		parameters {
			choice(name: 'SUITE', choices: ['Smoke', 'Regression'], description: 'Used only for a manual build - push/nightly decide this automatically.')
			string(name: 'SHEET_NAME', defaultValue: 'ALL', description: 'ALL discovers and runs every sheet in the selected Excel workbook. Enter an exact sheet/tab name to run only that sheet, or SessionDemo to run SessionSave -> SessionReuse sequentially.')
			string(name: 'SHEET_FILE', defaultValue: '', description: 'Optional workbook name or path. Examples: TestSuite_Pass, TestSuite_Pass.xlsx, testsheets\\TestSuite_Pass.xlsx. Leave blank to use test_sheet_file from config.yaml.')
			string(name: 'WORKERS', defaultValue: '2', description: 'Parallel worker processes per sheet run.')
			choice(name: 'BROWSER', choices: ['chromium', 'firefox', 'webkit'], description: 'Browser engine for this run.')
			booleanParam(name: 'HEADED', defaultValue: false, description: 'Run with a visible browser.')
			string(name: 'BASE_URL', defaultValue: '', description: 'Optional environment URL override.')
			booleanParam(name: 'NO_SCREENSHOTS', defaultValue: false, description: 'Skip failure screenshots for this run.')
			string(name: 'SLOW_MO_MS', defaultValue: '0', description: 'Playwright action delay in milliseconds.')
			choice(name: 'EMAIL_SEND_ON_OVERRIDE', choices: ['AUTO', 'always', 'failure_only'], description: 'AUTO keeps the existing suite-based email behavior.')
			string(name: 'EXTRA_EMAIL_TO', defaultValue: '', description: 'Optional extra recipient(s) for this build notification, comma-separated.')
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

						if (params.HEADED) {
							flags << '--headed'
						}
						if (params.BASE_URL?.trim()) {
							flags << "--base-url \"${params.BASE_URL.trim()}\""
						}
						if (params.NO_SCREENSHOTS) {
							flags << '--no-screenshot'
						}
						if (params.SLOW_MO_MS?.trim() && params.SLOW_MO_MS.trim() != '0') {
							flags << "--slow-mo ${params.SLOW_MO_MS.trim()}"
						}

						def emailSendOn = (params.EMAIL_SEND_ON_OVERRIDE && params.EMAIL_SEND_ON_OVERRIDE != 'AUTO')
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
						def suppliedFile = params.SHEET_FILE?.trim()
						def workbookPath = ''

						if (suppliedFile) {
							def candidates = [
								suppliedFile,
								"${suppliedFile}.xlsx",
								"testsheets\\${suppliedFile}",
								"testsheets\\${suppliedFile}.xlsx",
								"testsheets/${suppliedFile}",
								"testsheets/${suppliedFile}.xlsx"
							].unique()

							workbookPath = candidates.find { fileExists(it) }

							if (!workbookPath) {
								error("Excel workbook not found: ${suppliedFile}\n\nJenkins searched:\n${candidates.join('\\n')}")
							}
						} else {
							workbookPath = bat(
								returnStdout: true,
								script: '''
									@echo off
									.venv\\Scripts\\python.exe -c "import yaml; c=yaml.safe_load(open('config/config.yaml', encoding='utf-8')) or {}; print(c.get('test_sheet_file','').strip())"
								'''
							).trim()

							if (!workbookPath) {
								error('No Excel workbook configured. Supply SHEET_FILE or set test_sheet_file in config/config.yaml.')
							}

							if (!fileExists(workbookPath)) {
								error("Excel workbook configured in config.yaml was not found: ${workbookPath}")
							}
						}

						env.ACTIVE_SHEET_FILE = workbookPath
						echo "Excel workbook selected: ${env.ACTIVE_SHEET_FILE}"
					}
				}
			}

			stage('Resolve Excel sheets') {
				steps {
					script {
						if (params.SHEET_NAME?.trim() == 'SessionDemo') {
							env.RUN_SHEETS = ''
							env.HAS_SESSION_SHEETS = 'true'
							return
						}

						if (params.SHEET_NAME?.trim() && params.SHEET_NAME.trim() != 'ALL') {
							env.RUN_SHEETS = params.SHEET_NAME.trim()
							env.HAS_SESSION_SHEETS = 'false'
							echo "Selected Excel sheet: ${env.RUN_SHEETS}"
							return
						}

						def discoveredSheets = bat(
							returnStdout: true,
							script: """
								@echo off
								.venv\\Scripts\\python.exe -c "import openpyxl; wb=openpyxl.load_workbook(r'${env.ACTIVE_SHEET_FILE}', read_only=True); print('|||'.join(wb.sheetnames)); wb.close()"
							"""
						).trim()

						if (!discoveredSheets) {
							error("No worksheets found in Excel workbook: ${env.ACTIVE_SHEET_FILE}")
						}

						def allSheets = discoveredSheets
							.split('\\|\\|\\|')
							.collect { it.trim() }
							.findAll { it }

						def sessionSheets = ['SessionSave', 'SessionReuse']
						def normalSheets = allSheets.findAll { !sessionSheets.contains(it) }

						env.RUN_SHEETS = normalSheets.join('|')
						env.HAS_SESSION_SHEETS = allSheets.any { sessionSheets.contains(it) } ? 'true' : 'false'

						echo "Discovered Excel sheets: ${allSheets.join(', ')}"
						echo "Normal sheets: ${normalSheets.join(', ')}"

						if (env.HAS_SESSION_SHEETS == 'true') {
							echo 'SessionSave/SessionReuse detected. They will run sequentially.'
						}
					}
				}
			}

			stage('Run test sheets') {
				when {
					expression { params.SHEET_NAME?.trim() != 'SessionDemo' }
				}
				steps {
					script {
						def sheets = env.RUN_SHEETS
							? env.RUN_SHEETS.split('\\|').collect { it.trim() }.findAll { it }
							: []

						for (sheet in sheets) {
							echo "Running Excel sheet: ${sheet}"

							bat """
								@echo off
								.venv\\Scripts\\python.exe tests\\runner.py ^
									--sheet-file "${env.ACTIVE_SHEET_FILE}" ^
									--sheet-name "${sheet}" ^
									--suite ${env.SUITE} ^
									${env.RUN_FLAGS}
							"""
						}
					}
				}
			}

			stage('Run session demo (ordered)') {
				when {
					expression { params.SHEET_NAME?.trim() == 'SessionDemo' || env.HAS_SESSION_SHEETS == 'true' }
				}
				steps {
					bat """
						@echo off
						.venv\\Scripts\\python.exe tests\\runner.py ^
							--sheet-file "${env.ACTIVE_SHEET_FILE}" ^
							--sheet-name SessionSave ^
							--suite ${env.SUITE} ^
							${env.RUN_FLAGS}

						.venv\\Scripts\\python.exe tests\\runner.py ^
							--sheet-file "${env.ACTIVE_SHEET_FILE}" ^
							--sheet-name SessionReuse ^
							--suite ${env.SUITE} ^
							${env.RUN_FLAGS}
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
					reportFiles: 'execution_report.html',
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
