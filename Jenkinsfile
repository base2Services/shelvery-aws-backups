@Library('ciinabox') _

pipeline {

  agent {
    dockerfile {
      filename 'Dockerfile'
      label 'docker'
    }
  }

  stages {

    stage('Notify slack') {
      steps {
        slackSend color: '#70A1F0',
          message: "Shelvery pipeline started\n*Branch:* ${env.BRANCH_NAME}\n*Commit:* ${env.GIT_COMMIT}\n*Build:* <${env.BUILD_URL}|${env.BUILD_NUMBER}>"
      }
    }

    stage('Static Code Analysis') {
      steps {
        script {
          def prospectorStatus = sh script: "prospector", returnStatus: true
          if (prospectorStatus != 0) {
            // ignore failures here for now until issues are resolved
            echo "prospector failed with status code ${prospectorStatus}"
          }
        }
      }
    }

    stage('Unit Tests') {
      when { changeRequest target: 'master' }
      steps {
        script {
          //Source Account
          withAWS(role: env.SHELVERY_TEST_ROLE, region: 'ap-southeast-2') {

            sh "pwd"
            dir ('shelvery_tests'){
              def pytestStatus = sh script: "pytest -s -v -m source --source ${env.OPS_ACCOUNT_ID} --destination ${env.DEV_ACCOUNT_ID} --junit-xml=pytest_unit.xml", returnStatus: true
              junit 'pytest_unit.xml'
            

              if (pytestStatus != 0) {
                currentBuild.result = 'FAILURE'
                error("Shelvery unit tests failed with exit code ${pytestStatus}")
              }
            }
          }
        }
        script {
          withAWS(role: env.SHELVERY_TEST_ROLE, roleAccount: env.DEV_ACCOUNT_ID, region: 'ap-southeast-2') {
          //Destination Account  
            sh "pwd"
            dir ('shelvery_tests'){
              def pytestStatus = sh script: "pytest -s -v -m destination --source ${env.OPS_ACCOUNT_ID} --destination ${env.DEV_ACCOUNT_ID} --junit-xml=pytest_unit.xml", returnStatus: true
              junit 'pytest_unit.xml'

              if (pytestStatus != 0) {
                currentBuild.result = 'FAILURE'
                error("Shelvery unit tests failed with exit code ${pytestStatus}")
              }
            }
          }
        }
      }
    }

    stage('CLI Utility Test') {
      steps {
        sh "python setup.py build install --user"
        script {
          def shelveryCliStatus = sh script: "shelvery --version", returnStatus: true
          
          if (shelveryCliStatus != 254) {
            currentBuild.result = 'FAILURE'
            error("Shelvery CLI test failed with exit code ${shelveryCliStatus}")
          }
        }
      }
    }

    stage('Package') {
      steps {
        sh "python3 setup.py sdist"
        stash name: 'archive', includes: 'dist/*'
      }
    }

    stage('Release S3') {
      steps {
        unstash name: 'archive'

        script {
          def fileName = shellOut('cd $WORKSPACE/dist && ls -1 shelvery-*.tar.gz')
          def safebranch = env.BRANCH_NAME.replace("/", "_")
          def releaseFileName = env.BRANCH_NAME == 'master' ? fileName : fileName.replace('.tar.gz',"-${safebranch}.tar.gz")
          env["SHELVERY_S3_RELEASE"] = "https://${env.SHELVERY_DIST_BUCKET}.s3.amazonaws.com/release/${releaseFileName}"
          s3Upload(bucket: env.SHELVERY_DIST_BUCKET, file: "dist/${fileName}", path: "release/${releaseFileName}")

        }
        
      }
      post {
        success {
          slackSend color: '#00FF00', message: "built new shelvery release for banch ${env.BRANCH_NAME} and published to ${env.SHELVERY_S3_RELEASE}"
        }
      }
    }
    
  }

  post {
    success {
      slackSend color: '#00FF00',
        message: "Shelvery ${env.BRANCH_NAME} build <${env.BUILD_URL}|${env.BUILD_NUMBER}> successfully completed"
    }
    failure {
      slackSend color: '#FF0000',
        message: "Shelvery ${env.BRANCH_NAME} build <${env.BUILD_URL}|${env.BUILD_NUMBER}> failed"
    }
  }
}
