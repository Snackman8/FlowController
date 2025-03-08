#!/usr/bin/env python

from setuptools import setup

def read_requirements():
    with open("requirements.txt") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(name='FlowController',
      version='1.0',
      description='FlowController',
      author='Lawrence Yu',
      author_email='lawy888@gmail.com',
      url='https://github.com/Snackman8/FlowController',
      packages=['FlowController', 'FlowControllerWebApp'],
      include_package_data=True,
      install_requires=read_requirements(),
      entry_points={
        'console_scripts': ['FlowControllerWebApp=FlowControllerWebApp.__main__:console_entry',
                            'FlowController=FlowController.FlowController:console_entry',],
      }
)
