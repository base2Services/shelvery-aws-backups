from setuptools import setup

setup(name='shelvery', version='0.2.0', author='Base2Services R&D',
      author_email='itsupport@base2services.com',
      url='http://github.com/base2Services/shelvery',
      classifiers=[
          'Development Status :: 3 - Alpha',
          'Programming Language :: Python :: 3.6',
          'Intended Audience :: System Administrators',
          'Intended Audience :: Information Technology',
          'License :: OSI Approved :: MIT License',
          'Topic :: System :: Archiving :: Backup',
      ],
      keywords='aws backup lambda ebs rds ami',
      packages=['shelvery', 'shelvery_cli', 'shelvery_lambda'],
      install_requires=['boto3', 'python-dateutil'],
      python_requires='>=3.6',
      description='Backup manager for AWS EBS and AWS RDS services',
      entry_points={
          'console_scripts': ['shelvery = shelvery_cli.__main__:main'],
      })
