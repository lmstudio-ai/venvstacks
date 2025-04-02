project('dynlib-consumer', 'c', version: '1.0.0')

libcheckdynlib = dependency('checkdynlib')

py = import('python').find_installation(pure: false)
py.extension_module(
    'dynlib_consumer', 'dynlib_consumer.c',
    dependencies: libcheckdynlib,
    install: true,
    limited_api: '3.11',
)
