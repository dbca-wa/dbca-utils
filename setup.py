#!/usr/bin/env python

from setuptools import setup
from pathlib import Path

# Read the contents of the README file:
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name='dbca-utils',
    version='1.1.6',
    packages=['dbca_utils'],
    description='Utilities for Django/Python apps',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/dbca-wa/dbca-utils',
    author='Department of Biodiversity, Conservation and Attractions',
    author_email='asi@dbca.wa.gov.au',
    maintainer='Department of Biodiversity, Conservation and Attractions',
    maintainer_email='asi@dbca.wa.gov.au',
    license='Apache License, Version 2.0',
    zip_safe=False,
    keywords=['django', 'middleware', 'utility'],
    install_requires=[
        'Django>=2.1',
        'requests',
    ],
    classifiers=[
        'Framework :: Django',
        'Framework :: Django :: 2.2',
        'Framework :: Django :: 3.0',
        'Framework :: Django :: 3.2',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
