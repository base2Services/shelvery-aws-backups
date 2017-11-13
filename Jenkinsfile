#!groovy
@Library('github.com/base2Services/ciinabox-pipelines@release/version-0.1.1') _

pipeline {

  agent none

  parameters {
    string(name: 'DIST_BUCKET', defaultValue: 'dist.shelvery.base2.services')
  }

  stages {

    stage('Init') {
      agent {
        label 'docker'
      }
      steps {
        sh 'sudo git clean -d -x -f'
      }
    }

    stage('Static Code Analysis') {
      agent {
        docker {
          image 'python:3-alpine'
          args '-u 0'
        }
      }

      steps {
        echo "Shelvery pipeline: Static Code Analysis"

        sh """#!/bin/sh
pip install prospector

# do not fail on static code analysis
exit 0
"""

      }
    }

    stage('Automated Tests') {
      agent {
        docker {
          image 'python:3-alpine'
          args '-u 0'
        }
      }

      steps {
        echo "Shelvery pipeline: Automated tests"
        //run united tests
        sh """#!/bin/sh
pip install nose
pip install -r requirements.txt -t lib
export AWS_DEFAULT_REGION=us-east-1
nosetests --with-xunit
"""
        //report unit tests
        junit 'nosetests.xml'

        //verify cli utility gets installed
        sh """#!/bin/sh
python setup.py build install
which shelvery
"""
        sh 'chown -R 1000:1000 .'
      }
    }

    stage('Package') {
      agent {
        docker {
          image 'python:3-alpine'
          args '-u 0'
        }
      }
      steps {
        echo "Shelvery pipeline: Package"
        sh """#!/bin/sh
python3 setup.py sdist
"""
        sh 'chown -R 1000:1000 .'
        stash name: 'archive', includes: 'dist/*'
      }
    }

    stage('ReleaseS3') {
      agent {
        label 'docker'
      }
      steps {
        script {
          unstash name: 'archive'

          def gitsha = shellOut('git rev-parse --short HEAD'),
              fileName = shellOut('cd $WORKSPACE/dist && ls -1 *.tar.gz'),
              releaseFileName = env.BRANCH_NAME == 'master' ? fileName : fileName.replace('.tar.gz','-develop.tar.gz')
              releaseUrl = "https://${env.DIST_BUCKET}.s3.amazonaws.com/release/${releaseFileName}"
          echo "Shelvery pipeline: Release"

          sh """
#!/bin/bash
printenv
aws s3 cp dist/${fileName} s3://\$DIST_BUCKET/release/${releaseFileName}

"""
          if(env.BRANCH_NAME == 'master') {
            slackSend color: '#00FF00', channel: '#base2-tool-releases', message: "New Shelvery Release: <${releaseUrl}|$fileName>"
          }
        }
      }
    }

    stage('Release PyPI'){
      agent {
        docker {
          image 'python:3'
          args '-u 0'
        }
      }
      when {
        expression { env.BRANCH_NAME == 'master' || env.BRANCH_NAME == 'feature/jenkins-pipeline' }
      }
      environment {
        PYPI_CREDS = credentials('base2-itsupport-pypi')
      }
      steps {
        input 'Release to PyPI'
        script {
          withCredentials(
                  [
                          [$class: 'UsernamePasswordMultiBinding', credentialsId: 'base2-itsupport-pypi', usernameVariable: 'PYPICREDS_USR', passwordVariable: 'PYPICREDS_PSW'],
                  ]) {

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
            sh 'chown -R 1000:1000 .'
          }
        }
      }
    }
  }
  post {
    success {
      slackSend color: '#00FF00', message: "SUCCESSFUL: Job ${env.JOB_NAME} <${env.BUILD_URL}|${env.BUILD_NUMBER}>"
    }
    failure {
      slackSend color: '#FF0000', message: "FAILED: Job '${env.JOB_NAME} <${env.BUILD_URL}|${env.BUILD_NUMBER}>"
    }
  }
}
