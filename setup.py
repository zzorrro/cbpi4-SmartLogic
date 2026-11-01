from setuptools import setup, find_packages

setup(
    name='cbpi4-PIDMash',
    version='1.0.0',
    description='PID kettle logic with dynamic power limiting for mash steps',
    author='Sammy Brewery',
    url='https://github.com/zzorrro/cbpi4-PIDMash',
    license='MIT',
    packages=find_packages(),
    include_package_data=True,
    package_data={'': ['*.json', '*.md', '*.yaml']},
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Topic :: Home Automation',
    ],
)