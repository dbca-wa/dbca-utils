#!/usr/bin/env python

from setuptools import setup
from pathlib import Path

# Read the contents of the README file:
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name='dbca-utils',
    version='2.0.0',
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
        'Django>=3.2',
    ],
    classifiers=[
        'Framework :: Django',
        'Framework :: Django :: 3.2',
        'Framework :: Django :: 4.0',
        'Framework :: Django :: 4.2',
        'Framework :: Django :: 5.0',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
