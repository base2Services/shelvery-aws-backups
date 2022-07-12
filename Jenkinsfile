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
      steps {
        script {
          withAWS(role: env.SHELVERY_TEST_ROLE, region: 'us-east-1') {
            def pytestStatus = sh script: "python -m pytest --junit-xml=pytest_unit.xml shelvery_tests", returnStatus: true
            
            junit 'pytest_unit.xml'

            if (pytestStatus != 0) {
              currentBuild.result = 'FAILURE'
              error("Shelvery unit tests failed with exit code ${pytestStatus}")
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
      agent {
        label 'linux'
      }
      steps {
        script {
          unstash name: 'archive'

          def gitsha = shellOut('git rev-parse --short HEAD'),
              fileName = shellOut('cd $WORKSPACE/dist && ls -1 *.tar.gz'),
              releaseFileName = env.BRANCH_NAME == 'master' ? fileName : fileName.replace('.tar.gz','-develop.tar.gz')
              releaseUrl = "https://${env.SHELVERY_DIST_BUCKET}.s3.amazonaws.com/release/${releaseFileName}"
          
          echo "Shelvery pipeline: Release"

          sh "aws s3 cp dist/${fileName} s3://${params.SHELVERY_DIST_BUCKET}/release/${releaseFileName}"
        }
      }
      post {
        success {
          slackSend color: '#00FF00', message: "built new shelvery release for banch ${env.BRANCH_NAME} and published to s3://${params.SHELVERY_DIST_BUCKET}/release/${releaseFileName}"
        }
      }
    }

    stage('Release PyPI'){
      when {
        branch 'master'
      }
      steps {
        input 'Release to PyPI'
        script {
          withCredentials([usernamePassword(credentialsId: 'base2-pypi', usernameVariable: 'PYPICREDS_USR', passwordVariable: 'PYPICREDS_PSW')]) {
                        sh """#!/bin/bash
cat << EOT > /root/.pypirc
[distutils]
index-servers =
  pypi
  pypitest

[pypi]
repository=https://pypi.org/pypi
username=\${PYPICREDS_USR}
password=\${PYPICREDS_PSW}
EOT

python setup.py sdist upload -r pypi
"""
          }
        }
      }
      post {
        success {
          slackSend color: '#00FF00', channel: '#base2-tool-releases', message: "<https://pypi.python.org/pypi/shelvery|New Shelvery Release on PyPI>"
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
