# bootc_shared: the contract code that the Python frontends share. It is
# installed beside bootc_installer, in the directory that the launcher puts
# on sys.path, so `import bootc_shared` works in the installed tree as it
# does in a checkout (pytest.ini puts shared/python on the path).
shared_pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
shared_moduledir = join_paths(shared_pkgdatadir, 'bootc_shared')

install_subdir('bootc_shared',
  install_dir: shared_pkgdatadir,
  exclude_directories: ['__pycache__'],
)

# The data files that the package reads, each to the place where
# bootc_shared/_data.py looks: data/<contract>/<file>. The list is FILES of
# _data.py; tests/unit/test_shared_python_package.py compares the two.
install_data('../account/groups.json',
  install_dir: join_paths(shared_moduledir, 'data', 'account'))
install_data('../branding/copy-defaults.json',
  install_dir: join_paths(shared_moduledir, 'data', 'branding'))
install_data('../progress/dry-run-transcript.ndjson',
  install_dir: join_paths(shared_moduledir, 'data', 'progress'))
install_data('../recipe/encryption-choices.json',
  install_dir: join_paths(shared_moduledir, 'data', 'recipe'))
