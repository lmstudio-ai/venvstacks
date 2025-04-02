project('dynlib-publisher', 'c', version: '1.0.0')

py = import('python').find_installation(pure: false)

library(
    'checkdynlib', 'checkdynlib.c',
    install: true,
    install_dir: py.get_install_dir() / 'dynlib_publisher',
)
py.install_sources(['checkdynlib.h'], subdir: 'dynlib_publisher/include')
py.install_sources(['checkdynlib.pc'], subdir: 'dynlib_publisher')
