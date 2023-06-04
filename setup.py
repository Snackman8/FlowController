#!/usr/bin/env python

from distutils.core import setup

setup(name='FlowController',
      version='1.0',
      description='FlowController',
      author='Lawrence Yu',
      author_email='lawy888@gmail.com',
      url='https://github.com/Snackman8/FlowController',
      packages=['FlowController', 'FlowControllerWebApp'],
      include_package_data=True,
      install_requires=['croniter', 'pandas', 'SimpleMessageQueue']
)
